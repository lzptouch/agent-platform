/**
 * 会话 store：模式（chat/work）+ 会话列表 + 当前会话。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  sessionsList, sessionCreate, sessionUpdate, sessionDelete,
} from '@/api'
import type { AgentMode, Session } from '@/api/types'

const MODE_KEY = 'ap-vue-ep-mode'
const SESSION_KEY = 'ap-vue-ep-session'

export const useSessionStore = defineStore('session', () => {
  const mode = ref<AgentMode>('chat')
  const sessions = ref<Session[]>([])
  const currentSessionId = ref<string | null>(null)
  const loading = ref(false)

  try {
    const savedMode = localStorage.getItem(MODE_KEY)
    if (savedMode === 'chat' || savedMode === 'work') mode.value = savedMode
    currentSessionId.value = localStorage.getItem(SESSION_KEY) || null
  } catch { /* */ }

  function persist() {
    try {
      localStorage.setItem(MODE_KEY, mode.value)
      if (currentSessionId.value) localStorage.setItem(SESSION_KEY, currentSessionId.value)
      else localStorage.removeItem(SESSION_KEY)
    } catch { /* */ }
  }

  async function loadSessions() {
    loading.value = true
    try {
      const resp = await sessionsList({ mode: mode.value, page_size: 50 })
      sessions.value = resp.items
    } finally {
      loading.value = false
    }
  }

  async function switchMode(next: AgentMode) {
    if (next === mode.value) return
    mode.value = next
    currentSessionId.value = null
    persist()
    await loadSessions()
  }

  async function newSession(): Promise<Session> {
    const sess = await sessionCreate({ mode: mode.value })
    sessions.value = [sess, ...sessions.value]
    currentSessionId.value = sess.id
    persist()
    return sess
  }

  function selectSession(id: string) {
    currentSessionId.value = id
    persist()
  }

  async function renameSession(id: string, title: string) {
    await sessionUpdate(id, { title })
    const s = sessions.value.find(x => x.id === id)
    if (s) s.title = title
  }

  async function removeSession(id: string) {
    await sessionDelete(id)
    sessions.value = sessions.value.filter(x => x.id !== id)
    if (currentSessionId.value === id) {
      currentSessionId.value = null
      persist()
    }
  }

  function touchSession(id: string) {
    const s = sessions.value.find(x => x.id === id)
    if (s) {
      s.updated_at = new Date().toISOString()
      s.message_count += 2
      sessions.value = [s, ...sessions.value.filter(x => x.id !== id)]
    }
  }

  return {
    mode, sessions, currentSessionId, loading,
    loadSessions, switchMode, newSession, selectSession, renameSession, removeSession, touchSession,
  }
})
