# agent knowledge 目录索引

> - **依据代码**：`apps/server/src/`、`apps/ui/src/`、`apps/desktop/src/`（2026-11-01 复核重写）
> - **本目录定位**：项目所用技术的**原理剖析**——「为什么这么设计」+「当前代码落在哪」。
>   每篇结构：原理 → 本项目实现（带 `文件:行号` 锚点）→ 业界对照 → 参考。
> - **配套事实文档**：`../analysis/`（18 篇，当前实现的事实描述）；**事实与原理冲突时，
>   以代码为准**。

---

## 一、文档清单

### ① 能力链技术（后端）

| 编号 | 文档 | 原理主题 | 代码锚点 |
|------|------|---------|---------|
| 01 | [Skill 注册表与渐进式披露](./01_Skill注册表与渐进式披露.md) | 渐进式披露（Progressive Disclosure）；文件为真/DB 为索 | `domain/skill/manager.ts` |
| 02 | [MCP 协议原理与 stdio 实现](./02_MCP协议原理与stdio实现.md) | JSON-RPC 工具协议；stdio/sse/http 三传输；工具命名空间 | `mcp/manager.ts` + `mcp/servers/` |
| 03 | [Orchestrator-Workers 多智能体架构](./03_Orchestrator-Workers多智能体架构.md) | 编排者-工人模式；OODA 子循环 | `domain/research/manager.ts`（骨架） |
| 04 | [质量评分迭代与任务持久化](./04_质量评分迭代与任务持久化.md) | 评分闭环；checkpoint 续跑；全量 JSON 持久化的取舍 | `domain/research/manager.ts` |
| 05 | [本地向量检索与 BM25 混合检索](./05_本地向量检索与BM25混合检索.md) | Embedding + 内积；BM25 公式；min-max 加权融合 | `domain/rag/store.ts` |

### ② 运行时与系统技术

| 编号 | 文档 | 原理主题 | 代码锚点 |
|------|------|---------|---------|
| 07 | [Electron 进程模型与 utilityProcess 编排](./07_Electron进程模型与utilityProcess编排.md) | 主/渲染/utility 三进程；握手协议；熔断；孤儿回收 | `apps/desktop/src/main/` |
| 10 | [双 ABI 原生模块与 SQLite 数据层](./10_双ABI原生模块与数据层.md) | NODE_MODULE_VERSION；WAL；单写者与写锁退避 | `db/native.ts`、`db/client.ts` |

### ③ 前端专题

| 编号 | 文档 | 原理主题 | 代码锚点 |
|------|------|---------|---------|
| 06 | [Vue 3 前端与 SSE 消费](./06_Vue3前端与SSE消费.md) | fetch+ReadableStream 自研 SSE；断流续订三件套 | `apps/ui/src/api/sse.ts` |

### ④ 工程规范

| 编号 | 文档 | 主题 |
|------|------|------|
| 08 | [技术选型与开源参考](./08-技术选型与开源参考.md) | 当前依赖清单（Fastify 5 / better-sqlite3 / Electron 33 / Vue 3 …）与选型理由 |
| 09 | [代码规范](./09_代码规范.md) | 仓库级编码约定（ESM、分层、契约冻结、文档门禁） |

---

## 二、按问题反查

| 问题 | 去向 |
|---|---|
| 5 条能力链各自怎么实现？ | `../analysis/02_能力链实现.md` |
| Agent 循环怎么跑？事件有哪些？ | `../analysis/03_Agent执行引擎与事件协议.md` |
| Skill 为什么只注入名称+描述？ | 本目录 01 |
| MCP 工具怎么发现/调用？外部 Server 现状？ | 本目录 02 |
| 混合检索的分数怎么融合？ | 本目录 05 |
| 研究任务重启怎么续跑？ | 本目录 04 |
| 桌面端进程怎么拉起/崩溃怎么办？ | 本目录 07 + `../analysis/13` |
| 为什么 Electron 与 Node 能共用一份 node_modules？ | 本目录 10 |
| 前端为什么不使用 EventSource？ | 本目录 06 |
| 端点/表/事件的**当前数字**？ | `../analysis/00` §5 口径常量表 |

---

## 三、维护说明

- 本目录每篇都以**当前代码**为锚：实现换了（如向量层从 Milvus Lite 换为本地 SQLite），
  文档跟着换，不保留失效实现的操作步骤；
- 「建议接入但未接入」的技术不写进本目录（此前 07 Langfuse 属此类，已删除）；
- 与 `../analysis/` 互补：analysis 写「是什么/怎么跑」，本目录写「为什么」。
