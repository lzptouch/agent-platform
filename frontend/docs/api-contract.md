# 前端接口契约（API Contract）

> **唯一事实源**。所有前端实现必须按本文档对接后端；后端代码变更时必须同步更新本文档。

本文档对应后端版本：`backend/app/main.py`（version `1.1.0`）。所有端点前缀 `/api/v1`，**所有字段 snake_case**。

> 完整 35 个端点表、SSE 事件类型、字段速查见 `../前端多平台开发分析与计划.md` §2 与附录 A。

## 1. 通用约定

| 项 | 规则 | 证据 |
|---|---|---|
| baseURL | `/api/v1`（相对路径，由 Vite dev proxy 或 Nginx 反代） | — |
| 无客户端鉴权 | 后端无 `api_key_middleware`，密钥在服务端 `.env` | `main.py` 仅注册 `CORSMiddleware` |
| CORS | `allow_origins=["*"]`，前端不发凭证（`fetch` 不带 `credentials`） | `main.py:61-67` |
| 超时 | CRUD 15s；`/agent/run` 与 `/research/{id}/stream` **不设读超时**；`/agent/run/sync` 180s；`/rag/ingest` 300s | — |
| 错误格式 | `{"detail": "..."}`；`RuntimeError` 显式转 **503** | `agent.py:88`、`rag.py:28`、`web_research.py:23` |
| 取消 | 所有流式请求必须支持取消（AbortController 等价物） | 计划 §7.1-4 |

### HTTP 状态码语义

| 状态 | 含义 | 案例 |
|---|---|---|
| 200 | 正常 / 也用于降级返回（如 MCP 启动失败 / 工具调用失败返回 `error` 字段） | `mcp_servers.py:40-41`、`mcp_servers.py:81-82` |
| 400 | 业务校验失败 | 删除运行中研究任务：`research.py:237` |
| 404 | 资源不存在 | Skill / 文件 / 任务不存在 |
| **202** | **任务未完成（不是错误）** | `GET /research/{id}/result`：`research.py:174` |
| 422 | 请求体校验失败 | FastAPI 默认 |
| 500 | 服务异常 | — |
| 503 | 依赖未配置或不可用（区分服务端"语义"和"服务异常"） | `agent.py:88` 等 |

## 2. 能力门禁的 5 个端点（必须分别判断）

后端有 **2 套不同的 LLM Key**，3 个不同的检索 Key。前端门禁必须**分别**查询：

| 端点 | Key 归属 | 字段 |
|---|---|---|
| `GET /agent/status` | DashScope（主 LLM） | `api_key_configured` |
| `GET /web_research/status` | Serper / OpenAI | `serper_available` / `openai_available` |
| `GET /rag/stats` | **DeepSeek**（备选 LLM） | `llm_available` |
| `GET /research/health` | Bocha 或 Serper（检索）；DashScope（LLM） | `search_configured` / `llm_configured` |
| `GET /health` | 上述聚合 + `-1` / `mcp_servers_available`（**硬编码 3**，不可信） | 见下 |

### `/health` 字段陷阱

```jsonc
{
  "mcp_servers_available": 3,       // ⚠️ 硬编码 3，不可信（system.py:43）
  "rag_entities": -1,                // ⚠️ -1 = Milvus 不可用（system.py:19）
  "research_enabled": true,          // ⚠️ 硬编码 true
  "research_search_provider": "bocha" | "serper" | "none"
}
```

## 3. SSE 三件套（最高风险，必须实现）

### 3.1 `/agent/run`（POST + SSE）

15 种事件；详见 `sse-protocol.md`。**浏览器原生 `EventSource` 不可用**（不支持 POST）→ 必须 `fetch` + `ReadableStream` 手写解析。

### 3.2 `/research/{id}/stream`（GET + SSE）

2 种事件类型：`progress` / `final`。

**三个必须处理的语义**：

1. **1800s 上限断流不发 `final`**：`research.py:199` 循环到点退出，前端必须回查状态并**重订阅**。
2. **重订阅从 `sent=0` 全量重放**：`research.py:197`，与 `GET /research/{id}` 返回的最近 20 条叠加会产生重复。
3. **去重键 `stage + timestamp`**：`research_manager.py:144`，同 stage 会多次出现（如多轮 `worker_completed`）。

## 4. 静态托管约束（C7，可托管平台的实现必须满足）

- 产物根目录存在 `index.html`
- 一级子目录为 `assets/`（Vite 默认）
- `base: '/'`（不可配子路径）
- 资源引用为 `/assets/...` 绝对路径

证据：`main.py:85` 只 mount `/assets`；Nginx `location ^~ /assets/`（`conf.d/agent-platform.conf:91-96`）只对 `/assets/` 设长缓存。

## 5. 端点速查

完整列表见计划文档 §2.1（35 个）。这里列出实现优先级：

**P0（5 个核心）**：`/health`、`/agent/models`、`/agent/run`、`/skills`、`/mcp_servers`

**P1（深度研究 7 个）**：`/research/{health,POST,/stream,/result,/status,DELETE}`

**P2（19 个补齐项）**：`/files`、`/rag/*`、`/web_research/research`、`/agent/run/sync`、`/agent/chat`、`/skills/{reload,validate,files}`、`/mcp_servers/{reload,start,stop,tools,call}`

## 6. 类型定义（TS 模板）

见计划文档附录 A（含 `HealthResp` / `ModelsResp` / `RunRequest` / `SkillMeta` / `McpServerInfo` / `McpCallResponse` / `RagStatsResp` / `WebResearchStatusResp` / `ResearchHealthResp` / `ResearchSubmitResp` / `ResearchTaskStatusResp` / `ResearchProgressItem` 等）。