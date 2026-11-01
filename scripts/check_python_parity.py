#!/usr/bin/env python3
"""**Python ↔ TS 响应键**逐端点对比（契约零差异的「形状维度」）。

**为什么需要（design/16 §12.3）**：闸门 1 只校验「路径 + 方法是否注册」，
**不校验响应体的键** → TS 后端把
- `GET /files` 实现成 `{items,total}`（Python 是 `{total,files}`）
- `GET /workspaces` 实现成 `{items,total}`（Python 是 `{items,current}`）
- `GET /desktop/status` 少了 `runtime` / `components`
- `GET /cost/estimate` 键名完全不同
→ 前端拿到 `undefined` → 渲染报 `Cannot read properties of undefined`。

**做法**：从 **git HEAD**（改造前的 Python 实现）抽出每个 handler 的
`return {…}` 顶层键，与 TS 路由逐 handler 对比。

用法：python3 scripts/check_python_parity.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_ROUTES = ROOT / "apps" / "server" / "src" / "http" / "routes"


def git_show(rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{rel}"],
        capture_output=True,
        text=True,
    )
    return out.stdout if out.returncode == 0 else ""


def git_files(prefix: str, suffix: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "HEAD", "--name-only"],
        capture_output=True,
        text=True,
    )
    return [
        f
        for f in out.stdout.splitlines()
        if f.startswith(prefix) and f.endswith(suffix)
    ]


def top_keys(body: str) -> set[str]:
    """提取 `return {…}` 的**顶层**键（支持单行写法）。"""
    # 兼容 `return {...}` 与 `return reply.code(201).send({...})` 两种写法
    m = re.search(r"return\b[^\n]{0,80}?\{", body)
    if not m:
        return set()
    start = body.index("{", m.start())
    depth = 0
    end = -1
    quote: str | None = None
    for i in range(start, len(body)):
        ch = body[i]
        if quote:
            if ch == quote and body[i - 1] != "\\":
                quote = None
            continue
        if ch in "\"'`":
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return set()
    inner = body[start + 1 : end]

    keys: set[str] = set()
    d = 0
    buf = ""
    for ch in inner:
        if ch in "([{":
            d += 1
        elif ch in ")]}":
            d -= 1
        if ch == "," and d == 0:
            km = re.match(r"\s*[\"']?(\w+)[\"']?\s*:", buf)
            if km:
                keys.add(km.group(1))
            buf = ""
        else:
            buf += ch
    km = re.match(r"\s*[\"']?(\w+)[\"']?\s*:", buf)
    if km:
        keys.add(km.group(1))
    return keys


def python_handlers() -> dict[tuple[str, str], set[str]]:
    """Python 侧：`(METHOD, /api/v1/xxx) -> 返回键`。"""
    out: dict[tuple[str, str], set[str]] = {}
    for rel in git_files("backend/app/api/v1/", ".py"):
        src = git_show(rel)
        if not src:
            continue
        # 路由前缀
        pm = re.search(r'APIRouter\(prefix="([^"]*)"', src)
        prefix = pm.group(1) if pm else ""
        # 逐个 handler：从装饰器到下一个装饰器
        parts = re.split(r"(?=@router\.)", src)
        for part in parts:
            dm = re.match(
                r'@router\.(get|post|put|delete|patch)\(\s*"([^"]*)"', part
            )
            if not dm:
                continue
            method, path = dm.group(1).upper(), dm.group(2)
            raw = path if path.startswith("/api/") else prefix + path
            if not raw.startswith("/"):
                raw = "/" + raw
            # `api_router` 挂在 `/api/v1` 下（见 backend/app/api/v1/router.py）
            out[(method, "/api/v1" + raw)] = top_keys(part)
    return out


def ts_handlers() -> dict[tuple[str, str], set[str]]:
    """TS 侧：`(METHOD, /api/v1/xxx) -> 返回键`。"""
    out: dict[tuple[str, str], set[str]] = {}
    for f in sorted(SERVER_ROUTES.glob("*.ts")):
        src = f.read_text(encoding="utf-8")
        parts = re.split(r"(?=\n\s*app\.(?:get|post|put|delete|patch)\()", src)
        for part in parts:
            dm = re.match(
                r'\s*app\.(get|post|put|delete|patch)\(\s*["`](/api/v1[^"`]*)["`]', part
            )
            if not dm:
                continue
            out[(dm.group(1).upper(), dm.group(2))] = top_keys(part)
    return out


def runtime_keys(path: Path) -> dict[str, dict]:
    """读取 `dump_response_keys.mjs` 导出的**运行时**响应键。"""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    py = python_handlers()
    ts = ts_handlers()
    rt = runtime_keys(Path("/tmp/ts-keys.json"))
    if rt:
        # 以**运行时实际返回**为准（静态解析对 `reply.send({...})` 等写法不可靠）
        # 探针用**假 id**打路径参数端点 → 返回 404 错误体（不是真实响应形状）
        # → 这些端点**跳过**（它们的形状由「路径参数已存在」的前置条件决定）
        ts = {
            (k.split(" ", 1)[0], k.split(" ", 1)[1]): set(v.get("keys", []))
            for k, v in rt.items()
            if v.get("status") != 404
        }
    if not py:
        print("[check] git HEAD 里没有 backend/app/api/v1 → 跳过")
        return 0

    problems = []
    compared = 0
    for (method, path), py_keys in sorted(py.items()):
        ts_keys = ts.get((method, path))
        if ts_keys is None:
            continue
        compared += 1
        missing = py_keys - ts_keys
        if missing:
            problems.append((method, path, sorted(missing), sorted(ts_keys)))

    if problems:
        print("❌ 以下端点的 TS 响应**缺少** Python 侧有的键：\n")
        for method, path, missing, keys in problems:
            print(f"  {method:<6} {path}")
            print(f"      Python 有: {missing}")
            print(f"      TS     有: {keys}")
        print(f"\n共 {len(problems)} 处（已比对 {compared} 个端点）")
        return 1

    print(f"✅ 所有端点的响应键与改造前（Python）一致（已比对 {compared} 个端点）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
