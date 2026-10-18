# agent-platform 文档集

> **项目定位**：统一 Agent 平台，整合 4 个学习项目为 5 条能力链（**Skill / MCP / RAG / Web Research / Deep Research**）。FastAPI 后端 + Vue 3 前端，单端口部署。
> **文档集范围**：`doc/`（本目录，主题分析与通用原理）+ `deploy/`（随代码维护的部署手册）
> + `backend/docs/`（按能力链细分）+ `frontend/docs/`（接口契约与 SSE 协议）。

## 文档清单

| 类别 | # | 文档 | 核心回答 |
|---|---|------|----------|
| **analysis** | 01 | [模块.md](./analysis/01_模块.md) | 5 能力链如何编排？6 Skill / 3 MCP Server 怎么集成？ |
| analysis | 02 | [接口.md](./analysis/02_接口.md) | HTTP API 清单 + 4 链开关 + WebUI 架构 |
| analysis | 03 | [链路分析.md](./analysis/03_链路分析.md) | Agent 主链路 + Deep Research 时序图 |
| analysis | 04 | [三端一致性.md](./analysis/04_三端一致性.md) | Milvus Lite + tasks.json 持久化策略 |
| analysis | 05 | [可观测体系设计.md](./analysis/05_可观测体系设计.md) | 现状 + Prometheus/OTel/Langfuse/Sentry 改造 |
| analysis | 06 | [高并发.md](./analysis/06_高并发.md) | 线程池 + uvloop + SSE 限流 |
| analysis | 07 | [部署.md](./analysis/07_部署.md) | 单端口部署（FastAPI 托管前端 dist） |
| analysis | 08 | [测试体系.md](./analysis/08_测试体系.md) | 16 测试基线 + 五层模型 + 故障注入 |
| analysis | 09 | [代码规范.md](./analysis/09_代码规范.md) | pydantic-settings + Vue 3 + Ruff/mypy |
| analysis | 10 | [功能覆盖矩阵.md](./analysis/10_功能覆盖矩阵.md) | 三源项目（agent skill / MCP / webResearch）逐项功能对照与验证结论 |
| analysis | 11 | [deepResearch 整合分析](./analysis/11_deepResearch整合分析.md) | deep_research 融入方案：架构契合度 / 迁移计划 / 风险与验收 |
| **knowledge** | 00 | [README.md](./knowledge/00_README.md) | 项目独有技术 + 通用原理 + 前端专题 双索引 |
| knowledge | 01 | [Skill 注册表与四级 Skill 设计](./knowledge/01_Skill注册表与四级Skill设计.md) | SkillManager + 渐进式披露 + 6 Skill |
| knowledge | 02 | [MCP 协议原理与 stdio 实现](./knowledge/02_MCP协议原理与stdio实现.md) | MCPManager + 3 stdio Server + 工具反射 |
| knowledge | 03 | [Orchestrator-Workers 多智能体架构](./knowledge/03_Orchestrator-Workers多智能体架构.md) | Deep Research 5 阶段 + OODA + 评分 |
| knowledge | 04 | [质量评分迭代与任务持久化](./knowledge/04_质量评分迭代与任务持久化.md) | 评分机制 + tasks.json + SQLite 升级 |
| knowledge | 05 | [Milvus Lite 本地化与 BM25 混合检索](./knowledge/05_MilvusLite本地化与BM25混合检索.md) | Milvus Lite + BM25 Function + DashScope Embedding |
| knowledge | 06 | [Vue 3 极简前端与 SSE 自研消费](./knowledge/06_Vue3极简前端与SSE自研消费.md) | 8 组件 + 自研 readSSE + 4 链 UI |
| knowledge | 07 | [Langfuse 集成与 LLM 追踪](./knowledge/07_Langfuse集成与LLM追踪.md) | OTel 接入 + Prompt 版本化 + 评估 |
| **deployment** | 00 | [导览与总览](./deployment/00_导览与总览.md) | 部署形态 / 组件与端口 / deploy 文件地图 / 配置项 / 快速开始 |
| deployment | 07 | [故障排查手册](./deployment/07_故障排查手册.md) | 按症状检索的避坑清单（Compose / 构建 / 反代与 SSE / Windows） |

**总计**：11 篇 analysis + 8 篇 knowledge（含 00_README 索引）+ 2 篇 deployment = **21 篇**

> 部署手册随代码维护，放在 `deploy/` 而非本目录：
> [`deploy/README.md`](../deploy/README.md)（架构 + 步骤 + 排错 + 实测）与
> [`deploy/部署文件分析与操作手册.md`](../deploy/部署文件分析与操作手册.md)（文件全景 + 两条路线 + 验收清单）。

## 阅读顺序

- **架构师/新人**：先读 [analysis/01_模块.md](./analysis/01_模块.md) → [analysis/03_链路分析.md](./analysis/03_链路分析.md)
- **后端开发**：[analysis/02_接口.md](./analysis/02_接口.md) + knowledge 01~05
- **前端开发**：默认前端为 `frontend/web/vue-element-plus`（Vue 3 + TS + Element Plus），
  先看 [`frontend/README.md`](../frontend/README.md) 与 [`frontend/docs/`](../frontend/docs/) 的接口契约 / SSE 协议，
  再读 [analysis/02_接口.md](./analysis/02_接口.md) WebUI 章节 + knowledge 06（SSE 消费原理）
- **LLM 应用工程师**：knowledge 03 + knowledge 07（Langfuse）
- **验收 / 回归**：[analysis/10_功能覆盖矩阵.md](./analysis/10_功能覆盖矩阵.md)（功能完整性核查）
- **接手第 5 链**：[analysis/11_deepResearch 整合分析](./analysis/11_deepResearch整合分析.md)
- **运维 / 交付**：先读 [deployment/00_导览与总览.md](./deployment/00_导览与总览.md)（形态、端口、文件地图、快速开始），
  构建与运维细节见 [`deploy/README.md`](../deploy/README.md) 与
  [`deploy/部署文件分析与操作手册.md`](../deploy/部署文件分析与操作手册.md)；
  遇到报错直接查 [deployment/07_故障排查手册.md](./deployment/07_故障排查手册.md)
- **部署方案设计**：[analysis/07_部署.md](./analysis/07_部署.md)（设计建议与演进路线）+
  [analysis/05_可观测体系设计.md](./analysis/05_可观测体系设计.md)；
  **仓库内实际交付的部署工程**见 `deployment/00` 与 `deploy/`

## 目录分工

- `doc/analysis/` —— 主题深度分析（当前实现是什么、怎么组织的、有什么偏差）
- `doc/knowledge/` —— 通用原理剖析（协议、架构模式、第三方组件原理）
- `doc/deployment/` —— 应用侧部署导览与排错（读者视角）
- `deploy/*.md` —— **随代码维护**的部署操作手册（运维视角，紧贴 Docker 资产）
- `backend/docs/{mcp,rag,research,skills}/` —— 按能力链细分的模块文档
- `frontend/docs/` —— 接口契约（`api-contract.md`）/ SSE 协议（`sse-protocol.md`）/ 设计 Token（`design-tokens.md`）
- `CICD清理实施计划.md` —— 历史实施计划记录（CI/CD 与 K8s 工程已于 2026-10-18 移除）

### 历史沿革

- 原 `docs/`（仓库根）已于 2026-10-19 **并入本目录**：`功能覆盖矩阵.md` → [analysis/10](./analysis/10_功能覆盖矩阵.md)，
  `整合分析-deepResearch融入AgentPlatform.md` → [analysis/11](./analysis/11_deepResearch整合分析.md)；
  同名临时 HTML 渲染产物（`_tmp.html`）一并删除
- 原根目录 `部署文件分析与操作手册.md` 已于 2026-10-19 移入 [`deploy/`](../deploy/)
- 原 `devops/` 与 `deployment/01~06、08`（Jenkins / Harbor / K8s / 监控栈 / 压测）已移除，不再随仓库维护

## 外部资料来源

遵循计划文档 [`项目分析与通用知识文档建设计划.md`](c:\workspace\note\知识点\人工智能开发全栈\项目分析与通用知识文档建设计划.md) v1.1 的「五段式」结构（当前实现 → 原理剖析 → 业界做法调研 → 操作步骤 → 参考文献附录）。

主要参考：
- **官方文档**：FastAPI、Vue 3、Milvus Lite、Anthropic MCP、Anthropic Skills、Langfuse、OpenTelemetry
- **业界博客**：Anthropic「Building Effective Agents」(2024-12) + Anthropic「Multi-Agent Research System」(2025-06)
- **OSS 项目**：AutoGen、CrewAI、FastMCP、OpenLLMetry、Arize Phoenix

## 版本信息

- 文档生成时间：2026-09-15（analysis 01~09 / knowledge）；2026-10-18（deployment 重写）；2026-10-19（analysis 10/11 并入、前端收敛复核）
- 对应代码版本：截至 2026-09-15 agent-platform 仓库内容（analysis 01~09 / knowledge）；
  `docker-compose.yml` + `deploy/**`（deployment，2026-10-18 复核）；前端收敛为唯一实现 `frontend/web/vue-element-plus`（2026-10-19）
- 文档作者：本工作会话
- 维护方式：随源代码演进，每个文档头部注明「整理日期」+ 「对照当前代码复核：xxx」
