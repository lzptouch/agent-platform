/**
 * SSE 解析（POST /agent/run 与 GET /research/{id}/stream 共用）
 *
 * 实现要点（来自前端多平台开发分析与计划 §2.3 / §7.1）：
 * 1. 兼容 \n 与 \r\n 分包（buffer 残留 \r 时，丢弃 \r）
 * 2. 单条 JSON.parse 失败跳过，不中断流
 * 3. 跨 chunk 用 TextDecoder({stream:true}) 处理多字节截断
 * 4. 通过外部传入的 AbortSignal 支持取消
 */

import { buildApiUrl } from './client'

export interface SSEEventMap {
  'agent': import('./types').AgentEvent
  'research': import('./types').ResearchEvent
}

export type SSEKind = keyof SSEEventMap

export interface SSERunOptions {
  signal?: AbortSignal
  method?: 'GET' | 'POST'
  body?: unknown
  headers?: Record<string, string>
}

/**
 * 调用 SSE 端点并逐事件回调。
 * @param url 完整端点 URL（含 baseURL）
 * @param onEvent 单事件回调，类型由调用方断言
 * @param options.method 默认 GET；POST 时需同时给 body
 * @param options.body 仅 POST 用，JSON 序列化
 */
export async function runSSE<T>(
  url: string,
  onEvent: (ev: T) => void,
  options: SSERunOptions = {},
): Promise<void> {
  const headers: Record<string, string> = { Accept: 'text/event-stream', ...(options.headers ?? {}) }
  let body: BodyInit | undefined
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  const resp = await fetch(buildApiUrl(url), {
    method: options.method ?? 'GET',
    headers,
    body,
    signal: options.signal,
  })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const j = await resp.json()
      if (j && typeof j.detail === 'string') detail = j.detail
    } catch { /* */ }
    throw new Error(`${resp.status}: ${detail}`)
  }
  if (!resp.body) throw new Error('SSE response has no body')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      if ((window as unknown as { __sseDebug?: boolean }).__sseDebug) console.log('[sse] stream closed')
      return
    }
    buf += decoder.decode(value, { stream: true })
    // \r\n 兼容：仅按 \n 切，残留 \r 在解析时丢弃
    const parts = buf.split('\n')
    buf = parts.pop() ?? ''
    for (const raw of parts) {
      const line = raw.replace(/\r$/, '')
      if (!line.startsWith('data:')) continue
      const payload = line.slice(5).trim()
      if (!payload) continue
      try {
        const ev = JSON.parse(payload) as T
        if ((window as unknown as { __sseDebug?: boolean }).__sseDebug) {
          console.log('[sse]', (ev as { type?: string }).type)
        }
        onEvent(ev)
      } catch (err) {
        // 单条解析失败 → 跳过，不中断流
        if ((window as unknown as { __sseDebug?: boolean }).__sseDebug) {
          console.log('[sse-error]', String(err), payload.slice(0, 100))
        }
      }
    }
  }
}

/**
 * 调用 /agent/run（POST + SSE）。
 * 不设读超时（事件流由 `done` 终止）；AbortSignal 可立即取消。
 */
export function streamAgent(
  url: string,
  payload: import('./types').RunRequest,
  onEvent: (ev: import('./types').AgentEvent) => void,
  signal?: AbortSignal,
) {
  return runSSE<import('./types').AgentEvent>(url, onEvent, {
    method: 'POST',
    body: payload,
    signal,
  })
}

/**
 * 调用 /research/{id}/stream（GET + SSE）。
 * 实现「断流自动续订 + 进度去重」（核心三件套）：
 *   1. 流关闭后回查 GET /research/{id}，仅在仍非终态时重订阅
 *   2. 重订阅从 sent=0 全量重放，与已有事件按 (stage, timestamp) 去重
 *   3. 限速：最多每 1s 一次重订阅尝试
 *
 * 与 TS 后端 `routes/research.ts` 的 1800s 静默退出配套。
 */
/** P4-03：重连退避参数——此前固定 1s 重试且**无上限**，后端持续异常时会无限静默重连。 */
const RECONNECT_BASE_MS = 500
const RECONNECT_MAX_MS = 15_000
const RECONNECT_MAX_ATTEMPTS = 12

/** 指数退避 + ±20% 抖动（避免多客户端同时重连打垮服务端）。 */
function backoffMs(attempt: number): number {
  const raw = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** Math.max(0, attempt - 1))
  const jitter = raw * 0.2 * (Math.random() * 2 - 1)
  return Math.max(100, Math.round(raw + jitter))
}

export async function streamResearchWithReconnect(
  streamUrl: string,
  statusUrl: string,
  onProgress: (ev: import('./types').ResearchProgressItem) => void,
  onFinal: (ev: import('./types').ResearchFinalEv) => void,
  signal?: AbortSignal,
): Promise<import('./types').ResearchTaskStatusResp> {
  // 去重集合：key = `${stage}|${timestamp}`
  const seen = new Set<string>()
  const dedupKey = (stage: string, ts: string) => `${stage}|${ts}`

  const status = await fetch(statusUrl, { signal }).then(r => r.json()) as import('./types').ResearchTaskStatusResp

  /** P4-03：连续重连次数（达上限即放弃，不再无限静默重试）。 */
  let attempt = 0

  while (!signal?.aborted) {
    try {
      await runSSE<import('./types').ResearchEvent>(streamUrl, (ev) => {
        if (ev.type === 'progress') {
          const k = dedupKey(ev.stage, ev.timestamp)
          if (seen.has(k)) return
          seen.add(k)
          onProgress(ev)
        } else if (ev.type === 'final') {
          onFinal(ev)
        }
      }, { signal })
    } catch (e) {
      if (signal?.aborted) throw e
      // 网络中断等 → 继续循环，下面会回查状态
      attempt += 1
      if (attempt > RECONNECT_MAX_ATTEMPTS) {
        throw new Error(
          `研究流重连超过上限（${RECONNECT_MAX_ATTEMPTS} 次），已停止重试：${String(e)}`,
        )
      }
    }

    // 流自然结束（200s/1800s/服务端断开） → 回查状态
    let current: import('./types').ResearchTaskStatusResp
    try {
      current = await fetch(statusUrl, { signal }).then(r => r.json())
    } catch (e) {
      if (signal?.aborted) throw e
      // 网络不可达 → **退避**后重试（P4-03）
      attempt += 1
      if (attempt > RECONNECT_MAX_ATTEMPTS) {
        throw new Error(`研究状态回查超过上限（${RECONNECT_MAX_ATTEMPTS} 次），已停止重试`)
      }
      await sleep(backoffMs(attempt))
      continue
    }

    if (current.status === 'completed' || current.status === 'failed') {
      onFinal({
        type: 'final',
        status: current.status,
        quality_score: current.quality_score,
        iteration_count: current.iteration_count,
        error: current.error_message,
      })
      return current
    }

    // 仍非终态 → **退避**后重订阅（断流恢复关键；P4-03）
    attempt += 1
    if (attempt > RECONNECT_MAX_ATTEMPTS) {
      throw new Error(`研究流持续非终态且重连超过上限（${RECONNECT_MAX_ATTEMPTS} 次），已停止重试`)
    }
    await sleep(backoffMs(attempt))
  }

  return status
}

function sleep(ms: number) {
  return new Promise<void>((res, rej) => {
    const t = setTimeout(res, ms)
    // 透传 abort
    //（简化：调用方通过 signal 控制；如需精确中止可改成 AbortSignal-aware）
    void t
  })
}