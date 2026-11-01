import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import PermissionCard from '../../../../apps/ui/src/components/PermissionCard.vue'

const globalPlugins = { global: { plugins: [ElementPlus] } }

vi.mock('@/api', () => ({
  permissionResolve: vi.fn(async () => ({ ok: true })),
}))

const baseItem = {
  id: 7,
  tool_name: 'write_file',
  reason: '工作区外路径',
  risk: 'elevated',
  target: 'C:/data/out.txt',
  created_at: '2026-10-27T00:00:00Z',
}

describe('PermissionCard', () => {
  it('显示工具、目标与理由', () => {
    const w = mount(PermissionCard, { ...globalPlugins, props: { item: baseItem } })
    const text = w.text()
    expect(text).toContain('write_file')
    expect(text).toContain('C:/data/out.txt')
    expect(text).toContain('工作区外路径')
  })

  it('四个选项可用（normal/elevated）', () => {
    const w = mount(PermissionCard, { ...globalPlugins, props: { item: baseItem } })
    const labels = w.findAll('button').map((b) => b.text())
    expect(labels).toContain('允许本次')
    expect(labels).toContain('本次会话允许')
    expect(labels).toContain('本工作空间允许')
    expect(labels).toContain('拒绝')
  })

  it('critical 风险不提供「本工作空间允许」（防误授权）', () => {
    const w = mount(PermissionCard, { ...globalPlugins, props: { item: { ...baseItem, risk: 'critical' } } })
    const labels = w.findAll('button').map((b) => b.text())
    expect(labels).not.toContain('本工作空间允许')
    expect(labels).toContain('拒绝')
  })

  it('倒计时展示', () => {
    const w = mount(PermissionCard, { ...globalPlugins, props: { item: { ...baseItem, timeout_s: 45 } } })
    expect(w.text()).toContain('45s')
  })

  it('决策后触发 resolved 事件', async () => {
    const w = mount(PermissionCard, { ...globalPlugins, props: { item: baseItem } })
    await w.findAll('button').find((b) => b.text() === '允许本次')?.trigger('click')
    expect(w.emitted('resolved')).toBeTruthy()
    expect(w.emitted('resolved')?.[0]).toEqual([7])
  })

  it('item 为空时不渲染', () => {
    const w = mount(PermissionCard, { ...globalPlugins, props: { item: null } })
    expect(w.find('.perm-card').exists()).toBe(false)
  })
})
