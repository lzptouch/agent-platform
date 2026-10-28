import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import RoundGroup from './RoundGroup.vue'
import { useRoundsStore } from '@/stores/rounds'

const globalPlugins = { global: { plugins: [ElementPlus] } }

const steps = [
  { step_id: 1, kind: 'tool' as const, tool_name: 'read_file', tool_input: '{}' },
]

describe('RoundGroup（批次 02：轮次折叠接线）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('默认展开，显示轮次号与摘要', () => {
    const w = mount(RoundGroup, {
      ...globalPlugins,
      props: { runId: 'run-1', round: 2, summary: '读取了 3 个文件', steps },
    })
    expect(w.text()).toContain('第 2 轮')
    expect(w.text()).toContain('读取了 3 个文件')
    expect(w.find('.steps').exists()).toBe(true)
  })

  it('折叠态下只显示标题（内容收起）', async () => {
    const rounds = useRoundsStore()
    rounds.collapseRound('run-1', 2)

    const w = mount(RoundGroup, {
      ...globalPlugins,
      props: { runId: 'run-1', round: 2, summary: '摘要', steps },
    })
    // v-show → 元素在 DOM 中但不可见
    const body = w.find('.rg-body')
    expect(body.exists()).toBe(true)
    expect(body.attributes('style')).toContain('display: none')
  })

  it('点击标题切换折叠态（写回 rounds store）', async () => {
    const rounds = useRoundsStore()
    const w = mount(RoundGroup, {
      ...globalPlugins,
      props: { runId: 'run-1', round: 3, summary: 'x', steps },
    })
    expect(rounds.isCollapsed('run-1', 3)).toBe(false)
    await w.find('.rg-head').trigger('click')
    expect(rounds.isCollapsed('run-1', 3)).toBe(true)
    await w.find('.rg-head').trigger('click')
    expect(rounds.isCollapsed('run-1', 3)).toBe(false)
  })

  it('无步骤时不渲染', () => {
    const w = mount(RoundGroup, {
      ...globalPlugins,
      props: { runId: 'run-1', round: 1, summary: '', steps: [] },
    })
    expect(w.find('.round-group').exists()).toBe(false)
  })
})
