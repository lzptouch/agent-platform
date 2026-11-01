import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import ContextMeter from '../../../../apps/ui/src/components/ContextMeter.vue'

const sessionContext = vi.fn(async () => ({
  session_id: 's1',
  turns: 12,
  window: 128000,
  usage: { tokens: 40000, chars: 160000, ratio: 0.3125, token_limit: 108800 },
  thresholds: { compact: 0.7, summary: 0.85 },
}))

vi.mock('@/api', () => ({
  sessionContext: (...a: unknown[]) => sessionContext(...(a as [])),
}))

const globalPlugins = { global: { plugins: [ElementPlus] } }

describe('ContextMeter', () => {
  it('显示占用比', async () => {
    const w = mount(ContextMeter, { ...globalPlugins, props: { sessionId: 's1' } })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    expect(w.text()).toContain('31%')
  })

  it('可展开查看压缩事件', async () => {
    const events = [{ mode: 'contextSummary', before_tokens: 90000, after_tokens: 40000, saved_tokens: 50000 }]
    const w = mount(ContextMeter, { ...globalPlugins, props: { sessionId: 's1', events } })
    await w.vm.$nextTick()
    await w.find('.head').trigger('click')
    await w.vm.$nextTick()
    const text = w.text()
    expect(text).toContain('contextSummary')
    expect(text).toContain('90000')
    expect(text).toContain('50000')
  })

  it('无压缩事件时给出提示', async () => {
    const w = mount(ContextMeter, { ...globalPlugins, props: { sessionId: 's1' } })
    await w.vm.$nextTick()
    await w.find('.head').trigger('click')
    await w.vm.$nextTick()
    expect(w.text()).toContain('尚无压缩事件')
  })

  it('占用超阈值用告警色', async () => {
    sessionContext.mockResolvedValueOnce({
      session_id: 's1', turns: 30, window: 1000,
      usage: { tokens: 900, chars: 3600, ratio: 0.9 },
      thresholds: { compact: 0.7, summary: 0.85 },
    } as never)
    const w = mount(ContextMeter, { ...globalPlugins, props: { sessionId: 's1' } })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    expect(w.find('.fill.danger').exists()).toBe(true)
  })
})
