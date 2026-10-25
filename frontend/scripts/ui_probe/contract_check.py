#!/usr/bin/env python3
"""
前后端接口契约比对：前端 api/ 层调用的 (method, path) 是否都在后端 OpenAPI 中注册。

用法：cd backend && .venv/bin/python ../frontend/scripts/ui_probe/contract_check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:18040"
FRONT = Path(__file__).resolve().parents[2] / "web" / "vue-element-plus" / "src" / "api"

# 前端 api/index.ts: export const xxx = (args) => get/post/put/patch/del/upload<...>(Endpoints.yyy)
# 前端 api/endpoints.ts: key: (args) => `${API_BASE}/path`
CALL = re.compile(
    r"export\s+const\s+(\w+)\s*=\s*\([^)]*\)\s*=>\s*(get|post|put|patch|del|upload)\s*<[^>]*>?\s*\(\s*Endpoints\.(\w+)",
    re.S,
)
# 箭头函数形式： export const xxx = (a) => get(...)(Endpoints.yyy)
CALL2 = re.compile(
    r"export\s+const\s+(\w+)\s*=\s*\n?\s*\(?[^)]*\)?\s*=>\s*\n?\s*(get|post|put|patch|del|upload)\b",
    re.S,
)
# endpoints.ts 里紧跟 Endpoints.yyy 的模板字符串
EP = re.compile(r"(\w+):\s*(?:\([^)]*\)\s*=>\s*)?`([^`]+)`")
DYN = re.compile(r"(\w+):\s*\([^)]*\)\s*=>\s*`([^`]+)`")

HTTP = {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH", "del": "DELETE", "upload": "POST"}


def norm_template(t: str) -> str:
    """把模板字符串转成正则：{name} -> [^/]+，${API_BASE} 前缀去掉"""
    t = t.replace("${API_BASE}", "").replace("${API_BASE}", "")
    t = re.sub(r"\$\{[^}]+\}", "{p}", t)
    return "^" + re.sub(r"\{[^}]+\}", "[^/]+", t) + "$"


def main() -> int:
    idx = (FRONT / "index.ts").read_text(encoding="utf-8")
    eps = (FRONT / "endpoints.ts").read_text(encoding="utf-8")

    endpoints: dict[str, str] = {}
    for m in DYN.finditer(eps):
        endpoints[m.group(1)] = m.group(2)
    for m in EP.finditer(eps):
        endpoints.setdefault(m.group(1), m.group(2))

    # 解析每个导出函数 → (http method, endpoint key)
    calls: list[tuple[str, str, str]] = []
    for m in re.finditer(
        r"export\s+const\s+(\w+)\s*=\s*(.*?)(?=\nexport\s+const\s|\n//|\Z)", idx, re.S
    ):
        name, body = m.group(1), m.group(2)
        mm = re.search(r"\b(get|post|put|patch|del|upload)\s*<", body)
        if not mm:
            mm = re.search(r"\b(get|post|put|patch|del|upload)\s*\(", body)
        if not mm:
            continue
        verb = HTTP[mm.group(1)]
        for ep in re.findall(r"Endpoints\.(\w+)", body):
            calls.append((name, verb, ep))

    spec = httpx.get(f"{BASE}/openapi.json", timeout=20).json()
    server_ops: set[tuple[str, str]] = set()
    for path, ops in spec["paths"].items():
        for verb in ops:
            server_ops.add((verb.upper(), path))

    print(f"前端 API 导出函数：{len(calls)} 个调用点")
    print(f"后端 OpenAPI operation：{len(server_ops)} 个\n")

    bad: list[tuple[str, str, str]] = []
    ok = 0
    seen: set[tuple[str, str]] = set()
    for name, verb, ep in calls:
        tpl = endpoints.get(ep)
        if tpl is None:
            bad.append((name, verb, f"endpoints.ts 中找不到 {ep}"))
            continue
        path = "/api/v1" + tpl.replace("${API_BASE}", "")
        key = (verb, path)
        if key in seen:
            continue
        seen.add(key)
        matched = any(
            v == verb and re.match(norm_template(sp), path) for v, sp in server_ops
        )
        if matched:
            ok += 1
        else:
            bad.append((name, f"{verb} {path}", "后端无此路由"))

    print(f"契约匹配：{ok} 通过，{len(bad)} 不匹配")
    if bad:
        print("\n不匹配明细：")
        for name, sig, why in bad:
            print(f"  ✗ {name:26} {sig:52} {why}")
        print("\n→ 需修复：前端改 method/path，或后端补路由")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
