import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// 会话列表只走接口，不走本地存储（假空间落盘已移除）
vi.mock('@/api', () => ({
  sessionsList: vi.fn(async () => ({ items: [], total: 0 })),
  sessionCreate: vi.fn(async () => ({
    id: 's1', mode: 'chat', title: '', message_count: 0,
    created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z',
  })),
}))

import { useWorkspaceStore } from './workspace'

describe('workspace store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('空间分组不读 localStorage（无假数据）', async () => {
    const getSpy = vi.spyOn(Storage.prototype, 'getItem')
    const setSpy = vi.spyOn(Storage.prototype, 'setItem')
    const ws = useWorkspaceStore()
    await ws.loadTasks()
    ws.assignSpace('s1', null)
    ws.ensureSpace('测试空间')
    expect(getSpy).not.toHaveBeenCalled()
    expect(setSpy).not.toHaveBeenCalled()
  })

  it('空间创建仅在内存（刷新后不残留）', () => {
    const ws = useWorkspaceStore()
    const sp = ws.ensureSpace('内存空间')
    expect(sp.id).toBeTruthy()
    expect(ws.spaces.some(s => s.id === sp.id)).toBe(true)
    expect(localStorage.getItem('__ws_spaces')).toBeNull()
  })
})
