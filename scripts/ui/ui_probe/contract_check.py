#!/usr/bin/env python3
"""
前后端接口契约比对：前端 api/ 层调用的 (method, path) 是否都在后端 OpenAPI 中注册。

用法：cd backend && .venv/bin/python ../scripts/ui/ui_probe/contract_check.py

## 为什么在进程内读 OpenAPI，而不是 HTTP 拉 /openapi.json

早前实现是 `httpx.get("http://127.0.0.1:18040/openapi.json")`——**依赖一个正在运行的
后端实例**。这带来一个很隐蔽的失效模式：跑着的是**旧代码**的实例时，
检查器拿到的路由表比当前代码少一大截，于是把**已经存在的路由**判成"后端无此路由"。
实测踩过：18040 上有一个 3 天前启动的旧实例（69 个 operation），
而当前代码有 118 个 —— 30 条"不匹配"全是假阳性，门禁形同虚设，
真实契约断裂反而会被淹没。

现在改为**直接 import 当前代码的 app** 并读 ``app.openapi()``：
与运行中的实例无关，永远反映当前代码；也不需要先起服务。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

#: 仓库根（scripts/ui/ui_probe → 上三层）
ROOT = Path(__file__).resolve().parents[3]
#: 后端包所在目录（app.main）
BACKEND = ROOT / "backend"
FRONT = ROOT / "frontend" / "web" / "vue-element-plus" / "src" / "api"

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


#: 路径占位符：前端 ${expr} 与后端 {param} 两种写法
PLACEHOLDER = re.compile(r"\$\{[^}]*\}|\{[^}]*\}")
#: 替换占位符的哨兵（不含 '/'，保证切段安全）
_SENTINEL = "\x00P\x00"


def canon(t: str) -> list[str]:
    """把路径模板切成"段列表"，占位符统一成 '*'。

    Why 用模板分词而不是正则匹配：
      - 前端占位符里带 '/'（如 ``${resourcePath.split('/').map(...).join('/')}``），
        正则没法对齐；
      - FastAPI 的 ``{param:path}`` 能吞多级路径，但 OpenAPI 里只显示 ``{param}``，
        正则同样没法区分。
    先把占位符换成不含 '/' 的哨兵再切段，两侧就都是同构的段列表了。
    """
    t = t.replace("${API_BASE}", "")
    t = PLACEHOLDER.sub(_SENTINEL, t)
    return [seg.replace(_SENTINEL, "*") for seg in t.split("/") if seg]


def same_shape(front: list[str], back: list[str]) -> bool:
    """两侧段列表是否同形：段数相同，且非占位段的字面量一致。"""
    if len(front) != len(back):
        return False
    return all(f == b or f == "*" or b == "*" for f, b in zip(front, back))


def _load_openapi() -> dict:
    """读**当前代码**的 OpenAPI 规范（进程内导入，不依赖运行中的实例）。"""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    try:
        from app.main import app  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 无法导入后端 app（{BACKEND}）：{type(exc).__name__}: {exc}")
        print("  提示：请用后端虚拟环境运行："
              "cd backend && .venv/bin/python ../scripts/ui/ui_probe/contract_check.py")
        raise SystemExit(2) from exc
    return app.openapi()


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

    spec = _load_openapi()
    server_ops: set[tuple[str, str]] = set()
    for path, ops in spec["paths"].items():
        for verb in ops:
            if verb in ("get", "post", "put", "delete", "patch"):
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
        front_segs = canon(path)
        matched = any(
            v == verb and same_shape(front_segs, canon(sp)) for v, sp in server_ops
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
