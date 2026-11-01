import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import RunCostBar from '../../../../apps/ui/src/components/RunCostBar.vue'

const runCost = vi.fn(async () => ({
  items: [],
  totals: { llm_calls: 2, prompt_tokens: 1200, completion_tokens: 300, estimated_cost: 0.0021 },
  percentiles: { p50: 0.001, p90: 0.005, samples: 10 },
  pricing: [],
}))
const costEstimate = vi.fn(async () => ({
  percentiles: { p50: 0.001, p90: 0.005, samples: 10 },
  pricing: [],
}))

vi.mock('@/api', () => ({
  runCost: (...a: unknown[]) => runCost(...(a as [])),
  costEstimate: (...a: unknown[]) => costEstimate(...(a as [])),
}))

const globalPlugins = { global: { plugins: [ElementPlus] } }

describe('RunCostBar', () => {
  it('显示实际消耗与 token', async () => {
    const w = mount(RunCostBar, { ...globalPlugins, props: { runId: 'r1' } })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    const text = w.text()
    expect(text).toContain('$0.0021')
    expect(text).toContain('1500')
  })

  it('显示历史区间（p50~p90）', async () => {
    const w = mount(RunCostBar, { ...globalPlugins, props: { runId: 'r1' } })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    expect(w.text()).toContain('$0.0010')
    expect(w.text()).toContain('$0.0050')
  })

  it('运行中显示进行中', () => {
    const w = mount(RunCostBar, { ...globalPlugins, props: { runId: 'r1', running: true } })
    expect(w.text()).toContain('进行中')
  })

  it('无 runId 时不报错', () => {
    const w = mount(RunCostBar, { ...globalPlugins, props: { runId: null } })
    expect(w.find('.cost-bar').exists()).toBe(true)
  })
})
