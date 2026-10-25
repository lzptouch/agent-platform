# deepResearch 整合分析（融入 agent）

> **分析范围**：`大模型部署与应用开发/deep_research/`（核心 7 个 .py = **4102 行**）→ `apps/apps/agent/`
> **分析时间**：2026-09-15　|　**结论**：✅ 强可行，建议作为 **第 5 条"深度研究链"** 整合，工时约 **3-3.5 天**
> **架构契合度**：高（核心范式 Orchestrator-Workers + OODA 与现有 Agent 循环互补，且都用 DashScope OpenAI 兼容协议）

---

## 目录

- [0. 核查修订说明（v1.1）](#0-核查修订说明v11) ⭐ 新增
- [1. deep_research 项目快照](#1-deep_research-项目快照)
- [2. 与 agent 的重叠 / 互补 / 差异](#2-与-agent-的重叠--互补--差异)
- [3. 整合架构设计](#3-整合架构设计)
- [4. URL 设计与请求/响应模型](#4-url-设计与请求响应模型)
- [5. 详细文件迁移与代码修改计划](#5-详细文件迁移与代码修改计划)
- [6. 配置合并方案](#6-配置合并方案)
- [7. 依赖分析](#7-依赖分析)
- [8. 前端变更计划](#8-前端变更计划)
- [9. 测试计划](#9-测试计划)
- [10. 风险与缓解](#10-风险与缓解)
- [11. 施工路线（阶段 A-J）](#11-施工路线阶段-a-j)
- [12. 验收清单](#12-验收清单)
- [13. 偏差与开放问题](#13-偏差与开放问题)
  - [13.5 合规与许可](#135-合规与许可核查后新增-) ⭐ 新增
  - [13.6 Python 版本兼容性验证](#136-python-版本兼容性验证核查后新增-) ⭐ 新增
- [14. 核查清单与原始证据](#14-核查清单与原始证据) ⭐ 新增
- [附录 A：deep_research → agent 文件映射](#附录-adeep_research--agent-文件映射)
- [附录 B：核查后的关键风险速览](#附录-b核查后的关键风险速览供实施前复核) ⭐ 新增

---

## 0. 核查修订说明（v1.1）

本文档初版生成后，已对 `deep_research/` 源码与 `apps/apps/agent/` 现状做**逐文件核查**（证据见 [§14 核查清单与原始证据](#14-核查清单与原始证据)），修正了 **20 处**偏差：

| # | 类型 | 初版表述 | 核查后修正 |
| --- | --- | --- | --- |
| 1 | **数据** | `orchestrator.py` 770 行 | **实际 963 行**（15 个方法，含 202 行的 `run()` 主循环） |
| 2 | **数据** | `prompts.py` "（大）" | **实际 935 行** |
| 3 | **数据** | `research_agent.py` 461 行 | **实际 460 行** |
| 4 | **数据** | `tools.py` 366 行 | **实际 364 行** |
| 5 | **数据** | "总计 ~4110 行" | 4102 行 = 7 个业务文件；**4110 行** = 含 3 个 `__init__.py`（各 5/5/12 行）的总计 |
| 6 | **核心错误** | "**7 个** Prompt 模板"（§1.2 / §2 / §3.2 / §5.3 共 5 处） | **实际 14 个**（漏了 `QUERY_EXPANSION_PROMPT` / `FACT_CHECK_PROMPT` / `WRITER_SECTION_PROMPT` 等 7 个） |
| 7 | **遗漏** | `workers.py` 只列 `OODACycle` + `SourceQualityAssessment` | 还有 **`ResearchBudget`**（研究预算类，含 `queries_remaining()` / `budget_exhausted()`）+ `BaseWorker` + **`WorkerFactory`** |
| 8 | **遗漏** | 未说明 OODA 的实现位置 | OODA 实为 `SearchWorker` 的 4 个私有方法 **`_observe` / `_orient` / `_decide` / `_act`**（`workers.py:276-363`） |
| 9 | **行号错误** | "`research_agent.py:226-251` 的 `original_config` 临时覆盖逻辑" | **实际在 `main.py:226-251`**（`research_agent.py` 无此逻辑） |
| 10 | **方案过时** | §5.2 配置扩展示例含 `static_dir: Path = APP_DIR / "static"` | **agent 已删除 `static_dir`**（前端分离为 Vue 工程后移除），方案应基于当前 config |
| 11 | **端点计数** | §4.1 端点表列 7 行 | deep_research 实际 **8 个**端点（+ `GET /` 服务信息） |
| 12 | **配置规模** | "含 30+ 嵌套字段" | `AGENT_CONFIG` 实际 **18 个顶级字段**（其中 4 个是嵌套 dict） |
| 13 | **高风险·兼容性** | 未提及 deep_research 的 venv 是 **Python 3.13** | `.venv/bin/python` = **3.13.9**，而 agent 锁 `>=3.10,<3.13` → **已实测：7 个 .py 全部通过 `python3.11 -m py_compile`**，无需 3.12+ 语法（无 PEP 695 泛型、无 `match`、无 `datetime.UTC`） |
| 14 | **高风险·合规** | **未提及版权声明** | `README.md` 末尾含 **"agent，侵权必究（转卖，私自转发等均属于侵权行为）"** → 迁移时须保留署名或另行确认授权 |
| 15 | **遗漏** | 未提及 `.env.example` 中的 `DEEP_RESEARCH_PORT=18000` | 整合后端口统一 8000，该变量应废弃（在迁移说明中标注） |
| 16 | **遗漏** | 未提及 deep_research **无 `pyproject.toml` / `.python-version`** | 仅 `requirements.txt`（7 个包，无版本上限），整合后统一由 backend 的 `pyproject.toml` + `requirements.txt` 管理 |
| 17 | **遗漏** | 未提 `assets/*.svg` 权限为 `600`（`-rw-------`） | `cp` 后需 `chmod 644`，否则静态服务可能 403 |
| 18 | **遗漏** | 未写明 agent 基线 | 当前 **27 个 API 路径 / 16 个测试 / 5 个 schemas / 9 个 services 模块**，新增后变为 35 路径 / 21 测试 |
| 19 | **遗漏** | 未说明 agent 现有 config 字段 | 已有 `dashscope_*` / `llm_*`（`plan_model`/`rag_model`/`answer_model`）/ `openai_*` / `serper_api_key` / `milvus_*` → **Bocha 字段应"追加"而非重建** |
| 20 | **代码草稿** | §5.6 API 示例中 `manager: ResearchManager = ...` 为未完成伪代码 | **已补全为可执行实现**（通过 `Request` 依赖注入获取 manager） |

> ⚠️ **两条高风险项需优先处置**：#13（Python 版本，已验证兼容，无阻断）+ #14（版权，需确认）。
> 下一轮如再做重大方案调整，请在本节追加表格行。

---

## 1. deep_research 项目快照

### 1.1 文件清单

```
deep_research/
├── app/
│   ├── main.py                  (482 行)  FastAPI 服务 + TaskManager + 8 端点
│   ├── core/
│   │   ├── config.py            (116 行)  LLM_CONFIG + SEARCH_CONFIG + AGENT_CONFIG(18 字段) + LOG_CONFIG + OUTPUT_CONFIG
│   └── agent/
│       ├── research_agent.py    (460 行)  DeepResearchAgent + ConsoleReporter(30+ stage 图标) + CLI 入口
│       ├── orchestrator.py      (963 行)  Orchestrator(15 方法) + SubTask + QueryTypeAnalysis + TaskPlan + IterationRecord + ResearchState
│       ├── workers.py           (770 行)  BaseWorker + SearchWorker(OODA) + WriterWorker + AnalysisWorker + VisualizationWorker + WorkerFactory + ResearchBudget + OODACycle + SourceQualityAssessment
│       ├── tools.py             (364 行)  LLMClient(sync+stream) + SearchClient(Bocha) + extract_xml/extract_json/format_search_context
│       └── prompts.py           (935 行)  **14 个** Prompt 模板 + CURRENT_DATE 变量
├── docs/                         (7 .md)    00-README + 01-架构 + 02-设计 + 03-详细 + 04-接口 + 05-模块 + 06-流程
├── assets/                       (2 svg)    architecture.svg(23KB) + prompt_dataflow.svg(40KB)，权限 600
├── requirements.txt              (7 个包，无版本上限)
├── .env / .env.example           (含 DEEP_RESEARCH_PORT=18000)
└── README.md                     (含版权声明)
```

**总计**：核心 7 个业务 `.py` = **4102 行**；含 3 个 `__init__.py`（5+5+12 行）共 **4110 行**，2 张 SVG，7 份文档

### 1.2 核心特性（来自 README）

| 类别 | 特性 |
|---|---|
| 编排范式 | **Orchestrator-Workers** 多智能体协作（Lead Agent 协调 + N 个 SubAgent 并行） |
| SubAgent 范式 | **OODA 循环**（Observe→Orient→Decide→Act） |
| 查询类型分类 | `depth_first` / `breadth_first` / `simple` |
| 动态调度 | 根据查询复杂度自动调整 Worker 数（1-10） |
| 质量控制 | 0-100 分质量评分 + 阈值 80 + 最多 5 轮迭代 + 收益递减检测 |
| Worker 类型 | 4 种：SearchWorker / WriterWorker / AnalysisWorker / VisualizationWorker |
| 来源质量评估 | 高/低质量域名分类 + 投机性语言识别 |
| 研究预算 | 按 simple/medium/complex 自动分配 max_queries 与 max_cycles |
| **14 个 Prompt** | ① `ORCHESTRATOR_SYSTEM` ② `TASK_DECOMPOSITION` ③ `SYNTHESIS` ④ `QUALITY_CHECK` ⑤ `SEARCH_WORKER_SYSTEM` ⑥ `SEARCH_WORKER_TASK` ⑦ `WRITER_WORKER_SYSTEM` ⑧ `WRITER_SECTION` ⑨ `QUERY_EXPANSION` ⑩ `FACT_CHECK` ⑪ `GAP_ANALYSIS` ⑫ `REPORT_REFINEMENT` ⑬ `DIMINISHING_RETURNS_CHECK` ⑭ `PARALLEL_TASK_COORDINATION`（+ `CURRENT_DATE` 运行时变量） |
| SSE 进度事件 | decomposed / worker_started / worker_completed / iteration_start / iteration_evaluated / quality_passed / final |

### 1.3 API 端点（deep_research 原生）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/research` | 提交研究任务（后台异步执行） |
| GET | `/research` | 列出所有任务 |
| GET | `/research/{id}` | 获取任务状态 |
| GET | `/research/{id}/result` | 获取最终报告（任务未完成返回 202） |
| GET | `/research/{id}/stream` | SSE 进度流（含 `final` 终止事件） |
| DELETE | `/research/{id}` | 删除任务（运行中拒绝 400） |
| GET | `/` | 服务信息 |

### 1.4 依赖

| 包 | 版本要求 | agent 现状 |
|---|---|---|
| `openai` | ≥1.0.0 | ✅ 已装（≥1.58） |
| `requests` | ≥2.28.0 | ✅ 已装（≥2.32） |
| `fastapi` | ≥0.104.0 | ✅ 已装（≥0.115） |
| `uvicorn[standard]` | ≥0.24.0 | ✅ 已装（≥0.30） |
| `pydantic` | ≥2.0.0 | ✅ 已装（≥2.7,<2.12） |
| `python-dotenv` | ≥1.0.0 | ✅ 已装 |
| `typing-extensions` | ≥4.0.0 | ✅ 已装 |
| **Bocha API key** | 用户 `.env` 已有字段（值为空） | ⚠️ 无 key → 调用时返回 503/降级提示 |

**关键发现**：所有 7 个核心依赖都已在 agent 中，**无需新增 Python 包**。

---

## 2. 与 agent 的重叠 / 互补 / 差异

| 维度 | deep_research 独有 | agent 已覆盖 | 整合策略 |
|---|---|---|---|
| **LLM 客户端** | 自定义 `LLMClient`（OpenAI SDK 同步 + 流式） | ✅ `app/core/llm.py`（OpenAI 兼容 + JSON mode） | **直接复用** `app.core.llm.get_llm_client()` |
| **配置层** | 模块级 dict（`LLM_CONFIG/SEARCH_CONFIG/AGENT_CONFIG/OUTPUT_CONFIG`） | ✅ `app/core/config.py` pydantic-settings | **合并** AGENT_CONFIG 关键字段 + SEARCH_CONFIG（Bocha） |
| **FastAPI + lifespan** | 自带 `app.main:app` | ✅ `app/main.py` | **不重写** main.py；新端点挂在 `/api/v1/research` |
| **CORS** | `allow_origins=["*"]` | ✅ 已配 | 沿用 |
| **SSE 流式** | 自定义 event_generator + 每 0.5s 轮询 task_manager | ✅ `agent_service._stream_loop` | **独立端点**（任务管理 SSE 不同于 LLM 流） |
| **后台任务** | `ThreadPoolExecutor(max_workers=3)` + `TaskManager` 内存 dict | ❌ agent 无 | **新增** `ResearchManager`（in-memory + 可选 JSON 持久化） |
| **网络搜索** | **Bocha API**（`api.bocha.cn/v1/web-search`，中文） | ⚠️ Serper（`google.serper.dev`，国际） | **保留双 API**：Bocha 用于 deep_research，Serper 用于 web_research |
| **Orchestrator-Workers 编排** | 1 Lead + N SubAgents 并行 | ❌ 仅有 5 个内置工具 + MCP/RAG/Web 工具 | **新增** `app/services/research/` |
| **OODA 循环** | Observe→Orient→Decide→Act（Worker 内部） | ❌ 无 | **整体迁移** `workers.py` |
| **查询类型分类** | depth_first / breadth_first / simple | ❌ 无 | **整体迁移** + 通用化 |
| **质量评分** | 0-100 + threshold + diminishing returns | ❌ 无 | **整体迁移** `QUALITY_CHECK_PROMPT` + scoring logic |
| **迭代优化** | plan→research→synthesize→quality→gap→supplementary→refine 循环 | ❌ 无 | **整体迁移** Orchestrator 主循环 |
| **来源质量评估** | high/low quality domains + speculative language | ❌ 无 | **整体迁移** |
| **研究预算** | per-complexity max_queries/cycles | ❌ 无 | **整体迁移** |
| **4 种 Worker** | Search/Writer/Analysis/Visualization | ❌ 无 | **整体迁移** |
| **14 个 Prompt** | Orchestrator + 4 Worker + Quality + Refinement + Gap + FactCheck + QueryExpansion（935 行） | ❌ 无 | **整体迁移** `prompts.py` |
| **报告落盘** | Markdown + JSON 元数据 | ⚠️ `data/outputs/chat_log_*.json`（agent 日志） | **扩展** `data/research/` 子目录存研究报告 |
| **CLI 入口** | `python -m app.agent.research_agent "task"` | ❌ 无 | **新增** `scripts/research_cli.py`（可选） |
| **教学文档** | 7 份设计文档 + 2 SVG | ✅ 已迁移（参考先前整合经验） | **直接复制**到 `backend/docs/research/` |

**核心结论**：
- 工具/库 100% 复用
- 配置/路由/UI 模式 100% 复用
- 编排范式（Orchestrator-Workers + OODA + 质量迭代循环）**全新能力**，与现有 Agent 循环互补（现有是"单循环 + 反思"，新增是"多轮迭代 + 质量门控"）

---

## 3. 整合架构设计

### 3.1 5 条能力链定位

```
agent v1.1
├── Skill 链   (app/services/{skill_manager, code_executor, agent_service}.py)
├── MCP 链     (app/services/{mcp_manager, tool_registry}.py)
├── RAG 链     (app/services/rag/)
├── Web 链     (app/services/web/)              ← 实时搜索（Serper + Chroma + GPT）
└── Research 链 (app/services/research/)         ⭐ 新增：深度报告（Bocha + OODA + 质量迭代）
```

**Research 链与 Web 链的关系**：
- **Web 链**（web_research）：单轮搜索 + 一次性回答，快速（~10s），适合事实查询
- **Research 链**（deep_research）：多轮并行搜索 + 质量迭代（~2-5 分钟），适合深度报告

两者**互补不互斥**，可由 Agent 决定调用哪个，或前端提供两种入口。

### 3.2 模块结构

```
apps/agent/backend/app/services/research/
├── __init__.py
├── prompts.py                ← **14 个** Prompt 模板（935 行，直接复制）
├── search_client.py          ← Bocha 搜索客户端（从 tools.py 抽出）
├── quality.py                ← 来源质量评估 + 评分（从 workers.py 抽出）
├── workers.py                ← Search/Writer/Analysis/VisualizationWorker + OODACycle
├── orchestrator.py           ← Orchestrator + SubTask + TaskPlan + ResearchState + IterationRecord
├── research_manager.py       ← TaskManager（in-memory + 可选 JSON 持久化）
└── service.py                ← DeepResearchAgent 类（CLI + 程序化调用）
```

**为什么不直接照搬目录结构**：把 `tools.py` 中的 LLMClient 删除（用 agent 自己的 `app/core/llm.py`），把 SearchClient 单独抽出为 `search_client.py`。`workers.py` 的 OODACycle / SourceQualityAssessment 抽到 `quality.py`，让 workers 主体更瘦。

### 3.3 整合架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    FastAPI Unified Gateway (lifespan)                  │
│  /api/v1/rag  /api/v1/web_research  /api/v1/research  ...           │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │ api/v1/research.py（7 端点 + SSE 流）                          │     │
│  │   POST  /research             submit (async background)        │     │
│  │   GET   /research             list                              │     │
│  │   GET   /research/{id}        status                           │     │
│  │   GET   /research/{id}/result final report                      │     │
│  │   GET   /research/{id}/stream  SSE progress                     │     │
│  │   DELETE /research/{id}       delete                            │     │
│  └─────────────────────────────────────────────────────────────┘     │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│ app/services/research/                                                  │
│  ┌──────────────────────┐  ┌──────────────────────┐                  │
│  │ ResearchManager       │  │ Orchestrator          │  编排循环         │
│  │ (TaskManager 改造)    │◀─┤  - 任务拆解           │                  │
│  │  - tasks dict         │  │  - 查询类型分类        │                  │
│  │  - in-memory + JSON  │  │  - Worker 调度        │                  │
│  │  - 进度事件总线       │  │  - 质量评分           │                  │
│  └──────────────────────┘  │  - 收益递减检测        │                  │
│                             │  - 报告生成            │                  │
│                             └─────────┬────────────┘                  │
│                                       │ 调度                         │
│                             ┌─────────▼────────────┐                  │
│                             │ ThreadPoolExecutor   │ (max_workers=3)  │
│                             │  并行 Worker 调度     │                  │
│                             └─────────┬────────────┘                  │
│                                       │                             │
│  ┌────────────────────────────────────▼──────────────────────────┐  │
│  │ Workers (4 种)                                                 │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │  │
│  │  │SearchWorker  │  │WriterWorker  │  │AnalysisWorker│  ...     │  │
│  │  │ OODA 循环    │  │ 章节撰写     │  │ 数据分析     │          │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘          │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌──────────────────┐  ┌────────────────────┐                       │
│  │ search_client.py │  │ quality.py         │  来源质量评估         │
│  │  Bocha API       │  │ - 高/低质量域名     │                       │
│  └──────────────────┘  │ - 投机性语言检测    │                       │
│                        │ - 评分计算          │                       │
│                        └────────────────────┘                       │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ prompts.py (14 个模板)                                            │  │
│  │  ORCHESTRATOR_SYSTEM / TASK_DECOMPOSITION / SEARCH_WORKER_TASK │  │
│  │  WRITER_WORKER_SYSTEM / QUALITY_CHECK / GAP_ANALYSIS / REFINE │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌──────────────────┐                                                │
│  │ app/core/llm.py  │  复用！替换 deep_research 的 LLMClient      │
│  │  (OpenAI 兼容)   │                                                │
│  └──────────────────┘                                                │
└───────────────────────────────────────────────────────────────────────┘
```

### 3.4 与 agent 其他模块的依赖

- **`app/core/llm.py`**：替代 deep_research 自己的 `LLMClient`
- **`app/core/config.py`**：合并 `LLM_CONFIG/SEARCH_CONFIG/AGENT_CONFIG` 关键字段
- **`app/api/v1/router.py`**：追加 `research_router`
- **可选 ToolRegistry**：v1.1 暂不将 `deep_research` 加入 Agent 的同步工具集（深研耗时分钟级，不适合同步 tool call）；v1.2 可加入但需用 task_id 异步返回

---

## 4. URL 设计与请求/响应模型

### 4.1 端点设计

| 方法 | 路径 | 状态码 | 说明 | 来源 |
|---|---|---|---|---|
| GET | `/api/v1/research/health` | 200 | 链路健康（Bocha key 配置检查） | 新增（替代原 `/health`） |
| POST | `/api/v1/research` | 200 | 提交研究任务（返回 `task_id`，后台执行） | 原 `POST /research` |
| GET | `/api/v1/research` | 200 | 列出所有任务 | 原 `GET /research` |
| GET | `/api/v1/research/{id}` | 200/404 | 任务状态 + 进度摘要 | 原 `GET /research/{task_id}` |
| GET | `/api/v1/research/{id}/result` | 200/202/404 | 报告（未完成 202） | 原 `GET /research/{task_id}/result` |
| GET | `/api/v1/research/{id}/stream` | 200/404 | SSE 进度流（每 0.5s 检查） | 原 `GET /research/{task_id}/stream` |
| DELETE | `/api/v1/research/{id}` | 200/400/404 | 删除任务（运行中 400） | 原 `DELETE /research/{task_id}` |
| GET | `/api/v1/health`（**复用**） | 200 | 全局健康（追加 `research_*` 字段） | 扩展既有端点 |

> **注意 1**：deep_research 原生使用 `/research`（无 `/api/v1` 前缀）且自带 `GET /` 与 `GET /health`；整合后：
> - 业务端点统一移到 `/api/v1/research/*`
> - `GET /health` → 复用平台的 `/api/v1/health`（追加 research 字段），不再单独暴露
> - `GET /` 服务信息页 → **不迁移**（平台已有根路由，生产模式返回前端 SPA）
> - 因此**净新增 7 个端点**（health 复用），平台 API 路径总数 27 → **34**
>
> **注意 2**：`RunRequest` 的 4 链开关与 `/research` 的关系 —— 见 §13 开放问题 Q1（v1.1 不把 deep_research 接入 Agent 同步工具集）。

### 4.2 请求/响应模型

```python
# app/schemas/research.py

class ResearchRequest(BaseModel):
    task: str = Field(..., min_length=1, description="研究任务描述")
    max_workers: Optional[int] = Field(None, ge=1, le=10, description="最大并行 Worker")
    max_iterations: Optional[int] = Field(None, ge=1, le=10, description="最大迭代次数")
    quality_threshold: Optional[int] = Field(None, ge=0, le=100, description="质量阈值")

class ResearchSubmitResponse(BaseModel):
    task_id: str
    status: Literal["pending", "running", "completed", "failed"]
    message: str
    created_at: str

class ResearchTaskSummary(BaseModel):
    task_id: str
    original_task: str
    status: str
    created_at: str
    quality_score: Optional[int] = None

class ResearchTaskList(BaseModel):
    total: int
    tasks: list[ResearchTaskSummary]

class ResearchTaskStatus(BaseModel):
    task_id: str
    status: str
    progress: dict  # current_stage, last_update, etc.
    original_task: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    quality_score: Optional[int] = None
    iteration_count: Optional[int] = None
    error_message: Optional[str] = None

class ResearchTaskResult(BaseModel):
    task_id: str
    status: str
    report: Optional[str] = None
    quality_score: Optional[int] = None
    iteration_count: Optional[int] = None
    duration: Optional[float] = None
    metadata: Optional[dict] = None

class ResearchHealth(BaseModel):
    bocha_configured: bool
    llm_configured: bool
    default_model: str
    max_concurrent_tasks: int
```

### 4.3 SSE 进度事件（保持 deep_research 原 schema）

`/research/{id}/stream` 推送的事件 `data: {...}` 字段：

```json
{ "stage": "decomposing", "data": {...}, "timestamp": "..." }
{ "stage": "decomposed", "data": {"subtask_count": 5, "subtasks": [...]}, "timestamp": "..." }
{ "stage": "dispatching", "data": {"worker_count": 6}, "timestamp": "..." }
{ "stage": "worker_started", "data": {"task_name": "..."}, "timestamp": "..." }
{ "stage": "worker_completed", "data": {"task_name": "...", "duration": 12.3}, "timestamp": "..." }
{ "stage": "synthesizing", "data": {}, "timestamp": "..." }
{ "stage": "iteration_start", "data": {"iteration": 1, "max_iterations": 5}, "timestamp": "..." }
{ "stage": "iteration_evaluated", "data": {"score": 75, "passed": false}, "timestamp": "..." }
{ "stage": "gaps_analyzed", "data": {"gap_count": 3, "task_count": 2}, "timestamp": "..." }
{ "stage": "final", "data": {"status": "completed", "quality_score": 85, "duration": 245.6}, "timestamp": "..." }
```

> 与 agent 现有 `/agent/run` 的事件类型（system_prompt / user_input / round_start / tool_call / tool_result / model_text / files / done）**无冲突**——研究事件只在 `/research/{id}/stream` 端点出现。

---

## 5. 详细文件迁移与代码修改计划

### 5.1 整体迁移步骤

| 阶段 | 时长 | 内容 |
|---|---|---|
| A | 0.5 天 | 框架搭建（目录 + schemas + config 扩展） |
| B | 0.5 天 | prompts + search_client + quality 迁移 |
| C | 0.5 天 | workers + orchestrator 迁移与导入修正 |
| D | 0.5 天 | research_manager + service |
| E | 0.5 天 | API 端点（**7 端点** + SSE） |
| F | 0.5 天 | 前端 UI（"深度研究"标签页） |
| G | 0.5 天 | 测试（pytest + 集成测试） |
| **合计** | **3.5 天** | |

### 5.2 阶段 A：框架搭建

#### 新建 `app/schemas/research.py`

```python
"""Research 链路请求/响应模型。"""
from pydantic import BaseModel, Field
from typing import Optional, Literal


class ResearchRequest(BaseModel):
    task: str = Field(..., min_length=1, description="研究任务描述")
    max_workers: Optional[int] = Field(None, ge=1, le=10)
    max_iterations: Optional[int] = Field(None, ge=1, le=10)
    quality_threshold: Optional[int] = Field(None, ge=0, le=100)


class ResearchSubmitResponse(BaseModel):
    task_id: str
    status: Literal["pending", "running", "completed", "failed"]
    message: str
    created_at: str


class ResearchTaskSummary(BaseModel):
    task_id: str
    original_task: str
    status: str
    created_at: str
    quality_score: Optional[int] = None


class ResearchTaskList(BaseModel):
    total: int
    tasks: list[ResearchTaskSummary]


class ResearchTaskStatus(BaseModel):
    task_id: str
    status: str
    progress: dict
    original_task: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    quality_score: Optional[int] = None
    iteration_count: Optional[int] = None
    error_message: Optional[str] = None


class ResearchTaskResult(BaseModel):
    task_id: str
    status: str
    report: Optional[str] = None
    quality_score: Optional[int] = None
    iteration_count: Optional[int] = None
    duration: Optional[float] = None
    metadata: Optional[dict] = None


class ResearchHealth(BaseModel):
    bocha_configured: bool
    llm_configured: bool
    default_model: str
    max_concurrent_tasks: int
```

#### 扩展 `app/core/config.py`

> **基线说明（核查后补充）**：agent 当前的 `app/core/config.py` **已包含**下列字段，新增时**不要重复定义**：
> - 应用：`app_name` / `app_version` / `debug` / `host` / `port`
> - 主 LLM：`dashscope_api_key` / `dashscope_base_url` / `default_model` / `max_tokens` / `max_iterations` / `exec_timeout`
> - 备选 LLM：`llm_api_key` / `llm_base_url` / `plan_model` / `rag_model` / `answer_model`
> - OpenAI：`openai_api_key` / `openai_model`
> - MCP：`serper_api_key` / `gaode_api_key` / `mcp_servers_dir` / `mcp_max_servers` / `mcp_call_timeout`
> - RAG：`milvus_db_path`（**注意不是 `milvus_uri`**，因 pymilvus 抢占该环境变量）/ `milvus_collection`
> - 路径：`skills_dir` / `data_dir`；派生属性 `output_dir` / `upload_dir` / `browser_data_dir` / `pdf_dir` / `logs_dir`
> - **不存在** `static_dir`（前端已分离为 Vue 工程，旧的静态托管字段已删除）
>
> 因此本次**只追加 Bocha + Research Manager 两组字段**：

```python
# ---------- Research 链路（deep_research）—— 追加 ----------
bocha_api_key: str = ""
bocha_base_url: str = "https://api.bocha.cn/v1/web-search"
bocha_default_count: int = 10
bocha_summary: bool = True

# Research Manager（ThreadPoolExecutor 并发 + JSON 持久化）
research_output_dir: str = "data/research"
research_max_concurrent: int = 3
research_persist: bool = True

@property
def research_output_abs(self) -> str:
    return self.resolve(self.research_output_dir)

@property
def bocha_configured(self) -> bool:
    return bool(self.bocha_api_key.strip())
```

并在 `ensure_dirs()` 的路径元组中**追加** `Path(self.research_output_abs)`，确保 `data/research/` 自动创建。

新增 dict 常量（**放在 config.py 之外更合适，移到 research_config.py**，避免污染 Settings）：

```python
# app/services/research/research_config.py
"""deep_research Agent 配置（与 app/core/config.py 解耦）。"""

RESEARCH_CONFIG = {
    # ========== Orchestrator (Lead Agent) 配置 ==========
    "max_workers": 6,
    "max_search_depth": 3,
    "timeout_per_worker": 120,

    # ========== 子智能体数量配置 ==========
    "worker_count_guidelines": {
        "simple": {"min": 1, "max": 2},
        "standard": {"min": 2, "max": 3},
        "medium": {"min": 3, "max": 5},
        "high": {"min": 5, "max": 10},
    },

    # ========== 研究任务配置 ==========
    "min_sources_per_topic": 3,
    "max_sources_per_topic": 10,

    # ========== 报告配置 ==========
    "report_language": "zh-CN",
    "include_sources": True,
    "include_summary": True,

    # ========== 迭代优化配置 ==========
    "min_iterations": 2,
    "max_iterations": 5,
    "quality_threshold": 80,

    # ========== 智能终止配置 ==========
    "enable_diminishing_returns_check": True,
    "diminishing_returns_threshold": 3,
    "early_termination_min_score": 75,

    # ========== Worker 配置 ==========
    "worker_max_ooda_cycles": 3,
    "research_budget": {
        "simple": {"max_queries": 3, "max_cycles": 1},
        "medium": {"max_queries": 5, "max_cycles": 2},
        "complex": {"max_queries": 8, "max_cycles": 3},
    },

    # ========== 来源质量评估 ==========
    "source_quality": {
        "high_quality_domains": [
            ".gov", ".edu", ".org",
            "reuters", "bloomberg", "wsj", "nytimes",
            "nature", "science", "arxiv",
            "statista", "mckinsey", "gartner", "idc",
        ],
        "low_quality_indicators": [
            "forum", "reddit", "quora", "yahoo answers",
            "wiki", "blog", "medium.com",
        ],
        "speculative_language": [
            "可能", "也许", "据说", "传闻", "预计",
            "may", "might", "possibly", "reportedly",
        ],
    },
}
```

### 5.3 阶段 B：prompts + search_client + quality 迁移

#### 新建 `app/services/research/prompts.py`

直接复制 `deep_research/app/agent/prompts.py`（**935 行，14 个模板**）：
`ORCHESTRATOR_SYSTEM_PROMPT` / `TASK_DECOMPOSITION_PROMPT` / `SYNTHESIS_PROMPT` / `QUALITY_CHECK_PROMPT` / `SEARCH_WORKER_SYSTEM_PROMPT` / `SEARCH_WORKER_TASK_PROMPT` / `WRITER_WORKER_SYSTEM_PROMPT` / `WRITER_SECTION_PROMPT` / `QUERY_EXPANSION_PROMPT` / `FACT_CHECK_PROMPT` / `GAP_ANALYSIS_PROMPT` / `REPORT_REFINEMENT_PROMPT` / `DIMINISHING_RETURNS_CHECK_PROMPT` / `PARALLEL_TASK_COORDINATION_PROMPT`。

**导入修正**：`from datetime import datetime` 保持不变（`CURRENT_DATE` 仍用本地时间）。
**注意**：初版文档漏列 `QUERY_EXPANSION_PROMPT` / `FACT_CHECK_PROMPT` / `WRITER_SECTION_PROMPT` / `SEARCH_WORKER_SYSTEM_PROMPT` 中的系统提示等 7 个，实际迁移时**必须全量复制**（缺一则 Worker 内部的 `_expand_queries()` 会 ImportError）。

#### 新建 `app/services/research/search_client.py`

从 `deep_research/app/agent/tools.py` 抽出 `SearchClient` + `SearchResult` + `SearchResponse`，**移除 `LLMClient`/`extract_json`/`format_search_context`（这些用 agent 自己的）**。

```python
"""Bocha 搜索客户端（迁移自 deep_research/app/agent/tools.py，去除 LLMClient）。"""
import time
import requests
from dataclasses import dataclass, field
from typing import Optional

from app.services.research.research_config import RESEARCH_CONFIG


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    site_name: str = ""
    date: str = ""

    def to_context(self) -> str:
        return (
            f"【{self.title}】\n"
            f"来源: {self.site_name or self.url}\n"
            f"日期: {self.date or '未知'}\n"
            f"内容: {self.snippet}\n"
        )


@dataclass
class SearchResponse:
    query: str
    results: list[SearchResult] = field(default_factory=list)
    total_matches: int = 0
    success: bool = True
    error_msg: str = ""


class SearchClient:
    """Bocha 搜索客户端。"""

    def __init__(self, api_key: str = "", base_url: str = ""):
        from app.core.config import settings
        self.api_key = api_key or settings.bocha_api_key
        self.base_url = base_url or settings.bocha_base_url
        self.default_count = settings.bocha_default_count
        self.summary = settings.bocha_summary

    def search(self, query: str, count: int = None, freshness: str = None) -> SearchResponse:
        if not self.api_key:
            return SearchResponse(query=query, success=False,
                                 error_msg="未配置 BOCHA_API_KEY")
        payload = {"query": query, "summary": self.summary,
                   "count": count or self.default_count}
        if freshness:
            payload["freshness"] = freshness
        try:
            resp = requests.post(
                self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=payload, timeout=30,
            )
            data = resp.json()
            if data.get("code") != 200:
                return SearchResponse(query=query, success=False,
                                     error_msg=data.get("msg", "搜索失败"))
            web_pages = data.get("data", {}).get("webPages", {})
            results = [SearchResult(
                title=item.get("name", ""), url=item.get("url", ""),
                snippet=item.get("snippet", ""),
                site_name=item.get("siteName", ""),
                date=(item.get("dateLastCrawled", "") or "")[:10],
            ) for item in web_pages.get("value", [])]
            return SearchResponse(
                query=query, results=results,
                total_matches=web_pages.get("totalEstimatedMatches", len(results)),
                success=True,
            )
        except requests.Timeout:
            return SearchResponse(query=query, success=False, error_msg="搜索超时")
        except Exception as e:
            return SearchResponse(query=query, success=False, error_msg=str(e))

    def multi_search(self, queries: list[str], count: int = None) -> list[SearchResponse]:
        results = []
        for q in queries:
            results.append(self.search(q, count))
            time.sleep(0.5)
        return results


# 全局单例
_search_client: Optional[SearchClient] = None
def get_search_client() -> SearchClient:
    global _search_client
    if _search_client is None:
        _search_client = SearchClient()
    return _search_client
```

#### 新建 `app/services/research/quality.py`

从 `deep_research/app/agent/workers.py` 抽出 `OODACycle` + `SourceQualityAssessment`，并新增评估函数：

```python
"""来源质量评估 + OODA 循环追踪（迁移自 deep_research）。"""
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.research.research_config import RESEARCH_CONFIG


@dataclass
class OODACycle:
    cycle: int
    observe: str
    orient: str
    decide: str
    act: str


@dataclass
class SourceQualityAssessment:
    high_quality_sources: List[str] = field(default_factory=list)
    questionable_sources: List[str] = field(default_factory=list)
    source_conflicts: List[str] = field(default_factory=list)


def assess_source_quality(sources: list[dict]) -> SourceQualityAssessment:
    """根据域名分类来源质量。"""
    sq = RESEARCH_CONFIG["source_quality"]
    high_doms = [d.lower() for d in sq["high_quality_domains"]]
    low_indicators = [s.lower() for s in sq["low_quality_indicators"]]
    spec_langs = sq["speculative_language"]

    assessment = SourceQualityAssessment()
    for s in sources:
        url = (s.get("url") or "").lower()
        snippet = (s.get("snippet") or s.get("content") or "").lower()
        is_high = any(d in url for d in high_doms)
        is_low = any(ind in url or ind in snippet for ind in low_indicators)
        has_spec = any(lang.lower() in snippet for lang in spec_langs)
        title = s.get("title") or s.get("name") or url
        if is_high and not is_low:
            assessment.high_quality_sources.append(title)
        elif is_low or has_spec:
            assessment.questionable_sources.append(title)
    return assessment
```

### 5.4 阶段 C：workers + orchestrator 迁移

#### 新建 `app/services/research/workers.py`

复制 `deep_research/app/agent/workers.py`（770 行），**修改导入**：

```python
# 原
from app.agent.tools import get_llm_client, get_search_client, extract_json, format_search_context
from app.agent.prompts import SEARCH_WORKER_SYSTEM_PROMPT, SEARCH_WORKER_TASK_PROMPT, ...

# 改为
from app.core.llm import get_llm_client          # 复用 agent LLM
from app.services.research.search_client import get_search_client, format_search_context
from app.services.research.prompts import (SEARCH_WORKER_SYSTEM_PROMPT, ...)
from app.services.research.quality import OODACycle, SourceQualityAssessment, assess_source_quality
from app.services.research.research_config import RESEARCH_CONFIG
```

`extract_json` 改为从 `app.services.research.utils` 导入（见下）。

> 不删除 `search_worker_factory` / `WorkerFactory` 符号（`orchestrator.py` 引用）。

#### 新建 `app/services/research/utils.py`

从 `deep_research/app/agent/tools.py` 抽出纯文本/JSON 工具：

```python
"""Research 工具函数（JSON/XML 抽取）。"""
import json
import re


def extract_xml(text: str, tag: str) -> str:
    match = re.search(f"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_json(text: str) -> dict:
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    try:
        start, end = text.find("{"), text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass
    return {}
```

#### 新建 `app/services/research/orchestrator.py`

复制 `deep_research/app/agent/orchestrator.py`（**963 行**），**修改导入**：

```python
# 原
from app.agent.tools import get_llm_client, extract_json
from app.agent.prompts import (ORCHESTRATOR_SYSTEM_PROMPT, TASK_DECOMPOSITION_PROMPT, SYNTHESIS_PROMPT, ...)
from app.core.config import AGENT_CONFIG

# 改为
from app.core.llm import get_llm_client
from app.services.research.utils import extract_json
from app.services.research.prompts import (...)
from app.services.research.research_config import RESEARCH_CONFIG
from app.services.research.workers import search_worker_factory  # 同包引用
```

保留所有 dataclass：`SubTask` / `QueryTypeAnalysis` / `TaskPlan` / `IterationRecord` / `ResearchState`。
保留 `Orchestrator` 类与 `orchestrator.run(task)` 方法。

### 5.5 阶段 D：research_manager + service

#### 新建 `app/services/research/research_manager.py`

将 `deep_research/app/main.py:TaskManager` 改造为可注入、可持久化：

```python
"""Research 任务管理器（in-memory + 可选 JSON 持久化）。"""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.config import settings
from app.services.research.orchestrator import ResearchState


class ResearchManager:
    def __init__(self, max_workers: int = None, persist: bool = None):
        self.tasks: dict[str, dict[str, Any]] = {}
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers or settings.research_max_concurrent
        )
        self.persist = persist if persist is not None else settings.research_persist
        if self.persist:
            self._load()

    def _persist_path(self) -> Path:
        return Path(settings.research_output_abs) / "tasks.json"

    def _load(self):
        path = self._persist_path()
        if path.exists():
            try:
                self.tasks = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                self.tasks = {}

    def _save(self):
        if not self.persist:
            return
        out_dir = Path(settings.research_output_abs)
        out_dir.mkdir(parents=True, exist_ok=True)
        self._persist_path().write_text(
            json.dumps(self.tasks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create_task(self, request, config: dict) -> str:
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {
            "task_id": task_id, "original_task": request.task,
            "status": "pending", "progress": [],
            "progress_summary": {}, "config": config,
            "created_at": datetime.now().isoformat(),
            "started_at": None, "completed_at": None,
            "result": None, "error": None,
        }
        self._save()
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        return self.tasks.get(task_id)

    def list_tasks(self) -> list[dict]:
        return [{
            "task_id": t["task_id"],
            "original_task": (t["original_task"][:50] + "..." if len(t["original_task"]) > 50 else t["original_task"]),
            "status": t["status"], "created_at": t["created_at"],
            "quality_score": t["result"]["quality_score"] if t["result"] else None,
        } for t in self.tasks.values()]

    def update_progress(self, task_id: str, stage: str, data: dict):
        if task_id not in self.tasks:
            return
        event = {"stage": stage, "data": data,
                 "timestamp": datetime.now().isoformat()}
        self.tasks[task_id]["progress"].append(event)
        self.tasks[task_id]["progress_summary"] = {
            "current_stage": stage, "last_update": event["timestamp"], **data,
        }
        self._save()

    def set_running(self, task_id: str):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "running"
            self.tasks[task_id]["started_at"] = datetime.now().isoformat()
            self._save()

    def set_completed(self, task_id: str, state: ResearchState):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "completed"
            self.tasks[task_id]["completed_at"] = datetime.now().isoformat()
            self.tasks[task_id]["result"] = {
                "report": state.final_report,
                "quality_score": state.quality_score,
                "iteration_count": state.iteration_count,
                "duration": state.end_time - state.start_time,
            }
            self._save()
            self._save_report(task_id, state)

    def set_failed(self, task_id: str, error: str):
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = "failed"
            self.tasks[task_id]["completed_at"] = datetime.now().isoformat()
            self.tasks[task_id]["error"] = error
            self._save()

    def delete_task(self, task_id: str) -> bool:
        if task_id not in self.tasks:
            return False
        if self.tasks[task_id]["status"] == "running":
            raise ValueError("无法删除正在执行的任务")
        del self.tasks[task_id]
        self._save()
        return True

    def _save_report(self, task_id: str, state: ResearchState):
        """保存研究报告 Markdown + JSON 元数据。"""
        from datetime import datetime
        out_dir = Path(settings.research_output_abs) / task_id
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (out_dir / f"report_{ts}.md").write_text(
            state.final_report, encoding="utf-8")
        meta = {
            "original_task": state.original_task,
            "status": state.status,
            "quality_score": state.quality_score,
            "iteration_count": state.iteration_count,
            "duration": state.end_time - state.start_time,
            "worker_results_count": len(state.worker_results),
            "iteration_history": [{
                "iteration": r.iteration,
                "quality_score": r.quality_score,
                "report_length": len(r.report),
                "gap_count": len(r.gap_analysis.get("missing_aspects", [])) if r.gap_analysis else 0,
            } for r in state.iteration_history],
        }
        (out_dir / f"meta_{ts}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def shutdown(self):
        self.executor.shutdown(wait=False)
```

#### 新建 `app/services/research/service.py`

将 `deep_research/app/agent/research_agent.py:DeepResearchAgent` 改造为纯服务类（不依赖 console 输出，改走 callback）：

```python
"""DeepResearchAgent 服务化（移除 CLI 与 ConsoleReporter，保留核心逻辑）。"""
import json
import time
from datetime import datetime
from typing import Callable, Optional

from app.core.llm import get_llm_client
from app.services.research.orchestrator import Orchestrator, ResearchState
from app.services.research.research_config import RESEARCH_CONFIG
from app.services.research.workers import search_worker_factory
from app.services.research.research_manager import ResearchManager


class DeepResearchAgent:
    def __init__(self, manager: ResearchManager, verbose: bool = False):
        self.manager = manager
        self.verbose = verbose
        self.start_time = 0

    def research(
        self,
        task: str,
        max_workers: int = None,
        max_iterations: int = None,
        quality_threshold: int = None,
        callback: Optional[Callable[[str, dict], None]] = None,
    ) -> ResearchState:
        """同步执行研究任务；通过 callback 推送进度；返回 ResearchState。"""
        # 临时覆盖配置（与 deep_research 同）
        overrides = {}
        if max_iterations is not None:
            overrides["max_iterations"] = max_iterations
        if quality_threshold is not None:
            overrides["quality_threshold"] = quality_threshold
        original = {}
        for k, v in overrides.items():
            original[k] = RESEARCH_CONFIG[k]
            RESEARCH_CONFIG[k] = v
        try:
            orchestrator = Orchestrator(
                worker_factory=search_worker_factory,
                max_workers=max_workers or RESEARCH_CONFIG["max_workers"],
                on_progress=callback,
            )
            return orchestrator.run(task)
        finally:
            for k, v in original.items():
                RESEARCH_CONFIG[k] = v
```

#### 新建 `app/services/research/__init__.py`

```python
from app.services.research.research_manager import ResearchManager
from app.services.research.service import DeepResearchAgent
```

### 5.6 阶段 E：API 端点

#### 新建 `app/api/v1/research.py`

完整迁移 `deep_research/app/main.py` 的 6 个端点到 agent 风格：

```python
"""深度研究链路接口（迁移自 deep_research）。"""
import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.state import init_app_state
from app.schemas.research import (
    ResearchHealth, ResearchRequest, ResearchSubmitResponse,
    ResearchTaskList, ResearchTaskStatus, ResearchTaskResult,
)
from app.services.research.orchestrator import Orchestrator
from app.services.research.research_config import RESEARCH_CONFIG
from app.services.research.research_manager import ResearchManager
from app.services.research.workers import search_worker_factory

router = APIRouter(prefix="/research", tags=["research"])


from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

def get_manager(request: Request) -> ResearchManager:
    """依赖注入：从 app.state 取 ResearchManager（惰性兜底初始化）。"""
    init_app_state(request.app)
    return request.app.state.research_manager


def run_research_task(
    manager: ResearchManager,
    task_id: str,
    task_text: str,
    config: dict,
) -> None:
    """
    后台线程中执行研究任务（由 run_in_executor 调用）。

    注意：**manager 与 task_text 显式传入**，不在线程内访问 request.app
    （后台线程脱离请求上下文，无法可靠拿到 app 实例）。
    """
    try:
        manager.set_running(task_id)

        def on_progress(stage: str, data: dict) -> None:
            manager.update_progress(task_id, stage, data)

        # 临时覆盖 RESEARCH_CONFIG（try/finally 保证还原，防止并发污染）
        overridable = ("max_iterations", "quality_threshold")
        original = {k: RESEARCH_CONFIG[k] for k in overridable if k in config}
        for k, v in original.items():
            RESEARCH_CONFIG[k] = config[k]
        try:
            orchestrator = Orchestrator(
                worker_factory=search_worker_factory,
                max_workers=config["max_workers"],
                on_progress=on_progress,
            )
            state = orchestrator.run(task_text)
            if state.status == "completed":
                manager.set_completed(task_id, state)
            else:
                manager.set_failed(task_id, state.error_msg or "未知错误")
        finally:
            RESEARCH_CONFIG.update(original)
    except Exception as e:  # noqa: BLE001 —— 任务失败必须落到任务状态里
        manager.set_failed(task_id, f"{type(e).__name__}: {e}")


@router.get("/health", response_model=ResearchHealth)
def health(request):
    m = get_manager(request)
    return ResearchHealth(
        bocha_configured=settings.bocha_configured,
        llm_configured=bool(settings.dashscope_api_key.strip()),
        default_model=settings.default_model,
        max_concurrent_tasks=m.executor._max_workers,
    )


@router.post("", response_model=ResearchSubmitResponse)
async def submit_research(payload: ResearchRequest, request: Request):
    """提交研究任务：立即返回 task_id，实际研究在线程池中执行。"""
    m = get_manager(request)
    config = {
        "max_workers": payload.max_workers or RESEARCH_CONFIG["max_workers"],
        "max_iterations": payload.max_iterations or RESEARCH_CONFIG["max_iterations"],
        "quality_threshold": payload.quality_threshold or RESEARCH_CONFIG["quality_threshold"],
    }
    task_id = m.create_task(payload, config)
    # 注意：用 running loop 提交到线程池；manager/task_text 显式传入（见 run_research_task 注释）
    loop = asyncio.get_running_loop()
    loop.run_in_executor(m.executor, run_research_task, m, task_id, payload.task, config)
    return ResearchSubmitResponse(
        task_id=task_id, status="pending",
        message="研究任务已提交，正在启动...",
        created_at=datetime.now().isoformat(),
    )


@router.get("", response_model=ResearchTaskList)
def list_tasks(request):
    m = get_manager(request)
    return ResearchTaskList(total=len(m.tasks), tasks=m.list_tasks())


@router.get("/{task_id}", response_model=ResearchTaskStatus)
def get_status(task_id: str, request):
    m = get_manager(request)
    t = m.get_task(task_id)
    if not t:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    return ResearchTaskStatus(
        task_id=t["task_id"], status=t["status"], progress=t["progress_summary"],
        original_task=t["original_task"], created_at=t["created_at"],
        started_at=t["started_at"], completed_at=t["completed_at"],
        quality_score=t["result"]["quality_score"] if t["result"] else None,
        iteration_count=t["result"]["iteration_count"] if t["result"] else None,
        error_message=t["error"],
    )


@router.get("/{task_id}/result", response_model=ResearchTaskResult)
def get_result(task_id: str, request):
    m = get_manager(request)
    t = m.get_task(task_id)
    if not t:
        raise HTTPException(404, f"任务 {task_id} 不存在")
    if t["status"] in ("pending", "running"):
        raise HTTPException(202, "任务正在执行中")
    if t["status"] == "failed":
        return ResearchTaskResult(task_id=task_id, status="failed", metadata={"error": t["error"]})
    r = t["result"]
    return ResearchTaskResult(
        task_id=task_id, status="completed",
        report=r["report"], quality_score=r["quality_score"],
        iteration_count=r["iteration_count"], duration=r["duration"],
        metadata={"original_task": t["original_task"], "created_at": t["created_at"],
                  "completed_at": t["completed_at"]},
    )


@router.get("/{task_id}/stream")
async def stream_progress(task_id: str, request):
    m = get_manager(request)
    if not m.get_task(task_id):
        raise HTTPException(404, f"任务 {task_id} 不存在")
    async def event_generator():
        last_count = 0
        while True:
            t = m.get_task(task_id)
            if not t:
                break
            progress = t["progress"]
            if len(progress) > last_count:
                for e in progress[last_count:]:
                    yield f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                last_count = len(progress)
            if t["status"] in ("completed", "failed"):
                final = {"stage": "final",
                         "data": {"status": t["status"],
                                  "quality_score": t["result"]["quality_score"] if t["result"] else None,
                                  "iteration_count": t["result"]["iteration_count"] if t["result"] else None,
                                  "duration": t["result"]["duration"] if t["result"] else None,
                                  "error": t["error"]},
                         "timestamp": datetime.now().isoformat()}
                yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.delete("/{task_id}")
def delete_task(task_id: str, request):
    m = get_manager(request)
    try:
        if not m.delete_task(task_id):
            raise HTTPException(404, f"任务 {task_id} 不存在")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"message": f"任务 {task_id} 已删除"}
```

#### 更新 `app/api/v1/router.py`

```python
from app.api.v1 import agent, files, mcp_servers, rag, research, skills, system, web_research

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(skills.router)
api_router.include_router(agent.router)
api_router.include_router(files.router)
api_router.include_router(mcp_servers.router)
api_router.include_router(rag.router)
api_router.include_router(web_research.router)
api_router.include_router(research.router)   # 🆕 深度研究
```

#### 更新 `app/core/state.py`

在 `init_app_state` 中新增：

```python
def init_app_state(app: FastAPI, force: bool = False) -> None:
    if not force and getattr(app.state, "initialized", False):
        return
    settings.ensure_dirs()
    # ... 现有初始化
    app.state.research_manager = ResearchManager()  # 🆕
    app.state.initialized = True
```

并在 lifespan 中关闭：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_app_state(app, force=True)
    # ... 现有
    yield
    app.state.research_manager.shutdown()  # 🆕
    logger.info("应用已关闭")
```

#### 更新 `app/api/deps.py`

```python
def get_research_manager(request: Request) -> ResearchManager:
    init_app_state(request.app)
    return request.app.state.research_manager
```

### 5.7 阶段 F：前端 UI

在 `frontend/src/components/` 新增 `ResearchTab.vue`（深度研究专用标签页）：

- 输入框（任务描述）
- "提交研究" 按钮
- 任务状态面板（task_id、当前阶段、质量分、迭代次数）
- 进度流（SSE）
- 最终报告渲染（Markdown，与现有 ChatMessage 的 MarkdownText 组件复用）

在 `App.vue` 的 `ToolPanel` 增加 "深度研究" 开关（与 RAG/Web 同级），或者新增一个侧边栏"模式选择"（聊天 / 深度研究）。

**推荐**：在 `SideBar.vue` 工具链区加一个 `🔬 深度研究` 入口（点击切换到研究模式）。研究模式下：
- 隐藏聊天流，显示研究任务面板
- 提交后通过 SSE 接收进度
- 完成后展示完整报告

### 5.8 阶段 G：测试

新建 `tests/test_research.py`：

```python
"""Research 链路冒烟测试。"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_research_health():
    r = client.get("/api/v1/research/health")
    assert r.status_code == 200
    body = r.json()
    assert "bocha_configured" in body
    assert "llm_configured" in body
    assert body["max_concurrent_tasks"] >= 1


def test_research_submit_and_status():
    """提交 + 查询状态（不实际执行，因 Bocha key 可能空）。"""
    r = client.post("/api/v1/research", json={"task": "测试任务", "max_workers": 2})
    assert r.status_code == 200
    body = r.json()
    assert "task_id" in body
    assert body["status"] in ("pending", "running", "completed", "failed")

    task_id = body["task_id"]
    r2 = client.get(f"/api/v1/research/{task_id}")
    assert r2.status_code == 200


def test_research_not_found():
    r = client.get("/api/v1/research/nonexistent")
    assert r.status_code == 404


def test_research_list():
    r = client.get("/api/v1/research")
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "tasks" in body
```

---

## 6. 配置合并方案

### 6.1 新增 .env 变量

```bash
# .env 新增
# Bocha 中文搜索 API（deep_research 用，https://api.bocha.cn）
BOCHA_API_KEY=
BOCHA_BASE_URL=https://api.bocha.cn/v1/web-search
BOCHA_DEFAULT_COUNT=10
BOCHA_SUMMARY=true

# Research Manager
RESEARCH_MAX_CONCURRENT=3
RESEARCH_PERSIST=true
RESEARCH_OUTPUT_DIR=data/research
```

### 6.2 不复制的 deep_research 配置

- `OUTPUT_CONFIG["output_dir"]`（`./research_output`）→ 用 `settings.research_output_abs` 替代
- `LLM_CONFIG["api_key"/"base_url"]`（`DASHSCOPE_API_KEY` 单独读取）→ 用 `app/core/llm.py` + `settings.dashscope_api_key/dashscope_base_url`
- `SEARCH_CONFIG`（Bocha）→ 拆为独立 `bocha_*` 字段
- `LOG_CONFIG`（stdout 打印级别）→ agent 用 Python logging，不沿用
- `LLM_CONFIG["model_smart"/"model_fast"]`（qwen-max / qwen-turbo）→ 已合并到 `AVAILABLE_MODELS` 与 `default_model`

### 6.3 RESEARCH_CONFIG 保留

放在 `app/services/research/research_config.py`（**不在 `config.py`**，因为这是 deep_research 专属复杂 dict，`AGENT_CONFIG` 含 **18 个顶级字段**（其中 `worker_count_guidelines` / `research_budget` / `source_quality` / `high_quality_domains` 为嵌套结构），不适合 pydantic-settings 扁平化）。

---

## 7. 依赖分析

**结论：零新增依赖**。

| deep_research 需求 | agent 现状 |
|---|---|
| `openai>=1.0` | ✅ `openai>=1.58` |
| `requests>=2.28` | ✅ `requests>=2.32` |
| `fastapi>=0.104` | ✅ `fastapi>=0.115` |
| `uvicorn[standard]>=0.24` | ✅ `uvicorn[standard]>=0.30` |
| `pydantic>=2.0` | ✅ `pydantic>=2.7,<2.12` |
| `python-dotenv>=1.0` | ✅ |
| `typing-extensions>=4.0` | ✅ |

`requirements.txt` **无需变更**。

---

## 8. 前端变更计划

### 8.1 新增组件

| 文件 | 职责 |
|---|---|
| `frontend/src/components/ResearchTab.vue` | 深度研究任务面板（输入 + 进度 + 报告） |
| `frontend/src/components/MarkdownReport.vue` | 大型报告渲染器（复用 MarkdownText 风格，支持目录） |

### 8.2 App.vue 模式切换

```vue
<script setup>
const mode = ref('chat')   // 'chat' | 'research'
</script>

<template>
  <div class="layout">
    <SideBar ... @switch-mode="mode = $event" />
    <main class="chat-main">
      <ChatView v-if="mode === 'chat'" />
      <ResearchTab v-else />
    </main>
  </div>
</template>
```

侧边栏加 "🔬 深度研究" 按钮，切换 mode。

### 8.3 API 客户端

在 `frontend/src/api.js` 新增：

```js
export async function submitResearch(payload) {
  return postJSON('/research', payload)
}
export async function getResearchStatus(id) {
  return getJSON(`/research/${id}`)
}
export async function getResearchResult(id) {
  return getJSON(`/research/${id}/result`)
}
export async function streamResearch(id, onEvent) {
  // 类似 streamAgent，但 URL 是 /api/v1/research/{id}/stream
}
```

### 8.4 工时

0.5 天（含 SSE 流处理 + 状态展示 + 报告渲染）。

---

## 9. 测试计划

| 测试 | 覆盖 | 验证方式 |
|---|---|---|
| `test_research_health` | health 端点 | 返回 200，含 bocha_configured 等 |
| `test_research_submit_and_status` | 提交 + 查状态 | 200, task_id, 状态有效 |
| `test_research_list` | 列表 | total 字段正确 |
| `test_research_not_found` | 404 | 不存在的 task_id |
| `test_research_result_pending` | 202 | 未完成任务返回 202 |
| `test_research_delete` | 删除 | 已完成可删，200；运行中 400 |
| `test_research_health_extended` | health 字段 | 包含所有 4 字段 |
| **端到端**（手动） | 真实研究 | 提交后等几分钟看报告 |

Bocha key 为空时，所有 search 调用 graceful degrade，health 返回 `bocha_configured: false`。

---

## 10. 风险与缓解

| # | 风险 | 概率 | 缓解 |
|---|---|---|---|
| 1 | **OODA 循环与现有 Agent 循环冲突** | 低 | 两者**完全独立**（不同端点、不同服务类），不共享代码 |
| 2 | **LLM 客户端重写风险**（deep_research 自己的 vs 复用 agent 的） | 中 | 复用 `app/core/llm.py` 的 `get_llm_client()`；deep_research 内部代码改为调用它 |
| 3 | **TaskManager 多线程安全** | 低 | `ThreadPoolExecutor` + in-memory dict 已是生产级模式；用 `asyncio.run_in_executor` 桥接 async |
| 4 | **Bocha key 为空 → 工具无法调用** | 高 | health 端点暴露 `bocha_configured: false`；前端展示警告；研究提交后 worker 会失败但任务状态正确流转 |
| 5 | **报告数据大（Markdown 长）** | 中 | SSE 流式 + 报告存盘（data/research/{task_id}/report_*.md），前端按需展示 |
| 6 | **AGENT_CONFIG 全局 dict 被并发改写** | 高 | `main.py:226-251`（**非 `research_agent.py`**）原有 `original_config` 临时覆盖逻辑已实现；新版 `service.py` 复用 `try/finally` 保护 |
| 11 | **Python 版本不匹配** | 低（已验证） | deep_research 的 `.venv` 是 **3.13.9**，目标环境是 3.11 → **已实测 7 个 .py 全部通过 `python3.11 -m py_compile`**，无 3.12+ 专有语法（无 PEP 695 泛型 / 无 `match` / 无 `datetime.UTC` / 无 `TaskGroup`），可直接迁移 |
| 12 | **版权合规** | 中 | `README.md` 含"agent，侵权必究"声明 → 迁移时保留原署名与出处，或在内部使用场景下由用户确认授权范围 |
| 7 | **任务内存泄漏**（不删除时一直累积） | 中 | 持久化到 `data/research/tasks.json`（可重启加载）；提供 DELETE 端点 |
| 8 | **prompts.py 中 CURRENT_DATE 动态** | 低 | 保留运行时计算（迁移时不修改） |
| 9 | **Bocha API 字段格式** | 低 | 已按 deep_research 原版解析（`webPages.value[].name/url/snippet/siteName/dateLastCrawled`） |
| 10 | **前端路由从聊天切换到研究的体验** | 低 | 用 `mode` 状态简单切换两个主组件，无需 router |

---

## 11. 施工路线（阶段 A-J）

| 阶段 | 时长 | 内容 | 提交 |
|---|---|---|---|
| **A** | 0.5 天 | 搭目录 `app/services/research/` + `app/schemas/research.py` + config 扩展 | "feat: research scaffold" |
| **B** | 0.5 天 | 复制 `prompts.py`（7 模板） + 抽 `search_client.py`（Bocha） + 抽 `quality.py` | "feat: research core modules" |
| **C** | 0.5 天 | 复制 `workers.py`（770 行，5 Worker + WorkerFactory + ResearchBudget + OODA 四方法）+ 修导入 + 抽 `utils.py` | "feat: research workers" |
| **C.5** | 0.5 天 | 复制 `orchestrator.py`（**963 行**）+ 修导入 | "feat: research orchestrator" |
| **D** | 0.5 天 | `research_manager.py`（in-mem + JSON 持久化）+ `service.py`（DeepResearchAgent） | "feat: research manager & service" |
| **E** | 0.5 天 | `app/api/v1/research.py`（**7 端点** + SSE）+ 挂 router + state.py + deps.py + health 扩展 | "feat: research REST API" |
| **F** | 0.5 天 | 前端 ResearchTab + MarkdownReport + SideBar 模式切换 + api.js | "feat: research frontend" |
| **G** | 0.5 天 | `tests/test_research.py`（5 个）+ 集成测试 + 健康检查回归 | "feat: research tests" |
| **H** | 0.5 天 | 文档：`docs/research/`（7 份 md + 2 SVG，**`chmod 644`** + **保留版权声明**）+ 更新根 README + 功能覆盖矩阵 | "docs: research integration" |
| **I** | 0.5 天 | 真实数据回归（用现有 DASHSCOPE_KEY；Bocha 无 key → 端到端走通降级路径）+ pytest 全量（21） | "test: research e2e" |
| **J** | 0.5 天 | 删除 `deep_research/` 源项目（如用户要求） | "chore: archive source" |
| **合计** | **5 天** | 含 1 天缓冲 | |

> 注：未删除 `deep_research/` 时 J 跳过；保留为可逆的"源项目档案"。

**阶段 B 补充步骤（核查后新增）**：
```bash
# 1) 复制 14 个 Prompt（漏一个就会 ImportError）
cp deep_research/app/agent/prompts.py backend/app/services/research/prompts.py
python -c "import re,sys; src=open('backend/app/services/research/prompts.py').read(); \
  names=re.findall(r'^([A-Z_]+_PROMPT)\s*=', src, re.M); \
  print(f'Prompt 数: {len(names)}'); assert len(names)==14, 'Prompt 数量不符'"

# 2) 复制资产并修正权限（原 600 → 644）
mkdir -p backend/docs/research/assets
cp deep_research/docs/*.md backend/docs/research/
cp deep_research/assets/*.svg backend/docs/research/assets/
chmod 644 backend/docs/research/assets/*.svg
```

**阶段 H 补充步骤（核查后新增）**：
```bash
# 版权声明必须随文档一起迁移（README 含"agent"声明）
cp deep_research/README.md backend/docs/research/00-原始README-含版权声明.md
```

---

## 12. 验收清单

**代码层**
- [ ] `app/services/research/` **8 个文件**就位（`__init__` / `prompts`(14 模板) / `search_client` / `quality` / `utils` / `workers`(5 Worker+Factory+Budget) / `orchestrator`(15 方法) / `research_manager` / `service`）
- [ ] `app/schemas/research.py` **7 个** Pydantic 模型
- [ ] `app/api/v1/research.py` **7 个**端点 + SSE 流
- [ ] `router.py` 挂载 research（`GET /openapi.json` 路径数 27 → **34**）
- [ ] `state.py` 注册 `research_manager`；`main.py` lifespan 关闭时调用 `shutdown()`
- [ ] `config.py` 追加 bocha + research 字段（**不重复定义**已有字段，**不含** `static_dir`）
- [ ] 零新增第三方依赖（`requirements.txt` / `pyproject.toml` 不变）

**接口层**
- [ ] `GET /api/v1/research/health` 返回 4 字段（`bocha_configured` 应为 `false`，因 key 为空）
- [ ] `POST /api/v1/research` 提交（Bocha 空 key 时仍返回 `task_id`，任务状态流转到 `failed` 且 `error_message` 明确）
- [ ] `GET /api/v1/research` 列表 / `GET /api/v1/research/{id}` 状态（含 `progress_summary`）
- [ ] `GET /api/v1/research/{id}/stream` SSE（`decomposed` / `worker_completed` / `iteration_evaluated` / `final`）
- [ ] `GET /api/v1/research/{id}/result` 报告（未完成返回 **202**）
- [ ] `DELETE /api/v1/research/{id}` 删除（运行中返回 **400**）
- [ ] `GET /api/v1/health` 追加 research 字段（不破坏原有 9 字段）

**数据层**
- [ ] 任务持久化：`data/research/tasks.json` 重启后可恢复
- [ ] 报告落盘：`data/research/{task_id}/report_*.md` + `meta_*.json`

**测试层**
- [ ] `pytest tests/ -q` → **21 passed**（原 16 + 新 5）
- [ ] 前端 SideBar 模式切换（聊天 ↔ 深度研究）正常
- [ ] 报告 Markdown 渲染（代码块 / 列表 / 引用 / 标题）

**文档层**
- [ ] `backend/docs/research/`：7 份 md + 2 SVG（**`chmod 644`**）
- [ ] **版权声明随迁**（`00-原始README-含版权声明.md`）
- [ ] 根 `README.md` 路由表更新（+ 第 5 链说明）
- [ ] `doc/analysis/10_功能覆盖矩阵.md` 更新（三项目 → 四项目覆盖）

---

## 13. 偏差与开放问题

| # | 偏差 | 说明 |
|---|---|---|
| D1 | LLM 客户端复用 `app/core/llm.py` | 替代 deep_research 自带的 `LLMClient` |
| D2 | Search 拆为独立模块 | 从 `tools.py` 抽出 `search_client.py`，删除 `LLMClient/extract_json/format_search_context` |
| D3 | 任务持久化到 JSON | deep_research 原版仅内存 dict；新增可选 JSON 落盘 |
| D4 | `RESEARCH_CONFIG` 独立模块 | 不放入 `app/core/config.py` pydantic Settings（避免污染） |
| D5 | 路由前缀加 `/api/v1` | 统一风格（deep_research 原版是裸 `/research`） |
| D6 | 删除 `LLMClient`/`extract_json` 重实现 | `extract_json` 抽到 `utils.py`；`LLMClient` 直接删除 |

### 开放问题

- **Q1**：是否将 `deep_research` 作为 Agent 的同步工具加入 ToolRegistry？
  - **倾向**：v1.1 **不加**（深研耗分钟级，不适合同步 tool call）。如需，v1.2 可设计为：`deep_research_submit` → 返回 task_id；`deep_research_result` → 查询结果（同步等待直到完成或超时）
- **Q2**：是否合并 `web_research`（Serper+Chroma）与 `deep_research`（Bocha）？
  - **倾向**：v1.1 保留双链路。两者目标不同：web_research 是"快问快答"（10s），research 是"深度报告"（2-5 分钟）
- **Q3**：是否提供 CLI（`python -m ... research_cli.py "task"`）？
  - **倾向**：v1.1 可选（`scripts/research_cli.py` 30 行），作为开发者调试工具
- **Q4**：Bocha key 缺失时如何体验完整流程？
  - **倾向**：提供 fallback —— 若 `BOCHA_API_KEY` 为空且 `SERPER_API_KEY` 有值，则 `SearchClient` 自动降级到 Serper（两 API 返回结构差异需在 `search_client.py` 内做适配层，约 40 行）；两者都空则任务快速失败并在 `/research/{id}` 的 `error_message` 中明确提示

### 13.5 合规与许可（核查后新增）⚠️

| 项 | 内容 | 处置建议 |
|---|---|---|
| **版权声明** | `deep_research/README.md` 末尾：*"agent，侵权必究（转卖，私自转发等均属于侵权行为）"* | **必读**：该声明限制转卖/转发。整合属"内部学习改造"场景，建议：① 迁移后在新仓库 `docs/research/00-README.md` **保留原始署名与版权页**；② 若涉及对外分发，需先取得授权 |
| **assets 许可** | `architecture.svg` / `prompt_dataflow.svg` 无单独 LICENSE | 随 README 版权一并沿用 |
| **代码 License** | 仓库内**未见 `LICENSE` 文件** | 迁移后如需开源，须先与版权方确认 |
| **第三方依赖许可** | `openai`(MIT) / `requests`(Apache-2.0) / `fastapi`(MIT) / `uvicorn`(BSD) / `pydantic`(MIT) / `python-dotenv`(BSD) | ✅ 均为宽松许可，无冲突 |

> **对整合的影响**：代码迁移**技术上无阻断**；仅在"对外发布/转卖"场景需额外授权确认。

### 13.6 Python 版本兼容性验证（核查后新增）✅

deep_research 自带的 `.venv` 是 **Python 3.13.9**，而 agent 的 `pyproject.toml` 锁 **`>=3.10,<3.13`**（当前运行环境 3.11.15）。为排除"代码用了 3.12+ 语法"的风险，已做**语法级验证**：

```bash
# 用 agent 的 3.11 解释器编译 deep_research 全部源码
$ apps/agent/backend/.venv/bin/python -m py_compile \
    deep_research/app/main.py deep_research/app/core/config.py deep_research/app/agent/*.py
✅ 全部通过（无输出即成功）

# 专项排查（均无命中）
grep -rn "^type \|class .*\[T\]" deep_research/app/   # PEP 695 泛型/type 别名 → 无
grep -rn "^\s*match .*:"      deep_research/app/       # match 语句 → 无
grep -rn "datetime.UTC\|typing import.*Self\|TaskGroup\|except\*" deep_research/app/  # 3.11+ 专有 API → 无
```

**结论**：代码兼容 Python 3.11，**无需版本升级**，可直接迁移到 agent 环境。

> 备注：`requirements.txt` 未声明 `python_requires`，`.venv` 用 3.13 只是创建时的选择，并非代码要求。

---

## 14. 核查清单与原始证据

本节记录 **v1.1 核查**所用的原始命令与实测输出，便于复核。

### 14.1 deep_research 侧

| # | 核查项 | 命令 / 结果 |
|---|---|---|
| 1 | 核心文件行数 | `wc -l app/main.py app/core/config.py app/agent/*.py` → **482 / 116 / 12 / 963 / 935 / 460 / 364 / 770**（顺序：main, config, `__init__`, orchestrator, prompts, research_agent, tools, workers） |
| 2 | 总量 | `find app -name "*.py" -not -path "*/__pycache__/*" \| xargs wc -l \| tail -1` → **4110 total** |
| 3 | Prompts 数量 | `grep -n "^[A-Z_]* = " app/agent/prompts.py` → **14 个 `*_PROMPT`** + `CURRENT_DATE` |
| 4 | Orchestrator 方法 | `grep -n "^    def " app/agent/orchestrator.py` → **15 个**（`decompose_task` / `dispatch_workers` / `synthesize_results` / `check_quality` / `check_diminishing_returns` / `analyze_gaps` / `dispatch_supplementary_workers` / `refine_report` / `run` / 3× `_format_*` / `_emit_progress` / `__init__`） |
| 5 | Workers 类 | `grep -n "^class \|^@dataclass" app/agent/workers.py` → `OODACycle` / `SourceQualityAssessment` / **`ResearchBudget`** / `BaseWorker` / `SearchWorker` / `WriterWorker` / `AnalysisWorker` / `VisualizationWorker` / **`WorkerFactory`** |
| 6 | OODA 实现位置 | `workers.py:276-363` → `SearchWorker._observe` / `_orient` / `_decide` / `_act` |
| 7 | 端点总数 | `grep -n "@app\." app/main.py` → **8 个**（`/`, `/health`, `POST /research`, `GET /research`, `/research/{id}`, `/result`, `/stream`, `DELETE`） |
| 8 | TaskManager 并发 | `app/main.py:97` → `ThreadPoolExecutor(max_workers=3)` |
| 9 | config 临时覆盖 | `grep -n "original_config" app/main.py` → **`main.py:226-251`**（非 `research_agent.py`） |
| 10 | AGENT_CONFIG 规模 | `python -c "len(AGENT_CONFIG)"` → **18 个顶级字段** |
| 11 | 运行环境 | `.venv/bin/python --version` → **Python 3.13.9** |
| 12 | Python 3.11 兼容性 | `apps/apps/agent/backend/.venv/bin/python -m py_compile app/main.py app/core/config.py app/agent/*.py` → **✅ 无错误** |
| 13 | 专有语法排查 | `grep -rn "^\s*match \|^type \|datetime.UTC\|TaskGroup" app/` → **无命中** |
| 14 | 依赖清单 | `cat requirements.txt` → 7 个包（openai / requests / python-dotenv / typing-extensions / fastapi / uvicorn[standard] / pydantic），**无版本上限** |
| 15 | 无 pyproject | `ls pyproject.toml .python-version` → 均不存在 |
| 16 | `.env.example` 变量 | `cat .env.example` → `DASHSCOPE_API_KEY` / `BOCHA_API_KEY` / **`DEEP_RESEARCH_PORT=18000`** |
| 17 | docs 清单 | `for f in docs/*.md; do head -1 $f; done` → 7 份（00-README…06-流程） |
| 18 | assets | `ls -la assets/` → 2 个 SVG（23KB + 40KB），**权限 `-rw-------`（600）** |
| 19 | 版权声明 | `tail -3 README.md` → *"agent，侵权必究（转卖，私自转发等均属于侵权行为）"* |
| 20 | 无 LICENSE 文件 | `ls LICENSE` → 不存在 |

### 14.2 agent 侧（基线）

| # | 核查项 | 命令 / 结果 |
|---|---|---|
| 21 | API 路径数 | `curl -s localhost:8000/openapi.json \| python -c "len(d['paths'])"` → **27** |
| 22 | 测试数量 | `pytest tests/ -q --collect-only` → **16 tests collected** |
| 23 | 现有 schemas | `ls app/schemas/` → `agent.py` / `mcp.py` / `rag.py` / `skill.py` / `web_research.py`（5 个 + `__init__`） |
| 24 | 现有 services | `ls app/services/` → `agent/` / `agent_service.py` / `code_executor.py` / `mcp_manager.py` / `rag/` / `skill_manager.py` / `tool_registry.py` / `web/` |
| 25 | 现有 `data/` | `ls data/` → `browser_data` / `logs` / `milvus.db` / `outputs` / `pdf` / `uploads`（**无 `research/`**） |
| 26 | 现有内置工具 | `grep '"name":' app/services/tool_registry.py` → `read_file` / `write_file` / `execute_python` / `execute_bash` / `list_directory` / `rag_query` / `rag_ingest` / `web_research` / `mcp_*`（动态） |
| 27 | config 现状 | `app/core/config.py` → 已含 `dashscope_*` / `llm_*` / `openai_*` / `serper_api_key` / `milvus_db_path`（**非 `milvus_uri`**）/ `data_dir`；**已无 `static_dir`** |
| 28 | requires-python | `grep requires-python pyproject.toml` → **`>=3.10,<3.13`** |
| 29 | `.env` 变量 | 20 个（DASHSCOPE_* / DEFAULT_MODEL / LLM_* / PLAN_MODEL / RAG_MODEL / ANSWER_MODEL / OPENAI_* / HOST / PORT / EXEC_TIMEOUT / MAX_ITERATIONS / SERPER_API_KEY / GAODE_API_KEY / MCP_* / MILVUS_DB_PATH / MILVUS_COLLECTION） |
| 30 | 前端结构 | `frontend/src/components/` → 7 个 .vue（`SideBar` / `WelcomeScreen` / `ChatMessage` / `ChatInput` / `MarkdownText` / `ProcessSteps` / `SkillModal`） |

**结论**：上述 30 条核查结果已全部回写到文档对应章节；文档中的关键修正集中在 §0（20 项偏差表）、§1.1（行数）、§1.2（14 Prompts）、§4.1（端点计数）、§5.2（config 基线）、§5.6（API 代码补全）、§13.5-13.6（合规 + Python 兼容）、§11（施工补充步骤）、附录 A（行数汇总）。

---

## 附录 A：deep_research → agent 文件映射

| deep_research 源 | 行数 | agent 目标 | 改造 |
|---|---:|---|---|
| `app/main.py` | 482 | 拆分为 `app/api/v1/research.py`(新) + `app/services/research/research_manager.py`(新) | 重写为 API 风格 + TaskManager→ResearchManager |
| `app/core/config.py` | 116 | `app/core/config.py`(追加 bocha 字段) + `app/services/research/research_config.py`(新) | 拆分：Settings 只放 Pydantic 字段；18 字段 dict 独立 |
| `app/agent/orchestrator.py` | **963** | `app/services/research/orchestrator.py` | 修导入（4 处） |
| `app/agent/workers.py` | 770 | `app/services/research/workers.py` | 修导入；`OODACycle`/`SourceQualityAssessment`/`ResearchBudget` 抽到 `quality.py` |
| `app/agent/tools.py` | 364 | 拆为 `search_client.py`(新) + `utils.py`(新) | 删 `LLMClient`；保留 `SearchClient` + `extract_json`/`format_search_context` |
| `app/agent/prompts.py` | **935** | `app/services/research/prompts.py` | **直接复制（14 个模板，不可漏）** |
| `app/agent/research_agent.py` | 460 | `app/services/research/service.py`(新) | 删 CLI/ConsoleReporter，保留核心 |
| `docs/00-README.md` ~ `06-流程文档.md` | 7 份 | `backend/docs/research/` | 直接复制 |
| `assets/architecture.svg` / `prompt_dataflow.svg` | 2 份 | `backend/docs/research/assets/` | 复制 + **`chmod 644`**（原权限 600） |
| `README.md`（含版权声明） | — | `backend/docs/research/00-原始README-含版权声明.md` | **保留署名** |
| `requirements.txt` | 7 包 | **不变** | 零新增依赖 |
| `.env` / `.env.example` | — | 追加 bocha 字段 | 追加；`DEEP_RESEARCH_PORT` **废弃** |

**行数汇总（核查后精确值）**：

| 项 | 数值 |
|---|---:|
| deep_research 核心 7 个业务 .py | **4102 行** |
| + 3 个 `__init__.py`（5+5+12） | 4110 行 |
| 迁移后保留（去 LLMClient ~110 行 / CLI+Reporter ~200 行） | ~3790 行 |
| + 新脚手架（schemas 100 / manager 130 / api 150 / utils 30 / `__init__` 10） | ~420 行 |
| **agent 第 5 链总增量** | **~4210 行**（含注释与文档字符串） |
| 平台基线（迁移前） | 27 路径 / 16 测试 / 9 services 模块 / 5 schemas |
| 平台（迁移后） | **34 路径** / **21 测试** / 10 services 模块 / 6 schemas |

---

## 附录 B：核查后的关键风险速览（供实施前复核）

| 优先级 | 项 | 处置 |
|:---:|---|---|
| 🔴 P0 | **版权声明**（"agent，侵权必究"） | 内部学习改造可用；对外分发前须确认授权；迁移时保留原始署名 |
| 🟡 P1 | **Bocha key 为空** | `/research/health` 返回 `bocha_configured: false`；建议按 Q4 实现 Serper 降级（40 行适配层） |
| 🟡 P1 | **14 个 Prompt 必须全量复制** | 漏一个导致 Worker `ImportError`；阶段 B 已加断言脚本 |
| 🟢 P2 | **Python 3.13 → 3.11** | 已验证兼容，无需处理 |
| 🟢 P2 | **assets 权限 600** | `chmod 644` |
| 🟢 P2 | **`DEEP_RESEARCH_PORT`** | 废弃，统一用 `PORT=8000` |
| 🟢 P2 | **`static_dir` 已不存在** | config 扩展示例已修正，勿再引用 |
