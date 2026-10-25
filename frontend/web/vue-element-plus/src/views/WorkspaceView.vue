<template>
  <div class="workspace">
    <!-- 轻量上下文栏 -->
    <header class="ws-head">
      <div class="head-left">
        <span class="title">{{ taskTitle || '新建任务' }}</span>
        <el-tag size="small" effect="plain" :type="mode === 'chat' ? 'success' : mode === 'plan' ? 'info' : 'primary'">
          {{ MODE_LABEL[mode] }}
        </el-tag>
        <el-tag v-if="runState !== 'idle'" size="small" :type="runState === 'running' ? 'primary' : 'warning'" effect="plain">
          {{ runStateLabel }}
        </el-tag>
      </div>
      <div class="head-right">
        <el-button size="small" text @click="newTask">
          <el-icon><Plus /></el-icon>&nbsp;新建任务
        </el-button>
        <el-button size="small" text @click="renameTask" :disabled="!currentSessionId">重命名</el-button>
        <el-button size="small" text @click="deleteTask" :disabled="!currentSessionId">删除</el-button>
      </div>
    </header>

    <!-- 对话流 -->
    <div ref="scrollEl" class="ws-scroll">
      <div class="ws-inner">
        <!-- 空态：居中大标题 + 场景/能力 Chip -->
        <div v-if="!messages.length" class="empty">
          <h1 class="hero">Agent Platform, 我帮你</h1>
          <p class="hero-sub">用自然语言下达任务，我会自主拆解、调用工具并交付结果。</p>
          <ContextChips
            :model="caps"
            :show-scenes="true"
            @toggle="toggleCap"
            @scene="onScene"
            @more="openCommand"
          />
        </div>

        <template v-else>
          <div v-for="(m, i) in messages" :key="i" class="msg-wrap">
            <ChatMessage v-if="m.role === 'user'" :message="m" />
            <template v-else>
              <RunTimeline :steps="m.steps" :running="m.running" />
              <ChatMessage :message="m" />
              <ArtifactStrip v-if="m.files?.length" :files="m.files" />
            </template>
          </div>
        </template>
      </div>
    </div>

    <!-- Plan 审批卡 -->
    <div v-if="approval" class="plan-slot">
      <PlanCard
        :plan="approval.plan"
        :status="approvalStatus"
        :approving="approving"
        @approve="onApprove"
        @reject="onReject"
      />
    </div>

    <!-- 错误提示条（计划 §8.7：异常不得清空输入） -->
    <div v-if="errorBanner" class="error-bar">
      <el-icon><Warning /></el-icon><span>{{ errorBanner }}</span>
      <el-button size="small" text @click="errorBanner = ''">关闭</el-button>
    </div>

    <!-- 输入区 -->
    <footer class="ws-composer">
      <div class="composer-wrap">
        <ContextChips
          v-if="messages.length"
          class="cap-chips"
          :model="caps"
          @toggle="toggleCap"
          @scene="onScene"
          @more="openCommand"
        />
        <ComposerInput
          v-model="prompt"
          :mode="mode"
          :model="config.model"
          :model-options="modelOptions"
          :disabled="disabled"
          :running="running"
          @update:mode="setMode"
          @update:model="v => (config.model = v)"
          @send="send"
          @stop="stop"
          @attach="openAt"
          @at="openAt"
          @slash="openCommand"
        />
        <ContextBar
          :workspace="workspaceName"
          :permissive="permissive"
          @workspace="workspaceName = ''"
          @toggle-permission="permissive = !permissive"
        />
      </div>
    </footer>

    <!-- 命令面板 / 上下文选择 -->
    <CommandPalette
      v-model="cmdVisible"
      :skills="config.skills"
      @run="onCommand"
    />
    <AtPicker
      v-model="atVisible"
      :sessions="ws.tasks"
      :skills="config.skills"
      :files="fileOptions"
      @pick="onAtPick"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Warning } from '@element-plus/icons-vue'
import ChatMessage from '@/components/ChatMessage.vue'
import RunTimeline from '@/components/RunTimeline.vue'
import ArtifactStrip from '@/components/ArtifactStrip.vue'
import PlanCard from '@/components/PlanCard.vue'
import ComposerInput from '@/components/composer/ComposerInput.vue'
import ContextChips from '@/components/composer/ContextChips.vue'
import ContextBar from '@/components/composer/ContextBar.vue'
import CommandPalette from '@/components/composer/CommandPalette.vue'
import AtPicker from '@/components/composer/AtPicker.vue'
import type { PlanStep, AtItem } from '@/types/workspace'
import { useConfigStore } from '@/stores/config'
import { useWorkspaceStore, MODE_LABEL, toBackend, type WorkspaceMode } from '@/stores/workspace'
import { useSessionStore } from '@/stores/session'
import { streamAgent, runSSE } from '@/api/sse'
import { Endpoints } from '@/api/endpoints'
import { sessionDetail, sessionUpdate, sessionDelete, filesList, runApprove, runReject } from '@/api'
import type { AgentEvent } from '@/api/types'

interface Step {
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

interface Msg {
  role: 'user' | 'assistant'
  content?: string
  steps: Step[]
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

const route = useRoute()
const router = useRouter()
const config = useConfigStore()
const ws = useWorkspaceStore()
const sessionStore = useSessionStore()

const messages = ref<Msg[]>([])
const scrollEl = ref<HTMLDivElement>()
const prompt = ref('')
const running = ref(false)
const approving = ref(false)
const errorBanner = ref('')
const cmdVisible = ref(false)
const atVisible = ref(false)
const workspaceName = ref('')
const permissive = ref(false)
const fileOptions = ref<Array<{ name: string; size?: number }>>([])

const caps = reactive<Record<string, boolean>>({ mcp: false, rag: true, web: false, reflection: false, research: false })

const approval = ref<{ run_id: string; plan: PlanStep[] } | null>(null)
const approvalStatus = ref<'pending' | 'approved' | 'rejected'>('pending')

const mode = computed<WorkspaceMode>(() => ws.mode)
const currentSessionId = computed(() => ws.currentTaskId)
const taskTitle = computed(() => {
  const t = ws.tasks.find(x => x.id === ws.currentTaskId)
  if (!t) return ''
  return t.title || '未命名任务'
})
const modelOptions = computed(() =>
  (config.models?.models ?? []).map(m => ({ id: m.id, name: m.name, provider: m.provider })),
)
const runState = computed(() => {
  if (approval.value && approvalStatus.value === 'pending') return 'awaiting_approval'
  if (running.value) return 'running'
  return 'idle'
})
const runStateLabel = computed(() => {
  if (runState.value === 'awaiting_approval') return '等待确认计划'
  if (runState.value === 'running') return '执行中'
  return ''
})
const disabled = computed(() => approval.value !== null && approvalStatus.value === 'pending')

let ctl: AbortController | null = null
/** 当前正在流式输出的助手消息（审批后续播复用） */
let currentAssistant: Msg | null = null

onMounted(async () => {
  if (!config.ready) await config.init()
  await ws.loadTasks()
  await loadFiles()
  applyQuery()
  if (ws.currentTaskId) await loadHistory(ws.currentTaskId)
})

watch(() => route.query.task, async v => {
  const id = typeof v === 'string' ? v : null
  if (id && id !== ws.currentTaskId) {
    ws.selectTask(id)
    await loadHistory(id)
  }
})
watch(() => route.query.mode, v => {
  const m = typeof v === 'string' ? v : ''
  if (m === 'chat' || m === 'plan' || m === 'work') ws.setMode(m as WorkspaceMode)
})

function applyQuery() {
  const m = route.query.mode
  if (typeof m === 'string' && ['chat', 'plan', 'work'].includes(m)) ws.setMode(m as WorkspaceMode)
  const t = route.query.task
  if (typeof t === 'string') ws.selectTask(t)
}

function setMode(next: WorkspaceMode) {
  ws.setMode(next)
  router.replace({ path: '/workspace', query: { ...route.query, mode: next } })
  // 会话 mode 与目标模式冲突时（chat 会话 → plan/work）需新建任务：
  // 后端 session 绑定 mode，chat 会话不支持计划审批。
  const need = toBackend(next).mode
  const cur = ws.tasks.find(t => t.id === ws.currentTaskId)
  if (cur && cur.mode !== need) void newTask()
}

async function loadFiles() {
  try {
    const r = await filesList()
    fileOptions.value = r.files.map(f => ({ name: f.name, size: f.size }))
  } catch { fileOptions.value = [] }
}

async function loadHistory(sessionId: string) {
  try {
    const detail = await sessionDetail(sessionId)
    messages.value = detail.messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => m.role === 'user'
        ? { role: 'user', content: m.content } as Msg
        : {
            role: 'assistant', steps: [], texts: [m.content], skills: [], allSkills: [],
            thinking: '', files: (m.files ?? []) as Msg['files'], done: true,
            error: String(m.meta?.error ?? ''), running: false, stepSeq: 0,
          } as Msg)
    scrollToBottom()
  } catch {
    messages.value = []
  }
}

function newMsg(): Msg {
  return {
    role: 'assistant', steps: [], texts: [], skills: [], allSkills: [],
    thinking: '', files: [], done: false, error: '', running: true, stepSeq: 0,
  }
}

async function send() {
  const text = prompt.value.trim()
  if (!text || running.value) return
  errorBanner.value = ''

  let sessionId = ws.currentTaskId
  const { mode: backendMode, plan_first } = toBackend(mode.value)
  if (!sessionId) {
    // 会话 mode 必须与本次运行模式一致（chat 会话不能走计划审批）
    const sess = await sessionStore.newSession(backendMode)
    sessionId = sess.id
    ws.selectTask(sess.id)
    ws.tasks = [sess, ...ws.tasks]
    router.replace({ path: '/workspace', query: { ...route.query, task: sess.id, mode: mode.value } })
  } else {
    // 已有会话但模式不匹配 → 换新会话
    const cur = ws.tasks.find(t => t.id === sessionId)
    if (cur && cur.mode !== backendMode) {
      const sess = await sessionStore.newSession(backendMode)
      sessionId = sess.id
      ws.selectTask(sess.id)
      ws.tasks = [sess, ...ws.tasks]
      router.replace({ path: '/workspace', query: { ...route.query, task: sess.id, mode: mode.value } })
    }
  }

  messages.value.push({ role: 'user', content: text } as Msg)
  const assistant = reactive(newMsg())
  currentAssistant = assistant
  messages.value.push(assistant)
  prompt.value = ''
  running.value = true
  scrollToBottom()

  ctl = new AbortController()
  try {
    await streamAgent(Endpoints.agentRun, {
      prompt: text,
      model: config.model,
      mode: backendMode,
      plan_first,
      session_id: sessionId,
      skills: localStorage.getItem('ap-vue-ep-skills') !== null ? config.selectedSkills : null,
      enable_mcp: caps.mcp,
      mcp_servers: caps.mcp ? config.selectedServers : [],
      enable_rag: caps.rag,
      enable_web_research: caps.web,
      enable_reflection: caps.reflection,
    }, (ev) => appendEvent(assistant, ev), ctl.signal)
    if (sessionId) sessionStore.touchSession(sessionId)
  } catch (e: unknown) {
    if ((e as { name?: string }).name !== 'AbortError') {
      assistant.error = (e as Error).message ?? String(e)
      errorBanner.value = assistant.error
    }
  } finally {
    running.value = false
    assistant.running = false
    scrollToBottom()
  }
}

function stop() {
  ctl?.abort()
  running.value = false
}

async function onApprove(edited: PlanStep[]) {
  if (!approval.value) return
  approving.value = true
  try {
    await runApprove(approval.value.run_id, edited)
    approvalStatus.value = 'approved'
    const assistant = currentAssistant ?? (() => {
      const m = reactive(newMsg())
      currentAssistant = m
      messages.value.push(m)
      return m
    })()
    // 审批后通过 DB tail SSE 续播（忽略重放的 approval_required）
    ctl = new AbortController()
    await runSSE<AgentEvent>(`${Endpoints.runStream(approval.value.run_id)}?after_seq=0`, (ev) => {
      if (ev.type === 'approval_required') return
      appendEvent(assistant as Msg, ev)
    }, { signal: ctl.signal })
  } catch (e: unknown) {
    errorBanner.value = `审批失败：${(e as Error).message ?? e}`
  } finally {
    approving.value = false
    running.value = false
    approval.value = null
    scrollToBottom()
  }
}

async function onReject() {
  if (!approval.value) return
  try {
    await runReject(approval.value.run_id, '用户拒绝')
    approvalStatus.value = 'rejected'
    ElMessage.info('已拒绝该计划')
  } finally {
    approval.value = null
  }
}

function appendEvent(a: Msg, ev: AgentEvent) {
  switch (ev.type) {
    case 'meta':
      if (ev.session_id && ev.session_id !== ws.currentTaskId) {
        ws.selectTask(ev.session_id)
        router.replace({ path: '/workspace', query: { ...route.query, task: ev.session_id } })
        void ws.loadTasks()
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
      break
    case 'user_input':
      break
    case 'round_start':
      a.steps.push({ step_id: ++a.stepSeq, kind: 'plan', title: `第 ${ev.round} 轮`, text: '' })
      break
    case 'round_input':
      a.steps.push({
        step_id: ++a.stepSeq, kind: 'plan', title: '上下文快照',
        text: ev.messages.map(m => `[${m.index}] ${m.role}: ${m.preview}`).join('\n'),
      })
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
        text: (ev.actions ?? [])
          .map((act, i) => `#${i + 1} ${act.tool ?? '?'}: ${typeof act.input === 'string' ? act.input : JSON.stringify(act.input ?? {})}`)
          .join('\n') || '（无需工具调用）',
      })
      break
    case 'model_text':
      a.texts.push(ev.content)
      break
    case 'reasoning_delta':
      a.thinking += ev.content
      break
    case 'tool_call':
      a.steps.push({
        step_id: ++a.stepSeq, kind: 'tool', tool_name: ev.tool_name,
        tool_input: ev.tool_input, tool_source: ev.tool_source ?? 'builtin', mcp_server: ev.mcp_server ?? null,
      })
      break
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
    case 'approval_required':
      approval.value = { run_id: ev.run_id, plan: ev.plan }
      approvalStatus.value = 'pending'
      running.value = false
      break
    case 'error':
      a.error = ev.content
      a.running = false
      errorBanner.value = ev.content
      break
    case 'done':
      a.done = true
      a.running = false
      break
  }
  scrollToBottom()
}

function toggleCap(key: string) {
  caps[key] = !caps[key]
  if (key === 'mcp' && caps.mcp && !config.selectedServers.length) {
    config.selectedServers = ['weather']
  }
}

function onScene(key: string) {
  const presets: Record<string, string> = {
    daily: '帮我生成今天的日报，包含工作进展、问题与明日计划',
    code: '阅读当前工作区代码，指出潜在问题并给出修改建议',
    design: '帮我做一份产品方案演示文稿，输出为 HTML 单页',
  }
  prompt.value = presets[key] ?? ''
}

function openCommand() { cmdVisible.value = true }
function openAt() { atVisible.value = true }

function onCommand(key: string) {
  if (key === 'new-task') { void newTask(); return }
  if (key === 'mode-chat') { setMode('chat'); return }
  if (key === 'mode-plan') { setMode('plan'); return }
  if (key === 'mode-work') { setMode('work'); return }
  if (key === 'research') { caps.research = true; prompt.value = '请对该主题做一次深度研究并输出报告'; return }
  if (key === 'skills') { router.push('/admin/capabilities'); return }
  if (key.startsWith('skill:')) { prompt.value = `使用 ${key.slice(6)} 技能处理：`; return }
}

function onAtPick(item: AtItem) {
  const label = item.key.split(':').slice(1).join(':')
  prompt.value = `${prompt.value.replace(/@\S*$/, '').trim()} @${label} `.trimEnd() + ' '
}

async function newTask() {
  await ws.loadTasks()
  ws.selectTask(null)
  messages.value = []
  approval.value = null
  router.replace({ path: '/workspace', query: { mode: mode.value } })
}

async function renameTask() {
  if (!ws.currentTaskId) return
  try {
    const { value } = await ElMessageBox.prompt('任务名称', '重命名', { inputValue: taskTitle.value })
    await sessionUpdate(ws.currentTaskId, { title: value })
    await ws.loadTasks()
  } catch { /* 取消 */ }
}

async function deleteTask() {
  if (!ws.currentTaskId) return
  try {
    await ElMessageBox.confirm('删除后不可恢复，确认删除该任务？', '删除任务', { type: 'warning' })
    await sessionDelete(ws.currentTaskId)
    ws.selectTask(null)
    messages.value = []
    await ws.loadTasks()
    router.replace({ path: '/workspace', query: { mode: mode.value } })
  } catch { /* 取消 */ }
}

function scrollToBottom() {
  nextTick(() => {
    const el = scrollEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}
</script>

<style scoped>
.workspace { flex: 1; min-width: 0; display: flex; flex-direction: column; height: 100%; background: var(--bg); }
.ws-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 20px; border-bottom: 1px solid var(--border); flex: 0 0 auto;
}
.head-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.title { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.head-right { display: flex; align-items: center; gap: 4px; }
.ws-scroll { flex: 1; overflow-y: auto; }
.ws-inner { max-width: 640px; margin: 0 auto; padding: 20px 20px 8px; }
.msg-wrap { margin-bottom: 6px; }
.empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 8vh 0 4vh; text-align: center; }
.hero { margin: 0 0 6px; font-size: 26px; font-weight: 600; color: var(--text); }
.hero-sub { margin: 0 0 22px; color: var(--text-dim); font-size: 13.5px; }
.plan-slot { padding: 0 20px; flex: 0 0 auto; }
.error-bar {
  display: flex; align-items: center; gap: 8px; margin: 0 20px 8px; padding: 7px 10px;
  background: var(--bg-code); border: 1px solid var(--red); border-radius: var(--radius-sm);
  color: var(--red); font-size: 12.5px;
}
.error-bar span { flex: 1; }
.ws-composer { flex: 0 0 auto; padding: 8px 20px 14px; }
.composer-wrap { max-width: 640px; margin: 0 auto; }
.cap-chips { margin-bottom: 8px; }
</style>
