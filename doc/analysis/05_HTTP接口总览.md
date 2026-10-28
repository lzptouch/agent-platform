# HTTP 接口总览

> - **依据代码**：`backend/app/api/v1/*.py`、`backend/app/api/v1/router.py`、`backend/app/main.py`、`backend/app/schemas/*.py`
> - **资料来源**：2026-10-26 逐文件探查 + OpenAPI 规格导出（`app.openapi()`）
> - **整理日期**：2026-10-26
> - **对应基线**：commit `c4dac22`
> - **相关篇目**：`01` 架构总览 ｜ `02` 能力链 ｜ `03` 执行引擎 ｜ `06` 前端契约 ｜ `08` 调度 ｜ `12` 风险台账

---

# 第一部分 现状事实

## 一、总览

| 项 | 值 |
| --- | --- |
| 统一前缀 | `/api/v1`（`backend/app/main.py:87`） |
| 子 router 数 | **12** |
| 端点总数 | **69** |
| 方法分布 | GET 53 / POST 47 / DELETE 9 / PUT 7 / PATCH 2 |
| SSE 端点 | 5（`/agent/run`、`/runs/{run_id}/events`、`/runs/{run_id}/stream`、`/research/{task_id}/stream`、`/desktop/events`） |
| 鉴权 | **桌面形态**：会话令牌 + Host 白名单；**Web 形态**：单机无鉴权（`../plan/06` SEC-1b） |
| 限流 | **无** |
| 额外端点 | `GET /docs-info`（`include_in_schema=False`，不在 OpenAPI 中） |
| 文档 | `/docs`（Swagger）、`/redoc`（ReDoc）、`/openapi.json` |

**17 个子 router 的聚合**（`backend/app/api/v1/router.py`，均无自身前缀，统一由 `main.py` 加 `/api/v1`）：

| # | 模块 | 前缀 | 端点数 |
| --- | --- | --- | --- |
| 1 | `system.py` | — | 2 |
| 2 | `skills.py` | `/skills` | 11 |
| 3 | `agent.py` | `/agent` | 7 |
| 4 | `sessions.py` | `/sessions` | 5 |
| 5 | `runs.py` | `/runs` | 6 |
| 6 | `teams.py` | `/teams` | 7 |
| 7 | `schedules.py` | `/schedules` | 10 |
| 8 | `files.py` | `/files` | 4 |
| 9 | `mcp_servers.py` | `/mcp_servers` | 7 |
| 10 | `rag.py` | `/rag` | 4 |
| 11 | `web_research.py` | `/web_research` | 2 |
| 12 | `research.py` | `/research` | 7 |
| 13 | `permissions.py` | `/permissions` | 6 |
| 14 | `workspace.py` | `/workspaces` | 9 |
| 15 | `context.py` | `/context` | 7 |
| 16 | `extensions.py` | `/roles` `/plugins` `/boards` | 12 |
| 17 | `desktop.py` | `/desktop` | 12 |

> **合计：91 条路径 / 118 个操作**（S1~S8 新增 46 个操作，见 §2.14）。

## 二、端点全表

> 「响应」列只列成功响应的关键字段；「错误」列列**代码里显式 raise 的** `HTTPException`（不含 Pydantic 422 等框架默认行为）。`{x}` 为路径参数。

### 2.1 `system.py`（2）

| METHOD 路径 | 函数 | 响应 | SSE | 错误 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/metrics` | `metrics` | 运行指标：并发/成功率/耗时 p50~p90/LLM 成本/MCP 连接数（S7） | 否 | — |
| `GET /api/v1/health` | `health` | 17 字段聚合（status/app/version/skills_loaded/api_key_configured/output_dir/`mcp_servers_available`（S1 起读 MCP 注册表，不再硬编码）/rag_collection/rag_entities/web_search_available/llm_available/research_enabled/research_search_provider/research_configured/research_total_tasks/research_running_tasks/database/scheduler） | 否 | Milvus 失败 → `rag_entities=-1` 静默 |

### 2.2 `skills.py`（11）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/skills` | `list_skills` | — | `SkillListResponse{total, skills[]}` | — |
| `POST /api/v1/skills` | `create_skill` | `SkillCreate{name,description,content}` | `SkillMeta`（201） | **409** 同名 / **422** 校验失败 |
| `POST /api/v1/skills/import` | `import_skill` | `UploadFile` + query `overwrite:bool=False` | `SkillMeta` | 409 / 422（路径穿越/缺 SKILL.md/超限） |
| `POST /api/v1/skills/reload` | `reload_skills` | — | `{reloaded, skills[]}` | — |
| `GET /api/v1/skills/{name}` | `get_skill` | path | `SkillDetail`（含 content） | 404 |
| `PUT /api/v1/skills/{name}` | `update_skill` | `SkillUpdate{description?,content?}` | `SkillMeta` | 404 / **403**（内置只读）/ 422 |
| `POST /api/v1/skills/{name}/toggle` | `toggle_skill` | `SkillToggle{enabled}` | `SkillMeta` | 404 |
| `DELETE /api/v1/skills/{name}` | `delete_skill` | — | `{deleted, trash_path}` | 404 / **403**（内置不可删，软删到 `.trash/`） |
| `GET /api/v1/skills/{name}/export` | `export_skill` | — | zip 附件（`Content-Disposition: attachment`） | 404 |
| `POST /api/v1/skills/{name}/validate` | `validate_skill` | — | `ValidationResult{valid,message,name}` | 404 |
| `GET /api/v1/skills/{name}/files/{resource_path}` | `get_skill_resource` | path（`{resource_path:path}` 为路径转换器，可含 `/`） | `FileResponse` | 404（路径穿越由 `get_resource_path` 拦截） |

### 2.3 `agent.py`（7）

| METHOD 路径 | 函数 | 请求 | 响应 | SSE | 错误 |
| --- | --- | --- | --- | --- | --- |
| `GET /api/v1/agent/models` | `list_models` | — | `ModelsResponse{default_model, models[]}` | 否 | — |
| `GET /api/v1/agent/status` | `status` | — | `{ready, api_key_configured, default_model, max_iterations}` | 否 | — |
| `POST /api/v1/agent/run` | `run_agent` | `RunRequest` | SSE 事件流 | **是** | 事件流内 `{"type":"error"}` |
| `POST /api/v1/agent/run/sync` | `run_agent_sync` | `RunRequest` | `RunResult{model,prompt,rounds=0,finished,files,error,run_id,session_id,mode,answer}` | 否 | 事件内 error 填充 |
| `POST /api/v1/agent/runs/{run_id}/approve` | `approve_run` | `PlanApproval{edited_plan?}` | `RunOut` | 否 | **409**「不处于待审批状态」 |
| `POST /api/v1/agent/runs/{run_id}/reject` | `reject_run` | `PlanRejection{reason?}` | `RunOut` | 否 | **409** |
| `POST /api/v1/agent/chat` | `agent_chat` | `AgentChatRequest{query,reflection}` | `AgentChatResponse{query,plan,reflection_plan,memory,reasoning,answer}` | 否 | **503**（缺 Key）/ 500 |

### 2.4 `sessions.py`（5）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `POST /api/v1/sessions` | `create_session` | `SessionCreate{mode,title?,skills?,team_id?,config?}` | `SessionOut`（201） | 非法 mode → **422**（Pydantic Literal 校验） |
| `GET /api/v1/sessions` | `list_sessions` | query `mode`(pattern `^(chat\|work)$`), `page≥1`, `page_size 1..100`, `include_archived` | `Page[SessionOut]` | — |
| `GET /api/v1/sessions/{session_id}` | `get_session` | query `message_limit 1..500`, `before_seq` | `SessionDetail`（含 messages, has_more） | 404 |
| `PATCH /api/v1/sessions/{session_id}` | `update_session` | `SessionUpdate{title?,archived?,skills?,team_id?,config?}` | `SessionOut` | 404 |
| `DELETE /api/v1/sessions/{session_id}` | `delete_session` | — | 204（**级联删消息**） | 404 |

### 2.5 `runs.py`（6）

| METHOD 路径 | 函数 | 请求 | 响应 | SSE | 错误 |
| --- | --- | --- | --- | --- | --- |
| `GET /api/v1/runs` | `list_runs` | query `task_id?`, `page`, `page_size` | `Page[RunOut]` | 否 | — |
| `GET /api/v1/runs/{run_id}` | `get_run` | path | `RunOut` | 否 | 404 |
| `GET /api/v1/runs/{run_id}/events` | `list_run_events` | query `after_seq≥0`, `limit 1..2000` | `RunEventPage{items,last_seq,status,has_more}` | 否 | 404 |
| `GET /api/v1/runs/{run_id}/stream` | `stream_run_events` | query `after_seq` | SSE（DB tail 轮询） | **是** | 404；终态时补发 `{"type":"done","status":...}` |
| `POST /api/v1/runs/{run_id}/cancel` | `cancel_run` | path | `{ok, run_id, status:"interrupted"}` | 否 | 404（未知 run） |
| `POST /api/v1/runs/{run_id}/steer` | `steer_run` | body `instruction`（必填）、`mode`（`append`\|`replace_plan`） | `{ok, run_id, mode, status, note}` | 否 | 404 / **400**（缺指令）/ **422**（非法 mode） |

### 2.6 `teams.py`（7）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/teams` | `list_teams` | query `include_disabled=True` | `list[TeamOut]` | — |
| `POST /api/v1/teams` | `create_team` | `TeamCreate{name,skill_names,description?,prompt_prefix?,strategy?}` | `TeamOut`（201） | 409 重名 / 422 |
| `GET /api/v1/teams/{team_id}` | `get_team` | path | `TeamOut` | 404 |
| `PUT /api/v1/teams/{team_id}` | `update_team` | `TeamUpdate` | `TeamOut` | 409 / 422 / 404 |
| `DELETE /api/v1/teams/{team_id}` | `delete_team` | — | 204（**同时把会话 `team_id` 置 NULL**） | 404 |
| `POST /api/v1/teams/{team_id}/toggle` | `toggle_team` | `ToggleRequest{enabled}` | `TeamOut` | 404 |
| `POST /api/v1/teams/{team_id}/resolve` | `resolve_team` | `ResolveRequest{query,mode}` | `ResolveOut{team_id,team_name,strategy,skills[],prompt_preview,degraded,warnings[]}` | 404 |

### 2.7 `schedules.py`（10）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/schedules` | `list_schedules` | query `enabled:bool\|None` | `list[ScheduleOut]` | — |
| `POST /api/v1/schedules` | `create_schedule` | `ScheduleCreate` | `ScheduleOut`（201） | **422**（cron 非法 / 数量超 200 / work 未确认 `allow_unattended_tools`） |
| `POST /api/v1/schedules/validate` | `validate_cron` | `CronValidateRequest{cron_expr,timezone}` | `CronValidateOut{valid,error,next_runs[3]}` | 不抛错，非法时 `valid=False` |
| `GET /api/v1/schedules/health` | `scheduler_health` | — | `{role,owner,jobs,enabled}` | — |
| `GET /api/v1/schedules/{task_id}` | `get_schedule` | path | `ScheduleOut` | 404 |
| `PUT /api/v1/schedules/{task_id}` | `update_schedule` | `ScheduleUpdate` | `ScheduleOut`（**重建 job**） | 422 / 404 |
| `DELETE /api/v1/schedules/{task_id}` | `delete_schedule` | — | 204（**运行历史保留**，`runs.task_id` 置 NULL） | 404 |
| `POST /api/v1/schedules/{task_id}/toggle` | `toggle_schedule` | `ToggleRequest{enabled}` | `ScheduleOut` | 422（work 模式未确认）/ 404 |
| `POST /api/v1/schedules/{task_id}/run-now` | `run_now` | query `wait_seconds 0..300` | `{run_id,status}` | 404 |
| `GET /api/v1/schedules/{task_id}/runs` | `list_schedule_runs` | query `page`,`page_size` | `Page[RunOut]` | 404 |

### 2.8 `files.py`（4）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/files` | `list_files` | — | `{total, files[{name,size,is_image,url}]}` | — |
| `POST /api/v1/files/upload` | `upload_file` | `UploadFile` | `{name,size,url}` | **400** 非法文件名（**无大小限制**） |
| `GET /api/v1/files/{filename}` | `get_file` | path | `FileResponse` | 404 |
| `DELETE /api/v1/files/{filename}` | `delete_file` | path | `{deleted}` | 404 |

### 2.9 `mcp_servers.py`（7）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/mcp_servers` | `list_servers` | — | `McpServerListResponse{total,servers[]}` | — |
| `POST /api/v1/mcp_servers/reload` | `reload_servers` | — | `{reloaded,servers[]}` | 直接 `manager._tools_cache.clear()` |
| `GET /api/v1/mcp_servers/{name}` | `get_server` | path | `McpServerDetail{name,stage,description,status,tools[],error}` | 404；工具列举异常 → 200 + `error` 字段 |
| `POST /api/v1/mcp_servers/{name}/start` | `start_server` | — | `{name,status:"started",tools}` | 404 / 500 |
| `POST /api/v1/mcp_servers/{name}/stop` | `stop_server` | — | `{name,status:"stopped"}` | 404 |
| `GET /api/v1/mcp_servers/{name}/tools` | `list_tools` | path | `{server,tool_count,tools[]}` | 404 / 500 |
| `POST /api/v1/mcp_servers/{name}/call` | `call_tool` | `McpCallRequest{tool,arguments}` | `McpCallResponse{server,tool,result,error}` | 404；工具异常被转成字符串，填入 `error` 字段 |

### 2.10 `rag.py`（4）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `POST /api/v1/rag/query` | `rag_query` | `RagQueryRequest{query,limit 1..50}` | `RagQueryResponse{query,references,answer}` | **503**（缺 Key）/ 500 |
| `POST /api/v1/rag/retrieval` | `rag_retrieval_only` | 同上 | `{query,documents[],references}` | 500 |
| `POST /api/v1/rag/ingest` | `rag_ingest` | query `recreate:bool=True` | `IngestResponse{chunks,entities,collection}` | 500 |
| `GET /api/v1/rag/stats` | `rag_stats` | — | `RagStatsResponse{collection,entities,dense_dim=1024,embedding_model,llm_available}` | Milvus 不可用 → `entities=-1` 静默 |

### 2.11 `web_research.py`（2）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `POST /api/v1/web_research/research` | `web_research_endpoint` | `WebResearchRequest{query,profile?,output_format?}` | `WebResearchResponse{query,answer,reference_cards[]}` | **503**（缺 SERPER/OPENAI Key）/ 500 |
| `GET /api/v1/web_research/status` | `web_research_status` | — | `WebResearchStatusResponse{serper_available,openai_available,openai_model}` | — |

### 2.12 `research.py`（7）

| METHOD 路径 | 函数 | 请求 | 响应 | SSE | 错误 |
| --- | --- | --- | --- | --- | --- |
| `GET /api/v1/research/health` | `health` | — | `ResearchHealth{enabled,search_provider,search_configured,llm_configured,default_model,max_concurrent_tasks,output_dir,total_tasks,running_tasks}` | 否 | — |
| `POST /api/v1/research` | `submit_research` | `ResearchRequest{task,max_workers 1..10,max_iterations 1..10,quality_threshold 0..100}` | `ResearchSubmitResponse{task_id,status,message,created_at}` | 否 | 无检索 Key → **HTTP 200 + `status="failed"`**（非异常）；否则 `run_in_executor` 后台执行 |
| `GET /api/v1/research` | `list_research` | — | `ResearchTaskList{total,tasks[]}` | 否 | — |
| `GET /api/v1/research/{task_id}` | `get_research_status` | path | `ResearchTaskStatus`（progress 只回最近 20 条） | 否 | 404 |
| `GET /api/v1/research/{task_id}/result` | `get_research_result` | path | `ResearchTaskResult{task_id,status,report,quality_score,iteration_count,duration,metadata}` | 否 | 404 / **202** 未完成 |
| `GET /api/v1/research/{task_id}/stream` | `stream_research` | path | SSE 进度流 | **是** | 404 |
| `DELETE /api/v1/research/{task_id}` | `delete_research` | path | `{task_id,deleted,deleted_at}` | 否 | 404 / **400** 运行中不可删 |

### 2.14 S2~S8 新增端点（权限 / 工作空间 / 上下文成本 / 扩展三层 / 桌面）

> 本小节由 OpenAPI 规格导出（`backend/app/main.py` 的 `app.openapi()`），是**新增能力的权威清单**；
> 2.1~2.13 是手写细节表（保留请求 / 响应 / 错误语义）。

| 方法 | 路径 | 分组 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/boards/{board_id}/items` | extensions | 黑板任务项 |
| `POST` | `/api/v1/boards/{board_id}/items` | extensions | 新增黑板任务项 |
| `POST` | `/api/v1/boards/{board_id}/items/{item_id}/complete` | extensions | 完成任务项（触发重算） |
| `GET` | `/api/v1/boards/{board_id}/messages` | extensions | 黑板消息与通知 |
| `GET` | `/api/v1/changes/{change_id}/diff` | workspace | 一次变更的 diff |
| `POST` | `/api/v1/changes/{change_id}/revert` | workspace | 回退一次变更（从快照恢复） |
| `GET` | `/api/v1/cost/estimate` | context | 发起前的消耗区间（p50~p90） |
| `GET` | `/api/v1/desktop/components` | desktop | 组件安装状态 |
| `GET` | `/api/v1/desktop/events` | desktop | 桌面事件流（SSE） |
| `GET` | `/api/v1/desktop/permissions` | desktop | 读取三态权限规则 |
| `PUT` | `/api/v1/desktop/permissions` | desktop | 更新某条权限规则 |
| `POST` | `/api/v1/desktop/permissions/decision` | desktop | 对一次待确认操作给出临时决定 |
| `GET` | `/api/v1/desktop/preferences` | desktop | 读取桌面配置 |
| `PUT` | `/api/v1/desktop/preferences` | desktop | 更新桌面配置 |
| `POST` | `/api/v1/desktop/scheduler/resume-scan` | desktop | 扫描并补跑错过的定时任务 |
| `POST` | `/api/v1/desktop/shutdown` | desktop | 请求后端优雅退出 |
| `GET` | `/api/v1/desktop/status` | desktop | 桌面运行态快照 |
| `GET` | `/api/v1/desktop/workspace` | desktop | 当前工作区 |
| `PUT` | `/api/v1/desktop/workspace` | desktop | 切换工作区（立即生效） |
| `GET` | `/api/v1/memories` | context | 列出记忆（按作用域） |
| `POST` | `/api/v1/memories` | context | 写入一条记忆 |
| `DELETE` | `/api/v1/memories` | context | 删除一条记忆 |
| `POST` | `/api/v1/memories/clear` | context | 清空某作用域的记忆 |
| `GET` | `/api/v1/permissions/decisions` | permissions | 决策日志 / 待审批列表 |
| `POST` | `/api/v1/permissions/decisions` | permissions | 对一次待审批动作给出决策 |
| `GET` | `/api/v1/permissions/rules` | permissions | 列出权限规则 |
| `PUT` | `/api/v1/permissions/rules` | permissions | 新增/更新一条规则 |
| `DELETE` | `/api/v1/permissions/rules` | permissions | 删除一条规则 |
| `GET` | `/api/v1/permissions/sandbox` | permissions | 沙箱能力（诚实标注，不再硬编码 false） |
| `GET` | `/api/v1/plugins` | extensions | 已安装插件列表（含扫描结果） |
| `POST` | `/api/v1/plugins/install` | extensions | 安装插件包（原子切换） |
| `POST` | `/api/v1/plugins/rollback` | extensions | 回滚插件到上一版本 |
| `POST` | `/api/v1/plugins/scan` | extensions | 扫描本地插件目录（不安装） |
| `GET` | `/api/v1/roles` | extensions | 角色列表 |
| `POST` | `/api/v1/roles` | extensions | 创建角色 |
| `PATCH` | `/api/v1/roles/{role_id}` | extensions | 更新角色（不可改名） |
| `DELETE` | `/api/v1/roles/{role_id}` | extensions | 删除角色 |
| `GET` | `/api/v1/runs/{run_id}/artifacts` | workspace | 一次 run 的交付物（不含中间文件） |
| `POST` | `/api/v1/runs/{run_id}/artifacts/{artifact_id}/save-as` | workspace | 产物另存到指定位置 |
| `GET` | `/api/v1/runs/{run_id}/changes` | workspace | 一次 run 的变更列表 |
| `GET` | `/api/v1/runs/{run_id}/cost` | context | 一次运行的成本明细 |
| `GET` | `/api/v1/sessions/{session_id}/context` | context | 会话上下文占用 |
| `GET` | `/api/v1/workspaces` | workspace | 工作空间列表 |
| `POST` | `/api/v1/workspaces` | workspace | 创建工作空间 |
| `POST` | `/api/v1/workspaces/{workspace_id}/archive` | workspace | 归档工作空间（不删磁盘文件） |
| `POST` | `/api/v1/workspaces/{workspace_id}/switch` | workspace | 切换当前工作空间 |

## 三、错误与状态码语义

| 状态码 | 语义 | 出现位置 |
| --- | --- | --- |
| **200** | 成功（含「失败但数据化返回」：如 `POST /research` 无 Key 时 `status="failed"`） | 大部分 GET / POST |
| **201** | 创建成功 | `POST /skills`、`POST /teams`、`POST /schedules`、`POST /sessions` |
| **202** | **任务未完成**（Deep Research 结果未就绪） | `GET /research/{id}/result` |
| **204** | 删除成功（无 body） | `DELETE /sessions/{id}`、`DELETE /teams/{id}`、`DELETE /schedules/{id}` |
| **400** | 参数或状态不允许 | `files` 非法文件名、`DELETE /research/{id}` 运行中 |
| **403** | **内置资源只读保护** | `PUT/DELETE /skills/{name}` 对内置 Skill |
| **404** | 资源不存在 | 各 `{id}` / `{name}` 端点 |
| **409** | 冲突（重名 / 不在待审批状态） | `POST/PUT /skills`、`/teams`、`/agent/runs/{id}/approve\|reject` |
| **422** | 参数校验失败（Pydantic 默认 + 显式） | 全站 |
| **500** | 未捕获异常 | RAG / Web Research / MCP start 与 call |
| **503** | **能力缺失（缺 API Key）** | `POST /agent/chat`、`POST /rag/query`、`POST /web_research/research` |

**前端对应**（`frontend/web/vue-element-plus/src/api/client.ts:41-49` 的 `classify()`）：

| HTTP 状态 | 前端文案 |
| --- | --- |
| 202 | 「任务尚未完成」 |
| 400 / 404 / 422 / 503 / 5xx | 各自归一文案 |
| 0（网络中断/超时） | 「网络中断或超时」 / 「网络错误：…」 |

## 四、三条 SSE 端点

| 项 | `/agent/run` | `/runs/{id}/stream` | `/research/{task_id}/stream` |
| --- | --- | --- | --- |
| 触发 | POST（带 `RunRequest`） | GET（带 `after_seq`） | GET |
| 事件来源 | `AgentService.stream()` 实时产出 | **DB tail 轮询** `run_events` 表 | Research 进度 |
| 轮询间隔 | —（实时） | `STREAM_POLL_INTERVAL=0.3` s | `SSE_POLL_INTERVAL=0.5` s |
| 最长时长 | —（LLM 决定） | `STREAM_MAX_SECONDS=1800` | `SSE_MAX_DURATION=1800` |
| 终止事件 | `done` | 终态时 `done`（带 `status`） | `final` |
| 续订 | 不支持（一次性流） | `after_seq=N` 游标续订 | `stage\|ts` 去重键续订 |

**SSE 响应头三件套**（三条端点一致）：

```
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

## 五、鉴权与安全现状

| 项 | 现状 |
| --- | --- |
| 鉴权 | **桌面形态**：会话令牌 + Host 白名单（未授权 → 401 + 统一错误体）；**Web 形态**：单机无鉴权（`../plan/06` SEC-1b） |
| CORS | **S1 起收紧**：未显式配置 `CORS_ORIGINS` 时白名单为空（不再回落 `["*"]`）；响应头暴露 `X-Request-ID` |
| 限流 | 无 |
| 上传大小限制 | **无**（`POST /files/upload` 不校验大小） |
| 路径穿越防护 | `files` 的 `_safe_path()` 去目录成分；`skills` 的 `get_resource_path()` 校验 `startswith(base)`；zip 导入逐条拒绝 `..` 与 `/` 开头 |
| 代码执行边界 | 本地 subprocess + 5 条命令黑名单 + 180 s 超时，**无容器/无资源限制**（见 `11`） |

---

# 第二部分 原理剖析

## 六、为什么是「错误数据化」而不是「错误异常化」

平台的一个贯穿性设计：**工具与外部依赖的失败，尽量转化为数据返回给 LLM 或前端，而不是抛 HTTP 异常**。

| 场景 | 错误数据化 | 例子 |
| --- | --- | --- |
| 工具调用失败 | 包成 `{"error": "..."}` 回给 LLM | `tool_registry.py:222-250` |
| MCP 工具失败 | 转成字符串「MCP 工具调用失败: ...」 | `mcp_manager.py:175-179` |
| Deep Research 无检索 Key | `HTTP 200 + status="failed"` | `research.py:113-123` |
| Milvus 不可用 | `rag_entities=-1`（健康检查不失败） | `system.py:27-28`、`rag.py:58-59` |
| Agent 缺 Key | SSE 流内 `{"type":"error"}` + `done` | `agent_service.py:327-330` |

**理由**：

1. **Agent 循环不能因单个工具失败而中断**。如果 RAG 查询失败直接抛 500，Agent 的 function-calling 循环就断了；包成 `{"error": ...}` 返回，模型可以选择「换工具重试」或「如实告知用户」。
2. **健康检查必须是活探测而不是失败探测**。`/health` 的职责是「进程活着吗」，而不是「所有依赖都可用吗」——后者会让 K8s 的 liveness probe 因为 Milvus 临时不可用而反复重启容器。
3. **「失败但已知情」与「失败且未知情」要区分**。Deep Research 无 Key 是「配置缺失」，属于预期内状态（启动时已有 warning），用 `status="failed"` + 明确文案比 5xx 更准确地表达了「这不是异常，是配置问题」。

**代价**：客户端不能只用 HTTP 状态码判断成败，必须解析 body（如 `status` 字段、事件流内的 `error` 类型）。前端 `client.ts` 的 `classify()` 因此需要同时处理「202 未完成」「200 但 status=failed」「事件流内 error」三类「非错误码的失败」。

## 七、SSE 为什么是「拉模型」而不是「推模型」

三条 SSE 端点都是「客户端发起请求，服务端持续产出直到终态」的**拉模型**，不是「服务端主动推送」的推模型。这决定了：

- 可以用普通 HTTP 的 POST/GET + `after_seq` 游标做续订；
- 反向代理只需处理响应缓冲（`proxy_buffering off`），无需处理 upgrade 握手；
- 客户端断开 = 请求取消，服务端通过 `signal.aborted` 或客户端断开来停止生成器。

**代价**：没有「服务端主动通知」能力。定时任务执行完成、计划待审批等事件**不会主动推到前端**，前端必须自己轮询或刷新。这是 `plan_first` 流程中「计划产出后前端不会自动弹出审批卡」的根本原因——必须靠用户刷新或前端轮询 `/runs` 列表发现 `awaiting_approval` 状态的 run。

## 八、`/docs-info` 为什么不进 OpenAPI

`GET /docs-info`（`main.py:90-98`）用 `include_in_schema=False` 隐藏，原因是它是一个**引导性端点**（告诉用户 Swagger / ReDoc / 前端入口在哪），不是业务契约的一部分。把它排除在 schema 外，避免 `api_test.py` 的覆盖率统计把它算进去。

---

# 第三部分 已知边界与观察

| 编号 | 观察 | 证据 | 指向 |
| --- | --- | --- | --- |
| S-05-01 | `mcp_servers_available` 在 `/health` 中硬编码为 `3`，不反映实际注册数 | `backend/app/api/v1/system.py:47` | `12` D-6 |
| S-05-02 | MCP `start`/`stop` 是「启用/停用注册」语义，子进程只在调用时按需拉起；前端可能误以为 start 后进程常驻 | `backend/app/services/mcp_manager.py:8,77-86` | `12` D-7 |
| S-05-03 | `POST /research` 无检索 Key 时返回 200 + `status="failed"`，与 RESTful 状态码惯例冲突 | `backend/app/api/v1/research.py:113-123` | `12` D-35 |
| S-05-04 | `GET /research/{id}` 的 `progress` 只回最近 20 条，完整进度需走 SSE | `backend/app/api/v1/research.py:153` | `07` |
| S-05-05 | `POST /files/upload` 无大小限制，可被用于磁盘打满 | `backend/app/api/v1/files.py:38-48` | `12` §3 |
| S-05-06 | `POST /agent/chat` 是**非 SSE** 的完整 JSON 响应（含 `reasoning`/`answer`），与 `/agent/run` 的 SSE 形态不同 | `backend/app/api/v1/agent.py:132-144` | `03` §7 |
| S-05-07 | `POST /agent/run/sync` 的 `RunResult.rounds` 恒为 `0`（字段占位但未回填） | `backend/app/api/v1/agent.py:93` | `12` §2 |
| S-05-08 | `GET /mcp_servers/{name}` 的工具列举异常返回 **200 + `error` 字段**而非错误码 | `backend/app/api/v1/mcp_servers.py:40-41` | `12` §2 |
| S-05-09 | 所有 DELETE 端点（204）不可恢复，无回收站；Skill 删除是软删除（移入 `.trash/`）但会话/团队/任务不是 | `backend/app/api/v1/*.py` | `12` D-44 |
| S-05-10 | `rag_ingest` 的 `recreate` 默认 `True`，误调用会 DROP 整个 collection | `backend/app/api/v1/rag.py` | `12` §2 |

---

# 第四部分 改进指向

| 优先级 | 事项 | 台账编号 |
| --- | --- | --- |
| **P0** | 增加最小鉴权（单一 API Key 中间件）覆盖全部 `/api/v1` | `12` §3 |
| **P0** | CORS 白名单化 | `12` §3 |
| **P0** | `POST /files/upload` 增加大小与类型限制 | `12` §3 |
| **P1** | `/health` 的 `mcp_servers_available` 改为实际统计 | D-6 |
| **P1** | `POST /research` 无 Key 时的失败语义改为 503 或在契约文档中明确标注 | D-35 |
| **P1** | `POST /rag/ingest` 的 `recreate` 改为默认 `false` | `12` §2 |
| **P2** | `RunResult.rounds` 回填实际轮数 | `12` §2 |
| **P2** | 会话删除改为软删除（`deleted_at`） | D-44 |
| **P2** | MCP `status` 字段反映真实启用状态 | D-8 |

---

# 第五部分 核对方式

```bash
cd backend

# 1. 端点总数与方法分布（权威来源：OpenAPI）
.venv/Scripts/python.exe -c "
import collections
from app.main import app
ops = [(m.upper(), p) for p, o in app.openapi()['paths'].items() for m in o if m in ('get','post','put','patch','delete')]
print('总数:', len(ops)); print(collections.Counter(m for m,_ in ops))
"

# 2. SSE 端点（应为 3 条）
grep -rn "text/event-stream" app/api/v1/

# 3. 显式错误码
grep -rn "raise HTTPException" app/api/v1/ | sed 's/.*status_code=\([0-9]*\).*/\1/' | sort | uniq -c

# 4. 鉴权依赖（应为空）
grep -rn "Depends(verify\|get_current_user\|HTTPBearer\|OAuth2" app/api/v1/

# 5. 子 router 聚合
grep -c "include_router" backend/app/api/v1/router.py
```
