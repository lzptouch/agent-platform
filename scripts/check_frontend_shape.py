#!/usr/bin/env python3
"""核对**前端实际读取的字段**与 TS 后端的返回键是否一致。

**为什么需要（design/16 §12.3）**：闸门 1 只校验「路径 + 方法」→ TS 后端把
`GET /files` 实现成 `{items,total}`（Python 侧是 `{total,files}`）→ 前端
`items.value = (await filesList()).files` → `undefined` → `items.length` 抛错。

**做法**：
1. 前端 `api/endpoints.ts` → 函数名 → 路径；
2. 前端视图里「API 调用结果」上被读取的属性；
3. TS 后端路由源码里该端点的 `return {` 顶层键；
4. 报告「前端要 X、后端没给」。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "apps" / "ui" / "src"
SERVER = ROOT / "apps" / "server" / "src" / "http" / "routes"

# ---------- ① Endpoints 表 ----------
ep_src = (UI / "api" / "endpoints.ts").read_text(encoding="utf-8")
base_m = re.search(r"API_BASE\s*=\s*['\"]([^'\"]+)['\"]", ep_src)
API_BASE = base_m.group(1) if base_m else "/api/v1"

ep_const: dict[str, str] = {}
for m in re.finditer(r"(\w+):\s*`([^`]+)`", ep_src):
    raw = m.group(2).replace("${API_BASE}", API_BASE)
    raw = re.sub(r"\$\{[^}]+\}", "{param}", raw)
    ep_const[m.group(1)] = raw

# ---------- ② api 封装：函数名 → Endpoints 键 ----------
fn_to_ep: dict[str, str] = {}
for f in sorted((UI / "api").glob("*.ts")):
    if f.name.endswith(".spec.ts") or f.name == "endpoints.ts":
        continue
    s = f.read_text(encoding="utf-8")
    for m in re.finditer(
        r"export const (\w+)\s*=\s*(?:\([^)]*\)|[\w, ]+)?\s*=>\s*"
        r"(?:get|post|put|del|patch)<[^>]*>\(\s*Endpoints\.(\w+)",
        s,
    ):
        fn_to_ep[m.group(1)] = m.group(2)

# ---------- ③ 前端读取的字段 ----------
fields_by_fn: dict[str, set[str]] = {}
pat = re.compile(r"\(await\s+(\w+)\(\)\)\.(\w+)")
pat2 = re.compile(r"\b(\w+)\s*=\s*await\s+(\w+)\(\)[\s\S]{0,40}?\n?\s*[\w.\[\]]*?\.(\w+)\s*=")
for f in list(UI.rglob("*.vue")) + list(UI.rglob("*.ts")):
    if f.name.endswith(".spec.ts"):
        continue
    s = f.read_text(encoding="utf-8")
    for m in pat.finditer(s):
        fields_by_fn.setdefault(m.group(1), set()).add(m.group(2))
    for m in pat2.finditer(s):
        fields_by_fn.setdefault(m.group(2), set()).add(m.group(3))

# ---------- ④ TS 后端路由源码 ----------
server_src = ""
for f in sorted(SERVER.glob("*.ts")):
    server_src += f"\n// ==== {f.name} ====\n" + f.read_text(encoding="utf-8")


def server_keys(path: str) -> set[str] | None:
    """找该路径的 handler，抽取 `return {` 的顶层键。

    ⚠️ **必须逐 handler 切分**（而不是「从注册处往后取 N 字符」）——
    否则会取到**下一个端点**的 return（实测误报：`/workspaces` 取到了
    `/workspaces/{id}/manifest` 的 `{workspace_id, manifest}`）。
    """
    for part in re.split(r"(?=\n\s*app\.(?:get|post|put|delete|patch)\()", server_src):
        m = re.match(
            r'\s*app\.(?:get|post|put|delete|patch)\(\s*["`]' + re.escape(path) + r'["`]',
            part,
        )
        if not m:
            continue
        r = re.search(r"return\s*\{(.{0,900}?)\n\s*\};", part, re.S)
        if not r:
            continue
        body = r.group(1)
        keys = set(re.findall(r"(?m)^\s*(\w+)\s*[:,}]", body))
        # 单行 `{ a: 1, b: 2 }` 也要能取到
        inline = re.search(r"return\s*\{([^\n{}]*)\}", part)
        if inline:
            keys |= set(re.findall(r"(\w+)\s*:", inline.group(1)))
        return keys
    return None


# `.value` 是 Vue `ref` 的取值（不是响应字段）→ 必须排除，否则全是误报
IGNORE = {"length", "map", "filter", "then", "catch", "finally", "toString", "value"}
problems = []
checked = 0
for fn, fields in sorted(fields_by_fn.items()):
    ep = fn_to_ep.get(fn)
    if not ep:
        continue
    path = ep_const.get(ep)
    if not path or "{" in path:
        continue
    keys = server_keys(path)
    if keys is None:
        continue
    checked += 1
    missing = {f for f in fields if f not in keys and f not in IGNORE}
    if missing:
        problems.append((fn, path, sorted(missing), sorted(keys)))

if problems:
    print("❌ 前端读取的字段在 TS 后端响应里**不存在**：\n")
    for fn, path, missing, keys in problems:
        print(f"  {fn}()  →  {path}")
        print(f"      前端要: {missing}")
        print(f"      后端给: {keys}")
    print(f"\n共 {len(problems)} 处不一致（已核对 {checked} 个端点）")
    raise SystemExit(1)

print(f"✅ 前端读取的字段与后端响应键一致（已核对 {checked} 个端点）")
