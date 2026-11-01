import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useRoundsStore } from '../../../../apps/ui/src/stores/rounds'

describe('rounds store（折叠状态，S8 / WP-8.3）', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('默认未折叠', () => {
    const r = useRoundsStore()
    expect(r.isCollapsed('run1', 0)).toBe(false)
  })

  it('run 结束自动折叠该轮', () => {
    const r = useRoundsStore()
    r.collapseRound('run1', 0)
    expect(r.isCollapsed('run1', 0)).toBe(true)
  })

  it('可切换展开（不丢原文）', () => {
    const r = useRoundsStore()
    r.collapseRound('run1', 0)
    r.toggle('run1', 0)
    expect(r.isCollapsed('run1', 0)).toBe(false)
    r.toggle('run1', 0)
    expect(r.isCollapsed('run1', 0)).toBe(true)
  })

  it('不同 run 互不影响', () => {
    const r = useRoundsStore()
    r.collapseRound('run1', 0)
    expect(r.isCollapsed('run2', 0)).toBe(false)
  })

  it('清理某 run 的折叠状态', () => {
    const r = useRoundsStore()
    r.collapseRound('run1', 0)
    r.collapseRound('run2', 0)
    r.clearRun('run1')
    expect(r.isCollapsed('run1', 0)).toBe(false)
    expect(r.isCollapsed('run2', 0)).toBe(true)
  })
})
