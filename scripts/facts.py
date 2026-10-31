"""从代码提取**机器可验证的事实**——文档更新的唯一依据。

产出（JSON）：
- api: 端点路径 / 操作数 / 每条端点的方法+路径+摘要
- db: ORM 表清单、列数、迁移版本链
- modules: 后端各包的文件数与行数
- tests: 各测试目录的用例数
- config: settings 的全部字段
- events: agent_service 产出的事件类型
- tools: 工具注册表
- mcp: MCP Server 注册表
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

FACTS: dict = {}


# ---------------------------------------------------------------- API
def collect_api() -> None:
    from app.main import app

    spec = app.openapi()
    paths = spec.get("paths", {})
    ops: list[dict] = []
    for path, methods in sorted(paths.items()):
        for method, info in methods.items():
            if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                continue
            ops.append({
                "method": method.upper(),
                "path": path,
                "summary": (info.get("summary") or "").strip(),
                "tags": info.get("tags") or [],
            })
    FACTS["api"] = {
        "path_count": len(paths),
        "operation_count": len(ops),
        "operations": ops,
        "tag_count": len({t for o in ops for t in o["tags"]}),
    }


# ---------------------------------------------------------------- DB
def collect_db() -> None:
    from app.db.models import Base

    tables = []
    for name, table in sorted(Base.metadata.tables.items()):
        tables.append({
            "name": name,
            "columns": len(table.columns),
            "indexes": len(table.indexes),
            "constraints": len(table.constraints),
            "column_names": [c.name for c in table.columns],
        })

    versions = []
    mig_dir = BACKEND / "app" / "db" / "migrations" / "versions"
    for f in sorted(mig_dir.glob("*.py")):
        if f.name.startswith("__"):
            continue
        text = f.read_text(encoding="utf-8")
        rev = re.search(r'^revision\s*=\s*["\']([^"\']+)', text, re.M)
        down = re.search(r'^down_revision\s*=\s*["\']([^"\']+)', text, re.M)
        versions.append({
            "file": f.name,
            "revision": rev.group(1) if rev else None,
            "down_revision": down.group(1) if down else None,
        })

    FACTS["db"] = {
        "table_count": len(tables),
        "tables": tables,
        "migration_count": len(versions),
        "migrations": versions,
        "head": versions[-1]["revision"] if versions else None,
    }


# ---------------------------------------------------------------- 模块规模
def collect_modules() -> None:
    out = {}
    for group, base in (
        ("backend/app", BACKEND / "app"),
        ("backend/tests", BACKEND / "tests"),
        ("frontend/web", REPO / "frontend" / "web" / "vue-element-plus" / "src"),
        ("frontend/desktop", REPO / "frontend" / "desktop" / "src"),
        ("tests", REPO / "tests"),
    ):
        files, lines = 0, 0
        for p in base.rglob("*"):
            if p.is_dir() or "node_modules" in p.parts:
                continue
            if p.suffix not in (".py", ".ts", ".vue", ".mjs", ".js"):
                continue
            files += 1
            try:
                lines += len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError:
                pass
        out[group] = {"files": files, "lines": lines}
    FACTS["modules"] = out


# ---------------------------------------------------------------- 配置
def collect_config() -> None:
    from app.core.config import settings

    fields = {}
    for name in dir(settings):
        if name.startswith("_"):
            continue
        val = getattr(settings, name, None)
        if callable(val):
            continue
        fields[name] = type(val).__name__
    FACTS["config"] = {"count": len(fields), "fields": sorted(fields)}


# ---------------------------------------------------------------- 事件类型
def collect_events() -> None:
    src = (BACKEND / "app" / "services" / "agent_service.py").read_text(encoding="utf-8")
    types = sorted(set(re.findall(r'"type":\s*"([a-z_]+)"', src)))
    FACTS["events"] = {"count": len(types), "types": types}


# ---------------------------------------------------------------- 工具
def collect_tools() -> None:
    src = (BACKEND / "app" / "services" / "tool_registry.py").read_text(encoding="utf-8")
    names = sorted(set(re.findall(r'"name":\s*"([a-z_]+)"', src)))
    FACTS["tools"] = {"count": len(names), "names": names}


# ---------------------------------------------------------------- MCP
def collect_mcp() -> None:
    from app.services.mcp_manager import MCPManager

    reg = MCPManager.SERVER_REGISTRY
    FACTS["mcp"] = {
        "builtin_count": len(reg),
        "builtin": sorted(reg),
        "transports": ["stdio", "sse", "http"],
    }


# ---------------------------------------------------------------- 前端 API 封装
def collect_frontend() -> None:
    src = REPO / "frontend" / "web" / "vue-element-plus" / "src"
    api = src / "api" / "index.ts"
    text = api.read_text(encoding="utf-8") if api.exists() else ""
    exports = sorted(set(re.findall(r"export const (\w+)\s*=", text)))
    specs = sorted(p.name for p in src.rglob("*.spec.ts"))
    FACTS["frontend"] = {
        "api_export_count": len(exports),
        "api_exports": exports,
        "spec_files": len(specs),
        "spec_names": specs,
    }


def main() -> None:
    collect_api()
    collect_db()
    collect_modules()
    collect_config()
    collect_events()
    collect_tools()
    collect_mcp()
    collect_frontend()

    out = REPO / "tests" / "report" / "facts.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(FACTS, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"facts → {out}")
    print(f"  API: {FACTS['api']['path_count']} 路径 / {FACTS['api']['operation_count']} 操作")
    print(f"  DB: {FACTS['db']['table_count']} 表 / {FACTS['db']['migration_count']} 迁移 (head={FACTS['db']['head']})")
    print(f"  配置: {FACTS['config']['count']} 项")
    print(f"  事件: {FACTS['events']['count']} 类型")
    print(f"  工具: {FACTS['tools']['count']} 个")
    print(f"  MCP: {FACTS['mcp']['builtin_count']} 个内置")
    print(f"  前端: {FACTS['frontend']['api_export_count']} 个 API 封装 / {FACTS['frontend']['spec_files']} 个 spec")


if __name__ == "__main__":
    main()
