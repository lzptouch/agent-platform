import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { defineComponent, h, ref } from 'vue'
import { describe, expect, it } from 'vitest'

import ComposerInput from './ComposerInput.vue'

const globalPlugins = { global: { plugins: [ElementPlus] } }

const baseProps = {
  modelValue: '',
  mode: 'chat' as const,
  model: 'qwen-plus',
}

/** 带 v-model 的外壳（组件内部通过 emit 更新文本）。 */
const Harness = defineComponent({
  setup() {
    const text = ref('')
    return () =>
      h(ComposerInput, {
        modelValue: text.value,
        mode: 'chat',
        model: 'qwen-plus',
        'onUpdate:modelValue': (v: string) => {
          text.value = v
        },
      })
  },
})

describe('ComposerInput（批次 02：附件与长粘贴折叠）', () => {
  it('渲染附件条目（名称 + 大小）', () => {
    const w = mount(ComposerInput, {
      ...globalPlugins,
      props: {
        ...baseProps,
        attachments: [{ name: 'report.pdf', size: 2048 }],
      },
    })
    expect(w.text()).toContain('report.pdf')
    expect(w.text()).toContain('2.0 KB')
  })

  it('点击附件的移除按钮抛出 remove-attachment 事件（带下标）', async () => {
    const w = mount(ComposerInput, {
      ...globalPlugins,
      props: {
        ...baseProps,
        attachments: [{ name: 'a.txt', size: 10 }, { name: 'b.txt', size: 20 }],
      },
    })
    const removeButtons = w.findAll('.att-remove')
    expect(removeButtons).toHaveLength(2)
    await removeButtons[1].trigger('click')
    expect(w.emitted('remove-attachment')?.[0]).toEqual([1])
  })

  it('无附件时不渲染附件区', () => {
    const w = mount(ComposerInput, { ...globalPlugins, props: baseProps })
    expect(w.find('.attachments').exists()).toBe(false)
  })

  it('粘贴超过 3000 字符 → 折叠为可展开条目', async () => {
    const w = mount(Harness, globalPlugins)
    const ta = w.find('textarea')
    const long = 'x'.repeat(3500)

    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', {
      value: { getData: () => long },
    })
    await ta.element.dispatchEvent(event)
    await w.vm.$nextTick()

    expect(w.find('.paste-fold').exists()).toBe(true)
    expect(w.text()).toContain('3500')
    // 输入区里只留折叠标记，不灌入全文
    expect((ta.element as HTMLTextAreaElement).value).not.toContain('x'.repeat(100))
    expect((ta.element as HTMLTextAreaElement).value).toContain('折叠粘贴内容')
  })

  it('展开后全文回到输入区', async () => {
    const w = mount(Harness, globalPlugins)
    const ta = w.find('textarea')
    const long = 'y'.repeat(3200)
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { getData: () => long } })
    await ta.element.dispatchEvent(event)
    await w.vm.$nextTick()

    await w.findAll('.pf-btn').find((b) => b.text() === '展开')?.trigger('click')
    await w.vm.$nextTick()
    expect((ta.element as HTMLTextAreaElement).value).toContain('y'.repeat(3200))
    expect(w.find('.paste-fold').exists()).toBe(false)
  })

  it('短文本粘贴不折叠', async () => {
    const w = mount(Harness, globalPlugins)
    const ta = w.find('textarea')
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { getData: () => 'hello' } })
    await ta.element.dispatchEvent(event)
    await w.vm.$nextTick()
    expect(w.find('.paste-fold').exists()).toBe(false)
  })
})
