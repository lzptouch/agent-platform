#!/usr/bin/env python3
"""文档路径/术语映射表（改造前 → 改造后）。

**用途**：批量把文档中的旧实现引用换成新实现引用。
**边界**：只改**路径与术语**，不改语义；历史文档（审计报告 / 整改计划 /
实现交付记录）**不参与**批量替换 —— 它们记录的是「当时」的事实。

**配套门禁**：`scripts/check_doc_paths.py` —— 替换完成后跑它，
确保没有**漏网的旧路径**。

用法：
    python3 scripts/migrate_doc_paths.py --dump          # 只打印映射表
    python3 scripts/migrate_doc_paths.py --apply         # 对「当前实现」文档执行替换
"""
from __future__ import annotations

import io
import re
from pathlib import Path

ROOT = Path("/Users/lizhipeng/workspace/project/agent")

# ---------------------------------------------------------------- 路径映射
PATH_MAP: list[tuple[str, str]] = [
    # ---- Python 后端 → TS 后端 ----
    ("backend/app/main.py", "apps/server/src/main.ts"),
    ("backend/app/core/config.py", "apps/server/src/shared/config.ts"),
    ("backend/app/core/errors.py", "apps/server/src/shared/errors.ts"),
    ("backend/app/core/llm.py", "apps/server/src/shared/llm.ts"),
    ("backend/app/core/logging.py", "apps/server/src/shared/logger.ts"),
    ("backend/app/core/workspace.py", "apps/server/src/domain/workspace/service.ts"),
    ("backend/app/db/models.py", "apps/server/src/db/schema.ts"),
    ("backend/app/db/base.py", "apps/server/src/db/client.ts"),
    ("backend/app/db/migrations/", "apps/server/src/db/"),
    ("backend/app/schemas/", "apps/server/src/http/routes/"),
    ("backend/app/api/v1/system.py", "apps/server/src/http/routes/system.ts"),
    ("backend/app/api/v1/agent.py", "apps/server/src/http/routes/agent.ts"),
    ("backend/app/api/v1/sessions.py", "apps/server/src/http/routes/sessions.ts"),
    ("backend/app/api/v1/runs.py", "apps/server/src/http/routes/runs.ts"),
    ("backend/app/api/v1/teams.py", "apps/server/src/http/routes/teams.ts"),
    ("backend/app/api/v1/schedules.py", "apps/server/src/http/routes/schedules.ts"),
    ("backend/app/api/v1/files.py", "apps/server/src/http/routes/files.ts"),
    ("backend/app/api/v1/mcp_servers.py", "apps/server/src/http/routes/mcp-servers.ts"),
    ("backend/app/api/v1/permissions.py", "apps/server/src/http/routes/permissions.ts"),
    ("backend/app/api/v1/workspace.py", "apps/server/src/http/routes/workspace.ts"),
    ("backend/app/api/v1/context.py", "apps/server/src/http/routes/context.ts"),
    ("backend/app/api/v1/extensions.py", "apps/server/src/http/routes/extensions.ts"),
    ("backend/app/api/v1/rag.py", "apps/server/src/http/routes/rag.ts"),
    ("backend/app/api/v1/web_research.py", "apps/server/src/http/routes/web-research.ts"),
    ("backend/app/api/v1/research.py", "apps/server/src/http/routes/research.ts"),
    ("backend/app/api/v1/desktop.py", "apps/server/src/http/routes/desktop.ts"),
    ("backend/app/api/v1/router.py", "apps/server/src/http/app.ts"),
    ("backend/app/services/agent_service.py", "apps/server/src/domain/agent/"),
    ("backend/app/services/run_executor.py", "apps/server/src/domain/run/executor.ts"),
    ("backend/app/services/run_service.py", "apps/server/src/domain/run/service.ts"),
    ("backend/app/services/session_service.py", "apps/server/src/domain/session/service.ts"),
    ("backend/app/services/scheduler_service.py", "apps/server/src/domain/scheduler/service.ts"),
    ("backend/app/services/scheduler/delivery.py", "apps/server/src/domain/scheduler/delivery.ts"),
    ("backend/app/services/tool_registry.py", "apps/server/src/domain/tools/registry.ts"),
    ("backend/app/services/mcp_manager.py", "apps/server/src/mcp/manager.ts"),
    ("backend/app/services/skill_manager.py", "apps/server/src/domain/skill/manager.ts"),
    ("backend/app/services/code_executor.py", "apps/server/src/workers/sandbox.ts"),
    ("backend/app/services/security/permissions.py", "apps/server/src/domain/security/permissions.ts"),
    ("backend/app/services/security/policy.py", "apps/server/src/domain/security/policy.ts"),
    ("backend/app/services/security/sandbox.py", "apps/server/src/workers/sandbox.ts"),
    ("backend/app/services/chains/mcp/transport.py", "apps/server/src/mcp/transport.ts"),
    ("backend/app/services/research/research_manager.py", "apps/server/src/domain/research/manager.ts"),
    ("backend/app/services/research/orchestrator.py", "apps/server/src/domain/research/orchestrator.ts"),
    ("backend/app/services/workspace/service.py", "apps/server/src/domain/workspace/service.ts"),
    ("backend/app/services/workspace/manifest.py", "apps/server/src/domain/workspace/manifest.ts"),
    ("backend/app/desktop/bootstrap.py", "apps/server/src/http/bootstrap.ts"),
    ("backend/app/desktop/events.py", "apps/server/src/http/events.ts"),
    ("backend/app/desktop/launcher.py", "apps/server/src/main.ts"),
    ("backend/app/services/exec/accounting.py", "apps/server/src/domain/accounting/pricing.ts"),
    ("backend/tests/", "apps/server/tests/"),
    ("backend/skills/", "skills/"),
    ("backend/.env", ".env"),
    # ---- 通用后端目录（按最长优先）----
    ("backend/app/services/scheduler/rrule.py", "apps/server/src/domain/scheduler/rrule.ts"),
    ("backend/app/services/research/research_config.py", "apps/server/src/domain/research/config.ts"),
    ("backend/app/services/research/workers.py", "apps/server/src/domain/research/workers.ts"),
    ("backend/app/services/research/", "apps/server/src/domain/research/"),
    ("backend/app/services/web/serper_service.py", "apps/server/src/domain/web/serper.ts"),
    ("backend/app/services/web/", "apps/server/src/domain/web/"),
    ("backend/app/services/exec/memory.py", "apps/server/src/domain/exec/memory.ts"),
    ("backend/app/services/exec/context.py", "apps/server/src/domain/exec/context.ts"),
    ("backend/app/services/exec/", "apps/server/src/domain/exec/"),
    ("backend/app/services/permissions.py", "apps/server/src/domain/security/permissions.ts"),
    ("backend/app/services/scheduler_service.py", "apps/server/src/domain/scheduler/service.ts"),
    ("backend/app/services/security/", "apps/server/src/domain/security/"),
    ("backend/app/services/chains/", "apps/server/src/domain/"),
    ("backend/app/services/", "apps/server/src/domain/"),
    ("backend/app/core/state.py", "apps/server/src/http/context.ts"),
    ("backend/app/core/uploads.py", "apps/server/src/shared/config.ts"),
    ("backend/app/core/", "apps/server/src/shared/"),
    ("backend/app/desktop/", "apps/server/src/http/"),
    ("backend/app/workers/", "apps/server/src/workers/"),
    ("backend/app/db/", "apps/server/src/db/"),
    ("backend/app/", "apps/server/src/"),
    ("backend/tests/conftest.py", "apps/server/tests/setup.ts"),
    ("backend/tests", "apps/server/tests"),
    ("backend/pyproject.toml", "apps/server/package.json"),
    ("backend/requirements-dev.txt", "apps/server/package.json"),
    ("backend/requirements.txt", "apps/server/package.json"),
    ("backend/.venv/bin/python", "node"),
    ("backend/.venv", "apps/server/node_modules"),
    ("backend/scripts/", "scripts/"),
    ("backend/.env", ".env"),
    ("backend/data/", "data/"),
    ("backend/Dockerfile", "（Docker 形态已退场，无 Dockerfile）"),
    # ---- 前端 ----
    ("frontend/desktop/src/main/", "apps/desktop/src/main/"),
    ("frontend/desktop/src/preload/", "apps/desktop/src/preload/"),
    ("frontend/desktop/src/shared/", "apps/desktop/src/shared/"),
    ("frontend/desktop/src/", "apps/desktop/src/"),
    ("frontend/desktop/", "apps/desktop/"),
    ("frontend/web/vue-element-plus/src/", "apps/ui/src/"),
    ("frontend/web/vue-element-plus/", "apps/ui/"),
    ("frontend/scripts/build-frontend.mjs", "scripts/ui/build-frontend.mjs"),
    ("frontend/scripts/smoke.mjs", "scripts/ui/smoke.mjs"),
    ("frontend/", "apps/"),
]

# ---------------------------------------------------------------- 术语映射
TERM_MAP: list[tuple[str, str]] = [
    ("FastAPI `{\"detail\"", "统一错误体 `{\"code\",\"message\",\"detail\""),
    ("FastAPI 错误归一", "统一错误体归一"),
    ("FastAPI 应用", "Fastify 应用"),
    ("FastAPI", "Fastify"),
    ("uvicorn app.main:app", "node dist/main.js"),
    ("`uvicorn`", "`node dist/main.js`"),
    (".venv/bin/python -m pytest", "npx vitest run"),
    ("backend/.venv/bin/python -m pytest", "npx vitest run"),
    ("pytest tests/", "vitest run"),
    ("pytest `tests/`", "vitest run"),
    ("`pytest`", "`vitest`"),
    ("pytest 用例", "vitest 用例"),
    ("pytest 收集", "vitest 收集"),
    ("pytest 全量", "vitest 全量"),
    ("pytest 回归", "vitest 回归"),
    ("pytest 契约", "vitest 契约"),
    ("pytest 单测", "vitest 单测"),
    ("pytest", "vitest"),
    ("SQLAlchemy 2.0 metadata", "Drizzle schema"),
    ("SQLAlchemy", "Drizzle"),
    ("alembic", "migrations"),
    ("Alembic", "migrations"),
    ("Pydantic", "Zod"),
    ("pydantic", "zod"),
    ("Pydantic v2", "Zod"),
    ("contextvars", "AsyncLocalStorage"),
    ("asyncio.sleep", "setTimeout"),
    ("python-multipart", "@fastify/multipart"),
]

# ---------------------------------------------------------------- 文档分级
#: 历史归档文档 —— 记录的是「当时」的事实，**不做替换**，只加顶部横幅
HISTORICAL = {
    "doc/analysis/18_全面代码审计报告.md",
    "doc/analysis/19_二次全面审计报告.md",
    "doc/plan/07-全面代码审计整改计划.md",
    "doc/plan/08-二次全面审计整改计划.md",
    "doc/design/08-实现交付记录.md",
}

#: 需要批量替换的「当前实现」文档
CURRENT = [
    "README.md",
    "doc/README.md",
    "doc/analysis/00_README.md",
    "doc/analysis/01_架构总览.md",
    "doc/analysis/02_能力链实现.md",
    "doc/analysis/03_Agent执行引擎与事件协议.md",
    "doc/analysis/04_数据模型与持久化.md",
    "doc/analysis/05_HTTP接口总览.md",
    "doc/analysis/06_前端架构与接口契约.md",
    "doc/analysis/07_DeepResearch链路.md",
    "doc/analysis/08_调度与运行账本.md",
    "doc/analysis/09_部署形态与端口矩阵.md",
    "doc/analysis/10_可观测体系现状与方案.md",
    "doc/analysis/11_高并发现状与瓶颈.md",
    "doc/analysis/12_能力覆盖与风险台账.md",
    "doc/analysis/14_权限引擎与安全边界.md",
    "doc/analysis/15_工作区产物与变更回退.md",
    "doc/analysis/16_上下文经济性与成本核算.md",
    "doc/analysis/17_扩展层角色插件与黑板.md",
    "doc/design/00-总体设计.md",
    "doc/design/01-功能需求规格.md",
    "doc/design/02-系统架构设计.md",
    "doc/design/03-桌面壳与后端进程编排设计.md",
    "doc/design/04-本地数据与安全边界设计.md",
    "doc/design/05-数据模型与API设计.md",
    "doc/design/06-前端界面设计.md",
    "doc/design/07-实施路线图与风险.md",
    "doc/design/09-差距矩阵与整改清单.md",
    "doc/design/10-测试与验收策略.md",
    "doc/design/11-竞品对标与设计依据.md",
    "doc/design/13-能力演进与实现对照.md",
    "doc/design/14-测试与发布策略.md",
    "doc/design/15-目标形态与实现状态.md",
    "doc/plan/01-正确性与安全边界.md",
    "doc/plan/02-能力接线与扩展落地.md",
    "doc/plan/03-调度上下文与数据一致性.md",
    "doc/plan/04-前端契约与可观测补齐.md",
    "doc/plan/05-测试体系与CI门禁.md",
    "doc/plan/06-发布形态与规模化.md",
    "doc/plan/README.md",
    "doc/testing/00-全面测试计划.md",
    "doc/knowledge/01_Skill注册表与四级Skill设计.md",
    "doc/knowledge/02_MCP协议原理与stdio实现.md",
    "doc/knowledge/03_Orchestrator-Workers多智能体架构.md",
    "doc/knowledge/04_质量评分迭代与任务持久化.md",
    "doc/knowledge/05_MilvusLite本地化与BM25混合检索.md",
    "doc/knowledge/06_Vue3前端与SSE消费.md",
    "doc/knowledge/07_Langfuse集成与LLM追踪.md",
    "doc/knowledge/09_代码规范.md",
]


def apply(text: str) -> tuple[str, int]:
    n = 0
    for old, new in PATH_MAP:
        if old in text:
            n += text.count(old)
            text = text.replace(old, new)
    for old, new in TERM_MAP:
        if old in text:
            n += text.count(old)
            text = text.replace(old, new)
    return text, n


def main() -> None:
    import sys

    if "--dump" in sys.argv:
        for old, new in PATH_MAP:
            print(f"{old:55s} → {new}")
        print("--- 术语 ---")
        for old, new in TERM_MAP:
            print(f"{old:55s} → {new}")
        return

    total_files = 0
    total_hits = 0
    for rel in CURRENT:
        p = ROOT / rel
        if not p.exists():
            print(f"SKIP（不存在）{rel}")
            continue
        src = p.read_text(encoding="utf-8")
        out, hits = apply(src)
        if hits:
            p.write_text(out, encoding="utf-8")
            total_files += 1
            total_hits += hits
            print(f"  {rel:52s} 替换 {hits:4d} 处")
    print(f"\n完成：{total_files} 个文件，共替换 {total_hits} 处")


if __name__ == "__main__":
    main()
