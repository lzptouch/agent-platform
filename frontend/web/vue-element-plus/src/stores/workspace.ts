/**
 * 工作台 store（v3）：任务流 + 空间 + 工作区模式。
 *
 * 对应改造计划：
 *  - §2.4 A2 左栏常驻任务流
 *  - §2.4 A7 任务即会话、空间即文件夹
 *  - §8.1 Ask / Plan / Craft 三态
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { sessionsList, sessionCreate } from '@/api'
import type { Session } from '@/api/types'

/** 前端三态 → 后端参数映射（计划 §8.1） */
export type WorkspaceMode = 'chat' | 'plan' | 'work'

export const MODE_LABEL: Record<WorkspaceMode, string> = {
  chat: '对话',
  plan: '计划',
  work: '工作',
}

/** 计划（plan）模式对应后端 work + plan_first */
export function toBackend(mode: WorkspaceMode): { mode: 'chat' | 'work'; plan_first: boolean } {
  if (mode === 'chat') return { mode: 'chat', plan_first: false }
  if (mode === 'plan') return { mode: 'work', plan_first: true }
  return { mode: 'work', plan_first: false }
}

export interface Space {
  id: string
  name: string
  sessionIds: string[]
}

const SPACES_KEY = '__ws_spaces'

export const useWorkspaceStore = defineStore('workspace', () => {
  /** 全部任务（跨 chat/work 模式，不做 mode 过滤 —— 对齐 Trae/WorkBuddy 的统一任务流） */
  const tasks = ref<Session[]>([])
  const currentTaskId = ref<string | null>(null)
  const loading = ref(false)
  const mode = ref<WorkspaceMode>('chat')
  const sidebarCollapsed = ref(false)

  /** 空间分组（后端 spaces 接口未就绪，先用本地存储落地，接口就绪后切换） */
  const spaces = ref<Space[]>(readSpaces())

  function readSpaces(): Space[] {
    try {
      const raw = localStorage.getItem(SPACES_KEY)
      if (raw) {
        const arr = JSON.parse(raw) as Space[]
        if (Array.isArray(arr)) return arr
      }
    } catch { /* */ }
    return []
  }

  function persistSpaces() {
    try { localStorage.setItem(SPACES_KEY, JSON.stringify(spaces.value)) } catch { /* */ }
  }

  const ungrouped = computed(() => {
    const inSpace = new Set(spaces.value.flatMap(s => s.sessionIds))
    return tasks.value.filter(t => !inSpace.has(t.id))
  })

  async function loadTasks() {
    loading.value = true
    try {
      const resp = await sessionsList({ page_size: 100 })
      tasks.value = resp.items
    } finally {
      loading.value = false
    }
  }

  async function createTask(title?: string): Promise<Session> {
    const { mode: backendMode } = toBackend(mode.value)
    const sess = await sessionCreate({ mode: backendMode, title })
    tasks.value = [sess, ...tasks.value]
    currentTaskId.value = sess.id
    return sess
  }

  function selectTask(id: string | null) { currentTaskId.value = id }

  function setMode(next: WorkspaceMode) { mode.value = next }

  function toggleSidebar() { sidebarCollapsed.value = !sidebarCollapsed.value }

  function assignSpace(sessionId: string, spaceId: string | null) {
    spaces.value = spaces.value.map(s => ({
      ...s,
      sessionIds: s.sessionIds.filter(id => id !== sessionId),
    }))
    if (spaceId) {
      const hit = spaces.value.find(s => s.id === spaceId)
      if (hit) hit.sessionIds.push(sessionId)
    }
    persistSpaces()
  }

  function ensureSpace(name: string): Space {
    const found = spaces.value.find(s => s.name === name)
    if (found) return found
    const created: Space = { id: `sp_${Date.now().toString(36)}`, name, sessionIds: [] }
    spaces.value = [...spaces.value, created]
    persistSpaces()
    return created
  }

  return {
    tasks, currentTaskId, loading, mode, sidebarCollapsed, spaces, ungrouped,
    loadTasks, createTask, selectTask, setMode, toggleSidebar, assignSpace, ensureSpace,
  }
})
