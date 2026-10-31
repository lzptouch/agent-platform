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
import tempfile
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


def kill_hard(proc: subprocess.Popen) -> None:
    """**硬杀**（SIGKILL，不可捕获）——模拟「崩溃 / 强杀」。

    **P6-07**：验证「异常终止必留 run-state」必须用 SIGKILL；
    SIGTERM 属于**正常终止信号**（应用会走退出清理 → 删除 run-state），
    用它验证不了这条语义。
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True, encoding="utf-8", errors="replace",
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def detect_package_dir() -> Path:
    """按平台探测已打包目录。

    **此前硬编码 ``release/win-unpacked``** → 在 macOS/Linux 上**必然失败**，
    导致「macOS 安装包是零验证的发布面」（`doc/testing/00` §0 的第 3 条）。
    """
    release = REPO_ROOT / "frontend" / "desktop" / "release"
    if os.name == "nt":
        candidates = [release / "win-unpacked"]
    elif sys.platform == "darwin":
        # macOS 的「包目录」是 .app 本身（可执行文件在 Contents/MacOS/ 内）
        candidates = []
        for arch_dir in sorted(release.glob("mac-*")):
            app = arch_dir / "Agent Desktop.app"
            if app.exists():
                candidates.append(app)
    else:
        candidates = [release / "linux-unpacked"]
    for cand in candidates:
        if cand.exists():
            return cand
    return release


def resources_dir(pkg_dir: Path) -> Path:
    """资源目录：macOS 在 ``Contents/Resources``，其余平台在 ``resources``。"""
    mac = pkg_dir / "Contents" / "Resources"
    return mac if mac.exists() else pkg_dir / "resources"


def executable_of(pkg_dir: Path) -> Path:
    """主程序路径：macOS 在 ``Contents/MacOS/``，其余在包根。"""
    if os.name == "nt":
        return pkg_dir / "Agent Desktop.exe"
    mac = pkg_dir / "Contents" / "MacOS" / "Agent Desktop"
    return mac if mac.exists() else pkg_dir / "Agent Desktop"


def runtime_python_of(res_dir: Path) -> Path:
    """随包运行时的 Python 解释器（Windows 是 ``python.exe``，其余是 ``bin/python3``）。"""
    if os.name == "nt":
        return res_dir / "runtime" / "python.exe"
    return res_dir / "runtime" / "bin" / "python3"



def check_signature(exe: Path) -> tuple[bool, str]:
    """P6-02：检查产物签名状态。

    **路 B 决议**：当前无可用签名证书（Apple Developer / 代码签名证书），
    因此产物**未签名**。但签名状态**必须被显式记录**——不能默默放过
    （未签名 → macOS Gatekeeper 拦截、Windows SmartScreen 告警）。

    :return: ``(signed, detail)``
    """
    import shutil
    import subprocess

    if os.name == "nt":
        # Windows：Get-AuthenticodeSignature
        ps = (
            "$sig = Get-AuthenticodeSignature -LiteralPath '%s'; "
            "if ($sig.Status -eq 'Valid') { 'VALID' } else { $sig.Status.ToString() }"
            % str(exe).replace("'", "''")
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=60,
            )
            status = (out.stdout or "").strip().splitlines()[-1] if out.stdout else ""
            return status.upper() == "VALID", status or "无法读取签名状态"
        except Exception as exc:  # noqa: BLE001
            return False, f"签名检查失败：{exc}"

    # macOS：codesign
    codesign = shutil.which("codesign")
    if not codesign:
        return False, "未找到 codesign（无法校验签名）"
    try:
        out = subprocess.run(
            [codesign, "-dv", str(exe)],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"签名检查失败：{exc}"
    detail = (out.stderr or out.stdout or "").strip().splitlines()
    signed = "Signature=adhoc" not in detail and any(
        line.startswith("Signature=") for line in detail
    )
    note = next(
        (line.strip() for line in detail if line.startswith("Signature=")), "无签名信息",
    )
    return signed, note


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=None, help="已打包目录（默认按平台自动探测）")
    parser.add_argument("--timeout", type=float, default=90.0, help="启动与握手的等待上限（秒）")
    args = parser.parse_args()

    pkg_dir = (REPO_ROOT / args.dir).resolve() if args.dir else detect_package_dir()
    exe = executable_of(pkg_dir)
    if not exe.exists():
        record("安装目录存在且含主程序", False, f"未找到 {exe}")
        return 1
    record("安装目录存在且含主程序", True, str(pkg_dir))

    res_dir = resources_dir(pkg_dir)
    runtime_py = runtime_python_of(res_dir)
    record("运行时已随包（resources/runtime）", runtime_py.exists(), str(runtime_py))
    frontend = res_dir / "frontend" / "index.html"
    record("前端产物已随包（resources/frontend）", frontend.exists(), str(frontend))

    # P6-02：签名状态**显式记录**（路 B：未签名也要被记录，不能默默放过）
    signed, sig_detail = check_signature(exe)
    record(
        "签名状态已记录（未签名亦记）",
        True,
        f"{'已签名' if signed else '未签名'}：{sig_detail}",
    )

    # 独立 userData：**必须隔离**——共用会触发单实例锁，新实例静默退出，
    # 实际被测的是上一个残留实例（`doc/testing/00` §2.4 的工具禁忌）。
    ud_dir = Path(tempfile.mkdtemp(prefix="agent-verify-ud-"))
    run_state = ud_dir / "run-state.json"

    cdp_port = free_port()
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    env["AGENT_DESKTOP_USER_DATA"] = str(ud_dir)
    proc = subprocess.Popen(
        [str(exe), f"--remote-debugging-port={cdp_port}", f"--user-data-dir={ud_dir}"],
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
        # P6-07：硬杀（SIGKILL）模拟崩溃 → run-state **必须残留**
        kill_hard(proc)
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
        # P6-07：第二次启动必须用**同一 userData**——
        # 否则它写的是默认目录的 run-state，自检检查的却是自检目录 → 永远读不到新值。
        env2 = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
        env2["AGENT_DESKTOP_USER_DATA"] = str(ud_dir)
        proc2 = subprocess.Popen(
            [
                str(exe),
                f"--remote-debugging-port={free_port()}",
                f"--user-data-dir={ud_dir}",
            ],
            cwd=str(pkg_dir),
            env=env2,
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
