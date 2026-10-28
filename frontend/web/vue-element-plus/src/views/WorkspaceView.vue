<template>
  <div class="workspace" :class="{ 'compose-mode': composeMode }">
    <!-- 轻量上下文栏 -->
    <header v-if="!composeMode" class="ws-head">
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
    <div v-if="!composeMode" ref="scrollEl" class="ws-scroll">
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
              <RoundGroup
                v-for="g in roundGroups(m)"
                :key="`${m.runId}:${g.round}`"
                :run-id="m.runId"
                :round="g.round"
                :summary="g.summary"
                :steps="g.steps"
              />
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
          :attachments="attachments"
          @update:mode="setMode"
          @update:model="v => (config.model = v)"
          @send="send"
          @stop="stop"
          @attach="openAt"
          @at="openAt"
          @slash="openCommand"
          @remove-attachment="removeAttachment"
        />
        <div v-if="running && currentRunId" class="steer-bar">
          <el-input
            v-model="steerText"
            size="small"
            placeholder="追加指令（将在下一个工具边界生效；若命令正在执行，则命令结束后生效）"
            @keyup.enter="submitSteer"
          />
          <el-button size="small" type="primary" plain @click="submitSteer">追加</el-button>
        </div>
        <div class="meter-row">
          <RunCostBar :run-id="currentRunId" :running="running" :model="config.model" />
          <ContextMeter :session-id="ws.currentTaskId" :events="compressEvents" />
        </div>
        <ContextBar
          :workspace="workspaceName"
          :permissive="permissive"
          :level="permissions.effectiveLevel"
          @workspace="workspaceName = ''"
          @toggle-permission="permissive = !permissive"
        />
      </div>
    </footer>

    <!-- 权限审批卡（运行中出现待审批动作时弹出） -->
    <PermissionCard
      :item="currentApproval"
      @resolved="onApprovalResolved"
    />

    <!-- 右栏结果区（S3：产物/文件/变更/浏览器） -->
    <ResultPanel v-if="!composeMode" :run-id="currentRunId" />

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
import { ref, computed, reactive, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Warning } from '@element-plus/icons-vue'
import ChatMessage from '@/components/ChatMessage.vue'
import RoundGroup from '@/components/RoundGroup.vue'
import ArtifactStrip from '@/components/ArtifactStrip.vue'
import PlanCard from '@/components/PlanCard.vue'
import ComposerInput from '@/components/composer/ComposerInput.vue'
import ContextChips from '@/components/composer/ContextChips.vue'
import ContextBar from '@/components/composer/ContextBar.vue'
import CommandPalette from '@/components/composer/CommandPalette.vue'
import AtPicker from '@/components/composer/AtPicker.vue'
import PermissionCard from '@/components/PermissionCard.vue'
import ResultPanel from '@/components/ResultPanel.vue'
import RunCostBar from '@/components/RunCostBar.vue'
import ContextMeter from '@/components/ContextMeter.vue'

import type { PlanStep, AtItem } from '@/types/workspace'
import { useConfigStore } from '@/stores/config'
import { usePermissionsStore } from '@/stores/permissions'
import { useRoundsStore } from '@/stores/rounds'
import { runCancel, runSteer } from '@/api/desktop'
import { runsByStatus } from '@/api'
import { useWorkspaceStore, MODE_LABEL, toBackend, type WorkspaceMode } from '@/stores/workspace'
import { useSessionStore } from '@/stores/session'
import { streamAgent, runSSE } from '@/api/sse'
import { Endpoints } from '@/api/endpoints'
import { sessionDetail, sessionUpdate, sessionDelete, filesList, filesUpload, runApprove, runReject, runDetail } from '@/api'
import { checkUploadFile } from '@/api/upload-policy'
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
  /** 批次 02：该步骤所属轮次 */
  round?: number
}

/** 批次 02：轮次摘要（折叠后显示）。 */
interface RoundInfo {
  round: number
  /** 本轮助手输出文本 */
  text: string
  /** 本轮工具调用次数 */
  tools: number
  /** 摘要（优先压缩器产物，其次事件摘要） */
  summary: string
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
  /** S8：耗时三态（开始/完成时刻，毫秒） */
  startedAt: number
  finishedAt?: number
  /** 批次 02：运行 id（折叠态的键） */
  runId: string
  /** 批次 02：轮次信息 */
  rounds: RoundInfo[]
  /** 批次 02：当前轮次 */
  currentRound: number
}

const route = useRoute()
const router = useRouter()
const config = useConfigStore()
const ws = useWorkspaceStore()
const permissions = usePermissionsStore()
const rounds = useRoundsStore()

// ---- 权限审批（S2）：运行中每 2s 拉取待审批列表 ----
const currentApproval = computed(() => permissions.pendingApprovals[0] ?? null)
let approvalTimer: ReturnType<typeof setInterval> | null = null

// 运行中任务轮询（S4：左栏并行观察）
async function refreshRunning(): Promise<void> {
  try {
    const data = await runsByStatus('running', 50)
    ws.runningRunIds = data.items.map((r) => String(r.session_id ?? '')).filter(Boolean)
  } catch {
    // 轮询失败不影响主流程
  }
}
let runningTimer: ReturnType<typeof setInterval> | null = null

function startApprovalPolling(): void {
  if (approvalTimer) return
  void permissions.pollPending()
  approvalTimer = setInterval(() => void permissions.pollPending(), 2000)
}
function stopApprovalPolling(): void {
  if (approvalTimer) { clearInterval(approvalTimer); approvalTimer = null }
  if (runningTimer) { clearInterval(runningTimer); runningTimer = null }
}
function onApprovalResolved(id: number): void {
  permissions.pendingApprovals = permissions.pendingApprovals.filter(a => a.id !== id)
}

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
/** 附件（批次 02）：上限 50 个，添加后不自动发送。 */
const MAX_ATTACHMENTS = 50
const attachments = ref<Array<{ name: string; size: number; url: string }>>([])

/** 壳事件订阅的退订函数（批次 02）。 */
let unsubscribeOpenRun: (() => void) | null = null
let unsubscribeClipboard: (() => void) | null = null

const caps = reactive<Record<string, boolean>>({ mcp: false, rag: true, web: false, reflection: false, research: false })

const approval = ref<{ run_id: string; plan: PlanStep[] } | null>(null)
const currentRunId = ref<string | null>(null)
// S5：压缩事件（供上下文计量表展开查看）
const compressEvents = ref<Array<Record<string, unknown>>>([])
const approvalStatus = ref<'pending' | 'approved' | 'rejected'>('pending')

const mode = computed<WorkspaceMode>(() => ws.mode)
/** 速记形态（批次 02）：``?compose=1`` —— 只留输入区。 */
const composeMode = computed(() => route.query.compose === '1')
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
  startApprovalPolling()
  void permissions.refresh()
  void refreshRunning()
  runningTimer = setInterval(() => void refreshRunning(), 3000)

  // 批次 02：全页拖拽命中（页面任意处拖入文件即进入附件区）
  window.addEventListener('dragover', onDragOver)
  window.addEventListener('drop', onDrop)
  // 批次 02：壳事件（通知点击跳转 / 速记剪贴板预填）
  unsubscribeOpenRun = window.agentDesktop?.onOpenRun?.(v => void onOpenRun(v)) ?? null
  unsubscribeClipboard = window.agentDesktop?.onClipboard?.(text => {
    if (composeMode.value && !prompt.value) prompt.value = text
  }) ?? null

  if (!config.ready) await config.init()
  await ws.loadTasks()
  await loadFiles()
  applyQuery()
  if (ws.currentTaskId) await loadHistory(ws.currentTaskId)
})

onUnmounted(() => {
  window.removeEventListener('dragover', onDragOver)
  window.removeEventListener('drop', onDrop)
  unsubscribeOpenRun?.()
  unsubscribeClipboard?.()
  stopApprovalPolling()
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
            thinking: '', files: (m.files ?? []) as Msg['files'], done: true, startedAt: 0,
            error: String(m.meta?.error ?? ''), running: false, stepSeq: 0,
            runId: '', rounds: [], currentRound: 0,
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
    startedAt: Date.now(),
    runId: '', rounds: [], currentRound: 0,
  }
}

/** 把消息的步骤按轮次分组（批次 02：折叠接线）。 */
function roundGroups(m: Msg): Array<{ round: number; steps: Step[]; summary: string }> {
  const groups: Array<{ round: number; steps: Step[]; summary: string }> = []
  let cur: { round: number; steps: Step[]; summary: string } = { round: 0, steps: [], summary: '' }
  for (const s of m.steps) {
    const marker = s.kind === 'plan' && /^第 \d+ 轮$/.test(s.title ?? '')
    if (marker) {
      groups.push(cur)
      cur = { round: Number((s.title ?? '').replace(/[^\d]/g, '')) || 0, steps: [], summary: '' }
      continue
    }
    cur.steps.push(s)
  }
  groups.push(cur)
  return groups.map((g, i) => {
    const info = m.rounds[i]
    return { round: info?.round ?? g.round, steps: g.steps, summary: info?.summary ?? '' }
  })
}

/** 轮次收尾：补摘要 + 自动折叠该轮（折叠态存在 ``stores/rounds``）。 */
function finalizeRounds(a: Msg): void {
  for (const r of a.rounds) {
    if (r.summary) continue
    const t = r.text.trim().replace(/\s+/g, ' ')
    r.summary = t ? t.slice(0, 80) : (r.tools ? `调用了 ${r.tools} 个工具` : '（本轮无输出）')
  }
  if (!a.runId) return
  for (const r of a.rounds) rounds.collapseRound(a.runId, r.round)
}

async function send() {
  const text = prompt.value.trim()
  if (!text || running.value) return
  errorBanner.value = ''

  // 附件以「上下文块」随提示词下发（批次 02）——附件本身已落到后端产出目录
  const attBlock = attachments.value.length
    ? `\n\n【附件】\n${attachments.value
        .map(a => `- ${a.name}（${a.size} 字节）→ ${a.url}`)
        .join('\n')}`
    : ''
  const fullPrompt = text + attBlock
  attachments.value = []

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
      prompt: fullPrompt,
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

async function stop() {
  // S4：以后端状态为准 —— 先请求 cancel（真中止），abort 只作连接层清理
  const rid = currentRunId.value
  running.value = false
  if (rid) {
    try {
      await runCancel(rid)
      ElMessage.info('已请求停止（正在执行的命令结束后生效）')
    } catch {
      // 后端可能已结束（幂等）
    }
  }
  ctl?.abort()
}

// ---- 追加指令（S4）：注入下一个工具边界 ----
const steerText = ref('')
async function submitSteer(): Promise<void> {
  const rid = currentRunId.value
  const text = steerText.value.trim()
  if (!rid || !text) return
  try {
    await runSteer(rid, text)
    steerText.value = ''
    ElMessage.info('指令已排队（将在下一个工具边界生效）')
  } catch (e: unknown) {
    ElMessage.error(`追加失败：${(e as Error).message}`)
  }
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
    case 'context_compressed':
      compressEvents.value = [...compressEvents.value, ev as unknown as Record<string, unknown>]
      // 压缩器产物优先作为轮次摘要
      {
        const summary = String((ev as unknown as { summary?: string }).summary ?? '').trim()
        const last = a.rounds[a.rounds.length - 1]
        if (summary && last) last.summary = summary
      }
      break
    case 'meta':
      if (ev.run_id) {
        currentRunId.value = ev.run_id
        a.runId = ev.run_id
      }
      if (ev.session_id && ev.session_id !== ws.currentTaskId) {
        ws.selectTask(ev.session_id)
        router.replace({ path: '/workspace', query: { ...route.query, task: ev.session_id } })
        void ws.loadTasks()
      }
      break
    case 'notice':
      a.steps.push({ step_id: ++a.stepSeq, kind: 'plan', title: '提示', text: ev.content, round: a.currentRound })
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
      a.currentRound = ev.round
      a.steps.push({ step_id: ++a.stepSeq, kind: 'plan', title: `第 ${ev.round} 轮`, text: '', round: ev.round })
      a.rounds.push({ round: ev.round, text: '', tools: 0, summary: '' })
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
      {
        const last = a.rounds[a.rounds.length - 1]
        if (last) last.text += ev.content
      }
      break
    case 'reasoning_delta':
      a.thinking += ev.content
      break
    case 'tool_call':
      a.steps.push({
        step_id: ++a.stepSeq, kind: 'tool', tool_name: ev.tool_name,
        tool_input: ev.tool_input, tool_source: ev.tool_source ?? 'builtin', mcp_server: ev.mcp_server ?? null,
        round: a.currentRound,
      })
      {
        const last = a.rounds[a.rounds.length - 1]
        if (last) last.tools += 1
      }
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
      a.finishedAt = Date.now()
      errorBanner.value = ev.content
      finalizeRounds(a)
      break
    case 'done':
      a.done = true
      a.running = false
      a.finishedAt = Date.now()
      finalizeRounds(a)
      // 速记形态：运行结束后关小窗并把任务交给主窗口（批次 02）
      if (composeMode.value && a.runId) void window.agentDesktop?.openRun?.(a.runId)
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

// --------------------------------------------------------------------------- //
// 附件（批次 02）：全页拖拽 + 上限 50 + 类型/大小预检
// --------------------------------------------------------------------------- //
function onDragOver(e: DragEvent): void {
  if (!e.dataTransfer?.types?.includes('Files')) return
  // 必须阻止默认行为，否则浏览器会直接打开被拖入的文件
  e.preventDefault()
}

async function onDrop(e: DragEvent): Promise<void> {
  const files = e.dataTransfer?.files
  if (!files || !files.length) return
  e.preventDefault()
  await addFiles(Array.from(files))
}

async function addFiles(files: File[]): Promise<void> {
  if (!files.length) return
  if (attachments.value.length + files.length > MAX_ATTACHMENTS) {
    ElMessage.error(`附件数量已达上限（${MAX_ATTACHMENTS} 个）`)
    return
  }
  for (const f of files) {
    const reason = checkUploadFile(f)
    if (reason) {
      ElMessage.error(`${f.name}：${reason}`)
      continue
    }
    try {
      const fd = new FormData()
      fd.append('file', f)
      const res = await filesUpload(fd)
      attachments.value = [...attachments.value, { name: res.name, size: res.size, url: res.url }]
    } catch (err: unknown) {
      ElMessage.error(`${f.name} 上传失败：${(err as Error).message ?? err}`)
    }
  }
}

function removeAttachment(index: number): void {
  attachments.value = attachments.value.filter((_, i) => i !== index)
}

/** 通知点击 → 定位到对应 run（批次 02）。 */
async function onOpenRun(runId: string): Promise<void> {
  try {
    const rec = await runDetail(runId)
    const sid = rec.session_id
    if (!sid) return
    ws.selectTask(sid)
    await loadHistory(sid)
    router.replace({ path: '/workspace', query: { ...route.query, task: sid } })
    void ws.loadTasks()
  } catch {
    // run 不存在或后端不可达：保持当前视图
  }
}

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
/* 速记形态（批次 02）：输入区居中，不显示历史与右栏 */
.workspace.compose-mode .ws-composer { justify-content: center; padding: 24px 16px; }
.workspace.compose-mode .composer-wrap { width: 100%; max-width: 620px; }
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
.steer-bar { display: flex; gap: 6px; padding: 0 24px 8px; }
.meter-row { display: flex; gap: 16px; align-items: center; padding: 0 24px 6px; justify-content: center; }
</style>
