# Vue 3 + TypeScript 前端与 SSE 消费原理

> - **依据项目**：`apps/ui/`（Vue 3.5 + TS 5.7 + Element Plus 2.8 + Pinia 2.2 + Vite 6）
> - **资料来源**：本项目代码（2026-10-26 探查）+ MDN ReadableStream / EventSource 官方 + Vue 3 官方
> - **整理日期**：2026-10-26
> - **范围**：前端架构形态 + SSE 流式消费原理 + 断流恢复机制
> - **风格**：当前实现 → 原理剖析 → 业界做法对照 → 操作要点

---

# 第一部分 当前实现

## 一、工程形态

本项目的唯一前端实现是 `apps/ui/`：

| 维度 | 实现 |
| --- | --- |
| 框架 | Vue 3.5（`<script setup>` + Composition API）+ TypeScript 严格模式 |
| 构建 | Vite 6（`vue-tsc --noEmit && vite build`） |
| UI 库 | Element Plus 2.8 |
| 状态 | Pinia 2.2（4 个 setup 风格 store） |
| 路由 | Vue Router 4.4（`createWebHistory`，无守卫） |
| HTTP | 原生 `fetch`（自研 `api/client.ts`），**无 axios** |
| Markdown | markdown-it + DOMPurify + highlight.js |
| 结构 | 15 视图 / 13 组件 / 2 布局 / 4 store |

**信息架构是「双形态」**：v3 工作台（`/workspace`，任务流 + 三态模式 + 命令面板）与 admin 后台（`/admin/*`，能力管理）并存，由 localStorage 灰度开关 `__ws_v3` 决定默认入口。详见 `analysis/06_前端架构与接口契约.md`。

## 二、SSE 消费的最小实现

前端不依赖 `EventSource`，自研 `runSSE()`（`src/api/sse.ts`）：

```typescript
const reader = resp.body.getReader()
const decoder = new TextDecoder()
let buf = ''
while (true) {
  const { done, value } = await reader.read()
  if (done) return
  buf += decoder.decode(value, { stream: true })
  const parts = buf.split('\n')
  buf = parts.pop() ?? ''
  for (const raw of parts) {
    const line = raw.replace(/\r$/, '')
    if (!line.startsWith('data:')) continue
    const payload = line.slice(5).trim()
    try { onEvent(JSON.parse(payload)) } catch { /* 单条失败跳过 */ }
  }
}
```

四个工程要点：

1. **跨 chunk 多字节**：`TextDecoder({stream:true})` 把 UTF-8 多字节字符拆到相邻 chunk 时不会乱码；
2. **`\r\n` 兼容**：按 `\n` 切，残留的 `\r` 在解析时丢弃；
3. **单条失败不中断**：一条坏 JSON 只跳过，不断流；
4. **只认 `data:` 前缀**：本项目后端只用 `data:` 行，不用 `event:`/`id:` 字段。

---

# 第二部分 原理剖析

## 三、为什么用原生 fetch 而不是 EventSource

| 维度 | 自研 `runSSE`（fetch） | 原生 `EventSource` |
| --- | --- | --- |
| 请求方法 | ✅ POST（`/agent/run` 需要 body） | ❌ 仅 GET |
| 自定义请求头 | ✅ 可带 `Authorization` | ❌ 仅 URL 参数 |
| 取消 | ✅ `AbortController` | ❌ 需 `close()` |
| 自动重连 | ❌ 需手写 | ✅ 内置（但无业务游标） |
| 流式读取 | ✅ `ReadableStream` | ❌ 事件粒度 |

SSE 的本质是「一个永不立刻结束的 HTTP 响应」。`EventSource` 把这个响应封装成事件流，但它**只能发 GET 且不能带 body**——而 `/agent/run` 需要 POST 一个 `RunRequest`（含 prompt、skills、mode 等）。EventSource 做不到，只能自研。

**根本结论**：当流式接口需要「带请求体的 POST」时，EventSource 就不适用，必须退回 `fetch + ReadableStream` 手动解析 SSE 帧格式。

## 四、SSE 帧解析的状态机本质

SSE 协议规定事件以「空行」分隔，每条事件由若干 `field: value` 行组成。本项目只用 `data:` 字段，且每个事件是**一行 JSON**（`data: {...}\n\n`），因此解析器可以简化为：

```
按 \n 切分 → 滤出以 "data:" 开头的行 → slice(5) 去掉前缀 → trim → JSON.parse
```

**坑点**：网络层按 TCP 段交付，一个 SSE 事件可能被拆到多个 chunk，或多个事件挤在一个 chunk。解析器必须：
- 用 `buf` 暂存**最后一个不完整行**（`parts.pop()`），等下一个 chunk 拼接；
- 不假设 chunk 边界 = 事件边界。

这是所有流式解析（SSE / NDJSON / gRPC-streaming）的通用问题：**传输层的包边界 ≠ 应用层的消息边界**。

## 五、断流恢复：从「连接保活」到「业务游标」

SSE 长连接（研究进度最长 1800 s）必然断流。恢复有两层思路：

| 思路 | 机制 | 局限 |
| --- | --- | --- |
| **传输层保活** | TCP keepalive / WebSocket ping | 只能检测连接死，不能恢复丢失的事件 |
| **业务层游标** | 给每个事件一个序号（`seq` 或 `stage\|timestamp`），断流后从「上次收到的序号」继续 | 需要服务端支持续订 |

本项目两条链路各用一种游标：

- **运行事件回放**：`run_events` 表给每个事件分配递增 `seq`，前端断流后用 `GET /runs/{id}/stream?after_seq=N` 续订（**精确续订，不重放**）；
- **研究进度**：断流后重订阅会**全量重放**，前端用 `stage|timestamp` 去重键过滤重复（**重放 + 去重**）。

前者适合事件有序且有持久序号的场景；后者适合事件天然按阶段分组、重放成本低的场景。

## 六、为什么「断流后先回查状态再决定是否重订阅」

流结束有两种含义：**任务真的结束了**，或**连接断了但任务还在跑**。两者必须区分，否则会出现「任务还在跑但前端已停」的假死。

`streamResearchWithReconnect()` 的处理：流关闭后先 `GET /research/{id}` 查真实状态，只有仍是 `running` 才重订阅；若已 `completed/failed` 则合成一个 `final` 事件收尾。**这是把「传输层事件」与「业务层状态」解耦**——流的存活不代表任务的存活。

---

# 第三部分 业界做法对照

| 方案 | 代表 | 与本项目的差异 |
| --- | --- | --- |
| 原生 EventSource | 浏览器内置 | 仅 GET、无 body、自动重连但无业务游标 |
| `@microsoft/fetch-event-source` | Azure | 支持 POST + header + AbortController，但不处理跨 chunk 多字节截断的边界细节 |
| Socket.IO | — | 带自动重连与房间，但引入自定义协议与客户端库 |
| WebSocket | 原生 | 全双工；本项目只需服务端→客户端单向，SSE 更轻 |
| gRPC-web 流式 | gRPC | 强类型 + 双向，但需代理（envoy）与 code gen |

**选型结论**：本项目的「POST + SSE + 业务游标」组合，是在「需要带请求体 + 需要断流恢复 + 只需单向」三个约束下的最小解。

---

# 第四部分 操作要点

| 要点 | 说明 |
| --- | --- |
| 新增 SSE 端点 | 后端响应用 `data: {json}\n\n`，带 `Cache-Control: no-cache` + `X-Accel-Buffering: no`；前端复用 `runSSE` |
| 长连接续订 | 事件必须带可去重的序号（`seq` 或 `stage\|ts`）；断流后先回查状态再重订阅 |
| Nginx 反代 | 必须 `proxy_buffering off` + `proxy_read_timeout` 调大，否则流式被缓冲 |
| 调试 | 浏览器 console 设 `window.__sseDebug = true` 看每条事件 |
| 取消 | 所有 SSE 调用透传 `AbortSignal`，组件卸载时 `abort()` |

---

## 附录 A：参考资料

| # | 主题 | 链接 |
| --- | --- | --- |
| 1 | MDN EventSource | https://developer.mozilla.org/zh-CN/docs/Web/API/EventSource |
| 2 | MDN ReadableStream | https://developer.mozilla.org/zh-CN/docs/Web/API/ReadableStream |
| 3 | MDN AbortController | https://developer.mozilla.org/zh-CN/docs/Web/API/AbortController |
| 4 | Vue 3 官方 | https://cn.vuejs.org/ |
| 5 | fetch-event-source（参考） | https://github.com/Azure/fetch-event-source |
| 6 | 本项目分析文档 | `analysis/06_前端架构与接口契约.md`、`analysis/03_Agent执行引擎与事件协议.md` §5 |
