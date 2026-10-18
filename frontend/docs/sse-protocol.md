# SSE 协议实现规范

> 15 个前端实现共享的流式协议与样例。源代码事实见 `backend/app/services/agent_service.py` 与 `backend/app/services/research/research_manager.py`。

## 1. 通用 SSE 解析规则

```ts
// POST /api/v1/agent/run 与 GET /api/v1/research/{id}/stream 共用
async function* parseSSE(response: Response): AsyncGenerator<unknown> {
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) return
    buf += decoder.decode(value, { stream: true })
    // ⚠️ 兼容 \r\n：必须按 \n 切，buffer 内可能残留 \r
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try { yield JSON.parse(line.slice(6)) }
        catch { /* 跳过单条解析失败，不中断流 */ }
      }
    }
  }
}
```

### Apple（Swift，iOS 15+ / macOS 12+）样例

```swift
// URLSession.bytes(for:) 返回 (AsyncBytes, URLResponse)，AsyncBytes.lines 已处理跨 chunk 截断
for try await rawLine in bytes.lines {
    // ⚠️ 兼容 \r\n：按 \n 切后行尾可能残留 \r
    let line = rawLine.hasSuffix("\r") ? String(rawLine.dropLast()) : rawLine
    guard line.hasPrefix("data:") else { continue }
    let json = line.dropFirst(5).trimmingCharacters(in: .whitespaces)
    guard !json.isEmpty,
          let chunk = json.data(using: .utf8),
          let any = try? JSONSerialization.jsonObject(with: chunk),
          let dict = any as? [String: Any] else { continue }   // 跳过单条解析失败，不中断流
    handle(dict)
}
```

三个 Apple 专属注意点（15 个实现中只有 Apple 侧存在）：

1. 流式会话必须用独立 `URLSessionConfiguration.timeoutIntervalForRequest ≥ 1800`（默认 **60s** 会掐断研究流）。
2. 取消走 `Task.cancel()` → `AsyncThrowingStream.onTermination`（等价 `AbortController.abort()`）。
3. Swift 6 严格并发下 `[String: Any]` 非 `Sendable` → 事件类型须 `Sendable`（两个 Swift 实现用自研 `JSONValue`）。

## 2. Agent 事件（15 种）

`POST /api/v1/agent/run` body 形如 `{prompt, model?, skills?, enable_mcp?, mcp_servers?, enable_rag?, enable_web_research?, enable_reflection?}`。SSE 流事件类型：

| type | 字段 | 现有前端消费 | 备注 |
|---|---|:-:|---|
| `skills_selected` | `skills[]`,`all_skills[]`,`total` | ✅ | 头徽标 |
| `system_prompt` | `content`（路径已脱敏） | ❌ | 调试折叠区 |
| `user_input` | `content` | ❌ | 回声 |
| `round_start` | `round` | ❌ | 轮次分隔 |
| `round_input` | `messages[{index,role,preview}]` | ❌ | 上下文快照 |
| `model_text` | `content`,`round` | ✅ | 默认模式有 `round`，**反思模式无** |
| `tool_call` | `tool_name`,`tool_input`(JSON str),`round`(默认模式),`tool_source`,`mcp_server` | ✅ | 反思模式无 `round` |
| `tool_result` | `tool_name`,`result`(截断 2000),`round`(默认模式),`tool_source`,`mcp_server`,`references?`,`reference_cards?` | ✅ | 反思模式无 `round` |
| `files` | `files[{name,size,is_image}]` | ✅ | 产出文件 |
| `error` | `content` | ✅ | 默认模式后仍会发 files+done |
| `done` | — | ✅ | 收尾 |
| `reflection_start` | `mode` | ❌ | 值 `plan_action_reflection_answer` |
| `plan` | `actions[{tool,input}]` | ✅ | 默认模式不发，反思模式有 |
| `reflection_plan` | `actions[]` | ✅ | 同上 |
| `reasoning_delta` | `content` | ✅ | **仅反思模式** |

**`tool_source`**：`builtin` / `mcp` / `rag` / `web`（前端自造第 5 色 `plan`）。

**内部事件 `memory_item` 不对外**。

## 3. Research 事件（2 种）

`GET /api/v1/research/{id}/stream`：

| type | 字段 |
|---|---|
| `progress` | `{type:'progress', stage, data, timestamp}` —— `timestamp` 由 `research_manager.py:144` 写入 |
| `final` | `{type:'final', status, quality_score, iteration_count, error}` |

### 24 个 stage 枚举（`ResearchView.vue:31-41`）

```
decomposing, decomposed, dispatching, worker_started, worker_completed, worker_failed,
synthesizing, synthesized, quality_checking, quality_checked, iteration_start,
iteration_evaluated, quality_passed, iteration_continue, analyzing_gaps, gaps_analyzed,
dispatching_supplementary, supplementary_worker_started, supplementary_worker_completed,
refining_report, report_refined, no_supplementary_tasks, completed, failed
```

各 stage 的 `data` 字段见计划文档 §2.3.2。

## 4. 三个必须处理的语义（★核心）

### 4.1 1800s 静默断流

```python
# backend/app/api/v1/research.py:196-218
while elapsed < SSE_MAX_DURATION:  # 1800s
    ...
    if terminal: yield final; break
    await asyncio.sleep(0.5)
    elapsed += 0.5
# 到点后 while 退出，无 final，无关闭事件
```

**前端必备**：

```ts
async function streamWithAutoReconnect(taskId, onEvent) {
  while (true) {
    try {
      for await (const ev of parseSSE(await fetch(`/api/v1/research/${taskId}/stream`))) {
        onEvent(ev)
      }
    } catch (e) { /* 网络错误 */ }

    // 流自然结束 → 回查状态
    const status = await getJSON(`/api/v1/research/${taskId}`)
    if (status.status === 'completed' || status.status === 'failed') return status
    // 仍非终态 → 1s 后重订阅（限频：3 次/分钟）
    await sleep(1000)
  }
}
```

### 4.2 重订阅全量重放

```python
# backend/app/api/v1/research.py:197,204-205
sent = 0
while sent < len(progress):
    yield {...progress[sent]...}
    sent += 1
```

**前端必备去重**：

```ts
const seen = new Set<string>()
function dedupKey(stage: string, timestamp: string) { return `${stage}|${timestamp}` }
function isDup(progress: ResearchProgressItem) {
  const key = dedupKey(progress.stage, progress.timestamp)
  if (seen.has(key)) return true
  seen.add(key); return false
}
```

⚠️ **不能用 stage 单独作 key**：同 stage 会重复出现（如多轮 `worker_completed`）。

### 4.3 进度只回最近 20 条

```python
# backend/app/api/v1/research.py:153
progress=task["progress"][-20:]
```

GET 返回**仅最近 20 条**。前端必须**累积合并**已收到的所有进度事件，不能整段覆盖。

## 5. 步骤配对

`tool_call` 与 `tool_result` 的配对采用**前端自增 `step_id`**（不要依赖 `round`，反思模式无 `round`）：

```ts
let stepIdSeq = 0
const pending = new Map<number, Step>()  // step_id → step

case 'tool_call':
  const step = { step_id: ++stepIdSeq, kind:'tool', tool_name:ev.tool_name, ... }
  pending.set(step.step_id, step); emit(step)
  break
case 'tool_result':
  // 回填队首未完成的同名 step
  for (const id of [...pending.keys()].reverse()) {
    const s = pending.get(id)!
    if (s.tool_name === ev.tool_name && !s.result) {
      s.result = ev.result
      if (ev.references) s.references = ev.references
      if (ev.reference_cards) s.reference_cards = ev.reference_cards
      pending.delete(id); emit(s); break
    }
  }
```