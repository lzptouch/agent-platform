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
#: **旧 Python 后端已退场**（design/16 §11.10 · P8-04）→ 不再有 `backend/` 路径。
BACKEND = REPO / "backend"  # 仅保留常量，历史脚本引用时不报错

FACTS: dict = {}


# ---------------------------------------------------------------- API
def collect_api() -> None:
    # **改造要点（design/16 §11.10 · P8-04）**：改读**冻结的 OpenAPI 契约**
    # （`contract/openapi.json`）—— 旧后端退场后不再从运行中的应用取。
    spec_path = REPO / "contract" / "openapi.json"
    if not spec_path.exists():
        FACTS["api"] = {"path_count": 0, "operation_count": 0, "operations": [],
                        "tag_count": 0}
        return
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
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
    """**冻结 DDL** 解析出的表清单（`contract/tables.sql`）。

    **改造要点（design/16 §11.10 · P8-04）**：SQLAlchemy 元数据不可用
    （旧后端退场）→ 改为解析契约冻结的 DDL —— 这本来就是「被测对象必须
    等于的基准」，比从运行中的 ORM 取更稳定。
    """
    tables = []
    ddl_path = REPO / "contract" / "tables.sql"
    if ddl_path.exists():
        text = ddl_path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"(?is)CREATE TABLE\s+(?:IF NOT EXISTS\s+)?[\"\`]?(\w+)[\"\`]?\s*\((.*?)\n\s*\)\s*;",
            text,
        ):
            name, body = match.group(1), match.group(2)
            cols = [
                c.strip()
                for c in re.split(r",\s*(?=\n)", body)
                if c.strip() and not re.match(
                    r"(?i)^(PRIMARY KEY|FOREIGN KEY|UNIQUE|CHECK|CONSTRAINT)\b", c.strip()
                )
            ]
            tables.append({
                "name": name,
                "columns": len(cols),
                "indexes": 0,
                "constraints": 0,
                "column_names": [
                    re.match(r'^[\"\`]?(\w+)', c).group(1)  # type: ignore[union-attr]
                    for c in cols
                ],
            })
        tables.sort(key=lambda t: t["name"])

    # **改造要点（design/16 §11.10 · P8-04）**：Alembic 迁移链已退场，
    # 改为记录 TS 侧的迁移机制（`__migrations` + 基线 DDL）。
    versions = [{
        "file": "baseline-sql.ts",
        "revision": "0000_baseline",
        "down_revision": None,
    }]

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
        # **改造要点（design/16 §11.10 · P8-04）**：旧 Python 后端退场，
        # 规模统计改为「TS 后端 + Vue 渲染层 + Electron 壳 + 根级 E2E」。
        ("apps/server", REPO / "apps" / "server" / "src"),
        ("apps/server/tests", REPO / "apps" / "server" / "tests"),
        ("apps/ui", REPO / "apps" / "ui" / "src"),
        ("apps/desktop", REPO / "apps" / "desktop" / "src"),
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
    """**TS 后端**的配置字段清单。

    **改造要点（design/16 §11.10 · P8-04）**：旧 Python 后端退场后，
    不再能 ``from app.core.config import settings`` → 改为解析 TS 侧的
    `Settings` 接口字段（`apps/server/src/shared/config.ts`）。
    """
    src = (REPO / "apps" / "server" / "src" / "shared" / "config.ts").read_text(
        encoding="utf-8"
    )
    body = src.split("export interface Settings", 1)[-1].split("\n}", 1)[0]
    fields = sorted(set(re.findall(r"(?m)^\s{2}(readonly\s+)?([a-z_][a-z0-9_]*)\??:", body)))
    FACTS["config"] = {"count": len(fields), "fields": fields}


# ---------------------------------------------------------------- 事件类型
def collect_events() -> None:
    """**冻结契约**里的事件类型清单（`contract/events.json`）。

    **改造要点（design/16 §11.10 · P8-04）**：改读契约冻结产物，
    不再从（已退场的）Python 源码里正则提取。
    """
    path = REPO / "contract" / "events.json"
    if not path.exists():
        FACTS["events"] = {"count": 0, "types": []}
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data.get("agentEvents", [])
    types = sorted(
        e.get("name", "") if isinstance(e, dict) else str(e) for e in events
    )
    FACTS["events"] = {
        "count": len(types),
        "types": types,
        "sse_endpoints": [e.get("endpoint", "") for e in data.get("sse", [])],
    }


# ---------------------------------------------------------------- 工具
def collect_tools() -> None:
    src = (
        REPO / "apps" / "server" / "src" / "domain" / "tools" / "registry.ts"
    ).read_text(encoding="utf-8")
    names = sorted(set(re.findall(r'(?<![\w"])name:\s*"([a-z0-9_]+)"', src)))
    FACTS["tools"] = {"count": len(names), "names": names}


# ---------------------------------------------------------------- MCP
def collect_mcp() -> None:
    # **改造要点（design/16 §11.10 · P8-04）**：MCP 服务清单改从 TS 源码提取。
    mcp_dir = REPO / "apps" / "server" / "src" / "mcp" / "servers"
    src = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(mcp_dir.glob("*.ts"))
    ) if mcp_dir.exists() else ""

    reg = sorted(set(re.findall(r'(?<![\w"])name:\s*"([a-z0-9_]+)"', src)))
    FACTS["mcp"] = {
        "builtin_count": len(reg),
        "builtin": reg,
        "transports": ["stdio", "sse", "http"],
    }


# ---------------------------------------------------------------- 前端 API 封装
def collect_frontend() -> None:
    # **改造要点（design/16 §11.10 · P8-04）**：前端已迁入 `apps/ui/`。
    src = REPO / "apps" / "ui" / "src"
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
