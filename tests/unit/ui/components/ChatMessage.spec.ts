import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'

import ChatMessage from '../../../../apps/ui/src/components/ChatMessage.vue'

const globalPlugins = { global: { plugins: [ElementPlus] } }

describe('ChatMessage 耗时三态（S8 / WP-8.2）', () => {
  it('进行中显示动态耗时', () => {
    const msg = {
      role: 'assistant' as const,
      running: true,
      startedAt: Date.now() - 2500,
    }
    const w = mount(ChatMessage, { ...globalPlugins, props: { message: msg } })
    expect(w.text()).toContain('正在生成')
    expect(w.text()).toMatch(/\d+(\.\d+)?s|ms/)
  })

  it('完成后耗时定格', () => {
    const startedAt = 1000000
    const finishedAt = startedAt + 3200
    const msg = {
      role: 'assistant' as const,
      done: true,
      running: false,
      startedAt,
      finishedAt,
    }
    const w = mount(ChatMessage, { ...globalPlugins, props: { message: msg } })
    expect(w.text()).toContain('已完成')
    expect(w.text()).toContain('3.2s')
  })

  it('失败时显示错误与时长', () => {
    const startedAt = 1000000
    const finishedAt = startedAt + 1500
    const msg = {
      role: 'assistant' as const,
      error: '运行失败',
      running: false,
      startedAt,
      finishedAt,
    }
    const w = mount(ChatMessage, { ...globalPlugins, props: { message: msg } })
    expect(w.text()).toContain('运行失败')
    expect(w.text()).toContain('1.5s')
  })

  it('无时间戳时不显示耗时', () => {
    const msg = { role: 'assistant' as const, done: true }
    const w = mount(ChatMessage, { ...globalPlugins, props: { message: msg } })
    expect(w.text()).toContain('已完成')
    expect(w.text()).not.toMatch(/\(\d/)
  })
})
