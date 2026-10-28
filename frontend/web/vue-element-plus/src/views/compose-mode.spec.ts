import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// —— 依赖打桩：视图挂载即会拉配置 / 任务 / 文件 ——
vi.mock('@/api', () => ({
  filesList: vi.fn(async () => ({ files: [] })),
  filesUpload: vi.fn(async () => ({ name: 'x.txt', size: 1, url: '/api/v1/files/x.txt' })),
  sessionDetail: vi.fn(async () => ({ messages: [] })),
  sessionUpdate: vi.fn(async () => ({})),
  sessionDelete: vi.fn(async () => ({})),
  sessionCreate: vi.fn(async () => ({ id: 'sess-1', title: '', mode: 'chat' })),
  sessionsList: vi.fn(async () => ({ items: [], total: 0 })),
  runApprove: vi.fn(async () => ({})),
  runReject: vi.fn(async () => ({})),
  runDetail: vi.fn(async () => ({ id: 'run-1', session_id: 'sess-1' })),
  runsByStatus: vi.fn(async () => ({ items: [], total: 0 })),
  agentModels: vi.fn(async () => ({ models: [] })),
  agentStatus: vi.fn(async () => ({ status: 'ok' })),
  skillsList: vi.fn(async () => ({ skills: [] })),
  mcpList: vi.fn(async () => ({ servers: [] })),
  costEstimate: vi.fn(async () => ({ percentiles: { p50: null, p90: null, samples: 0 }, pricing: [] })),
  runCost: vi.fn(async () => ({ items: [], totals: {}, percentiles: {}, pricing: [] })),
  sessionContext: vi.fn(async () => ({ usage: {}, thresholds: {} })),
  permissionRules: vi.fn(async () => ({ rules: [], effective_level: 'ask' })),
  permissionPending: vi.fn(async () => ({ items: [] })),
  permissionDecisions: vi.fn(async () => ({ items: [] })),
  permissionResolve: vi.fn(async () => ({})),
  permissionRuleDelete: vi.fn(async () => ({})),
  permissionRuleSet: vi.fn(async () => ({})),
  permissionSandbox: vi.fn(async () => ({ level: 'policy_only', available: true, message: '' })),
}))

// —— 路由打桩：``useRoute()`` 读的是模块，不是 $route ——
let currentQuery: Record<string, string> = {}
vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => routeStub(currentQuery),
    useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  }
})
vi.mock('@/api/sse', () => ({
  streamAgent: vi.fn(async () => undefined),
  runSSE: vi.fn(async () => undefined),
}))
vi.mock('@/api/desktop', () => ({
  runCancel: vi.fn(async () => ({})),
  runSteer: vi.fn(async () => ({})),
}))

import WorkspaceView from './WorkspaceView.vue'
import WorkspaceLayout from '@/layouts/WorkspaceLayout.vue'

const globalPlugins = { global: { plugins: [ElementPlus] } }

/** 造一个带 query 的路由桩。 */
function routeStub(query: Record<string, string>) {
  return {
    query,
    params: {},
    path: '/workspace',
    fullPath: `/workspace?${new URLSearchParams(query).toString()}`,
    name: undefined,
    hash: '',
    matched: [],
    meta: {},
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    go: vi.fn(),
    resolve: vi.fn(),
    beforeEach: vi.fn(),
    afterEach: vi.fn(),
  }
}

describe('速记形态（批次 02：?compose=1）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    currentQuery = {}
  })

  it('compose=1 时不渲染对话流与右栏，只留输入区', async () => {
    currentQuery = { compose: '1' }
    const w = mount(WorkspaceView, globalPlugins)
    await w.vm.$nextTick()

    expect(w.find('.ws-scroll').exists()).toBe(false)
    expect(w.find('.ws-head').exists()).toBe(false)
    expect(w.find('.composer').exists()).toBe(true)
    expect(w.classes()).toContain('compose-mode')
  })

  it('普通形态仍渲染对话流', async () => {
    currentQuery = {}
    const w = mount(WorkspaceView, globalPlugins)
    await w.vm.$nextTick()

    expect(w.find('.ws-scroll').exists()).toBe(true)
    expect(w.classes()).not.toContain('compose-mode')
  })

  it('布局在 compose=1 时隐藏侧栏', async () => {
    currentQuery = { compose: '1' }
    const w = mount(WorkspaceLayout, {
      ...globalPlugins,
      global: {
        ...globalPlugins.global,
        plugins: [ElementPlus],
        stubs: { RouterView: true, 'router-view': true },
      },
    })
    await w.vm.$nextTick()

    expect(w.find('.side-nav').exists()).toBe(false)
  })
})
