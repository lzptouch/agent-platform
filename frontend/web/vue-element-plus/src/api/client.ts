/**
 * HTTP 客户端（fetch 封装 + 超时 + 错误归一 + 取消）
 *
 * 关键约束：
 * - 流式端点（/agent/run、/research/{id}/stream）**不设读超时**，由 SSE `done`/`final`/流断开自然终止
 * - `/agent/run/sync` 用 exec_timeout=180s
 * - `/rag/ingest` 用 300s（大量 PDF 入库慢）
 * - 其余 15s
 * - 错误归一：FastAPI `{"detail": ...}` 形式，503 区分「未配置 Key」与「服务异常」
 */

import { ApiError } from './types'

export type Method = 'GET' | 'POST' | 'DELETE' | 'PUT' | 'PATCH'

export interface RequestOptions {
  method?: Method
  body?: unknown
  /** 毫秒。默认 15000；流式传 0 表示不限读超时 */
  timeoutMs?: number
  signal?: AbortSignal
  /** 强制走 query 参数（rag/ingest 用） */
  query?: Record<string, string | number | boolean | undefined>
  /** FormData 上传（multipart） */
  formData?: FormData
}

const DEFAULT_TIMEOUT = 15_000

// ---------- 运行时 base（桌面远端模式） ----------
// 空串 = 同源（Web 形态与桌面本地模式）。仅桌面「远端模式」下由壳注入非空值。
let runtimeBase = ''

/** 设置运行时 API base。``null``/空串 = 回到同源。 */
export function setApiBase(base: string | null): void {
  runtimeBase = base ? base.replace(/\/+$/, '') : ''
}

/** 拼装完整 URL：绝对路径直接返回；相对路径叠加运行时 base（空则为同源）。 */
export function buildApiUrl(path: string): string {
  if (!runtimeBase) return path
  if (/^https?:\/\//.test(path)) return path
  return `${runtimeBase}${path.startsWith('/') ? path : `/${path}`}`
}

function joinUrl(path: string, query?: Record<string, string | number | boolean | undefined>): string {
  if (!query) return path
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null) continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `${path}?${s}` : path
}

function classify(status: number, detail: string): string {
  if (status === 202) return `任务尚未完成（${detail}）`  // 不是错误（research/result）
  if (status === 400) return detail
  if (status === 404) return `资源不存在（${detail}）`
  if (status === 422) return `请求参数错误（${detail}）`
  if (status === 503) return `服务未配置或依赖不可用（${detail}）`
  if (status >= 500) return `服务异常（${detail}）`
  return detail
}

export async function request<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = buildApiUrl(joinUrl(path, opts.query))
  const headers: Record<string, string> = {}
  let body: BodyInit | undefined

  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  } else if (opts.formData) {
    body = opts.formData
  }

  const ctl = new AbortController()
  const external = opts.signal
  if (external) {
    if (external.aborted) ctl.abort()
    else external.addEventListener('abort', () => ctl.abort(), { once: true })
  }

  // 流式（timeoutMs===0）不设读超时；其它用 setTimeout
  let timer: ReturnType<typeof setTimeout> | undefined
  if (opts.timeoutMs !== 0) {
    const t = opts.timeoutMs ?? DEFAULT_TIMEOUT
    timer = setTimeout(() => ctl.abort(new DOMException('TimeoutError', 'TimeoutError')), t)
  }

  let resp: Response
  try {
    resp = await fetch(url, {
      method: opts.method ?? (opts.body || opts.formData ? 'POST' : 'GET'),
      headers,
      body,
      signal: ctl.signal,
    })
  } catch (e: unknown) {
    if (timer) clearTimeout(timer)
    if ((e as { name?: string }).name === 'AbortError' || (e as { name?: string }).name === 'TimeoutError') {
      throw new ApiError(0, '网络中断或超时', path)
    }
    throw new ApiError(0, `网络错误：${(e as Error).message ?? e}`, path)
  }
  if (timer) clearTimeout(timer)

  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const j = await resp.json()
      if (j && typeof j.detail === 'string') detail = j.detail
    } catch { /* 忽略 */ }
    throw new ApiError(resp.status, classify(resp.status, detail), path)
  }

  // 202 不当作错误，但前端可能需要识别（如 research/result）
  if (resp.status === 202) {
    let detail = ''
    try { detail = (await resp.json()).detail ?? '' } catch { /* */ }
    throw new ApiError(202, classify(202, detail), path)
  }

  // 204 No Content / 空响应体：DELETE 类接口常见，不能直接 res.json()
  // （否则抛 "Unexpected end of JSON input"，导致删除操作被误判为失败）
  if (resp.status === 204) return null as T

  const raw = await resp.text()
  if (!raw) return null as T
  try {
    return JSON.parse(raw) as T
  } catch {
    return raw as unknown as T
  }
}

export const get  = <T>(path: string, opts?: Omit<RequestOptions, 'method'|'body'|'formData'>) =>
  request<T>(path, { ...opts, method: 'GET' })
export const post = <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method'|'body'|'formData'>) =>
  request<T>(path, { ...opts, method: 'POST', body })
export const del  = <T>(path: string, opts?: Omit<RequestOptions, 'method'|'body'|'formData'>) =>
  request<T>(path, { ...opts, method: 'DELETE' })
export const put  = <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method'|'body'|'formData'>) =>
  request<T>(path, { ...opts, method: 'PUT', body })
export const patch = <T>(path: string, body?: unknown, opts?: Omit<RequestOptions, 'method'|'body'|'formData'>) =>
  request<T>(path, { ...opts, method: 'PATCH', body })
export const upload = <T>(path: string, formData: FormData, opts?: Omit<RequestOptions, 'method'|'body'|'formData'>) =>
  request<T>(path, { ...opts, method: 'POST', formData })