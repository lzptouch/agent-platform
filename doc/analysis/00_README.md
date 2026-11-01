# agent-platform 代码分析文档集

> - **依据代码**：`apps/server/src/`、`skills/`、`apps/server/tests/`、`apps/ui/src/`、`apps/desktop/src/`、`deploy/README.md`
> - **资料来源**：2026-10-31 逐文件复核（含 OpenAPI 规格导出、vitest/vitest 实跑、SQLite 库结构交叉验证；口径常量由 `scripts/facts.py` 从代码直接提取）
> - **整理日期**：2026-10-31（S0~S8 阶段编码完成 + **P1~P6 六批次 83 项全部交付**后复核）
> - **文档集定位**：**当前代码的事实描述 + 风险台账**。目标形态与已实现标记见 `doc/design/`，通用原理见 `doc/knowledge/`，测试策略见 `doc/testing/`，部署操作手册见 `deploy/`。

---

## 一、本目录定位

| 目录 | 回答的问题 | 读者 |
|---|---|---|
| **`doc/analysis/`**（本目录） | 这个平台**现在**由什么组成、怎么跑、数据落在哪、哪里有风险 | 全角色 |
| `doc/design/` | **项目总目标**与**已实现部分的标记**（差距矩阵的状态列、阶段交付台账、能力演进对照） | 决策者 / 排期 |
| `doc/design/09` + `doc/design/12` | **还差什么**：差距矩阵（哪些没做）+ 阶段交付台账（做没做成） | 排期 / 追踪 |
| `doc/plan/` | **接下来怎么做**：P1~P6 六批次，每项含现象/根因/验收断言/测试用例 ID | 执行者 |
| `doc/design/11~15` | 竞品对标、阶段交付台账、能力演进对照、测试与发布策略、目标形态 | 追溯 |
| `doc/knowledge/` | 某个技术**为什么这样设计**（协议、架构模式、第三方组件原理） | 深入学习者 |
| `doc/testing/` | **可执行测试计划**：用例表、报告 schema、失败归类、CI 分层与门禁 | 测试 / 交付 |
| `deploy/README.md` + `deploy/部署文件分析与操作手册.md` | **怎么部署、怎么排错**（随代码维护的运维视角） | 运维 / 交付 |

**边界**：本目录只描述 `apps/server/src` + `apps/ui/src` + `apps/desktop/src` 的**当前实现**。
凡本目录未提及的能力，不存在；凡本目录标注「未接线 / 死代码 / 未生效」的，是代码中存在但无生效逻辑的模块或分支。
**凡"计划要做但还没做"的内容，一律不写在这里**，指向 `../design/09`（差距矩阵）。

> **口径变更说明（2026-10-31）**：原 `doc/plan/` 的 8 个批次已随批次 01~03 交付而整体删除；
> **2026-10-30 基于全量复核重建为 P1~P6 六批次**（49 条缺陷 + 13 个未接线模块 → 64 个工作项），
> 划分维度是「**修什么类型的病**」而非「做哪个模块」。
> **2026-10-31：六批次共 83 个工作项已全部交付**（P1~P6 状态列均为 ✅），本目录随之整体复核。
> 本目录原先指向 `../plan/xx` 的 39 处链接已统一改指 `../plan/` 或 `../design/09-差距矩阵与整改清单.md` 与本目录 `12` 篇的缺陷台账。

---

## 二、文档索引

| # | 文档 | 核心问题 | 主要读者 |
|---|---|---|---|
| 00 | 本文件 | 从哪读起、口径是什么 | 所有人 |
| 01 | [架构总览](./01_架构总览.md) | 平台由哪些层组成？启动做了什么？两种运行模式怎么区分？ | 所有人 |
| 02 | [能力链实现](./02_能力链实现.md) | Skill / MCP / RAG / Web Research / Deep Research 五条链各自怎么实现？ | 后端 / LLM 应用 |
| 03 | [Agent 执行引擎与事件协议](./03_Agent执行引擎与事件协议.md) | function-calling 循环怎么跑？SSE 事件各是什么？中断/steer 怎么生效？ | 后端 / 前端 |
| 04 | [数据模型与持久化](./04_数据模型与持久化.md) | 22 张业务表怎么设计？幂等与一致性怎么保证？ | 后端 / 数据 |
| 05 | [HTTP 接口总览](./05_HTTP接口总览.md) | 126 个操作分别做什么？错误码与状态码怎么用？ | 前后端 |
| 06 | [前端架构与接口契约](./06_前端架构与接口契约.md) | 19 个视图怎么组织？前端如何消费 SSE？前后端契约有哪些差异？ | 前端 |
| 07 | [DeepResearch 链路](./07_DeepResearch链路.md) | Orchestrator-Workers + OODA + 评分迭代怎么协同？ | LLM 应用 |
| 08 | [调度与运行账本](./08_调度与运行账本.md) | 定时任务如何防重、幂等、退避？运行记录如何回放？ | 后端 / 运维 |
| 09 | [部署形态与端口矩阵](./09_部署形态与端口矩阵.md) | 三种部署形态怎么选？端口/配置项/数据目录各是什么？ | 运维 / 交付 |
| 10 | [可观测体系现状与方案](./10_可观测体系现状与方案.md) | 现在能观测到什么？缺什么？ | 后端 / 运维 |
| 11 | [高并发现状与瓶颈](./11_高并发现状与瓶颈.md) | 真实并发模型是什么？瓶颈在哪？ | 后端 / 架构 |
| 12 | [能力覆盖与风险台账](./12_能力覆盖与风险台账.md) | 每个能力实现到什么程度？已知缺陷有哪些？ | 负责人 / 排期 |
| 13 | [桌面端现状盘点与需求论证](./13_桌面端现状盘点与需求论证.md) | 桌面端现在能做什么？与后端怎么耦合？ | 负责人 / 前端 / 后端 |
| **14** | [**权限引擎与安全边界**](./14_权限引擎与安全边界.md) | 三态权限怎么判定？审批怎么走？沙箱到底有没有？审计落在哪？ | 后端 / 安全 |
| **15** | [**工作区产物与变更回退**](./15_工作区产物与变更回退.md) | 工作空间怎么建？变更怎么记？产物怎么登记？回退怎么做？ | 后端 / 前端 |
| **16** | [**上下文经济性与成本核算**](./16_上下文经济性与成本核算.md) | 上下文怎么算账？压缩/裁剪阈值？记忆怎么注入？成本怎么记怎么查？ | 后端 / LLM 应用 |
| **17** | [**扩展层：角色 / 插件 / 黑板**](./17_扩展层角色插件与黑板.md) | 三个新扩展模块各自的能力边界？哪些只是 API 层生效？ | 后端 / 前端 |

> **新增 14~17 篇的理由**：S2（安全）、S3（工作区）、S5（上下文与成本）、S6（扩展层）四个阶段新增的能力，原先只在 `05`（接口表）与 `12`（台账）里被顺带提到，缺少**独立的功能流程说明**。
> 本次复核确认这四块都有**真实生效逻辑**且各自跨 3~5 个模块，值得独立成篇。

---

## 三、推荐阅读路径

| 角色 / 任务 | 顺序 |
|---|---|
| **新人（1~2 天）** | `01`（全景）→ `02`（五链）→ `03`（执行引擎）→ 按兴趣选 `04`/`06` |
| **后端开发** | `03`（执行引擎 + 事件协议）→ `05`（接口契约）→ `04`（数据层）→ `08`（调度）→ `14`/`15`/`16`/`17`（四个新能力域） |
| **前端开发** | `06`（架构 + 契约 + SSE 消费）→ `05`（接口全表）→ `03` §5~§6（事件来源）→ `15`（结果区数据源） |
| **运维 / 交付** | `09`（部署形态 + 端口 + 配置）→ `08`（调度与租约）→ `10`（可观测现状）→ `deploy/README.md` |
| **安全评审** | `14`（权限引擎 + 沙箱诚实口径 + 审计）→ `12` §三（安全专项）→ `15`（回退/另存的越权面） |
| **排期 / 评估** | `12`（覆盖矩阵 + 缺陷台账）→ `../design/09`（差距矩阵 → 阶段归属）→ `../design/12`（阶段交付台账） |
| **桌面端** | `13`（现状盘点）→ `../design/03`（壳与进程编排）→ `../design/08`（交付实况） |
| **按具体任务查** | 「想知道 X 在哪」→ `12` §1 覆盖矩阵的「实现篇号」列 → 直接跳该篇 |

---

## 四、口径声明

1. **一切结论以当前代码为准**，路径一律用仓库相对路径（`apps/server/src/...`、`apps/ui/src/...`、`apps/desktop/src/...`），关键事实带 `文件:行号`。
2. **事实篇（01~09、13~17）只写代码里存在的实现**，不写「建议」「路线图」；每篇末尾的「改进指向」只给**问题一句话 + 优先级 + `12` 台账条目号**。
3. **诊断篇（10~12）中的代码块均为「未实现（参考实现）」**，不代表仓库现状。
4. **数字统一取自 §5 的口径常量表**，各篇不独立统计。
5. **行号以 2026-10-29 工作区快照为准**（含未提交改动）；代码变更后需复核引用位置，各篇「核对方式」章节给出可执行命令。
6. **「已实现」的判定标准**：代码存在 **且** 有生效逻辑 **且** 有对应测试覆盖（三者缺一即算未完成，记入 `12` 台账）。
7. **未完成但已设计的功能**统一在 `../design/09` 立项，本目录只留指向，不再展开方案。

---

## 五、口径常量表（17 篇的唯一数字来源）

| # | 常量 | 值 | 复核方式 |
|---|---|---|---|
| 编号 | 指标 | 值 | 依据 |
|---|---|---|---|
| C01 | OpenAPI 路径数 / 操作数 | **98 / 126** | `contract/openapi.json`（GET 57 · POST 49 · DELETE 10 · PUT 8 · PATCH 2） |
| C02 | 数据表数 | **22** | `contract/tables.sql`（与 `apps/server/src/db/schema.ts` 逐字一致） |
| C03 | 迁移版本数 | **1**（`0000_baseline`） | `apps/server/src/db/migrate.ts`（旧库走「标记基线 + 增量补列」） |
| C04 | 需求条目数 | **95** | `doc/design/01-功能需求规格.md`（✅ 92 / ⏳ 3 / ⛔ 0） |
| C05 | 功能基线项数 | **185** | `baseline/features.csv`（闸门 4：不许缩水） |
| C06 | 内置 Skill 数 | **6** | `skills/`（data-analysis / frontend-design / marketing-materials / pdf / ralph-loop / skill-creator） |
| C07 | MCP Server 数 / 工具数 | **3 / 12** | weather 2 · search 3 · xiaohongshu 7 ｜ `apps/server/src/mcp/servers/`；另有**两级配置**（用户级 + 项目级）可追加 |
| C08 | 静态工具数 | **11** | 内置 8（`tool_search`/`tool_load`/`read_file`/`write_file`/`execute_python`/`execute_bash`/`emit_artifact`/`list_directory`）+ RAG 2 + Web 1 ｜ `apps/server/src/domain/tools/registry.ts` |
| C09 | 共享服务数 | **14** | `apps/server/src/http/context.ts`（skill / executor / mcp / tool / research / session / run / team / agent / run-executor / scheduler / desktop / permission / orchestration） |
| C10 | RAG collection / 向量维度 | **`hybrid_demo` / 1024** | `apps/server/src/shared/config.ts`；`apps/server/src/domain/rag/store.ts` |
| C11 | 前端视图数 | **19** | `apps/ui/src/views/*.vue` |
| C12 | 前端组件数 / 布局数 | **23 / 2** | `apps/ui/src/components/`（根 15 + composer 7 + layout 1）、`apps/ui/src/layouts/` |
| C13 | 前端 store 数 | **7** | config / session / workspace / permissions / desktop / desktopSettings / rounds |
| C14 | 前端 API 常量数 / 封装函数数 | **96 / 96** | `apps/ui/src/api/endpoints.ts`、`apps/ui/src/api/index.ts` |
| C15 | Agent SSE 事件名 | **后端 26 / 前端 TS 联合 26** | `apps/ui/src/api/types.ts`（`AgentEvent`）—— 2026-11-01 补齐 `loop_detected`，**前后端已对齐** |
| C16 | Research SSE 事件 / 评分维度 | **2 / 6** | `progress`、`final`；完整性·准确性·深度·结构·可读性·来源质量 |
| C17 | **TS 后端 vitest 用例** | **69 passed / 0 failed**（5 文件） | `apps/server/tests/`（contract / db / domain / packaging / response-shape） |
| C18 | **前端 vitest 用例** | **102 passed**（20 文件） | `apps/ui/src/**/*.spec.ts` |
| C19 | 旧路径 redirect 数 | **13** | `apps/ui/src/router/index.ts` |
| C20 | **端口矩阵** | Vite dev **5185** → proxy **18040**；本地后端 **8000**；**桌面端 = OS 分配的随机 loopback 端口** | `apps/ui/vite.config.ts`；`apps/server/src/main.ts`（`port: 0`） |
| C21 | 模型默认值 | `default_model=qwen-plus`、`rag_model=deepseek-chat`、`answer_model=deepseek-reasoner` | `apps/server/src/shared/config.ts`（⚠️ 见下方「模型可用性」） |
| C22 | 关键阈值 | `max_iterations=20`、`chat_max_iterations=5`、`exec_timeout=180`、`schedule_max_concurrent=2`、`permission_approval_timeout=120`、`context_budget_ratio=0.85`、`context_compact_threshold=0.70`、`context_summary_threshold=0.85`、`context_memory_max=5` | `apps/server/src/shared/config.ts` |
| C23 | **桌面壳 vitest 用例** | **62 passed**（11 文件） | `apps/desktop/src/**/*.test.ts` |
| C24 | **大模型端到端** | **20**（Playwright 驱动真实安装包） | `tests/e2e/llm-e2e.mjs` —— 大模型问答 / 多轮上下文 / RAG 入库+检索 / 13 个功能页 |
| C25 | 权限 scope / decision | **5 / 3** | `tool`、`file`、`command`、`network`、`action` × `deny`、`ask`、`allow` ｜ `apps/server/src/domain/security/permissions.ts` |
| C26 | 调度租约 TTL / 续约间隔 | **60s / 20s** | `schedule_lease_ttl`、`schedule_lease_renew` ｜ `apps/server/src/shared/config.ts` |
| C27 | 运行状态数 | **8**（终态 5） | `queued`/`running`/`awaiting_approval` + `success`/`failed`/`skipped`/`interrupted`/`rejected` ｜ `apps/server/src/domain/run/service.ts` |
| C28 | **配置字段数 / `AGENT_*` 环境变量数** | **110 / 12** | `apps/server/src/shared/config.ts`（`Settings` 接口） |
| C29 | **安装包体积** | **125.4MB**（dmg · macOS arm64）；后端产物 **104.7MB** | `deploy/README.md` §4（预算 120MB / 30MB / 120MB） |
| C30 | **原生模块 ABI** | Node **137** / Electron **130** | `apps/server/.native/abi-<ABI>/`（`scripts/rebuild-native.mjs` 生成） |
| C31 | **代码规模** | TS 后端 **61 文件 / 12.9k 行**（含测试 7 / 930 行）· 前端 **85 / 10.8k** · 桌面壳 **28 / 3.3k** · 根 E2E **11 / 2.7k** | `scripts/facts.py` |
| C32 | **事件类型数** | **26** | `contract/events.json`（`agentEvents`） |

> **实测（2026-11-01 · 单运行时改造后）**：
> TS 后端 vitest **69 passed / 0 failed**（5 文件）｜ 前端 vitest **102 passed / 20 文件**｜
> 桌面壳 vitest **62 passed / 11 文件** ｜ **大模型端到端 20/20** ｜ 接口冒烟 **38/38**（35 端点）｜
> 打包自检 **9/9** ｜ 安装包 **125.4MB**（macOS arm64 dmg + zip，另有 x64 版本）｜
> OpenAPI **98 唯一路径 / 126 操作** ｜ 事件 **26** ｜ 表 **22** ｜ 需求 **95** ｜ 功能基线 **185**。
>
> **对照口径（改造前 Python 后端，用于等价性回归）**：后端 `pytest` **692 passed / 3 skipped / 0 failed**（695 例）。
>
> 口径常量可用 `python3 scripts/facts.py` 一键从代码重新提取（输出 `tests/report/facts.json`）。

> **⚠️ 模型可用性（2026-11-01 实测）**：本账号**没有** `deepseek-chat` / `deepseek-reasoner`
> （C21 的 RAG / 问答默认模型），也**没有** `qwen3-max`。实测可用：`qwen-plus`、`qwen-max`
> 与 Embedding `text-embedding-v3`（维度 1024）。`qwen-turbo` 有 429 限流。
> 生产部署需按账号实际开通的模型覆盖 `DASHSCOPE_*` / `LLM_*` / `DEFAULT_MODEL` /
> `RAG_MODEL` / `ANSWER_MODEL`（`.env`，已被 `.gitignore` 排除）。
>
> **桌面端**：后端 `apps/server/src/http/{bootstrap,events,static,sse}.ts` + `http/routes/desktop.ts`（12 端点）；
> 壳工程 `apps/desktop/`（Electron 主进程 / 托盘 / 快捷键 / 通知 / 更新 / 事件桥 / `utilityProcess` 编排）；
> 前端 `apps/ui/src/api/desktop.ts`、右侧结果区、��本条与上下文表、角色/插件/黑板三视图。
> 设计见 `../design/00~07`，差距对照见 `../design/09`，竞品对标见 `../design/11`，
> **单运行时改造方案见 `../design/16`**，**实测证据见 `../test-runs/P9-final/`**。

：
>
> 口径常量可用 `node scripts/facts.py` 一键从代码重新提取（输出 `tests/report/facts.json`）。

> **桌面端**：后端 `app/desktop/`（launcher / bootstrap / events）、`api/v1/desktop.py`（12 端点）；壳工程 `apps/desktop/`（Electron 主进程 / 托盘 / 快捷键 / 通知 / 更新 / 事件桥）；前端 `api/desktop.ts`、右侧结果区（S3）、成本条与上下文表（S5）、角色/插件/黑板三视图（S6）。设计见 `../design/00~07`，差距对照见 `../design/09`，竞品对标见 `../design/11`。

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
| R-01 | 官方 | Fastify 路由与依赖注入 | https://fastapi.tiangolo.com/tutorial/ |
| R-02 | 官方 | Fastify StreamingResponse（SSE） | https://fastapi.tiangolo.com/advanced/custom-response/ |
| R-03 | 官方 | Zod Settings | https://docs.zod.dev/latest/concepts/zod_settings/ |
| R-04 | 官方 | Drizzle 2.0 ORM | https://docs.sqlalchemy.org/en/20/orm/ |
| R-05 | 官方 | migrations 教程 | https://migrations.sqlalchemy.org/en/latest/tutorial.html |
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
| R-23 | 官方 | RFC 5545 iCalendar RRULE | https://datatracker.ietf.org/doc/html/rfc5545#section-3.3.10 |
| R-24 | 官方 | POSIX rlimit / setrlimit | https://pubs.opengroup.org/onlinepubs/9699919799/functions/setrlimit.html |

> 各篇附录只引用本表的编号；本表未收录的链接写在该篇附录中。

---

> **阅读本目录前请记住三件事**：① 这里只描述**当前代码**，不描述计划（计划在 `../design/09`）；② 所有数字以 §5 常量表为准；③ 每条结论都带 `文件:行号`，可自行核对。
