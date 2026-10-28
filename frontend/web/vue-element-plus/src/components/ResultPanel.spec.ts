import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ResultPanel from './ResultPanel.vue'

vi.mock('@/api', () => ({
  runArtifacts: vi.fn(async () => ({ items: [] })),
  runChanges: vi.fn(async () => ({ items: [] })),
  changeDiff: vi.fn(async () => ({ kind: 'text', diff: '' })),
  changeRevert: vi.fn(async () => ({ reverted: 'x' })),
}))

const globalPlugins = { global: { plugins: [ElementPlus] } }

// 折叠持久化会写 localStorage → 每个用例前清理，避免状态串扰；
// 同时把视口设宽（jsdom 默认 1024 会触发窄屏自动折叠，干扰断言）
beforeEach(() => {
  localStorage.clear()
  Object.defineProperty(window, 'innerWidth', { value: 1400, writable: true, configurable: true })
})

describe('ResultPanel（右栏四视图）', () => {
  it('四个 Tab 均可切换', async () => {
    const w = mount(ResultPanel, { ...globalPlugins, props: { runId: 'r1' } })
    const tabs = w.findAll('.tab').map((t) => t.text())
    expect(tabs).toEqual(['产物', '文件', '变更', '浏览器'])

    // 切换到变更
    await w.findAll('.tab')[2].trigger('click')
    expect(w.find('.result-changes').exists() || w.text().includes('暂无变更')).toBe(true)

    // 切换到浏览器（占位）
    await w.findAll('.tab')[3].trigger('click')
    expect(w.text()).toContain('浏览器视图')
  })

  it('无 runId 时产物视图为空态', async () => {
    const w = mount(ResultPanel, { ...globalPlugins, props: { runId: null } })
    await w.vm.$nextTick()
    expect(w.text()).toContain('暂无交付物')
  })

  it('可折叠/展开', async () => {
    const w = mount(ResultPanel, { ...globalPlugins, props: { runId: 'r1' } })
    expect(w.classes()).not.toContain('collapsed')
    await w.find('.collapse-btn').trigger('click')
    expect(w.classes()).toContain('collapsed')
  })

  it('折叠状态持久化（S8）', async () => {
    const w = mount(ResultPanel, { ...globalPlugins, props: { runId: 'r1' } })
    await w.find('.collapse-btn').trigger('click')
    expect(localStorage.getItem('__result_panel_collapsed')).toBe('1')
    // 重新挂载 → 读到持久化的折叠态
    const w2 = mount(ResultPanel, { ...globalPlugins, props: { runId: 'r1' } })
    expect(w2.classes()).toContain('collapsed')
  })
})
