# agent-platform 代码分析文档集

> - **依据代码**：`backend/app/`、`backend/skills/`、`backend/tests/`、`frontend/web/vue-element-plus/src/`、`frontend/desktop/src/`、`deploy/`、`docker-compose.yml`
> - **资料来源**：2026-10-27 逐文件复核（含 OpenAPI 规格导出、pytest/vitest 实跑、SQLite 库结构交叉验证）
> - **整理日期**：2026-10-27（S0~S8 阶段编码完成后复核）
> - **文档集定位**：**当前代码的事实描述 + 风险台账**。目标形态与已实现标记见 `doc/design/`，**尚未实现但已设计的功能见 `doc/plan/`**，通用原理见 `doc/knowledge/`，部署操作手册见 `deploy/`。

---

## 一、本目录定位

| 目录 | 回答的问题 | 读者 |
|---|---|---|
| **`doc/analysis/`**（本目录） | 这个平台**现在**由什么组成、怎么跑、数据落在哪、哪里有风险 | 全角色 |
| `doc/design/` | **项目总目标**与**已实现部分的标记**（差距矩阵的状态列、阶段交付台账） | 决策者 / 排期 |
| `doc/plan/` | **还没做、但已经设计清楚**的功能（分批排期用） | 负责人 / 排期 |
| `doc/design/` | 目标形态与阶段化设计（`09` 差距矩阵、`08` 交付实况） | 负责人 / 架构 |
| `doc/design/11~14` | 竞品对标、阶段交付台账、能力演进对照、测试与发布策略（**已实现标记的主载体**） | 追溯 |
| `doc/knowledge/` | 某个技术**为什么这样设计**（协议、架构模式、第三方组件原理） | 深入学习者 |
| `deploy/README.md` + `deploy/部署文件分析与操作手册.md` | **怎么部署、怎么排错**（随代码维护的运维视角） | 运维 / 交付 |

**边界**：本目录只描述 `backend/app` + `frontend/web/vue-element-plus` + `frontend/desktop/src` 的**当前实现**。
凡本目录未提及的能力，不存在；凡本目录标注「未实现」的，是代码中预留但无生效逻辑的字段或分支；
**凡"计划要做但还没做"的内容，一律不写在这里，已迁到 `doc/plan/`**。

---

## 二、文档索引

| # | 文档 | 核心问题 | 主要读者 |
|---|---|---|---|
| 00 | 本文件 | 从哪读起、口径是什么 | 所有人 |
| 01 | [架构总览](./01_架构总览.md) | 平台由哪些层组成？启动做了什么？两种运行模式怎么区分？ | 所有人 |
| 02 | [能力链实现](./02_能力链实现.md) | Skill / MCP / RAG / Web Research / Deep Research 五条链各自怎么实现？ | 后端 / LLM 应用 |
| 03 | [Agent 执行引擎与事件协议](./03_Agent执行引擎与事件协议.md) | function-calling 循环怎么跑？SSE 事件各是什么？ | 后端 / 前端 |
| 04 | [数据模型与持久化](./04_数据模型与持久化.md) | 22 张业务表怎么设计？幂等与一致性怎么保证？ | 后端 / 数据 |
| 05 | [HTTP 接口总览](./05_HTTP接口总览.md) | 91 个端点分别做什么？错误码与状态码怎么用？ | 前后端 |
| 06 | [前端架构与接口契约](./06_前端架构与接口契约.md) | 19 个视图怎么组织？前端如何消费 SSE？前后端契约有哪些差异？ | 前端 |
| 07 | [DeepResearch 链路](./07_DeepResearch链路.md) | Orchestrator-Workers + OODA + 评分迭代怎么协同？ | LLM 应用 |
| 08 | [调度与运行账本](./08_调度与运行账本.md) | 定时任务如何防重、幂等、退避？运行记录如何回放？ | 后端 / 运维 |
| 09 | [部署形态与端口矩阵](./09_部署形态与端口矩阵.md) | 三种部署形态怎么选？端口/配置项/数据目录各是什么？ | 运维 / 交付 |
| 10 | [可观测体系现状与方案](./10_可观测体系现状与方案.md) | 现在能观测到什么？缺什么？ | 后端 / 运维 |
| 11 | [高并发现状与瓶颈](./11_高并发现状与瓶颈.md) | 真实并发模型是什么？瓶颈在哪？ | 后端 / 架构 |
| 12 | [能力覆盖与风险台账](./12_能力覆盖与风险台账.md) | 每个能力实现到什么程度？已知缺陷有哪些？ | 负责人 / 排期 |
| 13 | [桌面端现状盘点与需求论证](./13_桌面端现状盘点与需求论证.md) | 桌面端现在能做什么？与后端怎么耦合？ | 负责人 / 前端 / 后端 |

> 2026-09 口径的旧文档（合并前 `apps/agent/` 形态）已清理：其结论已被本篇与 `../design/` 覆盖，**不再保留副本**。

---

## 三、推荐阅读路径

| 角色 / 任务 | 顺序 |
|---|---|
| **新人（1~2 天）** | `01`（全景）→ `02`（五链）→ `03`（执行引擎）→ 按兴趣选 `04`/`06` |
| **后端开发** | `03`（执行引擎 + 事件协议）→ `05`（接口契约）→ `04`（数据层）→ `08`（调度） |
| **前端开发** | `06`（架构 + 契约 + SSE 消费）→ `05`（接口全表）→ `03` §5~§6（事件来源） |
| **运维 / 交付** | `09`（部署形态 + 端口 + 配置）→ `08`（调度与租约）→ `10`（可观测现状）→ `deploy/README.md` |
| **排期 / 评估** | `12`（覆盖矩阵 + 缺陷台账）→ `../plan/`（待办批次）→ `../design/09`（差距矩阵 → 阶段归属） |
| **桌面端** | `13`（现状盘点）→ `../design/03`（壳与进程编排）→ `../design/08`（交付实况） |
| **按具体任务查** | 「想知道 X 在哪」→ `12` §1 覆盖矩阵的「实现篇号」列 → 直接跳该篇 |

---

## 四、口径声明

1. **一切结论以当前代码为准**，路径一律用仓库相对路径（`backend/app/...`、`frontend/web/vue-element-plus/src/...`、`frontend/desktop/src/...`），关键事实带 `文件:行号`。
2. **事实篇（01~09、13）只写代码里存在的实现**，不写「建议」「路线图」；每篇末尾的「改进指向」只给**问题一句话 + 优先级 + `12` 台账条目号**。
3. **诊断篇（10~12）中的代码块均为「未实现（参考实现）」**，不代表仓库现状。
4. **数字统一取自 §5 的口径常量表**，各篇不独立统计。
5. **行号以基线 commit 为准**；代码变更后需复核引用位置，`05` 各篇「核对方式」章节给出可执行命令。
6. **「已实现」的判定标准**：代码存在 **且** 有生效逻辑 **且** 有对应测试覆盖（三者缺一即算未完成，记入 `12` 台账）。
7. **未完成但已设计的功能**统一在 `../plan/` 立项，本目录只留指向，不再展开方案。

---

## 五、口径常量表（13 篇的唯一数字来源）

| # | 常量 | 值 | 复核方式 |
|---|---|---|---|
| C01 | 后端子 router | **17** | `backend/app/api/v1/router.py` |
| C02 | 后端端点 | **91 路径 / 118 操作** | GET 53 / POST 47 / DELETE 9 / PUT 7 / PATCH 2 ｜ OpenAPI 规格导出 |
| C03 | SSE 端点数 | **5** | `/agent/run`、`/runs/{id}/events`、`/runs/{id}/stream`、`/research/{id}/stream`、`/desktop/events` |
| C04 | 数据库业务表数 | **22**（物理表 23，含 `alembic_version`） | `backend/app/db/models.py` |
| C05 | Alembic 版本数 | **8** | `0001_init` / `0002_desktop` / `0003_mode_unify` / `0004_security` / `0005_workspace` / `0006_context` / `0007_extensions` / `0008_rag_ingest` |
| C06 | 内置 Skill 数 | **6** | `backend/skills/*/SKILL.md` |
| C07 | MCP Server 数 | **3** | weather / search / xiaohongshu ｜ `mcp_manager.py` |
| C08 | 静态工具数 | **9 + 2 MCP 检索工具** | 内置 7（含 `tool_search`/`tool_load`）+ RAG 2 ｜ `tool_registry.py` |
| C09 | 共享服务数 | **17** | `backend/app/core/state.py` + `desktop_service` / `scheduler_service` / `permission_service` 等 |
| C10 | RAG collection / 向量维度 | **`hybrid_demo` / 1024** | `core/config.py`；`milvus_store.py` |
| C11 | 前端视图数 | **19** | `src/views/*.vue` |
| C12 | 前端组件数 / 布局数 | **21 / 2** | `src/components/`（含 `composer/`）、`src/layouts/` |
| C13 | 前端 store 数 | **6** | config / session / workspace / permissions / desktop / rounds |
| C14 | 前端 API 常量数 | **93** | `src/api/endpoints.ts` |
| C15 | 前端 Agent 事件类型 | **27** | `src/api/types.ts`（含 S2~S7 新增的 `interrupted`/`steer_injected`/`context_compressed` 等） |
| C16 | Research SSE 事件 / stage | **2 / 24** | `progress`、`final` |
| C17 | 后端 pytest 用例 | **326** | 22 个测试文件（含 S2/S3/S4/S5/S6/S7 契约套件） |
| C18 | 前端 vitest 用例 | **83** | 18 个测试文件 |
| C19 | 旧路径 redirect 数 | **13** | `src/router/index.ts` |
| C20 | 端口矩阵 | Vite dev **5185** → proxy **18040**；本地后端 **8000/8001**；Compose 对外 **8080**；容器内后端 **8000**；Milvus **19530** | `vite.config.ts`；`docker-compose.yml` |
| C21 | 模型默认值 | `default_model=qwen-plus`、`plan_model=qwen-plus`、`rag_model=qwen-turbo`、`answer_model=qwen-plus`（**统一千问**） | `core/config.py`；`backend/.env` |
| C22 | 关键阈值 | `max_iterations=20`、`chat_max_iterations=5`、`exec_timeout=180`、`schedule_max_concurrent=2`、`permission_approval_timeout=120`、`context_budget_ratio=0.85`、`context_compact_threshold=0.70`、`context_summary_threshold=0.85`、`context_memory_max=5` | `core/config.py` |

> **实测（2026-10-28 · 批次 01~03 交付后）**：后端 pytest **366 passed / 0 failed**；前端 vitest **83 passed**；桌面壳 vitest **45 passed** + typecheck 0 错误；端到端套件 **44 passed / 0 skipped**；打包产物自检 **9/9 通过**（`scripts/verify_desktop_package.py`）。
>
> **桌面端**：后端 `app/desktop/`（launcher / bootstrap / events）、`api/v1/desktop.py`；壳工程 `frontend/desktop/`（Electron 主进程 / 托盘 / 快捷键 / 通知 / 更新 / 事件桥）；前端 `api/desktop.ts`、右侧结果区（S3）、成本条与上下文表（S5）、角色/插件/黑板三视图（S6）。设计见 `../design/00~07`，差距对照见 `../design/09`，竞品对标见 `../design/11`。

---

## 六、资产说明

| 目录 | 内容 | 维护方式 |
|---|---|---|
| `assets/ui/` | 本平台界面截图 | 界面变更后需重新截图更新 |
| `assets/reference/` | 外部产品（Trae / WorkBuddy）官网与界面取证截图 | **非本平台界面**，仅作设计对标参考，不随代码更新 |

---

## 七、公共参考

| # | 类型 | 主题 | 链接 |
|---|---|---|---|
| R-01 | 官方 | FastAPI 路由与依赖注入 | https://fastapi.tiangolo.com/tutorial/ |
| R-02 | 官方 | FastAPI StreamingResponse（SSE） | https://fastapi.tiangolo.com/advanced/custom-response/ |
| R-03 | 官方 | Pydantic Settings | https://docs.pydantic.dev/latest/concepts/pydantic_settings/ |
| R-04 | 官方 | SQLAlchemy 2.0 ORM | https://docs.sqlalchemy.org/en/20/orm/ |
| R-05 | 官方 | Alembic 教程 | https://alembic.sqlalchemy.org/en/latest/tutorial.html |
| R-06 | 官方 | SQLite WAL 模式 | https://www.sqlite.org/wal.html |
| R-07 | 官方 | APScheduler 用户指南 | https://apscheduler.readthedocs.io/en/3.x/userguide.html |
| R-08 | 官方 | Milvus Lite | https://milvus.io/docs/milvus_lite.md |
| R-09 | 官方 | Milvus 全文检索（BM25 Function） | https://milvus.io/docs/full-text-search.md |
| R-10 | 官方 | Anthropic Model Context Protocol | https://modelcontextprotocol.io |
| R-11 | 官方 | Anthropic Agent Skills | https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills |
| R-12 | 标准 | OWASP API Security Top 10 (2023) | https://owasp.org/API-Security/editions/2023/en/0x11-t10/ |
| R-13 | 官方 | MDN EventSource / ReadableStream / AbortController | https://developer.mozilla.org/zh-CN/docs/Web/API/EventSource |
| R-14 | 官方 | 阿里云百炼（DashScope）模型服务 | https://help.aliyun.com/zh/model-studio/ |
| R-15 | 官方 | 博查 AI 搜索 API | https://open.bochaai.com/ |
| R-16 | 官方 | Serper.dev 搜索 API | https://serper.dev/ |
| R-17 | 官方 | Vue 3 / Element Plus / Pinia / Vue Router | https://cn.vuejs.org/ ｜ https://element-plus.org/zh-CN/ ｜ https://pinia.vuejs.org/ ｜ https://router.vuejs.org/ |
| R-18 | 官方 | Vite 6 构建与开发服务器 | https://cn.vite.dev/ |
| R-19 | 官方 | Docker Compose 规范 | https://docs.docker.com/compose/ |
| R-20 | 官方 | Nginx 反向代理（含 `proxy_buffering`） | https://nginx.org/en/docs/http/ngx_http_proxy_module.html |
| R-21 | 官方 | Electron | https://www.electronjs.org/docs/latest |
| R-22 | 官方 | electron-builder | https://www.electron.build/ |

> 各篇附录只引用本表的编号；本表未收录的链接写在该篇附录中。

---

> **阅读本目录前请记住三件事**：① 这里只描述**当前代码**，不描述计划（计划在 `../plan/`）；② 所有数字以 §5 常量表为准；③ 每条结论都带 `文件:行号`，可自行核对。
