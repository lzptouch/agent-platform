# agent 代码分析文档集

> - **依据代码**：`apps/server/src/`（TypeScript 后端，Fastify 5）、`apps/ui/src/`（Vue 3）、`apps/desktop/src/`（Electron 33 壳）、`skills/`、`contract/`、`baseline/features.csv`
> - **整理日期**：2026-11-01（单运行时改造完成后，按 TS 代码逐模块复核重写）
> - **文档集定位**：**当前代码的事实描述**（平台由什么组成、功能怎么跑、数据落在哪）。目标形态见 `doc/design/`，通用原理见 `doc/knowledge/`，测试计划见 `tests/docs/testing/`，部署操作见 `deploy/README.md`。

---

## 一、本目录定位

| 目录 | 回答的问题 | 读者 |
|---|---|---|
| **`doc/analysis/`**（本目录） | 这个平台**现在**由什么组成、各功能的**执行流程**怎么走、数据落在哪 | 全角色 |
| `doc/design/` | 项目总目标与已实现标记（差距矩阵、交付台账） | 决策者 / 排期 |
| `doc/design/` 附录 | 批次计划（原 `doc/plan/`，2026-11-01 并入） | 执行者 |
| `doc/knowledge/` | 项目所用技术**为什么这么设计**（协议、架构模式、第三方组件原理） | 深入学习者 |
| `tests/docs/testing/` | 可执行测试计划 | 测试 / 交付 |
| `deploy/README.md` | 桌面端发布手册 | 运维 / 交付 |

**边界**：本目录只描述 `apps/server/src` + `apps/ui/src` + `apps/desktop/src` 的**当前实现**。
凡标注「未接线 / 未生效 / 骨架」的，指代码中存在对应模块或契约，但当前运行路径不产生完整效果。
**计划类内容不写在这里**，统一指向 `../design/09`（差距矩阵 + 批次附录）。

> **2026-11-01 重组说明**：本目录原为 00~19 共 20 篇。本次按「功能与执行流程分析」的定位重组：
> - `13_桌面端现状盘点与需求论证`（改造前快照）**已删除**，由新篇 [`13_桌面壳与进程编排`](./13_桌面壳与进程编排.md) 取代（描述当前 Electron 壳的事实）；
> - `18_全面代码审计报告`、`19_二次全面审计报告`（2026-10-31 两次审计的历史快照）**已移出本目录**——审计记录属历史台账，其整改结论已沉淀进 `../design/09` 附录「07」「08」与各篇「现状」描述；
> - `10`、`11` 两篇去掉「方案/改造」内容，只保留**现状事实**（方案类内容归 `../design/09` 附录）。

---

## 二、文档索引

| # | 文档 | 核心问题 |
|---|---|---|
| 00 | 本文件 | 从哪读起、口径是什么 |
| 01 | [架构总览](./01_架构总览.md) | 平台由哪些层组成？启动做了什么？两种运行模式怎么区分？ |
| 02 | [能力链实现](./02_能力链实现.md) | Skill / MCP / RAG / Web Research / Deep Research 五条链各自怎么实现？哪些是当前的真实状态？ |
| 03 | [Agent 执行引擎与事件协议](./03_Agent执行引擎与事件协议.md) | function-calling 循环怎么跑？26 种事件各是什么、谁在发射？中断/steer 怎么生效？ |
| 04 | [数据模型与持久化](./04_数据模型与持久化.md) | 22 张业务表怎么设计？幂等与一致性怎么保证？ |
| 05 | [HTTP 接口总览](./05_HTTP接口总览.md) | 126 个操作分别做什么？错误码与状态码怎么用？ |
| 06 | [前端架构与接口契约](./06_前端架构与接口契约.md) | 19 个视图怎么组织？前端如何消费 SSE？ |
| 07 | [DeepResearch 链路](./07_DeepResearch链路.md) | 研究任务的阶段骨架、持久化与 SSE 进度流怎么实现？距完整编排差什么？ |
| 08 | [调度与运行账本](./08_调度与运行账本.md) | 定时任务如何防重、幂等？运行记录如何落账与回放？ |
| 09 | [部署形态与端口矩阵](./09_部署形态与端口矩阵.md) | 唯一的交付形态（桌面安装包）与开发态三进程怎么跑？端口/配置/数据目录各是什么？ |
| 10 | [可观测性实现](./10_可观测性实现.md) | 日志 / 指标 / 计量 / 事件总线，现在各自能观测到什么？ |
| 11 | [并发模型与资源边界](./11_并发模型与资源边界.md) | 槽位信号量、SQLite 单写者、子进程限额的真实并发模型是什么？ |
| 12 | [能力覆盖与风险台账](./12_能力覆盖与风险台账.md) | 每个能力实现到什么程度？缺陷台账（冻结）与安全专项 |
| 13 | [桌面壳与进程编排](./13_桌面壳与进程编排.md) | Electron 壳如何拉起/监护/回收 TS sidecar？握手与引导怎么走？ |
| 14 | [权限引擎与安全边界](./14_权限引擎与安全边界.md) | 三态权限怎么判定？审批怎么走？当前真实的安全边界是哪几层？ |
| 15 | [工作区产物与变更回退](./15_工作区产物与变更回退.md) | 工作空间怎么建？产物怎么登记？变更回退的真实状态？ |
| 16 | [上下文经济性与成本核算](./16_上下文经济性与成本核算.md) | 历史怎么裁剪？token 怎么估算？成本怎么记怎么查？记忆的真实接线状态？ |
| 17 | [扩展层：角色 / 插件 / 黑板](./17_扩展层角色插件与黑板.md) | 角色/插件/黑板/编排四个扩展模块各自的能力边界与接线状态？ |

---

## 三、推荐阅读路径

| 角色 / 任务 | 顺序 |
|---|---|
| **新人（1~2 天）** | `01`（全景）→ `13`（桌面壳）→ `02`（五链）→ `03`（执行引擎） |
| **后端开发** | `03` → `05` → `04` → `08` → `14`~`17` |
| **前端开发** | `06` → `05` → `03` §5（事件协议）→ `15` |
| **运维 / 交付** | `deploy/README.md`（发布手册）→ `09` → `10` → `08` |
| **安全评审** | `14` → `13` §5（引导与守卫）→ `12` §三（安全专项）→ `15` |
| **排期 / 评估** | `12`（覆盖矩阵 + 缺陷台账）→ `../design/09`（差距矩阵 + 批次附录） |

---

## 四、口径声明

1. **一切结论以当前代码为准**，路径用仓库相对路径，关键事实带 `文件:行号`；行号以 2026-11-01 工作区为准，代码变更后需复核。
2. 本目录各篇**只写代码里存在的实现与真实生效路径**；「计划/建议」一律指向 `../design/09` 与其批次附录。
3. **数字统一取自 §5 的口径常量表**，各篇不独立统计。
4. 「已实现」的判定标准：代码存在 **且** 有生效逻辑 **且** 有对应测试覆盖。

---

## 五、口径常量表（本目录各篇的唯一数字来源）

| 编号 | 指标 | 值 | 依据 |
|---|---|---|---|
| C01 | OpenAPI 路径数 / 操作数 | **98 / 126** | `contract/openapi.json`（GET 57 · POST 49 · DELETE 10 · PUT 8 · PATCH 2） |
| C02 | 数据表数 | **22** | `contract/tables.sql`（与 `apps/server/src/db/schema.ts` 逐字对应） |
| C03 | 迁移版本数 | **1**（`0000_baseline` 一次建到最终态） | `apps/server/src/db/migrate.ts`（旧库自动备份 + 标记基线） |
| C04 | 需求条目数 | **95** | `doc/design/01-功能需求规格.md`（✅ 92 / ⏳ 3 / ⛔ 0） |
| C05 | 功能基线项数 | **185** | `baseline/features.csv` |
| C06 | 内置 Skill 数 | **6** | `skills/`（data-analysis / frontend-design / marketing-materials / pdf / ralph-loop / skill-creator） |
| C07 | 内置 MCP Server 数 / 工具数 | **3 / 10** | search 2 · weather 1 · xiaohongshu 7 ｜ `apps/server/src/mcp/servers/`；另支持两级配置（`~/.agent/mcp.json` + 项目级 `mcp.json`） |
| C08 | 静态工具数 | **11** | 内置 8（tool_search / tool_load / read_file / write_file / execute_python / execute_bash / emit_artifact / list_directory）+ RAG 2 + Web 1 ｜ `apps/server/src/domain/tools/registry.ts` |
| C09 | 服务容器成员数 | **11** | `apps/server/src/http/context.ts`（session / run / workspace / permission / code / mcp / scheduler / skill / rag / research / team） |
| C10 | RAG collection / 向量维度 | **`hybrid_demo` / 1024** | `apps/server/src/shared/config.ts`；`apps/server/src/domain/rag/store.ts` |
| C11 | 前端视图数 | **19** | `apps/ui/src/views/*.vue`（含 NotFoundView） |
| C12 | 前端组件数 / 布局数 | **23 / 2** | `apps/ui/src/components/`（根 15 + composer 7 + layout 1）、`apps/ui/src/layouts/` |
| C13 | 前端 store 数 | **7** | config / session / workspace / permissions / desktop / desktopSettings / rounds |
| C14 | 前端 API 封装函数数 | **96** | `apps/ui/src/api/index.ts` |
| C15 | Agent 事件类型数（契约） | **26** | `contract/events.json`；当前代码实际发射 **20** 种（未发射 6 种见 `03` §5.4） |
| C16 | Research SSE 事件类型 | **4** | `stage` / `progress` / `done` / `error` ｜ `apps/server/src/domain/research/manager.ts` |
| C17 | 后端 vitest 用例 | **69 passed / 0 failed**（5 文件） | `tests/unit/server/`（contract / db / domain / packaging / response-shape） |
| C18 | 前端 vitest 用例 | **102 passed**（20 文件） | `apps/ui/src/**/*.spec.ts` |
| C19 | 前端旧路径 redirect 数 | **13** | `apps/ui/src/router/index.ts` |
| C20 | 端口矩阵 | Vite dev **5185** → proxy **18040**；桌面态 = OS 分配的随机 loopback 端口（`port: 0`） | `apps/ui/vite.config.ts`；`apps/server/src/main.ts` |
| C21 | 模型默认值 | `default_model=qwen-plus`、`plan_model=deepseek-chat`、`rag_model=deepseek-chat`、`answer_model=deepseek-reasoner`、Embedding `text-embedding-v3` | `apps/server/src/shared/config.ts` |
| C22 | 关键阈值 | `max_iterations=20`、`chat_max_iterations=5`、`exec_timeout=180`、`interactive_max_concurrent=4`、`schedule_max_concurrent=2`、`permission_approval_timeout=120`、`context_budget_ratio=0.85`、`context_memory_max=5` | `apps/server/src/shared/config.ts` |
| C23 | 桌面壳 vitest 用例 | **62 passed**（11 文件） | `apps/desktop/src/**/*.test.ts` |
| C24 | 大模型端到端 | **20/20**（Playwright 驱动真实安装包） | `tests/e2e/llm-e2e.mjs` |
| C25 | 权限 scope / decision | **5 / 3** | `tool`、`file`、`command`、`network`、`action` × `allow`、`ask`、`deny` ｜ `apps/server/src/domain/security/permissions.ts` |
| C26 | 调度租约 TTL / 续约间隔 | **60s / 20s** | `schedule_lease_ttl`、`schedule_lease_renew` ｜ `apps/server/src/shared/config.ts` |
| C27 | 运行状态数 | **8**（终态 5） | `queued`/`running`/`awaiting_approval` + `success`/`failed`/`skipped`/`interrupted`/`rejected` ｜ `apps/server/src/domain/run/service.ts` |
| C28 | 配置字段数 / 桌面环境变量数 | **110 / 14** | `apps/server/src/shared/config.ts`（Zod schema 82 + 派生 28）；13 个 `AGENT_*` + `PLAYWRIGHT_BROWSERS_PATH` |
| C29 | 安装包体积 | **125.4MB**（dmg · macOS arm64） | `deploy/README.md` §4 |
| C30 | 原生模块 ABI | Node **137** / Electron **130**（双 ABI 加载） | `apps/server/.native/abi-<ABI>/`（`scripts/rebuild-native.mjs` 生成） |
| C31 | 代码规模 | TS 后端 **61 文件 / 12.9k 行** · 前端 **10.8k 行** · 桌面壳 **28 文件 / 3.3k 行** | `wc -l` 实测 |
| C32 | 内置权限规则数 | **18** | `BUILTIN_RULES` ｜ `apps/server/src/domain/security/permissions.ts` |

> **实测（2026-11-01 · 单运行时改造后）**：后端 vitest 69 / 前端 102 / 桌面壳 62 全绿；
> 接口冒烟 38/38（35 端点）；打包自检 9/9；OpenAPI 98 路径 / 126 操作；事件 26；表 22；功能基线 185。
> 证据链见 `../test-runs/P9-final/`。
>
> 口径常量可用 `python3 tests/scripts/facts.py` 从代码重新提取。

---

## 六、资产说明

| 目录 | 内容 | 维护方式 |
|---|---|---|
| `assets/ui/` | 本平台界面截图 | 界面变更后需重新截图更新 |
| `assets/reference/` | 外部产品官网与界面取证截图 | 仅作设计对标参考，不随代码更新 |

---

## 七、公共参考

| # | 类型 | 主题 | 链接 |
|---|---|---|---|
| R-01 | 官方 | Fastify 5（路由 / 钩子 / 错误处理） | https://fastify.dev/docs/latest/ |
| R-02 | 官方 | better-sqlite3（同步 API / 事务 / nativeBinding） | https://github.com/WiseLibs/better-sqlite3 |
| R-03 | 官方 | Zod schema 校验 | https://zod.dev/ |
| R-04 | 官方 | SQLite WAL 模式 | https://www.sqlite.org/wal.html |
| R-05 | 官方 | OpenAI Node SDK（兼容 DashScope 端点） | https://github.com/openai/openai-node |
| R-06 | 官方 | croner（cron 触发器） | https://github.com/Hexagon/croner |
| R-07 | 标准 | RFC 5545 iCalendar RRULE（rrule.js） | https://datatracker.ietf.org/doc/html/rfc5545#section-3.3.10 |
| R-08 | 官方 | BM25 与混合检索原理 | https://en.wikipedia.org/wiki/Okapi_BM25 |
| R-09 | 官方 | Anthropic Model Context Protocol | https://modelcontextprotocol.io |
| R-10 | 官方 | Anthropic Agent Skills（渐进式披露） | https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills |
| R-11 | 标准 | OWASP API Security Top 10 (2023) | https://owasp.org/API-Security/editions/2023/en/0x11-t10/ |
| R-12 | 官方 | MDN ReadableStream / AbortController / EventSource | https://developer.mozilla.org/zh-CN/docs/Web/API/ReadableStream |
| R-13 | 官方 | 阿里云百炼（DashScope）模型服务 | https://help.aliyun.com/zh/model-studio/ |
| R-14 | 官方 | 博查 AI 搜索 API | https://open.bochaai.com/ |
| R-15 | 官方 | Serper.dev 搜索 API | https://serper.dev/ |
| R-16 | 官方 | Vue 3 / Element Plus / Pinia / Vue Router | https://cn.vuejs.org/ ｜ https://element-plus.org/zh-CN/ ｜ https://pinia.vuejs.org/ ｜ https://router.vuejs.org/ |
| R-17 | 官方 | Vite 构建与开发服务器 | https://cn.vite.dev/ |
| R-18 | 官方 | Electron（utilityProcess / powerMonitor / 单实例锁） | https://www.electronjs.org/docs/latest |
| R-19 | 官方 | electron-builder | https://www.electron.build/ |
| R-20 | 官方 | POSIX rlimit / ulimit | https://pubs.opengroup.org/onlinepubs/9699919799/functions/setrlimit.html |

> 各篇附录只引用本表编号；本表未收录的链接写在该篇附录中。

---

> **阅读本目录前请记住三件事**：① 这里只描述**当前代码**，不描述计划；② 所有数字以 §5 常量表为准；③ 每条结论都带 `文件:行号`，可自行核对。
