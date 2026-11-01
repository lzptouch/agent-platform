#!/usr/bin/env python3
"""核对冻结 OpenAPI 契约里 **200 响应是数组** 的端点，与 TS 实现的返回形状。

**为什么需要**：闸门 1 只校验「路径 + 方法是否注册」，**不校验响应形状** →
TS 后端把 `GET /teams` 实现成 `{items:[...]}` 而契约要求**裸数组** → 前端
`teams.value = await teamsList()` 拿到对象 → el-table 报 `Me is not iterable`。

用法：python3 scripts/check_response_shape.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contract" / "openapi.json"
ROUTES = ROOT / "apps" / "server" / "src" / "http" / "routes"

spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
schemas = spec.get("components", {}).get("schemas", {})


def resolve(node: dict) -> dict:
    """解开 $ref。"""
    ref = node.get("$ref")
    if not ref:
        return node
    name = ref.split("/")[-1]
    return schemas.get(name, node)


def array_responses() -> list[tuple[str, str]]:
    out = []
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            resp = op.get("responses", {}).get("200", {}).get("content", {}).get(
                "application/json", {}
            ).get("schema", {})
            r = resolve(resp)
            if r.get("type") == "array":
                out.append((path, method.upper()))
    return out


# TS 路由源码里，形如 `return { items: ... }` 的返回
src_all = ""
for f in sorted(ROUTES.glob("*.ts")):
    src_all += f"\n// ==== {f.name} ====\n" + f.read_text(encoding="utf-8")

print(f"契约中 200 响应为**数组**的端点：{len(array_responses())} 个\n")

problems = []
for path, method in array_responses():
    # 在 TS 源码里找该路径的注册处
    key = path.replace("/api/v1", "").replace("{", "").replace("}", "")
    m = re.search(
        rf'app\.(get|post|put|delete)\(\s*["`]{re.escape(path)}["`]',
        src_all,
    )
    if not m:
        continue
    # 取该注册处之后 1500 字符，找 `return { items:` 之类
    idx = m.start()
    chunk = src_all[idx : idx + 1500]
    ret = re.search(r"return\s*\{[^}]*?\bitems\b", chunk, re.S)
    if ret:
        problems.append((path, method, ret.group(0).replace("\n", " ")[:70]))

if problems:
    print("❌ 以下端点的 TS 实现返回了 `{items:...}`，但契约要求**裸数组**：\n")
    for path, method, snippet in problems:
        print(f"  {method:<6} {path}")
        print(f"         → {snippet}")
    print(f"\n共 {len(problems)} 处形状不一致")
    raise SystemExit(1)

print("✅ 所有「数组型」端点的响应形状与契约一致")
