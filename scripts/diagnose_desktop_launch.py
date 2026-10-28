#!/usr/bin/env python
"""桌面端启动诊断：抓取「壳的主进程输出 + 错误页内容 + 后端日志」。

用途：打包态出现「窗口没加载到后端页面」时，定位到底是 sidecar 没起来、
握手没收到，还是页面加载失败。

用法：
    backend/.venv/Scripts/python.exe scripts/diagnose_desktop_launch.py --dir frontend/desktop/release/win-unpacked
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def http_json(url: str, timeout: float = 4.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def main() -> int:
    # Windows 控制台默认 GBK，日志里可能有 UTF-8 字符 → 强制 UTF-8 输出
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="frontend/desktop/release/win-unpacked")
    ap.add_argument("--wait", type=float, default=45.0)
    args = ap.parse_args()

    pkg_dir = (REPO_ROOT / args.dir).resolve()
    exe = pkg_dir / ("Agent Desktop.exe" if os.name == "nt" else "Agent Desktop")
    if not exe.exists():
        print(f"[FAIL] 未找到可执行文件: {exe}")
        return 1

    cdp = free_port()
    out_path = Path(os.environ.get("TEMP", "/tmp")) / "wb-shell-stdout.log"
    log = open(out_path, "wb")
    env = {k: v for k, v in os.environ.items() if k != "ELECTRON_RUN_AS_NODE"}
    proc = subprocess.Popen(
        [str(exe), f"--remote-debugging-port={cdp}"],
        cwd=str(pkg_dir),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    print(f"[INFO] 已启动 {exe}（pid={proc.pid}，调试端口 {cdp}）")

    try:
        deadline = time.time() + args.wait
        targets: list[dict] = []
        while time.time() < deadline:
            status, body = http_json(f"http://127.0.0.1:{cdp}/json/list")
            if status == 200:
                try:
                    targets = json.loads(body)
                except json.JSONDecodeError:
                    targets = []
                if targets:
                    break
            time.sleep(1.0)

        print("\n=== 1) 窗口目标（CDP /json/list）===")
        if not targets:
            print("（无目标：主进程可能未创建窗口）")
        for t in targets:
            print(f"- type={t.get('type')} title={t.get('title')!r}")
            print(f"  url={t.get('url')}")

        print("\n=== 2) 错误页内容（若窗口停在 data: URL）===")
        for t in targets:
            url = t.get("url") or ""
            if url.startswith("data:"):
                html = urllib.parse.unquote(url.split(",", 1)[1])
                text = re.sub(r"<[^>]+>", " ", html)
                text = re.sub(r"\s+", " ", text).strip()
                print(text[:1200])

        print("\n=== 3) 壳主进程 stdout/stderr ===")
        log.flush()
        raw = out_path.read_bytes().decode("utf-8", errors="replace")
        print(raw[-3000:] if raw else "（无输出）")

        print("\n=== 4) 后端日志尾部 ===")
        appdata = os.environ.get("APPDATA") or os.environ.get("HOME") or ""
        pkg = json.loads((REPO_ROOT / "frontend" / "desktop" / "package.json").read_text(encoding="utf-8"))
        blog = Path(appdata) / (pkg.get("productName") or "Agent Desktop") / "logs" / "backend.log"
        if blog.exists():
            print(blog.read_bytes().decode("utf-8", errors="replace")[-2500:])
        else:
            print(f"（无后端日志：{blog}）")

        print("\n=== 5) run-state ===")
        rs = blog.parent.parent / "run-state.json"
        print(rs.read_text(encoding="utf-8", errors="replace") if rs.exists() else "（未生成）")
    finally:
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                )
            else:
                proc.terminate()
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
