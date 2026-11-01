/**
 * 会话 store 单测（阶段 0）。
 *
 * 覆盖 4 个关键行为：
 *  1. loadSessions 按 mode 过滤并写入列表
 *  2. newSession 创建后置顶并选中
 *  3. selectSession 持久化到 localStorage
 *  4. removeSession 删除当前会话时清空选中并移除 localStorage 键
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const sessionsList = vi.fn()
const sessionCreate = vi.fn()
const sessionUpdate = vi.fn()
const sessionDelete = vi.fn()

vi.mock('@/api', () => ({
  sessionsList: (...a: unknown[]) => sessionsList(...a),
  sessionCreate: (...a: unknown[]) => sessionCreate(...a),
  sessionUpdate: (...a: unknown[]) => sessionUpdate(...a),
  sessionDelete: (...a: unknown[]) => sessionDelete(...a),
}))

import { useSessionStore } from '../../../../apps/ui/src/stores/session'

const MODE_KEY = 'ap-vue-ep-mode'
const SESSION_KEY = 'ap-vue-ep-session'

describe('useSessionStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    sessionsList.mockReset()
    sessionCreate.mockReset()
    sessionUpdate.mockReset()
    sessionDelete.mockReset()
  })

  it('loadSessions 按 mode 过滤并写入列表', async () => {
    sessionsList.mockResolvedValue({ items: [{ id: 's1', title: 'A', message_count: 2 }], total: 1 })
    const st = useSessionStore()
    await st.loadSessions()
    expect(sessionsList).toHaveBeenCalledWith({ mode: 'chat', page_size: 50 })
    expect(st.sessions).toHaveLength(1)
    expect(st.sessions[0]?.title).toBe('A')
  })

  it('newSession 创建后置顶并选中', async () => {
    const created = { id: 's2', title: '', message_count: 0 }
    sessionCreate.mockResolvedValue(created)
    const st = useSessionStore()
    st.sessions = [{ id: 's1', title: '旧', message_count: 0 }] as never
    const got = await st.newSession()
    expect(got).toBe(created)
    expect(st.currentSessionId).toBe('s2')
    expect(st.sessions[0]?.id).toBe('s2')
    expect(localStorage.getItem(SESSION_KEY)).toBe('s2')
  })

  it('selectSession 持久化到 localStorage', () => {
    const st = useSessionStore()
    st.selectSession('s9')
    expect(st.currentSessionId).toBe('s9')
    expect(localStorage.getItem(SESSION_KEY)).toBe('s9')
  })

  it('removeSession 删除当前会话时清空选中并移除持久化键', async () => {
    sessionDelete.mockResolvedValue(undefined)
    const st = useSessionStore()
    st.sessions = [{ id: 's1', title: 'A', message_count: 0 }] as never
    st.selectSession('s1')
    await st.removeSession('s1')
    expect(st.sessions).toHaveLength(0)
    expect(st.currentSessionId).toBeNull()
    expect(localStorage.getItem(SESSION_KEY)).toBeNull()
  })

  it('switchMode 会重置当前会话并刷新列表', async () => {
    sessionsList.mockResolvedValue({ items: [], total: 0 })
    const st = useSessionStore()
    st.selectSession('s1')
    await st.switchMode('work')
    expect(st.mode).toBe('work')
    expect(st.currentSessionId).toBeNull()
    expect(localStorage.getItem(MODE_KEY)).toBe('work')
  })
})
