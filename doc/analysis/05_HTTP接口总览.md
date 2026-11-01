# HTTP 接口总览

> **依据代码**：`apps/server/src/http/routes/*.ts`（17 个子路由）、`http/app.ts`、`shared/errors.ts`；契约 `contract/openapi.json`、`contract/errors.json`（2026-11-01 复核）
> **口径**：路径/操作数 C01。

# 第一部分 现状事实

## 一、总览

- 全部业务端点挂在 `/api/v1/` 下：**98 条路径 / 126 个操作**（C01），
  与 `contract/openapi.json` **零差异**（契约闸门 1 保证）；
- 路由注册入口 `http/routes/index.ts`：17 个 `register*Routes()`；
- 另有 3 个契约外端点：`/__desktop/bootstrap`（引导）、`/__desktop/ping`（探活）、
  `/docs-info`（文档入口提示）；
- 错误体统一 `{code, message, detail, request_id}`；成功响应形状按契约逐端点冻结
  （`response-shape` 测试把关）。

## 二、端点全表（126 操作，按子路由分组）

### agent（7）—— Agent 运行
| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/agent/models` | 可用模型列表（4 个 Qwen） |
| GET | `/api/v1/agent/status` | 就绪状态（Key/默认模型/迭代上限） |
| POST | `/api/v1/agent/run` | 运行 Agent（SSE 事件流） |
| POST | `/api/v1/agent/run/sync` | 运行 Agent（阻塞式） |
| POST | `/api/v1/agent/runs/{run_id}/approve` | 批准计划并续跑 |
| POST | `/api/v1/agent/runs/{run_id}/reject` | 拒绝计划 |
| POST | `/api/v1/agent/chat` | WR 范式 Agent（plan→action→reflection→answer） |

### sessions（7）—— 双模式会话
`POST /sessions`（建）· `GET /sessions`（列表：模式过滤 + 分页 + 归档/回收站维度）·
`GET /sessions/{id}`（详情 + 消息分页 `before_seq`）· `PATCH /sessions/{id}`（改名/归档/配置）·
`DELETE /sessions/{id}`（软删，204）· `DELETE /sessions/{id}/purge`（物理删除）·
`GET /sessions/{id}/context`（历史回放预览 + 预算）。

### runs（11）—— 运行账本
`GET /runs` · `GET /runs/{id}` · `GET /runs/{id}/events`（分页回放）·
`GET /runs/{id}/stream`（SSE，DB tail + `Last-Event-ID` 续传）· `POST /runs/{id}/cancel` ·
`POST /runs/{id}/steer` · `GET /runs/{id}/cost` · `GET /runs/{id}/changes` ·
`GET /runs/{id}/artifacts` · `GET /runs/{id}/artifacts/{aid}/download` ·
`POST /runs/{id}/artifacts/{aid}/save-as`。

### schedules（10）—— 定时任务
`GET/POST /schedules` · `GET /schedules/health` · `POST /schedules/validate`（cron 校验 +
下次触发预览）· `GET/PUT/DELETE /schedules/{id}` · `POST /schedules/{id}/toggle` ·
`POST /schedules/{id}/run-now` · `GET /schedules/{id}/runs`。
注意：`GET /schedules` 返回**裸数组**（契约形状）。

### skills（11）—— Skill 管理
`GET/POST /skills` · `GET/PUT/DELETE /skills/{name}` · `POST /skills/{name}/toggle` ·
`POST /skills/{name}/validate` · `GET /skills/{name}/export` ·
`GET /skills/{name}/files/{resource_path}` 与 `GET /skills/{name}/files/*`（多段路径）·
`POST /skills/import`（base64 zip）· `POST /skills/reload`。

### teams（7）—— Skill 团队
`GET/POST /teams` · `GET/PUT/DELETE /teams/{id}` · `POST /teams/{id}/toggle` ·
`POST /teams/{id}/resolve`（预览展开结果：策略 none/sequential/router）。

### mcp_servers（9）—— MCP 管理
`GET /mcp_servers` · `GET /mcp_servers/config`（两级配置合并 + sources）·
`POST /mcp_servers/config/reload` · `POST /mcp_servers/reload` · `GET /mcp_servers/{name}` ·
`POST /mcp_servers/{name}/start|stop` · `GET /mcp_servers/{name}/tools` ·
`POST /mcp_servers/{name}/call`。

### rag（4）—— 本地文档库
`POST /rag/ingest`（解析 `userData/pdf/` 入库）· `POST /rag/retrieval`（仅混合检索）·
`POST /rag/query`（检索 + `[n]` 引用问答）· `GET /rag/stats`。
缺 `DASHSCOPE_API_KEY` 一律 503。

### web_research（2）
`POST /web_research/research`（**当前恒 503**，见 `02` §4）· `GET /web_research/status`。

### research（7）—— Deep Research
`GET /research/health` · `POST /research` · `GET /research` · `GET /research/{id}` ·
`GET /research/{id}/result` · `GET /research/{id}/stream`（SSE）· `DELETE /research/{id}`。

### permissions（6）—— 权限
`GET/PUT/DELETE /permissions/rules`（PUT 支持 `{level}` 档位批量设置）·
`GET/POST /permissions/decisions`（待审批列表 / 提交决策唤醒阻塞中的执行）·
`GET /permissions/sandbox`（沙箱能力与限额实况）。

### workspaces（6）+ changes（2）
`GET/POST /workspaces`（列表含 `current`）· `GET/PUT /workspaces/{id}/manifest` ·
`POST /workspaces/{id}/switch` · `POST /workspaces/{id}/archive` ·
`GET /changes/{id}/diff` · `POST /changes/{id}/revert`。

### files（5）
`GET /files/policy`（白名单 + 限额）· `GET /files`（输出目录清单，键为 `files`）·
`POST /files/upload`（multipart，扩展名白名单，50MB/100MB）· `GET /files/{filename}` ·
`DELETE /files/{filename}`。

### memories（4）—— 记忆
`GET /memories`（按 scope）· `POST /memories` · `DELETE /memories?path=`（限三作用域目录内）·
`POST /memories/clear`。

### desktop（12）—— 桌面态专属
`GET /desktop/status`（含 runtime/components/scheduler/security 快照）·
`GET /desktop/components` · `GET/PUT /desktop/preferences` · `GET/PUT /desktop/workspace` ·
`GET /desktop/events`（SSE，`after_id` + `max_events`）· `POST /desktop/shutdown` ·
`GET/PUT /desktop/permissions` · `POST /desktop/permissions/decision`（once/always/deny，
仅后两者落库）· `POST /desktop/scheduler/resume-scan`（补跑错过任务）。

### extensions：roles（4）+ plugins（4）+ boards（4）+ orchestrate（1）
`GET/POST /roles`、`PATCH/DELETE /roles/{id}`（内置角色不可删、不可改名）；
`GET /plugins`、`POST /plugins/{scan,install,rollback}`；
`GET/POST /boards/{id}/items`、`POST /boards/{id}/items/{iid}/complete`、`GET /boards/{id}/messages`；
`POST /orchestrate`（登记即返回，**无实际编排执行**，见 `17` §5）。

### system（4）
`GET /health`（17+ 字段系统快照）· `GET /metrics`（并发/成功率/24h 运行/耗时 p50/p90/
表计数/进程指标）· `GET /cost/estimate`（`{percentiles:{p50,p90,samples}, pricing}`）·
`GET /cost/estimate/tokens`（扩展端点，按 token 估算单次成本）。

## 三、错误与状态码语义

13 个错误码（`contract/errors.json`、`shared/errors.ts:26`）：

| code | HTTP | 用途 |
|---|---|---|
| E_VALIDATION | 400/415/422 | 参数/校验失败 |
| E_NOT_FOUND | 404 | 资源不存在 |
| E_CONFLICT | 409 | 状态冲突（如重复批准、无快照回退） |
| E_AUTH | 401/421 | 会话未建立 / 非法 Host |
| E_PERMISSION | 403 | 权限拒绝 |
| E_RUN / E_WORKSPACE / E_MCP / E_SCHEDULER / E_FILE | 400 | 领域错误 |
| E_TOO_LARGE | 413 | 上传超限 |
| E_UPSTREAM | 502/503 | 上游（LLM/检索）不可用 |
| E_INTERNAL | 500 | 未处理异常兜底 |

`HttpError(status, detail)` 语义等价 FastAPI 的 `HTTPException`；
Fastify schema 校验失败统一转 400/E_VALIDATION。

## 四、四条 SSE 端点

见 `03` §5.1（传输形态与续传语义）。⚠️ 全应用**不得**启用 `@fastify/compress`
（会缓冲 SSE）。

## 五、鉴权与安全现状

- **桌面态**（`AGENT_DESKTOP=1`）：Host 白名单（421）+ `/api/v1/` 强制会话
  （`X-Agent-Desktop-Token` Header 或 `agent_desktop_session` HttpOnly Cookie，
  8h TTL，常量时间比较）；静态资源豁免；引导端点用一次性 nonce（详见 `13` §4）；
- **非桌面态**（仅开发用）：守卫不启用，绑定 `127.0.0.1`；
- `AGENT_API_KEY`（Web 形态遗留配置）当前**无任何读取方**。

# 第二部分 原理剖析

## 六、为什么是「错误数据化」而不是「错误异常化」

错误体是**契约的一部分**：前端按 `code` 分支渲染（如 503 区分「未配置 Key」与
「服务异常」，`apps/ui/src/api/client.ts:55`），E2E 按 `code` 断言。
异常只在进程内传递（`AppError/HttpError`），出进程一律是结构化数据——
这让「错误」可以被测试冻结、被前端消费、被日志检索（`request_id` 串联）。

## 七、SSE 为什么是「拉模型」而不是「推模型」

`runs/{id}/stream` 不订阅内存队列，而是**轮询 DB**（300ms 一轮 `SELECT seq > cursor`）：
进程重启、多标签页、断线重连都不丢事件（账本在 SQLite 里），也不需要
为每个连接维护播放位置。代价是 300ms 的尾延迟——对秒级的 LLM 轮次可忽略。

## 八、`/docs-info` 为什么不进 OpenAPI

它与 `/__desktop/*` 一样是**壳与运维的带外通道**，不属于业务契约；
契约文件（`contract/openapi.json`）是前后端一致性闸门的基准，只冻结业务面。

# 第三部分 核对方式

```bash
# 端点表 ↔ OpenAPI 一致性（契约闸门 1）
cd apps/server && npx vitest run tests/contract.test.ts
# 响应形状
cd apps/server && npx vitest run tests/response-shape.test.ts
# 前后端字段一致
python3 tests/scripts/check_frontend_shape.py
```
