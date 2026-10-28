# agent knowledge 目录索引（扩充版）

> - **依据项目**：`c:\workspace\project\agent-platform`（统一 Agent 平台 5 能力链 + 4 运行域）
> - **资料来源**：本项目代码（2026-10-26 复核）+ Anthropic MCP 官方文档 + Langfuse 官方 + AutoGen/CrewAI 仓库 + Milvus Lite 官方
> - **整理日期**：2026-10-26（首发 2026-09-15，本次按 commit `c4dac22` 复核口径）
> - **本目录定位**：agent 涉及的通用原理 + 项目独有技术沉淀；按主题分层 + 按问题反查双索引
> - **配套事实文档**：`doc/analysis/`（13 篇，当前实现的事实描述与风险台账）

---

## 一、按主题分层

### ① 项目独有技术（深度剖析 agent 内部实现）

| 编号 | 文档 | 主题 | 关键价值 |
|------|------|------|---------|
| 01 | [Skill 注册表与四级 Skill 设计](./01_Skill注册表与四级Skill设计.md) | SkillManager + @skill 装饰器 + 6 Skill 实现 | 对比 Anthropic Skills / Claude Code Skills |
| 02 | [MCP 协议原理与 stdio 实现](./02_MCP协议原理与stdio实现.md) | MCPManager + 3 stdio Server + 工具静态反射 | 与 Anthropic MCP 官方规范对照 |
| 03 | [Orchestrator-Workers 多智能体架构](./03_Orchestrator-Workers多智能体架构.md) | Deep Research 6 阶段 + OODA 子循环 + 质量评分 | Anthropic 2025 多 Agent 报告对照 |
| 04 | [质量评分迭代与任务持久化](./04_质量评分迭代与任务持久化.md) | `tasks.json` + 线程池 + 重启恢复 | 对比 CrewAI / AutoGen 状态管理 |
| 05 | [Milvus Lite 本地化与 BM25 混合检索](./05_MilvusLite本地化与BM25混合检索.md) | BM25 Function + 稠密向量 + Hybrid Search | 对比 Qdrant / Weaviate 本地部署 |
| 06 | [Vue 3 前端与 SSE 消费](./06_Vue3前端与SSE消费.md) | 15 视图 + `api/sse.ts` runSSE + 断流续订去重 | 对比 fetch-event-source / WebSocket 方案 |
| 07 | [Langfuse 集成与 LLM 追踪](./07_Langfuse集成与LLM追踪.md) | OTel 原生 + Generation/Span + Trace 串联 | 对比 Arize Phoenix / OpenLLMetry |

### ② 通用原理（交叉引用其他项目同源编号）

| 编号 | 文档 | 关联项目 | 本项目实践要点 |
|------|------|---------|--------------|
| 10 | API 鉴权机制 | finance-report / industry-research | **未启用鉴权**（CORS 全开 + 无 JWT）—— 单机 POC 设计；生产需补 |
| 11 | 中间件与安全架构（CORS） | 全部项目 | `app/main.py:62` `allow_origins=["*"]` 是 OWASP API8 风险点 |
| 12 | 流式处理与异步（asyncio/SSE） | 全部项目 | 后端 `StreamingResponse` + 前端自研 `readSSE` 逐事件解析 |
| 13 | 可观测性体系设计（OTel） | 全部项目 | **Langfuse/OTel 未接入**（knowledge 07 为建议性文档）；缺 Prometheus + 链路追踪 |
| 14 | 数据库选型与持久化策略 | industry-research | **SQLite（WAL）9 表**承载业务元数据 + Milvus Lite（RAG 向量）+ 文件系统（内容）；`DATABASE_URL` 可切 PG |
| 15 | RAG 与向量检索原理 | finance-report / industry-research | Milvus BM25 Function + Dense hybrid；Embedding 走 DashScope API |
| 16 | LLM 输出可靠性工程 | 全部项目 | function calling JSON 解析；plan/reflection 兜底；tool_result 异常处理 |
| 17 | Python 后端项目分层与配置规范 | 全部项目 | `app/{api,core,mcp,services,schemas}/` 分层；pydantic-settings + @lru_cache 单例 |
| 18 | 多数据源一致性设计模式 | industry-research | 仅 Milvus + 文件 JSON，**实际无强一致性诉求** |

### ③ 前端专题（跨项目共用基础）

| 编号 | 文档 | 主题 | 关键价值 |
|------|------|------|---------|
| 20 | Vue 3 `<script setup>` + Element Plus 前端模式 | 15 视图 + 双形态（v3 工作台 / admin 后台） | 见 knowledge 06 |
| 21 | 自研 SSE 消费器（`runSSE`） | `src/api/sse.ts` | 与 EventSource / fetch-event-source 对比 |
| 22 | Tool 来源着色与可视化 | 能力 Chip + 工具来源标记 | 设计模式借鉴 |
| 23 | 单端口部署：FastAPI 托管前端 dist | `app/main.py:102-119` SPA fallback | 与 nginx 反代模式对比 |

---

## 二、按问题反查

### Q：5 条能力链分别是什么？怎么启用？
→ 看 [analysis/02_能力链实现.md](../analysis/02_能力链实现.md)

### Q：HTTP API 清单？鉴权？CORS？
→ 看 [analysis/05_HTTP接口总览.md](../analysis/05_HTTP接口总览.md)

### Q：用户提问后端怎么流转？SSE 怎么发？
→ 看 [analysis/03_Agent执行引擎与事件协议.md](../analysis/03_Agent执行引擎与事件协议.md)

### Q：Milvus Lite BM25 Function 怎么用？
→ 看 [knowledge/05_MilvusLite本地化与BM25混合检索.md](./05_MilvusLite本地化与BM25混合检索.md)

### Q：MCP 工具怎么发现？怎么调用？
→ 看 [knowledge/02_MCP协议原理与stdio实现.md](./02_MCP协议原理与stdio实现.md)

### Q：Deep Research 怎么编排多 Agent？
→ 看 [knowledge/03_Orchestrator-Workers多智能体架构.md](./03_Orchestrator-Workers多智能体架构.md)

### Q：任务怎么持久化？重启能恢复吗？
→ 看 [knowledge/04_质量评分迭代与任务持久化.md](./04_质量评分迭代与任务持久化.md)

### Q：前端怎么连后端？SSE 怎么解析？
→ 看 [knowledge/06_Vue3前端与SSE消费.md](./06_Vue3前端与SSE消费.md)

### Q：项目怎么部署？端口怎么配？
→ 看 [analysis/09_部署形态与端口矩阵.md](../analysis/09_部署形态与端口矩阵.md)

### Q：LLM 调用怎么追踪？Langfuse 怎么接入？
→ 看 [knowledge/07_Langfuse集成与LLM追踪.md](./07_Langfuse集成与LLM追踪.md)

---

## 三、agent 项目独有亮点总结

### 3.1 五条能力链（核心）

| 链 | 关键能力 | 文档 |
|----|---------|------|
| **Skill** | 6 Skill + SkillManager 渐进式披露 | [01](./01_Skill注册表与四级Skill设计.md) |
| **MCP** | 3 stdio Server + 工具静态反射 | [02](./02_MCP协议原理与stdio实现.md) |
| **RAG** | Milvus Lite BM25+稠密 混合检索 + `[n]` 引用 | [05](./05_MilvusLite本地化与BM25混合检索.md) |
| **Web Research** | Serper + 多线程爬虫 + Chroma + 引用卡片 | (跨项目) |
| **Deep Research** | Orchestrator-Workers + OODA + 评分迭代 + tasks.json 持久化 | [03](./03_Orchestrator-Workers多智能体架构.md) + [04](./04_质量评分迭代与任务持久化.md) |

### 3.2 三大创新

1. **Milvus Lite BM25 Function**：服务端分词，无需本地分词器（业界首创）
2. **任务持久化 + 重启恢复**：研究中断不丢失（生产级）
3. **单端口部署**：FastAPI 托管前端 dist，省一层 nginx

### 3.3 运行模式与能力开关

Agent 请求的主开关是 **`mode`（chat / work）+ `plan_first` + `team_id`**；`enable_mcp` / `enable_rag` / `enable_web_research` / `enable_reflection` 是**在 mode 允许的范围内进一步收窄**的辅助开关。

```python
# Agent 请求 payload（前端透传）
{
    "prompt": str,
    "mode": "chat" | "work",   # chat=只读工具；work=全量工具
    "plan_first": bool,        # 仅 work；先生成计划待人工确认
    "team_id": str | None,     # 与 skills 互斥
    "skills": [str] | None,
    "enable_mcp": bool, "enable_rag": bool,
    "enable_web_research": bool, "enable_reflection": bool
}
```

工具可见性由 `ToolRegistry.get_combined_tools(profile=...)` 统一裁决（`chat` 只读 / `work` 全量），`enable_*` 只在其子集上叠加。详见 `analysis/03_Agent执行引擎与事件协议.md` §3。

---

## 四、文档维护说明

- 本目录每篇文档头部注明「依据项目/资料来源/整理日期」
- 通用原理优先引用其他项目同源编号，避免重复
- 项目独有技术按 01~07 编号，遵循计划 §十二 五段式结构（当前实现 → 原理剖析 → 业界做法调研 → 操作步骤 → 参考文献附录）
- 与 `analysis/` **互补**：`analysis/` 是各能力链的**当前实现事实**；本目录是**跨能力链的通用原理 + 横向技术**（原 `backend/docs/{mcp,rag,research,skills}/` 已于 2026-10-28 删除）
- 计划文档：`项目分析与通用知识文档建设计划.md`（v1.1）
- **首次整理**：2026-09-15 / **本次扩充**：2026-09-15（增加 Q/A 反查 + 项目亮点总结）
