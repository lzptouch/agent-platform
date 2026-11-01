/**
 * SSE 解析单测（阶段 0）。
 *
 * 覆盖 runSSE 的 5 个关键行为：
 *  1. 逐事件回调且顺序正确
 *  2. \r\n 分包兼容
 *  3. 单条 JSON 解析失败 → 跳过，不中断流
 *  4. 跨 chunk 的多字节字符不被截断
 *  5. 非 2xx → 抛出带状态码与 detail 的错误
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { runSSE } from '../../../../apps/ui/src/api/sse'

/** 构造一个可分块读取的 Response 替身 */
function makeStream(chunks: string[]): Response {
  const encoder = new TextEncoder()
  let i = 0
  return {
    ok: true,
    status: 200,
    body: {
      getReader() {
        return {
          async read() {
            if (i >= chunks.length) return { done: true, value: undefined }
            const value = encoder.encode(chunks[i++])
            return { done: false, value }
          },
        }
      },
    },
  } as unknown as Response
}

describe('runSSE', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('逐事件回调并保持顺序', async () => {
    const fetchMock = vi.mocked(fetch)
    fetchMock.mockResolvedValue(
      makeStream([
        'data: {"type":"round_start","round":1}\n\n',
        'data: {"type":"model_text","content":"你好"}\n\n',
        'data: {"type":"done"}\n\n',
      ]),
    )
    const seen: Array<{ type: string }> = []
    await runSSE<{ type: string }>('/x', ev => seen.push(ev))
    expect(seen.map(e => e.type)).toEqual(['round_start', 'model_text', 'done'])
  })

  it('兼容 \\r\\n 分包', async () => {
    vi.mocked(fetch).mockResolvedValue(
      makeStream(['data: {"type":"done"}\r\n\r\n']),
    )
    const seen: Array<{ type: string }> = []
    await runSSE<{ type: string }>('/x', ev => seen.push(ev))
    expect(seen).toEqual([{ type: 'done' }])
  })

  it('单条 JSON 非法时跳过且不中断流', async () => {
    vi.mocked(fetch).mockResolvedValue(
      makeStream([
        'data: {bad json}\n\n',
        'data: {"type":"done"}\n\n',
      ]),
    )
    const seen: Array<{ type: string }> = []
    await runSSE<{ type: string }>('/x', ev => seen.push(ev))
    expect(seen.map(e => e.type)).toEqual(['done'])
  })

  it('跨 chunk 的多字节字符不被截断', async () => {
    // "中" 占 3 字节，故意从中间切开
    const bytes = new TextEncoder().encode('data: {"type":"model_text","content":"中"}\n\n')
    const mid = 20
    const part1 = new Uint8Array(bytes.slice(0, mid))
    const part2 = new Uint8Array(bytes.slice(mid))
    let i = 0
    const resp = {
      ok: true,
      status: 200,
      body: {
        getReader() {
          return {
            async read() {
              if (i === 0) { i++; return { done: false, value: part1 } }
              if (i === 1) { i++; return { done: false, value: part2 } }
              return { done: true, value: undefined }
            },
          }
        },
      },
    } as unknown as Response
    vi.mocked(fetch).mockResolvedValue(resp)
    const seen: Array<{ type: string; content?: string }> = []
    await runSSE<{ type: string; content?: string }>('/x', ev => seen.push(ev))
    expect(seen[0]?.content).toBe('中')
  })

  it('非 2xx 时抛出带状态码与后端 detail 的错误', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 429,
      json: async () => ({ detail: '并发已达上限' }),
    } as unknown as Response)
    await expect(runSSE('/x', () => {})).rejects.toThrow(/429.*并发已达上限/)
  })

  it('AbortSignal 取消时 fetch 抛出 AbortError', async () => {
    const ac = new AbortController()
    vi.mocked(fetch).mockImplementation((_u, init) => {
      return new Promise((_res, rej) => {
        init?.signal?.addEventListener('abort', () => {
          const e = new Error('aborted')
          e.name = 'AbortError'
          rej(e)
        })
      })
    })
    const p = runSSE('/x', () => {}, { signal: ac.signal })
    ac.abort()
    await expect(p).rejects.toThrow(/abort/i)
  })
})
