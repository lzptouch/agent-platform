# Vue 3 前端与 SSE 消费

> **依据代码**：`apps/ui/src/`（重点 `api/client.ts`、`api/sse.ts`）（2026-11-01 复核重写）
> **原理主题**：① 用 fetch + ReadableStream 自研 SSE 消费器；② 长任务进度流的
> 「断流续订 + 去重 + 退避」三件套。

---

## 一、前端形态

Vue 3 `<script setup>` + TypeScript + Vite + Element Plus + Pinia + vue-router。
同源架构：桌面态壳直接加载 `http://127.0.0.1:<port>`（sidecar 托管 dist），
开发态 Vite proxy 转发 `/api`——**没有跨域面**，因此 `runtimeBase` 恒为空串
（`client.ts:35`），前端代码里没有 baseURL 切换逻辑。

工程数字：19 视图 / 23 组件 / 7 store / 96 个 API 封装函数
（口径见 `../analysis/00` §5 C11~C14）。

## 二、原理：为什么自研 `runSSE` 而不是 EventSource

EventSource 的三个硬限制在本项目全部命中：

| 限制 | 本项目的诉求 |
|---|---|
| 只支持 GET | 主事件流是 **POST `/agent/run`**（请求体带模式/技能/开关） |
| 自动重连语义固定 | 续传必须走业务游标（`Last-Event-ID` / 状态回查），自动重连会重复消费 |
| 无法读原始字节处理边界 | 需要处理多字节字符截断与坏行跳过 |

fetch + `resp.body.getReader()` 拿到的是**原始字节流**，自行实现 SSE 行解析
（`sse.ts:34-94`）：

```ts
buf += decoder.decode(value, { stream: true })  // TextDecoder 流模式：多字节字符跨 chunk 不碎
const parts = buf.split('\n')                    // 兼容 \r\n：残留的 \r 解析时丢弃
buf = parts.pop() ?? ''                          // 末段不完整，留到下一 chunk
// 只取 data: 行；单条 JSON.parse 失败 → 跳过，不中断流
```

要点：① `{stream:true}` 让半个 UTF-8 字符留在解码器内部状态里；
② 缓冲残留处理分包（TCP 任意切）；③ 坏事件隔离（一条脏数据不毁整条流）；
④ `AbortSignal` 贯通取消。

## 三、原理：断流续订三件套（`streamResearchWithReconnect`）

研究任务分钟级运行，SSE 会被系统休眠/网络抖动断开。服务端的续传语义是
「重订后全量重放」，前端必须配套三件事（`sse.ts:134-208`）：

1. **状态回查**：流关闭后先 `GET /research/{id}`——已是终态就直接收官
   （把状态端点当「最终事实」），非终态才重订阅；
2. **重放去重**：`(stage, timestamp)` 集合判重，重放的事件不重复渲染；
3. **退避 + 上限**：指数退避 500ms → 15s（±20% 抖动，防多客户端共振），
   **最多 12 次**——超过即抛错。无限静默重连会把「服务端已死」伪装成
   「还在努力」，错误必须能浮出水面。

## 四、HTTP 客户端（`client.ts`）

- **超时分级**：默认 15s；`/agent/run/sync` 180s（对齐后端 `exec_timeout`）；
  `/rag/ingest` 300s（批量 PDF 入库慢）；流式端点 `timeoutMs=0`（由 `done` 自然终止）；
- **错误归一**：`ApiError(status, 文案, path)`，按状态码分类文案
  （503 区分「未配置 Key」与「服务异常」）；202（任务未完成）与 204（删成功无 body）
  特判；
- **取消**：内部 AbortController + 外部 signal 桥接。

## 五、状态与渲染

- `session` / `rounds` store 把事件流重组为「轮次 → 步骤 → 消息」的展示模型
  （RoundGroup / ProcessSteps / RunTimeline 组件消费）；
- Markdown 渲染：markdown-it + **DOMPurify**（`FORBID_TAGS:['style','iframe','form']`）
  + highlight.js；
- 引用统一：RAG / Web Research 两路引用经 `citations.ts` 适配为同一 `Citation`
  类型，ProcessSteps 只渲染这一种。

## 六、业界对照

| 方案 | 能力 | 本项目为何不用 |
|---|---|---|
| EventSource | GET + 自动重连 | 不能 POST；重连语义不符 |
| fetch-event-source | POST + 解析 | 多一个依赖，自研 30 行已覆盖且可控（去重/退避是业务语义） |
| WebSocket | 双向 | 无双向需求；多一层协议与鉴权面 |

## 参考

- `../analysis/00` §7 R-12（MDN ReadableStream/AbortController）
- `../analysis/06`（前端架构事实）
