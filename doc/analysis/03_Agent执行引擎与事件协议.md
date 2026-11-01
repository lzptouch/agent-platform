# Agent 执行引擎与事件协议

> **依据代码**：`apps/server/src/domain/agent/loop.ts`、`domain/run/executor.ts`、`domain/tools/{registry,builtin,executor}.ts`、`http/routes/{agent,runs}.ts`、`http/sse.ts`、`contract/events.json`（2026-11-01 复核）

# 第一部分 现状事实

## 一、执行模型总览

```
POST /api/v1/agent/run（SSE）
  └─ runExecutor.executeStream()            domain/run/executor.ts:185
       ├─ 槽位信号量（交互 4 / 调度 2，分离）   executor.ts:74-76
       ├─ prepare()：mergeTools + system prompt 组装
       ├─ runService.createRun()（落账 + 工作空间绑定）
       ├─ 前置事件：meta / skills_selected / system_prompt / user_input
       ├─ plan_first → generatePlan() → approval_required → 挂起
       └─ streamLoop() / streamReflection()  domain/agent/loop.ts:107
            └─ for iteration in 0..limit: LLM → tool_calls → dispatchBuiltinTool → 回喂
```

- **async generator 直出**：事件从循环体一路 yield 到 SSE 通道，无队列中转；
- LLM 调用是**逐轮非流式**（`client.chat.completions.create`，无 `stream=True`），
  `model_text` 事件每轮一次（内容为该轮完整文本）；首字延迟 = 首轮完整响应时间
  （E2E 实测 522ms 量级）。

## 二、主循环逐步（`streamLoop`，`loop.ts:107-299`）

1. **组装消息**：system（Skill 块 + 团队提示词前缀）+ 历史（只回放 user/assistant，
   见 §八）+ 当前 prompt；
2. **每轮开头**检查：deadline（超时 → error+done）、cancelHook（→ interrupted+done）；
3. 发 `round_start` / `round_input`（消息清单预览，每条截 120 字符）；
4. 调 LLM（`max_tokens=8192`），随后 `recordCall()` 计量落 `llm_calls`
   （失败只告警不阻断）；
5. 有文本 → `model_text`；**无 tool_calls → `done{status:"completed"}` 结束**；
6. 有 tool_calls：assistant 消息入列，逐个工具：
   - 工具边界再查 cancelHook；**steerHook**（有注入 → `steer_injected` 事件 +
     `[用户补充指令]` user 消息）；
   - **循环指纹**：`sha256(工具名|排序后的参数JSON)`，同一指纹第 3 次出现且
     `loopHook` 允许 → `loop_detected`（只告知，不中止；中止由迭代上限兜底）；
   - `tool_call`（入参截 4000 字符）→ `dispatchBuiltinTool()` → `tool_result`
     （结果截 2000 字符）→ tool 消息回喂；
7. 达上限 → `error` + `done{status:"failed"}`。

工具结果统一 `{ok, ...}` 结构，异常**不抛穿**（转为 `{ok:false,error}` 回喂模型，
`builtin.ts:4`）。

## 三、工具注册表与 Profile（`domain/tools/registry.ts`）

- **静态工具 11 个**（C08）：内置 8 + RAG 2 + Web 1；动态 MCP 工具按
  `mcp_<server>__<tool>` 命名空间并入；
- **Profile 裁剪**：`chat` 只留 `read_file` / `list_directory`（+ `rag_query` + 只读 MCP）；
  `work` 全量；`assertProfileConsistency()` 断言 chat 档案不含写类工具；
- **角色工具上界**：`mergeTools(opts.roleTools)` 支持按角色声明裁剪（MCP 工具豁免）——
  但当前执行路径**未传入** `roleTools`（`executor.ts:206-214` 的 prepare 调用没有它），
  `role_id` 参数经路由接收后**不产生实际效果**；
- **延迟装载器** `LazyToolLoader`（`tool_search` / `tool_load` 两个引导工具）：
  目录检索 + 按需装载完整 Schema；当前执行器未把 loader 实例挂进 `toolContext`
  （`executor.ts:312-318`），工具调用时退化为一进程内临时 loader
  （`builtin.ts:160`）——即「延迟装载」语义未在运行路径生效。

## 四、模式与计划审批

- `mode=plan` 在路由层归一为 `work + plan_first=true`（`routes/agent.ts:35`）；
- plan_first：先 `generatePlan()`（`loop.ts:379`，LLM JSON 数组，失败降级单步计划）
  → `runService.savePlan()`（状态 `awaiting_approval`）→ 发 `approval_required{run_id, plan}`
  → `done{status:"awaiting_approval"}` **挂起**；
- 审批：`POST /agent/runs/{id}/approve`（可带 `edited_plan`）→ 状态回 `queued` +
  meta 写 `resume_of/approved_at` → `resumeAfterApproval()` 续跑；
  `reject` → 状态 `rejected`；
- **重启续跑**：`resumePendingApprovals()` 扫描 `awaiting_approval` 且
  `meta.approved_at` 存在的 run 续跑（`executor.ts:124`）；
- 反思模式（`streamReflection`，`loop.ts:302`）：plan（LLM JSON）→ 复用主循环行动 →
  `reflection_plan`（最多 `reflection_max_rounds=2` 轮）→ done。chat 模式请求反思会被
  忽略并发 `notice` 事件。

## 五、SSE 事件协议

### 5.1 传输形态

4 条 SSE 端点（`contract/events.json`）：

| 端点 | 事件名位置 | 续传 |
|---|---|---|
| `POST /api/v1/agent/run` | payload 的 `type` 字段（event 名恒为 `message`） | 无 |
| `GET /api/v1/runs/{id}/stream` | SSE `event:` 字段 + `id:` = seq | `Last-Event-ID` / `after_seq` |
| `GET /api/v1/research/{id}/stream` | SSE `event:` 字段 | 轮询 + 心跳（前端负责重订） |
| `GET /api/v1/desktop/events` | `message` + 事件体带 `id` | `after_id` 补发；`max_events` 有界模式 |

统一响应头：`Cache-Control: no-cache`、`X-Accel-Buffering: no`、`Connection: keep-alive`
（`http/sse.ts:10`）；写失败即标记通道关闭，循环检查 `channel.closed` 退出。

### 5.2 契约事件清单（26 种，C15）

`skills_selected`、`system_prompt`、`user_input`、`round_start`、`round_input`、
`model_text`、`reasoning_delta`、`tool_call`、`tool_result`、`files`、`error`、`done`、
`reflection_start`、`plan`、`reflection_plan`、`meta`、`approval_required`、`notice`、
`interrupted`、`steer_injected`、`plan_replaced`、`context_compressed`、`context_trimmed`、
`busy`、`memory_item`、`loop_detected`。

### 5.3 前置事件序列（每次 run 固定）

`meta`（run_id / session_id / mode / team / resolved_skills）→ `skills_selected`
（选中 + 全部 + total）→ `system_prompt`（默认只发 summary：长度/技能/工具数；
`debug_prompt=true` 才发全文）→ `user_input`。

### 5.4 契约与实现的事件差（当前真实状态）

| 事件 | 发射点 | 状态 |
|---|---|---|
| 其余 20 种 | `loop.ts` / `executor.ts` | ✅ 有发射 |
| `reasoning_delta` | 无 | ⬜ 契约保留（当前逐轮非流式，无增量推理事件） |
| `files` | 无（`executeSync` 读它，恒为 `[]`） | ⬜ 契约保留 |
| `plan_replaced` | 无 | ⬜ 契约保留（审批改计划只落库，不发事件） |
| `context_compressed` / `context_trimmed` | 无 | ⬜ 契约保留（压缩未执行，见 `16` §2.3） |
| `memory_item` | 无（`/agent/chat` 消费它，恒空） | ⬜ 契约保留 |

### 5.5 中断与转向

- **取消**：`POST /runs/{id}/cancel` → 控制句柄 `cancelled=true`（`executor.ts:95`）+
  DB 置 `interrupted`；循环在「轮首 / 工具前 / 工具后」三个边界检查 →
  `interrupted{phase}` + done。终态守卫保证不被后续 finish 覆盖
  （`run/service.ts:295` 的 `TERMINAL_STATUSES`）；
- **steer**：`POST /runs/{id}/steer` → 指令入队，下一个**工具边界**取出注入
  （保序，取空即清）；
- **busy**：槽位 30s 排队超时 → `busy{limit}` + `done{failed}`。

## 六、执行扩展子包（`domain/exec/` + `domain/accounting/`）

- `exec/tokens.ts`：token 估算（英文 4 字符≈1 token，CJK 1.5 字符≈1 token）；
- `exec/accounting.ts`：`recordCall()` 每次 LLM 调用落 `llm_calls`（含**单价快照**）；
  `aggregateRun()` 聚合到 run 行（收尾时由 `RunService.finish` 回写，经
  `registerUsageProvider` 注入防循环依赖）；
- `accounting/pricing.ts`：单价表（7 模型 + 兜底），`pricing_json` 配置可覆盖；
- `exec/tokens.ts` / `accounting` 详见 `16_上下文经济性与成本核算.md`。

# 第二部分 原理剖析

## 七、为什么主链路是 function calling 而不是 plan→action→reflection→answer

function calling 把「下一步做什么」的决策权交给模型本身，框架只负责执行与回喂——
循环体极小（一轮 = 一次 LLM 调用 + 若干工具分发），行为上限由模型能力决定，
不依赖脆弱的 JSON 计划解析。反思模式作为**可选分支**保留（`enable_reflection`），
其 plan/reflection 两段都要求 LLM 输出 JSON 数组并用正则截取兜底。

## 八、为什么历史回放必须过滤 tool 消息

OpenAI 兼容接口要求 `tool` 消息与 assistant 的 `tool_calls` **严格配对**。
历史消息是从 DB 重建的，中间态（tool 消息、带 tool_calls 的 assistant）一旦混入，
配对关系就破坏（400）。因此 `sessionService.buildHistory()` 只回放 user 与
最终 assistant 文本（`session/service.ts:342`），并按 `session_history_limit=10` 条 +
`8000` 字符双预算从旧到新裁剪、保证首条是 user。

## 九、为什么工具结果要截断（4000 / 2000 字符）

工具输出直接进上下文。`tool_call` 入参截 4000、`tool_result` 结果截 2000，
把单次循环的上下文增量限制在可预期范围；完整内容不落事件但已落盘（文件工具
真实写盘），模型可用 `read_file` 再取。截断是**上下文经济性**的第一道闸（其余见 `16`）。

## 十、为什么计划审批用「挂起 + 恢复」而不是「阻塞等待」

审批可能隔几小时才来。阻塞一个请求连接等审批，既占槽位又怕断线。
挂起态把计划落库（`awaiting_approval`），连接当即释放；审批端点触发
`resumeAfterApproval()` 重入执行流，且 `meta.resume_of/approved_at` 让
**进程重启后**也能扫描续跑（`resumePendingApprovals()`）。

## 十一、为什么用 SSE 而不是 WebSocket

见 `01_架构总览.md` §十。补充执行侧理由：`run_events` 表本身就是有序账本，
SSE 的 `Last-Event-ID` 与「DB tail + seq 游标」天然同构——断线重连 =
从上次 seq 继续 SELECT，无需任何额外协议。
