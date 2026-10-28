import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import SideNav from './SideNav.vue'

const routerPush = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/workspace', query: {} }),
  useRouter: () => ({ push: routerPush }),
}))

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => ({
    tasks: [],
    spaces: [],
    currentTaskId: null,
    sidebarCollapsed: false,
    toggleSidebar: () => {},
    selectTask: () => {},
  }),
}))

const globalPlugins = { global: { plugins: [ElementPlus] } }

function labels(w: ReturnType<typeof mount>): string[] {
  return w.findAll('.nav-item').map((b) => b.text().trim())
}

describe('SideNav 统一导航（S8：侧栏恒定）', () => {
  it('workspace 与 admin 两种变体渲染完全相同的导航项', () => {
    const a = mount(SideNav, { ...globalPlugins, props: { variant: 'workspace' } })
    const b = mount(SideNav, { ...globalPlugins, props: { variant: 'admin' } })
    expect(labels(b)).toEqual(labels(a))
    expect(labels(a).length).toBeGreaterThanOrEqual(10)
  })

  it('导航项含助理与项目入口', () => {
    const w = mount(SideNav, { ...globalPlugins, props: { variant: 'workspace' } })
    const text = labels(w).join('|')
    expect(text).toContain('助理')
    expect(text).toContain('项目')
  })

  it('旧版入口已移除（v3 工作台为唯一形态）', () => {
    const w = mount(SideNav, { ...globalPlugins, props: { variant: 'workspace' } })
    const text = labels(w)
    expect(text).not.toContain('对话（旧）')
    expect(text).not.toContain('工作（旧）')
  })

  it('点击导航项走路由', async () => {
    const w = mount(SideNav, { ...globalPlugins, props: { variant: 'workspace' } })
    await w.findAll('.nav-item')[1].trigger('click')
    expect(routerPush).toHaveBeenCalledWith('/assistant')
  })
})
