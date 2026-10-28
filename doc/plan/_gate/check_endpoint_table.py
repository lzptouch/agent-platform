"""校验 `doc/analysis/05_HTTP接口总览.md` 的端点表与真实 OpenAPI 是否一致。

- 文档里写的路径必须在代码里存在（不能写过时的端点）；
- 代码里有的路径必须在文档里出现（不能漏）。

用法：python doc/plan/_gate/check_endpoint_table.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "doc" / "analysis" / "05_HTTP接口总览.md"

sys.path.insert(0, str(ROOT / "backend"))


def code_endpoints() -> set[tuple[str, str]]:
    from app.main import app

    spec = app.openapi()
    out: set[tuple[str, str]] = set()
    for path, methods in spec.get("paths", {}).items():
        for method in methods:
            if method in ("get", "post", "put", "patch", "delete"):
                out.add((method.upper(), path))
    return out


def doc_endpoints(text: str) -> set[tuple[str, str]]:
    """从文档表格里抽 (METHOD, path)。"""
    out: set[tuple[str, str]] = set()
    # 格式 A：`| \`GET /api/v1/xxx\` | ...`（手写表，方法与路径同格）
    for m in re.finditer(r"\|\s*`?([A-Z]+)\s+(/api/v1[^`|\s]*)`?\s*\|", text):
        method, path = m.group(1).upper(), m.group(2)
        if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            out.add((method, path))
    # 格式 B：`| \`GET\` | \`/api/v1/xxx\` | ...`（OpenAPI 导出表，方法与路径分格）
    for m in re.finditer(r"\|\s*`([A-Z]+)`\s*\|\s*`(/api/v1[^`]+)`\s*\|", text):
        method, path = m.group(1).upper(), m.group(2)
        if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            out.add((method, path))
    return out


def main() -> int:
    text = io.open(DOC, encoding="utf-8").read()
    code = code_endpoints()
    doc = doc_endpoints(text)

    # 路径参数归一（{run_id} 之类要一致，这里只比较字面量）
    missing_in_doc = sorted(code - doc)
    missing_in_code = sorted(doc - code)

    print(f"代码端点 {len(code)} 个（方法×路径）｜文档端点 {len(doc)} 个")
    if missing_in_doc:
        print(f"\n[X] 代码有、文档漏（{len(missing_in_doc)}）：")
        for method, path in missing_in_doc:
            print(f"    {method:6} {path}")
    if missing_in_code:
        print(f"\n[X] 文档有、代码无（{len(missing_in_code)}）：")
        for method, path in missing_in_code:
            print(f"    {method:6} {path}")
    if not missing_in_doc and not missing_in_code:
        print("\n[OK] 文档端点表与代码完全一致")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
