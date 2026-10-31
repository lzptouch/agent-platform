# HTTP 接口总览

> - **依据代码**：`backend/app/api/v1/*.py`、`backend/app/api/v1/router.py`、`backend/app/api/deps.py`、`backend/app/main.py`、`backend/app/schemas/*.py`
> - **资料来源**：2026-10-31 逐文件探查 + OpenAPI 规格导出（`app.openapi()`；口径由 `scripts/facts.py` 从代码直接提取）
> - **整理日期**：2026-10-31（S0~S8 阶段编码完成 + **P1~P6 六批次 83 项全部交付**后复核）
> - **对应基线**：commit `7385dcd` + 工作区未提交改动
> - **相关篇目**：`01` 架构总览 ｜ `02` 能力链 ｜ `03` 执行引擎 ｜ `06` 前端契约 ｜ `08` 调度 ｜ `12` 风险台账 ｜ `14` 权限 ｜ `15` 工作区 ｜ `16` 上下文成本 ｜ `17` 扩展层

---

# 第一部分 现状事实

## 一、总览

| 项 | 值 |
| --- | --- |
| 统一前缀 | `/api/v1`（`backend/app/main.py:148`） |
| 子 router 数 | **17** |
| 端点总数 | **98 条唯一路径 / 126 个操作** |
| 方法分布 | GET **57** / POST **49** / DELETE **10** / PUT **8** / PATCH **2** |
| SSE 端点 | **4**（`/agent/run`、`/runs/{run_id}/stream`、`/research/{task_id}/stream`、`/desktop/events`）——**`/runs/{run_id}/events` 是分页 JSON，不是 SSE** |
| 鉴权 | **桌面形态**：Host 白名单 + 会话令牌/Cookie；**Web 形态**：**完全无鉴权** |
| 限流 | **无**（仅有 Agent 并发预算信号量，见 `11`） |
| 鉴权型 `Depends` | **0 个**——86 处 `Depends` 全是「从 `app.state` 取共享服务」的服务获取器（`backend/app/api/deps.py:21-83`） |
| 额外端点 | `GET /docs-info`（`include_in_schema=False`）；桌面态另有 `GET /__desktop/bootstrap`、`GET /__desktop/ping`（`main.py:167-175`） |
| 文档 | `/docs`（Swagger）、`/redoc`（ReDoc）、`/openapi.json` |

**17 个子 router 的聚合**（`backend/app/api/v1/router.py:26-42`，统一由 `main.py` 加 `/api/v1`）：

| # | 模块 | router 前缀 | tags | 端点数 | 注册行 |
| --- | --- | --- | --- | --- | --- |
| 1 | `system.py` | — | `system` | 2 | `router.py:26` |
| 2 | `skills.py` | `/skills` | `skills` | 11 | `router.py:27` |
| 3 | `agent.py` | `/agent` | `agent` | 7 | `router.py:28` |
| 4 | `sessions.py` | `/sessions` | `sessions` | 6 | `router.py:29` |
| 5 | `runs.py` | `/runs` | `runs` | 6 | `router.py:30` |
| 6 | `teams.py` | `/teams` | `teams` | 7 | `router.py:31` |
| 7 | `schedules.py` | `/schedules` | `schedules` | 10 | `router.py:32` |
| 8 | `files.py` | `/files` | `files` | 5 | `router.py:33` |
| 9 | `mcp_servers.py` | `/mcp_servers` | `mcp` | 9 | `router.py:34` |
| 10 | `permissions.py` | `/permissions` | `permissions` | 6 | `router.py:35` |
| 11 | `workspace.py` | **无前缀** | `workspace` | 12 | `router.py:36` |
| 12 | `context.py` | **无前缀** | `context` | 7 | `router.py:37` |
| 13 | `extensions.py` | **无前缀** | `extensions` | 13 | `router.py:38` |
| 14 | `rag.py` | `/rag` | `rag` | 4 | `router.py:39` |
| 15 | `web_research.py` | `/web_research` | `web_research` | 2 | `router.py:40` |
| 16 | `research.py` | `/research` | `research` | 7 | `router.py:41` |
| 17 | `desktop.py` | `/desktop` | `desktop` | 12 | `router.py:42` |

> ⚠️ **`workspace.py:17`、`context.py:16`、`extensions.py:15` 的 `APIRouter()` 没有 prefix**——它们的路径是 `/workspaces`、`/memories`、`/roles`、`/plugins`、`/boards`、`/cost` 等**顶级路径片段**，不是子前缀。
>
> **合计：98 条唯一路径 / 126 个操作**（S1~S8 新增 46 个操作；P1~P6 六批次新增 8 个操作，见 §2.13~§2.14）。

### 1.1 `api/v1` 之外的端点（`backend/app/main.py`）

| 方法 | 路径 | 说明 | 位置 |
| --- | --- | --- | --- |
| GET | `/docs-info` | 文档索引（`include_in_schema=False`） | `main.py:178` |
| GET | `/__desktop/bootstrap?t=<nonce>` | 桌面一次性引导，下发 HttpOnly Cookie 后 302 | `main.py:167` |
| GET | `/__desktop/ping` | 免鉴权存活探针 | `main.py:172` |
| GET | `/` + `/{full_path:path}` | SPA 托管回退（`/api/*` 未匹配保持 404） | `main.py:190-207` |

> 后两个仅在 `settings.desktop_mode` 为真时注册。

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

### 2.4 `sessions.py`（6）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `POST /api/v1/sessions` | `create_session` | `SessionCreate{mode,title?,skills?,team_id?,config?}` | `SessionOut`（201） | 非法 mode → **422**（Pydantic Literal 校验） |
| `GET /api/v1/sessions` | `list_sessions` | query `mode`(pattern `^(chat\|plan\|work)$`), `page≥1`, `page_size 1..100`, `include_archived` | `Page[SessionOut]`（**默认过滤已软删会话**） | — |
| `GET /api/v1/sessions/{session_id}` | `get_session` | query `message_limit 1..500`, `before_seq` | `SessionDetail`（含 messages, has_more） | 404 |
| `PATCH /api/v1/sessions/{session_id}` | `update_session` | `SessionUpdate{title?,archived?,skills?,team_id?,config?}` | `SessionOut` | 404 |
| `DELETE /api/v1/sessions/{session_id}` | `delete_session` | — | 204（**软删除**：置 `deleted_at` + `archived=1`，**消息行保留**） | 404 |
| `DELETE /api/v1/sessions/{session_id}/purge` | `purge_session` | — | 204（**永久删除**：物理删除会话与消息） | 404 |

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

### 2.8 `files.py`（5）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/files` | `list_files` | — | `{total, files[{name,size,is_image,url}]}` | — |
| `GET /api/v1/files/policy` | `upload_policy` | — | `{extensions[],builtin_extensions[],max_file_bytes,max_request_bytes}`（**上传白名单单一真相源**，前端运行时拉取） | — |
| `POST /api/v1/files/upload` | `upload_file` | `UploadFile` | `{name,size,url}` | **400** 非法文件名 / **415** 类型不在白名单 / **413** 超单文件 50MB 或单请求 100MB |
| `GET /api/v1/files/{filename}` | `get_file` | path | `FileResponse` | 404 |
| `DELETE /api/v1/files/{filename}` | `delete_file` | path | `{deleted}` | 404 |

### 2.9 `mcp_servers.py`（9）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/mcp_servers` | `list_servers` | — | `McpServerListResponse{total,servers[]}`（含**真实连接状态** `status` 与可读 `reason`） | — |
| `GET /api/v1/mcp_servers/config` | `get_mcp_config` | query `workspace_root?` | `{servers{},errors[],sources[]}`（**两级配置合并结果**：用户级 `~/.agent/mcp.json` + 项目级 `<workspace>/.agent/mcp.json`） | — |
| `POST /api/v1/mcp_servers/config/reload` | `reload_mcp_config` | query `workspace_root?` | `{ok,servers[]}`（重读两级配置并清空工具缓存） | — |
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
| `POST /api/v1/rag/ingest` | `rag_ingest` | query `recreate:bool=False`（**批次 03 起默认 `False`**，增量幂等） | `IngestResponse{chunks,entities,collection}` | 500 |
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

### 2.13 `permissions.py`（6）

| METHOD 路径 | 函数 | 请求 | 响应 | 错误 |
| --- | --- | --- | --- | --- |
| `GET /api/v1/permissions/rules` | `list_rules` | query `scope?`, `workspace_id?` | `{rules[], effective_level}` | — |
| `PUT /api/v1/permissions/rules` | `set_rule` | body `scope`, `pattern\|target`, `decision`(deny\|ask\|allow), `risk?` | `{ok, rule}` | **422** 参数非法 |
| `DELETE /api/v1/permissions/rules` | `delete_rule` | body `scope`, `pattern\|target` | `{ok}` | **422** 参数非法 |
| `GET /api/v1/permissions/decisions` | `list_decisions` | query `status=pending\|resolved`, `run_id?` | 待审批列表或决策日志（倒序，**上限 200 条**） | — |
| `POST /api/v1/permissions/decisions` | `submit_decision` | body `decision_id`, `choice`∈`allow_once\|allow_session\|allow_workspace\|deny` | `{ok, decision}` | **422**（非法 choice / 未知 id）｜`AppError` |
| `GET /api/v1/permissions/sandbox` | `sandbox_capability` | — | `SandboxCapability{level,available,platform,enforced_paths[],enforced_commands[],message}` | — |

> `allow_workspace` 会把本次决策**反推成一条工作空间规则落库**（`api/v1/permissions.py:134-154` → `security/permissions.py:424-454`）。
> 详见 `14_权限引擎与安全边界.md`。

### 2.14 S2~S8 与 P1~P6 新增端点（工作空间 / 上下文成本 / 扩展三层 / 桌面）

> 本小节由 OpenAPI 规格导出（`backend/app/main.py` 的 `app.openapi()`），是**新增能力的权威清单**；
> 2.1~2.13 是手写细节表（保留请求 / 响应 / 错误语义）。

| 方法 | 路径 | 分组 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/v1/boards/{board_id}/items` | extensions | 黑板任务项 |
| `POST` | `/api/v1/boards/{board_id}/items` | extensions | 新增黑板任务项（201） |
| `POST` | `/api/v1/boards/{board_id}/items/{item_id}/complete` | extensions | 完成任务项（触发重算） |
| `GET` | `/api/v1/boards/{board_id}/messages` | extensions | 黑板消息与通知（`to_role` / `notifications_only`） |
| `GET` | `/api/v1/changes/{change_id}/diff` | workspace | 一次变更的 diff（query `workspace_id`） |
| `POST` | `/api/v1/changes/{change_id}/revert` | workspace | 回退一次变更（从快照恢复）；**走权限判定，被拒 → 403 `E_PERMISSION`** |
| `GET` | `/api/v1/cost/estimate` | context | 发起前的消耗区间（p50~p90），query `model` |
| `GET` | `/api/v1/desktop/components` | desktop | 组件安装状态 |
| `GET` | `/api/v1/desktop/events` | desktop | 桌面事件流（SSE，query `after_id` / `max_events`） |
| `GET` | `/api/v1/desktop/permissions` | desktop | 读取三态权限规则 + 沙箱可用性 |
| `PUT` | `/api/v1/desktop/permissions` | desktop | 更新某条权限规则（422） |
| `POST` | `/api/v1/desktop/permissions/decision` | desktop | 对一次待确认操作给出临时决定（422） |
| `GET` | `/api/v1/desktop/preferences` | desktop | 读取桌面配置 |
| `PUT` | `/api/v1/desktop/preferences` | desktop | 更新桌面配置（422） |
| `POST` | `/api/v1/desktop/scheduler/resume-scan` | desktop | 扫描并补跑错过的定时任务（422） |
| `POST` | `/api/v1/desktop/shutdown` | desktop | 请求后端优雅退出 |
| `GET` | `/api/v1/desktop/status` | desktop | 桌面运行态快照（含调度器健康 + 权限档位） |
| `GET` | `/api/v1/desktop/workspace` | desktop | 当前工作区 |
| `PUT` | `/api/v1/desktop/workspace` | desktop | 切换工作区（立即生效，发 `workspace_changed` 事件；400 缺 path） |
| `GET` | `/api/v1/memories` | context | 列出记忆（按作用域 `user\|workspace\|project`） |
| `POST` | `/api/v1/memories` | context | 写入一条记忆（201） |
| `DELETE` | `/api/v1/memories` | context | 删除一条记忆（body `scope` + `path`） |
| `POST` | `/api/v1/memories/clear` | context | 清空某作用域的记忆 |
| `POST` | `/api/v1/orchestrate` | extensions | **多 Agent 编排**（parallel / sequential / review）；`subtasks[].deps` 用子任务下标；可传 `board_id` 登记黑板任务项（422 参数非法 / 503 未绑定 Agent） |
| `GET` | `/api/v1/plugins` | extensions | 已安装插件列表（含扫描结果） |
| `POST` | `/api/v1/plugins/install` | extensions | 安装插件包（原子切换，zip b64 或本地目录）；安装成功后**当前进程立即 reload 技能** |
| `POST` | `/api/v1/plugins/rollback` | extensions | 回滚插件到上一版本 |
| `POST` | `/api/v1/plugins/scan` | extensions | 扫描本地插件目录（不安装） |
| `GET` | `/api/v1/roles` | extensions | 角色列表（自动 sync 内置角色） |
| `POST` | `/api/v1/roles` | extensions | 创建角色（201） |
| `PATCH` | `/api/v1/roles/{role_id}` | extensions | 更新角色（**不可改名**） |
| `DELETE` | `/api/v1/roles/{role_id}` | extensions | 删除角色 |
| `GET` | `/api/v1/runs/{run_id}/artifacts` | workspace | 一次 run 的交付物（不含中间文件；含 `kind` 与 `url`——浏览器类产物的来源页面） |
| `GET` | `/api/v1/runs/{run_id}/artifacts/{artifact_id}/download` | workspace | 下载产物文件（桌面态原生「另存」对话框用；404 产物或文件不存在） |
| `POST` | `/api/v1/runs/{run_id}/artifacts/{artifact_id}/save-as` | workspace | 产物另存到指定位置（**`dest` 不做路径限制**） |
| `GET` | `/api/v1/runs/{run_id}/changes` | workspace | 一次 run 的变更列表 |
| `GET` | `/api/v1/runs/{run_id}/cost` | context | 一次运行的成本明细 + 分位 + 价目表 |
| `GET` | `/api/v1/sessions/{session_id}/context` | context | 会话上下文占用（token/字符/比例），query `turns 1..200` |
| `GET` | `/api/v1/workspaces` | workspace | 工作空间列表（含 `current`） |
| `POST` | `/api/v1/workspaces` | workspace | 创建工作空间（201） |
| `POST` | `/api/v1/workspaces/{workspace_id}/archive` | workspace | 归档工作空间（不删磁盘文件） |
| `GET` | `/api/v1/workspaces/{workspace_id}/manifest` | workspace | 读取工作空间 manifest（五字段：`writable_roots`/`default_policy`/`model`/`skills`/`extensions`） |
| `PUT` | `/api/v1/workspaces/{workspace_id}/manifest` | workspace | 更新工作空间 manifest（**带类型校验**，非法值 → 422）；`writable_roots` **立即影响下一次写文件**的权限判定 |
| `POST` | `/api/v1/workspaces/{workspace_id}/switch` | workspace | 切换当前工作空间（**并广播 `workspace_changed` 事件**，桌面壳渲染进程可感知） |

## 三、错误与状态码语义

| 状态码 | 语义 | 出现位置 |
| --- | --- | --- |
| **200** | 成功（含「失败但数据化返回」：如 `POST /research` 无 Key 时 `status="failed"`） | 大部分 GET / POST |
| **201** | 创建成功 | `POST /skills`、`POST /teams`、`POST /schedules`、`POST /sessions` |
| **202** | **任务未完成**（Deep Research 结果未就绪） | `GET /research/{id}/result` |
| **204** | 删除成功（无 body） | `DELETE /sessions/{id}`、`DELETE /sessions/{id}/purge`、`DELETE /teams/{id}`、`DELETE /schedules/{id}` |
| **400** | 参数或状态不允许 | `files` 非法文件名、`DELETE /research/{id}` 运行中、`POST /runs/{id}/steer` 空指令、`PUT /desktop/workspace` 缺 path |
| **403** | **内置资源只读保护 / 权限拒绝** | `PUT/DELETE /skills/{name}` 对内置 Skill；`POST /changes/{id}/revert` 权限引擎拒绝（`E_PERMISSION`） |
| **404** | 资源不存在 | 各 `{id}` / `{name}` 端点；`GET /runs/{id}/artifacts/{aid}/download` 产物或文件不存在 |
| **409** | 冲突（重名 / 不在待审批状态） | `POST/PUT /skills`、`/teams`、`/agent/runs/{id}/approve\|reject` |
| **413** | **请求体过大** | `POST /files/upload`（单文件 50MB / 单请求 100MB）；`POST /skills/import`（zip 20MB） |
| **415** | **媒体类型不支持** | `POST /files/upload`（扩展名/MIME 不在白名单） |
| **422** | 参数校验失败（Pydantic 默认 + 显式） | 全站；`PUT /workspaces/{id}/manifest`（manifest 字段类型非法）；`POST /orchestrate`（参数非法） |
| **500** | 未捕获异常 | RAG / Web Research / MCP start 与 call |
| **503** | **能力缺失（缺 API Key）/ 依赖未就绪** | `POST /agent/chat`、`POST /rag/query`、`POST /web_research/research`；`POST /orchestrate`（未绑定 Agent） |

**显式异常统计**（2026-10-31 复核实测）：`HTTPException` **120** 处 + `AppError` **3** 处 = **123**。
自定义 `status_code` 分布：404×50、422×39、500×9、201×8、409×6、400×6、503×4、403×4、413×3、204×3、415×1、202×1。

**前端对应**（`frontend/web/vue-element-plus/src/api/client.ts:57-65` 的 `classify()`）：

| HTTP 状态 | 前端文案 |
| --- | --- |
| 202 | 「任务尚未完成」 |
| 400 / 404 / 422 / 503 / 5xx | 各自归一文案 |
| 0（网络中断/超时） | 「网络中断或超时」 / 「网络错误：…」 |

## 四、四条 SSE 端点

| 项 | `/agent/run` | `/runs/{id}/stream` | `/research/{task_id}/stream` | `/desktop/events` |
| --- | --- | --- | --- | --- |
| 触发 | POST（带 `RunRequest`） | GET（带 `after_seq`） | GET | GET（带 `after_id` / `max_events`） |
| 事件来源 | `AgentService.stream()` 实时产出 | **DB tail 轮询** `run_events` 表 | Research 进度 | 进程内**环形缓冲**（200 条） |
| 轮询间隔 | —（实时） | `STREAM_POLL_INTERVAL=0.3` s | `SSE_POLL_INTERVAL=0.5` s | `EVENT_POLL_INTERVAL=0.3` s |
| 最长时长 | —（LLM 决定） | `STREAM_MAX_SECONDS=1800` | `SSE_MAX_DURATION=1800` | `EVENT_MAX_SECONDS=3600` |
| 终止事件 | `done` | 终态时 `done`（带 `status`） | `final` | `max_events` 满足即结束 |
| 续订 | 不支持（一次性流） | `after_seq=N` 游标续订 | `stage\|ts` 去重键续订 | `after_id=N` 游标补发 |
| 事件类型 | **24** 个（见 `03` §5.1） | 同上（附 `seq`） | `progress` / `final` | `hello` / `heartbeat` / `workspace_changed` / `scheduler_rescued` / `permission_requested` / `permission_resolved` |

**SSE 响应头三件套**（四条端点一致）：

```
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

> **`GET /api/v1/runs/{run_id}/events` 不是 SSE**——它是分页 JSON（`runs.py:51-62`，返回 `RunEventPage{items,last_seq,status,has_more}`），用于「一次性拉全量历史」。

## 五、鉴权与安全现状

| 项 | 现状 |
| --- | --- |
| 鉴权 | **桌面形态**：Host 白名单（loopback + 端口一致）+ 会话 Cookie / `X-Agent-Desktop-Token`（未授权 → 401 + 统一错误体）；**Web 形态**：**完全无鉴权** |
| CORS | **S1 起收紧**：未显式配置 `CORS_ORIGINS` 时白名单为空（不再回落 `["*"]`）；响应头暴露 `X-Request-ID` |
| 限流 | 无 |
| 上传大小限制 | **有**：单文件 **50MB** / 单请求 **100MB**（超限 → **413**），类型不在白名单 → **415** |
| 路径穿越防护 | `files` 的 `_safe_path()` 去目录成分；`skills` 的 `get_resource_path()` 校验 `startswith(base)`；zip 导入逐条拒绝 `..` 与 `/` 开头 |
| 代码执行边界 | 本地 subprocess + rlimit 限额 + 命令黑名单 + 180 s 超时，**无容器隔离**（见 `11` §2、`14` §3） |
| 业务权限 | 判定入口是 `ToolRegistry.dispatch()`；HTTP 层仅 `POST /changes/{id}/revert` 直接调引擎（详见 `14`） |

---

# 第二部分 原理剖析

## 六、为什么是「错误数据化」而不是「错误异常化」

平台的一个贯穿性设计：**工具与外部依赖的失败，尽量转化为数据返回给 LLM 或前端，而不是抛 HTTP 异常**。

| 场景 | 错误数据化 | 例子 |
| --- | --- | --- |
| 工具调用失败 | 包成 `{"error": "..."}` 回给 LLM | `tool_registry.py:225-288` |
| MCP 工具失败 | 转成字符串「MCP 工具调用失败: ...」 | `mcp_manager.py:188-197` |
| Deep Research 无检索 Key | `HTTP 200 + status="failed"` | `research.py:112-123` |
| Milvus 不可用 | `rag_entities=-1`（健康检查不失败） | `system.py`、`rag.py:58-59` |
| Agent 缺 Key | SSE 流内 `{"type":"error"}` + `done` | `agent_service.py:419-424` |

**理由**：

1. **Agent 循环不能因单个工具失败而中断**。如果 RAG 查询失败直接抛 500，Agent 的 function-calling 循环就断了；包成 `{"error": ...}` 返回，模型可以选择「换工具重试」或「如实告知用户」。
2. **健康检查必须是活探测而不是失败探测**。`/health` 的职责是「进程活着吗」，而不是「所有依赖都可用吗」——后者会让 K8s 的 liveness probe 因为 Milvus 临时不可用而反复重启容器。
3. **「失败但已知情」与「失败且未知情」要区分**。Deep Research 无 Key 是「配置缺失」，属于预期内状态（启动时已有 warning），用 `status="failed"` + 明确文案比 5xx 更准确地表达了「这不是异常，是配置问题」。

**代价**：客户端不能只用 HTTP 状态码判断成败，必须解析 body（如 `status` 字段、事件流内的 `error` 类型）。前端 `client.ts` 的 `classify()` 因此需要同时处理「202 未完成」「200 但 status=failed」「事件流内 error」三类「非错误码的失败」。

## 七、SSE 为什么是「拉模型」而不是「推模型」

四条 SSE 端点都是「客户端发起请求，服务端持续产出直到终态」的**拉模型**，不是「服务端主动推送」的推模型。这决定了：

- 可以用普通 HTTP 的 POST/GET + `after_seq` / `after_id` 游标做续订；
- 反向代理只需处理响应缓冲（`proxy_buffering off`），无需处理 upgrade 握手；
- 客户端断开 = 请求取消，服务端通过 `signal.aborted` 或客户端断开来停止生成器。

**代价**：没有「服务端主动通知」能力。定时任务执行完成、计划待审批等事件**不会主动推到前端**，前端必须自己轮询或刷新。这是 `plan_first` 流程中「计划产出后前端不会自动弹出审批卡」的根本原因——必须靠用户刷新或前端轮询 `/runs` 列表发现 `awaiting_approval` 状态的 run。

> 桌面端的 `/desktop/events` 是**唯一接近推送语义**的通道，但方向仍是「壳主动发起订阅」，不是「后端主动推送」。

## 八、`/docs-info` 为什么不进 OpenAPI

`GET /docs-info`（`main.py:178-186`）用 `include_in_schema=False` 隐藏，原因是它是一个**引导性端点**（告诉用户 Swagger / ReDoc / 前端入口在哪），不是业务契约的一部分。把它排除在 schema 外，避免覆盖率统计把它算进去。

桌面态的 `/__desktop/bootstrap` 与 `/__desktop/ping` 同样 `include_in_schema=False`——它们是**壳进程的一次性引导通道**，不属于业务 API 契约。

---

# 第三部分 已知边界与观察

| 编号 | 观察 | 证据 | 指向 |
| --- | --- | --- | --- |
| S-05-01 | ~~`mcp_servers_available` 在 `/health` 中硬编码为 `3`~~ **已修**（S1 WP-1.9 起读 MCP 注册表） | `backend/app/api/v1/system.py:69` | 已关闭 |
| S-05-02 | MCP `start`/`stop` 是「启用/停用注册」语义，子进程只在调用时按需拉起；前端可能误以为 start 后进程常驻 | `backend/app/services/mcp_manager.py:8,94-100` | `12` §2 |
| S-05-03 | `POST /research` 无检索 Key 时返回 200 + `status="failed"`，与 RESTful 状态码惯例冲突 | `backend/app/api/v1/research.py:112-123` | `12` §2 |
| S-05-04 | `GET /research/{id}` 的 `progress` 只回最近 20 条，完整进度需走 SSE | `backend/app/api/v1/research.py:141-163` | `07` |
| S-05-05 | ~~`POST /files/upload` 无大小限制~~ **已修**（批次 01 WP-2：415 类型 + 413 大小 50MB/100MB） | `backend/app/api/v1/files.py:54-102`；`core/uploads.py` | 已关闭 |
| S-05-06 | `POST /agent/chat` 是**非 SSE** 的完整 JSON 响应（含 `reasoning`/`answer`），与 `/agent/run` 的 SSE 形态不同 | `backend/app/api/v1/agent.py:132-144` | `03` §1 |
| S-05-07 | `POST /agent/run/sync` 的 `RunResult.rounds` 恒为 `0`（字段占位但未回填） | `backend/app/api/v1/agent.py:73-101` | `12` §2 |
| S-05-08 | `GET /mcp_servers/{name}` 的工具列举异常返回 **200 + `error` 字段**而非错误码 | `backend/app/api/v1/mcp_servers.py:31-42` | `12` §2 |
| S-05-09 | 所有 DELETE 端点（204）不可恢复，无回收站；Skill 删除是软删除（移入 `.trash/`）但会话/团队/任务不是 | `backend/app/api/v1/*.py` | `12` §2 |
| S-05-10 | ~~`rag_ingest` 的 `recreate` 默认 `True`~~ **已改**（批次 03：默认 `False`） | `backend/app/api/v1/rag.py:45` | 已关闭 |
| S-05-11 | **API 层无任何鉴权型 `Depends`**——81 处 `Depends` 全是服务获取器；Web 形态的 `/api/v1` 全部端点裸奔 | `backend/app/api/deps.py:21-83` | `12` §3 |
| S-05-12 | `POST /runs/{run_id}/artifacts/{artifact_id}/save-as` 的 `dest` **不做路径限制**，可写任意绝对路径（与 `revert` 端点的权限判定不对称） | `backend/app/api/v1/workspace.py:119-127` | `12` §3 |
| S-05-13 | `GET /api/v1/runs/{run_id}/events` 与 `/stream` 语义相近（前者分页 JSON、后者 SSE），命名易混淆 | `backend/app/api/v1/runs.py:51,65` | `06` §6 |
| S-05-14 | `POST /changes/{id}/revert` 是 API 层**唯一**直接触发权限引擎的端点 | `backend/app/api/v1/workspace.py:99-116` | `14` §5 |
| S-05-15 | `scheduled_tasks.delivery_json` 有读无写——**没有任何 API 能配置投递通道** | `backend/app/api/v1/schedules.py`；`scheduler_service.py:556-561` | `08` §1.7 |

---

# 第四部分 改进指向

| 优先级 | 事项 | 台账编号 |
| --- | --- | --- |
| **P0** | 增加最小鉴权（单一 API Key 中间件）覆盖全部 `/api/v1` | `12` §3 |
| ~~**P0**~~ | ~~CORS 白名单化~~ **已完成**（S1 WP-1.2） | 已关闭 |
| ~~**P0**~~ | ~~`POST /files/upload` 增加大小与类型限制~~ **已完成**（批次 01 WP-2） | 已关闭 |
| **P1** | `POST /research` 无 Key 时的失败语义改为 503 或在契约文档中明确标注 | `12` §2 |
| **P1** | `save-as` 的 `dest` 增加路径约束（与 `revert` 对齐走权限判定） | `12` §3 |
| **P1** | 为 `scheduled_tasks.delivery_json` 增加写入 API | `08` §1.7 |
| **P2** | `RunResult.rounds` 回填实际轮数 | `12` §2 |
| **P2** | 会话删除改为软删除（`deleted_at`） | `12` §2 |
| **P2** | `/runs/{id}/events` 与 `/runs/{id}/stream` 在契约文档中明确区分命名 | `06` §6 |

---

# 第五部分 核对方式

```bash
cd backend

# 1. 端点总数与方法分布（权威来源：OpenAPI）
.venv/bin/python -c "
import collections
from app.main import app
spec = app.openapi()
ops = [(m.upper(), p) for p, o in spec['paths'].items() for m in o if m in ('get','post','put','patch','delete')]
print('唯一路径:', len(spec['paths']), '操作:', len(ops)); print(collections.Counter(m for m,_ in ops))
"

# 2. SSE 端点（应为 4 条）
grep -rn "text/event-stream" app/api/v1/

# 3. 显式错误码
grep -rn "raise HTTPException" app/api/v1/ | sed 's/.*status_code=\([0-9]*\).*/\1/' | sort | uniq -c
grep -rn "AppError" app/api/v1/ | wc -l

# 4. 鉴权依赖（应为空）
grep -rn "Depends(verify\|get_current_user\|HTTPBearer\|OAuth2" app/api/v1/

# 5. 子 router 聚合（应为 17）
grep -c "include_router" app/api/v1/router.py

# 6. 三处无 prefix 的 router（workspace / context / extensions）
grep -n "APIRouter(" app/api/v1/workspace.py app/api/v1/context.py app/api/v1/extensions.py
```
