/**
 * HTTP 客户端单测（阶段 0 基建 + 缺陷回归）。
 *
 * 覆盖：
 *  1. 204 No Content 不抛 JSON 解析错（DELETE 类接口回归）
 *  2. 空响应体返回 null
 *  3. 正常 JSON 解析
 *  4. 统一错误体归一（detail 提取 + 状态码分类）
 *  5. 503 未配置服务 → 明确文案
 *  6. 超时 → ApiError(0)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { request, get, del } from '../../../../apps/ui/src/api/client'
import { ApiError } from '../../../../apps/ui/src/api/types'

function jsonResp(status: number, body: unknown, ok = status < 400): Response {
  return {
    ok,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
  } as unknown as Response
}

function emptyResp(status: number): Response {
  return {
    ok: status < 400,
    status,
    json: async () => { throw new SyntaxError('Unexpected end of JSON input') },
    text: async () => '',
  } as unknown as Response
}

describe('api/client', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
  afterEach(() => vi.unstubAllGlobals())

  it('204 No Content 返回 null 而不抛解析错', async () => {
    vi.mocked(fetch).mockResolvedValue(emptyResp(204))
    await expect(del('/api/v1/teams/abc')).resolves.toBeNull()
  })

  it('空响应体（200）返回 null', async () => {
    vi.mocked(fetch).mockResolvedValue(emptyResp(200))
    await expect(get('/api/v1/files')).resolves.toBeNull()
  })

  it('正常 JSON 被解析', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResp(200, { total: 3, files: [] }))
    await expect(get('/api/v1/files')).resolves.toEqual({ total: 3, files: [] })
  })

  it('错误响应提取 detail 并归一状态码', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResp(422, { detail: [{ msg: 'bad' }] }, false))
    await expect(request('/api/v1/x', { method: 'POST', body: {} })).rejects.toBeInstanceOf(ApiError)
  })

  it('503 未配置服务给出明确文案', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResp(503, { detail: '未配置 SERPER_API_KEY' }, false))
    try {
      await request('/api/v1/web_research/research', { method: 'POST', body: {} })
      expect.fail('应抛出 ApiError')
    } catch (e) {
      const err = e as ApiError
      expect(err.status).toBe(503)
      expect(err.message).toContain('服务未配置')
    }
  })

  it('超时被归一为 ApiError(0)', async () => {
    vi.mocked(fetch).mockImplementation(() => new Promise((_r, rej) => {
      setTimeout(() => {
        const e = new Error('aborted')
        e.name = 'TimeoutError'
        rej(e)
      }, 5)
    }))
    await expect(request('/api/v1/slow', { timeoutMs: 1 })).rejects.toMatchObject({ status: 0 })
  })
})
