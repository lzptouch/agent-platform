<template>
  <div class="work-view">
    <aside class="work-sidebar">
      <div class="sidebar-head">
        <span>工作会话</span>
        <el-button size="small" type="primary" @click="onNewSession">新建</el-button>
      </div>
      <div
        v-for="s in sessionStore.sessions"
        :key="s.id"
        class="session-item"
        :class="{ active: s.id === sessionStore.currentSessionId }"
        @click="onSelectSession(s.id)"
      >
        <span class="session-name">{{ s.title || '未命名任务' }}</span>
        <el-tag size="small" effect="plain" type="info">{{ s.message_count }}</el-tag>
      </div>
      <el-empty v-if="!sessionStore.sessions.length" description="暂无工作会话" :image-size="60" />
    </aside>

    <div class="work-main">
      <div class="work-header">
        <el-segmented
          :model-value="'work'"
          :options="[{ label: '对话模式', value: 'chat' }, { label: '工作模式', value: 'work' }]"
          @change="(v: string) => v === 'chat' && $router.push('/chat')"
        />
        <el-checkbox v-model="planFirst">先规划后执行（Plan）</el-checkbox>
        <el-select v-model="teamId" placeholder="选择技能团队（可选）" clearable size="small" style="width: 200px" @change="onTeamChange">
          <el-option v-for="t in teams.filter(x => x.enabled)" :key="t.id" :label="t.name" :value="t.id" />
        </el-select>
        <el-popover v-if="!teamId" placement="bottom" :width="300" trigger="click">
          <template #reference>
            <el-button size="small">Skill（{{ selectedSkills.length }}/{{ config.skills.length }}）</el-button>
          </template>
          <el-checkbox-group v-model="selectedSkills">
            <el-checkbox v-for="s in config.skills.filter(x => x.enabled)" :key="s.name" :value="s.name">{{ s.name }}</el-checkbox>
          </el-checkbox-group>
        </el-popover>
        <el-tag v-else size="small" type="success">已绑定团队，单项 Skill 选择已禁用</el-tag>
      </div>

      <div class="work-scroll" ref="scrollEl">
        <div class="work-inner">
          <el-empty v-if="!messages.length" description="描述一个工作目标，Agent 将规划并执行，产出文件与报告" />

          <ChatMessage v-for="(m, i) in messages" :key="i" :message="m" :skills-list="config.skills" />

          <!-- Plan 审批卡片 -->
          <el-card v-if="approval" class="approval-card" shadow="never">
            <template #header>
              <span>📋 执行计划待确认</span>
            </template>
            <div v-for="(step, i) in approval.plan" :key="step.id" class="plan-step">
              <span class="plan-id">{{ i + 1 }}</span>
              <div class="plan-body">
                <el-input v-model="step.title" size="small" placeholder="步骤标题" />
                <el-input v-model="step.detail" size="small" placeholder="步骤说明" style="margin-top: 4px" />
              </div>
            </div>
            <div class="plan-actions">
              <el-button type="primary" :loading="approving" @click="onApprove">确认执行</el-button>
              <el-button type="danger" plain @click="onReject">拒绝</el-button>
            </div>
          </el-card>
        </div>
      </div>

      <div class="work-input">
        <el-input
          v-model="prompt"
          type="textarea"
          :rows="3"
          :disabled="!!approval"
          placeholder="描述要完成的工作目标… Enter 发送，Shift+Enter 换行"
          @keydown="onKeydown"
        />
        <div class="input-actions">
          <el-button size="small" :disabled="!lastConfig" @click="toSchedule">转为定时任务</el-button>
          <el-button v-if="!running" type="primary" :disabled="!prompt.trim() || !!approval" @click="send">执行</el-button>
          <el-button v-else type="danger" @click="stop">停止</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useConfigStore } from '@/stores/config'
import { useSessionStore } from '@/stores/session'
import { streamAgent, runSSE } from '@/api/sse'
import { sessionDetail, teamsList, runApprove, runReject } from '@/api'
import { Endpoints } from '@/api/endpoints'
import type { AgentEvent, Team } from '@/api/types'
import ChatMessage from '@/components/ChatMessage.vue'

interface WorkMessage {
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

interface PlanStep { id: number; title: string; detail: string }

const router = useRouter()
const config = useConfigStore()
const sessionStore = useSessionStore()

const prompt = ref('')
const running = ref(false)
const approving = ref(false)
const messages = ref<WorkMessage[]>([])
const scrollEl = ref<HTMLDivElement>()
const planFirst = ref(false)
const teamId = ref<string | null>(null)
const teams = ref<Team[]>([])
const selectedSkills = ref<string[]>([])
const approval = ref<{ run_id: string; plan: PlanStep[] } | null>(null)
const lastConfig = ref<Record<string, unknown> | null>(null)
let ctl: AbortController | null = null
let replayingAfterApproval = false

onMounted(async () => {
  config.init()
  sessionStore.mode = 'work'
  await sessionStore.loadSessions()
  teams.value = await teamsList().catch(() => [])
  // 会话模式不可变：若恢复的会话不属于 work 列表，则开新会话
  if (sessionStore.currentSessionId &&
      !sessionStore.sessions.some(s => s.id === sessionStore.currentSessionId)) {
    sessionStore.currentSessionId = null
  }
  if (sessionStore.currentSessionId) await loadHistory(sessionStore.currentSessionId)
})

async function loadHistory(sessionId: string) {
  try {
    const detail = await sessionDetail(sessionId)
    if (detail.team_id) teamId.value = detail.team_id
    messages.value = detail.messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => m.role === 'user'
        ? { role: 'user', content: m.content } as WorkMessage
        : {
            role: 'assistant', steps: [], texts: [m.content], skills: [], allSkills: [],
            thinking: '', files: m.files as WorkMessage['files'], done: true,
            error: String(m.meta?.error ?? ''), running: false, stepSeq: 0,
          } as WorkMessage)
    scrollToBottom()
  } catch {
    sessionStore.currentSessionId = null
  }
}

async function onNewSession() {
  messages.value = []
  approval.value = null
  const sess = await sessionStore.newSession()
  sessionStore.selectSession(sess.id)
}

async function onSelectSession(id: string) {
  sessionStore.selectSession(id)
  approval.value = null
  await loadHistory(id)
}

function onTeamChange() {
  // 团队绑定时单选 Skill 禁用（UI 已通过 v-if 隐藏）
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

function newAssistantMsg(): WorkMessage {
  return {
    role: 'assistant', steps: [], texts: [], skills: [], allSkills: [],
    thinking: '', files: [], done: false, error: '', running: true, stepSeq: 0,
  }
}

async function send() {
  const text = prompt.value.trim()
  if (!text || running.value || approval.value) return

  if (!sessionStore.currentSessionId) {
    const sess = await sessionStore.newSession()
    sessionStore.selectSession(sess.id)
  }
  const sessionId = sessionStore.currentSessionId

  messages.value.push({ role: 'user', content: text } as WorkMessage)
  const assistant = reactive(newAssistantMsg())
  messages.value.push(assistant)
  prompt.value = ''
  running.value = true
  scrollToBottom()

  const payload = {
    prompt: text,
    model: config.model,
    mode: 'work' as const,
    session_id: sessionId,
    team_id: teamId.value,
    plan_first: planFirst.value,
    skills: teamId.value ? null : (selectedSkills.value.length ? selectedSkills.value : null),
    enable_mcp: config.enableMcp,
    mcp_servers: config.enableMcp ? config.selectedServers : [],
    enable_rag: config.enableRag,
    enable_web_research: config.enableWeb,
    enable_reflection: config.enableReflection,
  }
  lastConfig.value = payload

  ctl = new AbortController()
  try {
    await streamAgent(Endpoints.agentRun, payload, (ev) => appendEvent(assistant, ev), ctl.signal)
    if (sessionId) sessionStore.touchSession(sessionId)
  } catch (e: unknown) {
    if ((e as { name?: string }).name !== 'AbortError') {
      assistant.error = (e as Error).message ?? String(e)
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

async function onApprove() {
  if (!approval.value) return
  approving.value = true
  const runId = approval.value.run_id
  const editedPlan = approval.value.plan
  approval.value = null
  const assistant = reactive(newAssistantMsg())
  messages.value.push(assistant)
  running.value = true
  try {
    await runApprove(runId, editedPlan)
    // 审批后通过 DB tail SSE 继续观看执行（忽略重放的 approval_required）
    replayingAfterApproval = true
    ctl = new AbortController()
    try {
      await runSSE<AgentEvent>(`${Endpoints.runStream(runId)}?after_seq=0`, (ev) => appendEvent(assistant, ev), { signal: ctl.signal })
    } finally {
      replayingAfterApproval = false
    }
    ElMessage.success('执行完成')
  } catch (e: unknown) {
    if ((e as { name?: string }).name !== 'AbortError') {
      assistant.error = (e as Error).message ?? String(e)
    }
  } finally {
    approving.value = false
    running.value = false
    assistant.running = false
    assistant.done = true
    if (sessionStore.currentSessionId) sessionStore.touchSession(sessionStore.currentSessionId)
  }
}

async function onReject() {
  if (!approval.value) return
  try {
    await runReject(approval.value.run_id, '用户拒绝')
    ElMessage.info('已拒绝该计划')
  } finally {
    approval.value = null
  }
}

function toSchedule() {
  if (!lastConfig.value) return
  sessionStorage.setItem('schedule_prefill', JSON.stringify({
    prompt: lastConfig.value.prompt,
    mode: 'work',
    plan_first: planFirst.value,
    team_id: teamId.value,
    skills: teamId.value ? [] : selectedSkills.value,
    enable_mcp: config.enableMcp,
    mcp_servers: config.enableMcp ? config.selectedServers : [],
    enable_rag: config.enableRag,
    enable_web_research: config.enableWeb,
    enable_reflection: config.enableReflection,
  }))
  router.push('/schedules?prefill=1')
}

function appendEvent(a: WorkMessage, ev: AgentEvent) {
  switch (ev.type) {
    case 'meta':
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
    case 'approval_required':
      // 审批后的事件回放会重放该事件，跳过避免审批卡片复现
      if (replayingAfterApproval) break
      approval.value = { run_id: ev.run_id, plan: ev.plan.map(p => ({ ...p })) }
      a.running = false
      break
    case 'model_text':
      a.texts.push(ev.content)
      break
    case 'reasoning_delta':
      a.thinking += ev.content
      break
    case 'tool_call':
      a.steps.push({
        step_id: ++a.stepSeq, kind: 'tool',
        tool_name: ev.tool_name, tool_input: ev.tool_input,
        tool_source: ev.tool_source ?? 'builtin', mcp_server: ev.mcp_server ?? null,
      })
      break
    case 'tool_result': {
      for (let i = a.steps.length - 1; i >= 0; i--) {
        const s = a.steps[i]
        if (s.kind === 'tool' && s.tool_name === ev.tool_name && s.result === undefined) {
          s.result = ev.result
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
.work-view { display: flex; height: 100%; }
.work-sidebar { width: 220px; border-right: 1px solid var(--border); overflow-y: auto; padding: 12px; }
.sidebar-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-weight: 600; }
.session-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 6px; cursor: pointer; }
.session-item:hover { background: var(--bg-sidebar); }
.session-item.active { background: var(--bg-sidebar); outline: 1px solid var(--accent); }
.session-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.work-main { flex: 1; display: flex; flex-direction: column; }
.work-header { display: flex; align-items: center; gap: 12px; padding: 12px 24px; border-bottom: 1px solid var(--border); }
.work-scroll { flex: 1; overflow-y: auto; padding: 16px 24px; }
.work-inner { max-width: 900px; margin: 0 auto; }
.work-input { padding: 12px 24px 18px; border-top: 1px solid var(--border); background: var(--bg); }
.input-actions { margin-top: 8px; display: flex; justify-content: flex-end; gap: 8px; }
.approval-card { margin: 12px 0; border: 1px solid var(--accent); }
.plan-step { display: flex; gap: 8px; align-items: flex-start; margin-bottom: 8px; }
.plan-id { width: 22px; height: 22px; border-radius: 50%; background: var(--accent); color: #fff; display: grid; place-items: center; font-size: 12px; flex-shrink: 0; margin-top: 4px; }
.plan-body { flex: 1; }
.plan-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
</style>
