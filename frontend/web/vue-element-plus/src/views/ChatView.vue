<template>
  <div class="chat-view">
    <div class="chat-header">
      <div class="header-left">
        <el-button size="small" @click="drawerVisible = true">
          <el-icon><List /></el-icon>&nbsp;会话
        </el-button>
        <el-segmented
          :model-value="'chat'"
          :options="[{ label: '对话模式', value: 'chat' }, { label: '工作模式', value: 'work' }]"
          @change="(v: string) => v === 'work' && $router.push('/work')"
        />
        <span v-if="currentTitle" class="session-title">{{ currentTitle }}</span>
      </div>
      <div class="header-right">
        <el-select v-model="config.model" placeholder="选择模型" size="default" style="width: 220px">
          <el-option v-for="m in config.models?.models ?? []" :key="m.id" :label="`${m.name} · ${m.provider}`" :value="m.id" />
        </el-select>
      </div>
    </div>

    <el-alert v-if="config.banner" :title="config.banner" type="warning" :closable="false" show-icon style="margin: 12px 0" />

    <div class="chat-scroll" ref="scrollEl">
      <div class="chat-inner">
        <div v-if="!messages.length" class="welcome">
          <el-card shadow="never">
            <h3>对话模式（Ask）</h3>
            <p class="hint">只聊不动手：支持多轮上下文、本地文档与网络检索；需要写文件/执行代码时请切换到「工作模式」。</p>
            <div class="suggestions">
              <el-button v-for="s in suggestions" :key="s.title" @click="applySuggestion(s)">
                {{ s.title }}
              </el-button>
            </div>
          </el-card>
        </div>

        <ChatMessage v-for="(m, i) in messages" :key="i" :message="m" :skills-list="config.skills" />
      </div>
    </div>

    <div class="chat-input">
      <el-input
        v-model="prompt"
        type="textarea"
        :rows="3"
        placeholder="问点什么… Enter 发送，Shift+Enter 换行"
        @keydown="onKeydown"
      />
      <div class="input-actions">
        <el-button v-if="!running" type="primary" :disabled="!prompt.trim()" @click="send">发送</el-button>
        <el-button v-else type="danger" @click="stop">停止</el-button>
      </div>
    </div>

    <el-drawer v-model="drawerVisible" title="对话会话" size="300px">
      <el-button type="primary" size="small" style="width: 100%; margin-bottom: 12px" @click="onNewSession">新建会话</el-button>
      <div
        v-for="s in sessionStore.sessions"
        :key="s.id"
        class="session-item"
        :class="{ active: s.id === sessionStore.currentSessionId }"
        @click="onSelectSession(s.id)"
      >
        <span class="session-name">{{ s.title || '未命名会话' }}</span>
        <span class="session-meta">{{ s.message_count }} 条</span>
        <el-button
          size="small" text type="danger" class="session-del"
          @click.stop="onRemoveSession(s.id)"
        >删除</el-button>
      </div>
      <el-empty v-if="!sessionStore.sessions.length" description="暂无会话" :image-size="60" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted } from 'vue'
import { List } from '@element-plus/icons-vue'
import { useConfigStore } from '@/stores/config'
import { useSessionStore } from '@/stores/session'
import { streamAgent } from '@/api/sse'
import { sessionDetail } from '@/api'
import { Endpoints } from '@/api/endpoints'
import type { AgentEvent } from '@/api/types'
import ChatMessage from '@/components/ChatMessage.vue'

interface ChatMessage {
  role: 'user' | 'assistant'
  content?: string
  steps: ProcessStep[]
  texts: string[]
  skills: string[]
  allSkills: string[]
  thinking: string
  files: Array<{ name: string; size: number; is_image: boolean }>
  done: boolean
  error: string
  running: boolean
  stepSeq: number
}

interface ProcessStep {
  step_id: number
  kind: 'tool' | 'plan'
  tool_name?: string
  tool_input?: string
  tool_source?: string
  mcp_server?: string | null
  result?: string
  references?: string
  reference_cards?: import('@/api/types').ReferenceCard[]
  title?: string
  text?: string
}

const config = useConfigStore()
const sessionStore = useSessionStore()
const prompt = ref('')
const running = ref(false)
const messages = ref<ChatMessage[]>([])
const scrollEl = ref<HTMLDivElement>()
const drawerVisible = ref(false)
let ctl: AbortController | null = null

const suggestions = [
  { title: '查天气', mcp: true, prompt: '查一下北京今天的天气' },
  { title: '本地文档检索', rag: true, prompt: '总结一下 data/pdf/ 里的内容' },
  { title: '网络检索', web: true, prompt: '查一下最近的 AI 新闻' },
]

const currentTitle = computed(() => {
  const s = sessionStore.sessions.find(x => x.id === sessionStore.currentSessionId)
  return s?.title || ''
})

onMounted(async () => {
  config.init()
  sessionStore.mode = 'chat'
  await sessionStore.loadSessions()
  if (sessionStore.currentSessionId) {
    await loadHistory(sessionStore.currentSessionId)
  }
})

async function loadHistory(sessionId: string) {
  try {
    const detail = await sessionDetail(sessionId)
    messages.value = detail.messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => m.role === 'user'
        ? { role: 'user', content: m.content } as ChatMessage
        : {
            role: 'assistant', steps: [], texts: [m.content], skills: [], allSkills: [],
            thinking: '', files: m.files as ChatMessage['files'], done: true,
            error: String(m.meta?.error ?? ''), running: false, stepSeq: 0,
          } as ChatMessage)
    scrollToBottom()
  } catch {
    sessionStore.currentSessionId = null
  }
}

function applySuggestion(s: typeof suggestions[number]) {
  prompt.value = s.prompt
  if (s.mcp) config.enableMcp = true
  if (s.rag) config.enableRag = true
  if (s.web) config.enableWeb = true
  send()
}

async function onNewSession() {
  messages.value = []
  const sess = await sessionStore.newSession()
  sessionStore.selectSession(sess.id)
  drawerVisible.value = false
}

async function onSelectSession(id: string) {
  sessionStore.selectSession(id)
  drawerVisible.value = false
  await loadHistory(id)
}

async function onRemoveSession(id: string) {
  await sessionStore.removeSession(id)
  if (!sessionStore.currentSessionId) messages.value = []
}

function scrollToBottom() {
  nextTick(() => {
    const el = scrollEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function newAssistantMsg(): ChatMessage {
  return {
    role: 'assistant',
    steps: [],
    texts: [],
    skills: [],
    allSkills: [],
    thinking: '',
    files: [],
    done: false,
    error: '',
    running: true,
    stepSeq: 0,
  }
}

async function send() {
  const text = prompt.value.trim()
  if (!text || running.value) return

  // 无会话时自动创建
  if (!sessionStore.currentSessionId) {
    const sess = await sessionStore.newSession()
    sessionStore.selectSession(sess.id)
  }
  const sessionId = sessionStore.currentSessionId

  messages.value.push({ role: 'user', content: text } as ChatMessage)
  // 必须 reactive：否则流式事件对原始对象的修改不会触发子组件更新
  const assistant = reactive(newAssistantMsg())
  messages.value.push(assistant)
  prompt.value = ''
  running.value = true
  scrollToBottom()

  ctl = new AbortController()
  try {
    if ((window as unknown as { __sseDebug?: boolean }).__sseDebug) console.log('[send] start, session:', sessionId)
    await streamAgent(Endpoints.agentRun, {
      prompt: text,
      model: config.model,
      mode: 'chat',
      session_id: sessionId,
      // chat 模式默认不注入 Skill（null 由后端解释为 []）；
      // 仅当用户显式调整过 Skill 选择（有 localStorage 记录）才注入
      skills: localStorage.getItem('ap-vue-ep-skills') !== null ? config.selectedSkills : null,
      enable_mcp: config.enableMcp,
      mcp_servers: config.enableMcp ? config.selectedServers : [],
      enable_rag: config.enableRag,
      enable_web_research: config.enableWeb,
      enable_reflection: config.enableReflection,
    }, (ev) => appendEvent(assistant, ev), ctl.signal)
    if (sessionId) sessionStore.touchSession(sessionId)
  } catch (e: unknown) {
    if ((e as { name?: string }).name !== 'AbortError') {
      assistant.error = (e as Error).message ?? String(e)
    }
  } finally {
    if ((window as unknown as { __sseDebug?: boolean }).__sseDebug) {
      console.log('[send] finally, texts:', assistant.texts.length, 'done:', assistant.done)
    }
    running.value = false
    assistant.running = false
    scrollToBottom()
  }
}

function stop() {
  ctl?.abort()
  running.value = false
}

function appendEvent(a: ChatMessage, ev: AgentEvent) {
  switch (ev.type) {
    case 'meta':
      // 记录后端分配的会话（自动创建场景）
      if (ev.session_id && ev.session_id !== sessionStore.currentSessionId) {
        sessionStore.selectSession(ev.session_id)
        sessionStore.loadSessions()
      }
      break
    case 'notice':
      a.steps.push({ step_id: ++a.stepSeq, kind: 'plan', title: '提示', text: ev.content })
      break
    case 'skills_selected':
      a.skills = ev.skills
      a.allSkills = ev.all_skills
      break
    case 'system_prompt':
      ;(a as unknown as { systemPrompt: string }).systemPrompt = ev.content
      break
    case 'user_input':
      break
    case 'round_start':
      a.steps.push({ step_id: ++a.stepSeq, kind: 'plan', title: `第 ${ev.round} 轮`, text: '' })
      break
    case 'round_input':
      a.steps.push({ step_id: ++a.stepSeq, kind: 'plan', title: '上下文快照', text: ev.messages.map(m => `[${m.index}] ${m.role}: ${m.preview}`).join('\n') })
      break
    case 'reflection_start':
      a.steps.push({ step_id: ++a.stepSeq, kind: 'plan', title: '反思模式', text: `mode=${ev.mode}` })
      break
    case 'plan':
    case 'reflection_plan':
      a.steps.push({
        step_id: ++a.stepSeq,
        kind: 'plan',
        title: ev.type === 'plan' ? 'Plan（任务规划）' : 'Reflection（反思补充）',
        text: (ev.actions ?? []).map((act, i) => `#${i + 1} ${act.tool ?? '?'}: ${typeof act.input === 'string' ? act.input : JSON.stringify(act.input ?? {})}`).join('\n') || '（无需工具调用）',
      })
      break
    case 'model_text':
      a.texts.push(ev.content)
      break
    case 'reasoning_delta':
      a.thinking += ev.content
      break
    case 'tool_call': {
      a.steps.push({
        step_id: ++a.stepSeq,
        kind: 'tool',
        tool_name: ev.tool_name,
        tool_input: ev.tool_input,
        tool_source: ev.tool_source ?? 'builtin',
        mcp_server: ev.mcp_server ?? null,
      })
      break
    }
    case 'tool_result': {
      for (let i = a.steps.length - 1; i >= 0; i--) {
        const s = a.steps[i]
        if (s.kind === 'tool' && s.tool_name === ev.tool_name && s.result === undefined) {
          s.result = ev.result + (ev.result.length >= 2000 ? '\n\n⚠️ 服务端已截断到 2000 字符' : '')
          if (ev.references) s.references = ev.references
          if (ev.reference_cards) s.reference_cards = ev.reference_cards
          break
        }
      }
      break
    }
    case 'files':
      a.files = ev.files
      break
    case 'error':
      a.error = ev.content
      a.running = false
      break
    case 'done':
      a.done = true
      a.running = false
      break
  }
  scrollToBottom()
}
</script>

<style scoped>
.chat-view { display: flex; flex-direction: column; height: 100%; }
.chat-header { display: flex; justify-content: space-between; align-items: center; padding: 16px 24px; border-bottom: 1px solid var(--border); }
.header-left { display: flex; align-items: center; gap: 12px; }
.session-title { color: var(--text-dim); font-size: 13px; }
.chat-scroll { flex: 1; overflow-y: auto; padding: 16px 24px; }
.chat-inner { max-width: 880px; margin: 0 auto; }
.welcome :deep(.el-card) { background: var(--bg-sidebar); border: 1px solid var(--border); }
.welcome h3 { margin: 0 0 4px; }
.hint { color: var(--text-dim); margin: 0 0 16px; }
.suggestions { display: flex; gap: 8px; flex-wrap: wrap; }
.chat-input { padding: 12px 24px 18px; border-top: 1px solid var(--border); background: var(--bg); }
.input-actions { margin-top: 8px; display: flex; justify-content: flex-end; }
.session-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 6px; cursor: pointer; }
.session-item:hover { background: var(--bg-sidebar); }
.session-item.active { background: var(--bg-sidebar); outline: 1px solid var(--accent); }
.session-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.session-meta { color: var(--text-dim); font-size: 12px; }
.session-del { padding: 0 4px; }
</style>
