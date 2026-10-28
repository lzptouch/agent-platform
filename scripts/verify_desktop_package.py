#!/usr/bin/env python
"""打包后自检：启动已打包的桌面端，验证「拉起 sidecar → 握手 → 加载页面 → 退出清理」全链路。

对应 doc/roadmap/01-阶段S0 §6 的「打包后自检」与 doc/roadmap/12 §4 的发布冒烟清单。

用法：
    backend/.venv/Scripts/python.exe scripts/verify_desktop_package.py
    backend/.venv/Scripts/python.exe scripts/verify_desktop_package.py --dir frontend/desktop/release/win-unpacked

退出码：0 = 全部通过；1 = 存在失败项（逐项打印）。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    return ok


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def http_json(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except OSError as exc:
        return 0, str(exc)


def page_targets(cdp_port: int) -> list[dict]:
    status, body = http_json(f"http://127.0.0.1:{cdp_port}/json/list", timeout=3)
    if status != 200:
        return []
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return []


def user_data_dir() -> Path:
    appdata = os.environ.get("APPDATA") or os.environ.get("HOME") or ""
    pkg = json.loads((REPO_ROOT / "frontend" / "desktop" / "package.json").read_text(encoding="utf-8"))
    return Path(appdata) / (pkg.get("productName") or pkg.get("name") or "agent-desktop")


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="frontend/desktop/release/win-unpacked", help="已打包目录")
    parser.add_argument("--timeout", type=float, default=90.0, help="启动与握手的等待上限（秒）")
    args = parser.parse_args()

    pkg_dir = (REPO_ROOT / args.dir).resolve()
    exe = pkg_dir / ("Agent Desktop.exe" if os.name == "nt" else "Agent Desktop")
    if not exe.exists():
        record("安装目录存在且含主程序", False, f"未找到 {exe}")
        return 1
    record("安装目录存在且含主程序", True, str(pkg_dir))

    runtime_py = pkg_dir / "resources" / "runtime" / "python.exe"
    record("运行时已随包（resources/runtime）", runtime_py.exists(), str(runtime_py))
    frontend = pkg_dir / "resources" / "frontend" / "index.html"
    record("前端产物已随包（resources/frontend）", frontend.exists(), str(frontend))

    run_state = user_data_dir() / "run-state.json"
    if run_state.exists():
        run_state.unlink()

    cdp_port = free_port()
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    proc = subprocess.Popen(
        [str(exe), f"--remote-debugging-port={cdp_port}"],
        cwd=str(pkg_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        # 1) 窗口加载到后端托管页面（= 握手成功）
        deadline = time.time() + args.timeout
        backend_url = ""
        while time.time() < deadline and proc.poll() is None:
            for t in page_targets(cdp_port):
                url = t.get("url") or ""
                if t.get("type") == "page" and url.startswith("http://127.0.0.1"):
                    backend_url = url
                    break
            if backend_url:
                break
            time.sleep(0.5)
        record(
            "窗口加载到后端托管页面（握手成功）",
            bool(backend_url),
            backend_url or f"{args.timeout}s 内未出现后端页面目标",
        )

        # 2) run-state 记录了 sidecar
        deadline = time.time() + 30
        data = None
        while time.time() < deadline:
            if run_state.exists():
                try:
                    data = json.loads(run_state.read_text(encoding="utf-8"))
                    break
                except json.JSONDecodeError:
                    pass
            time.sleep(0.5)
        record(
            "run-state.json 记录 sidecar（pid/port）",
            bool(data and data.get("pid") and data.get("port")),
            json.dumps(data, ensure_ascii=False) if data else "未生成",
        )

        if data:
            # 3) 免鉴权存活探针
            status, body = http_json(f"http://127.0.0.1:{data['port']}/__desktop/ping")
            record("sidecar 存活探针 /__desktop/ping", status == 200, f"HTTP {status} {body[:60]}")

            # 4) 未鉴权访问受保护 API 必须被拒（统一错误体）
            status, body = http_json(f"http://127.0.0.1:{data['port']}/api/v1/health")
            ok = status == 401
            detail = f"HTTP {status}"
            if ok:
                try:
                    payload = json.loads(body)
                    ok = payload.get("code") == "E_AUTH" and bool(payload.get("request_id"))
                    detail = f"HTTP 401 code={payload.get('code')} request_id={payload.get('request_id')}"
                except json.JSONDecodeError:
                    ok = False
            record("未鉴权访问 /api/v1/** 被拒且为统一错误体", ok, detail)

        # 5) 强制结束后：run-state 允许残留（强杀不走优雅退出），
        #    但**下次启动必须回收孤儿**——这才是该文件存在的意义
        kill_tree(proc)
        deadline = time.time() + 15
        while time.time() < deadline and run_state.exists():
            time.sleep(0.5)
        leftover = run_state.exists()
        old_pid = None
        if leftover:
            try:
                old_pid = json.loads(run_state.read_text(encoding="utf-8")).get("pid")
            except json.JSONDecodeError:
                pass
        record(
            "强杀后 run-state 残留属预期（供孤儿回收使用）",
            True,
            f"残留={leftover} old_pid={old_pid}",
        )

        # 5.1) 重新启动：必须写出新的 run-state，且旧 pid 不再存活（孤儿被回收）
        proc2 = subprocess.Popen(
            [str(exe), f"--remote-debugging-port={free_port()}"],
            cwd=str(pkg_dir),
            env={k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 120
            new_data = None
            while time.time() < deadline:
                if run_state.exists():
                    try:
                        new_data = json.loads(run_state.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        new_data = None
                    if new_data and new_data.get("pid") and new_data.get("pid") != old_pid:
                        break
                time.sleep(0.5)
            record(
                "重启后写出新的 run-state（旧孤儿被回收）",
                bool(new_data and new_data.get("pid") and new_data.get("pid") != old_pid),
                f"old_pid={old_pid} new={json.dumps(new_data, ensure_ascii=False) if new_data else None}",
            )
        finally:
            kill_tree(proc2)
    finally:
        kill_tree(proc)

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"\n自检结果：{passed}/{len(CHECKS)} 项通过")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
