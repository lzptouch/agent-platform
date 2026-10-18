<template>
  <div class="schedules-view">
    <div class="page-head">
      <h2>定时任务</h2>
      <div>
        <el-tag v-if="health" size="small" :type="health.role === 'primary' ? 'success' : 'info'" style="margin-right: 8px">
          调度器：{{ health.role === 'primary' ? '运行中' : '待机' }} · {{ health.jobs }} 个任务
        </el-tag>
        <el-button type="primary" @click="openCreate">新建任务</el-button>
      </div>
    </div>

    <el-table :data="tasks" v-loading="loading" style="width: 100%" row-key="id"
      @expand-change="(row: Schedule) => loadRuns(row.id)">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="run-history">
            <el-table :data="runsMap[row.id] ?? []" size="small" v-loading="runsLoading[row.id]">
              <el-table-column label="状态" width="110">
                <template #default="{ row: r }">
                  <el-tag size="small" :type="statusType(r.status)">{{ statusText(r.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="触发" width="80">
                <template #default="{ row: r }">{{ r.trigger === 'schedule' ? '定时' : r.trigger === 'manual' ? '手动' : 'API' }}</template>
              </el-table-column>
              <el-table-column prop="started_at" label="开始时间" width="180">
                <template #default="{ row: r }">{{ formatTime(r.started_at) }}</template>
              </el-table-column>
              <el-table-column label="耗时" width="90">
                <template #default="{ row: r }">{{ r.duration_ms != null ? (r.duration_ms / 1000).toFixed(1) + 's' : '-' }}</template>
              </el-table-column>
              <el-table-column prop="result_summary" label="摘要" min-width="200" show-overflow-tooltip />
              <el-table-column prop="error" label="错误" min-width="140" show-overflow-tooltip />
              <el-table-column label="操作" width="110">
                <template #default="{ row: r }">
                  <el-button size="small" @click="openRunEvents(r.id)">事件回放</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="schedule_text" label="调度" width="150" />
      <el-table-column label="模式" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.mode === 'work' ? 'warning' : 'info'">{{ row.mode === 'work' ? '工作' : '对话' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="下次运行" width="170">
        <template #default="{ row }">{{ row.enabled ? formatTime(row.next_run_at) : '-' }}</template>
      </el-table-column>
      <el-table-column label="上次状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.last_status)">{{ statusText(row.last_status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="健康" width="80">
        <template #default="{ row }">
          <el-tooltip v-if="row.health !== 'ok'" :content="`连续失败 ${row.consecutive_failures} 次${row.last_error ? '：' + row.last_error : ''}`">
            <el-tag size="small" :type="row.health === 'degraded' ? 'danger' : 'warning'">{{ row.health === 'degraded' ? '异常' : '警告' }}</el-tag>
          </el-tooltip>
          <span v-else style="color: var(--el-color-success)">●</span>
        </template>
      </el-table-column>
      <el-table-column prop="run_count" label="次数" width="70" />
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @change="(v: boolean) => onToggle(row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button size="small" @click="onRunNow(row)" :loading="runningNow[row.id]">立即运行</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建 / 编辑抽屉 -->
    <el-drawer v-model="drawerVisible" :title="editing ? '编辑任务' : '新建任务'" size="520px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="如：每日销售报告" />
        </el-form-item>
        <el-form-item label="任务内容（prompt）">
          <el-input v-model="form.prompt" type="textarea" :rows="4" placeholder="Agent 每次触发要执行的任务" />
        </el-form-item>
        <el-form-item label="调度方式">
          <el-radio-group v-model="form.schedule_kind">
            <el-radio value="interval">固定间隔</el-radio>
            <el-radio value="cron">cron 表达式</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.schedule_kind === 'interval'" label="间隔（秒，≥60）">
          <el-input-number v-model="form.interval_seconds" :min="60" :step="60" />
        </el-form-item>
        <el-form-item v-else label="cron 表达式（5 段）">
          <el-input v-model="form.cron_expr" placeholder="如 0 9 * * *（每天 09:00）" @input="onCronInput" />
          <div v-if="cronPreview" class="cron-preview">
            <span v-if="cronPreview.valid" style="color: var(--el-color-success)">
              ✓ 未来触发：{{ cronPreview.next_runs.map(formatTime).join('，') }}
            </span>
            <span v-else style="color: var(--el-color-danger)">✗ {{ cronPreview.error }}</span>
          </div>
        </el-form-item>
        <el-form-item label="模式">
          <el-radio-group v-model="form.mode">
            <el-radio value="chat">对话（只读）</el-radio>
            <el-radio value="work">工作（可写文件/执行代码）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="技能团队（可选，与下方 Skill 互斥）">
          <el-select v-model="form.team_id" clearable placeholder="选择团队" style="width: 100%">
            <el-option v-for="t in teams.filter(x => x.enabled)" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!form.team_id" label="Skill（可选）">
          <el-select v-model="form.skills" multiple style="width: 100%">
            <el-option v-for="s in config.skills.filter(x => x.enabled)" :key="s.name" :label="s.name" :value="s.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="能力开关">
          <el-checkbox v-model="form.enable_rag">RAG</el-checkbox>
          <el-checkbox v-model="form.enable_web_research">Web 检索</el-checkbox>
          <el-checkbox v-model="form.enable_mcp">MCP</el-checkbox>
          <el-checkbox v-model="form.enable_reflection" :disabled="form.mode === 'chat'">反思循环</el-checkbox>
        </el-form-item>
        <template v-if="form.mode === 'work'">
          <el-alert type="warning" :closable="false" style="margin-bottom: 12px"
            title="工作模式任务无人值守执行，可写文件与执行代码，请确认任务内容可信" />
          <el-form-item>
            <el-checkbox v-model="form.allow_unattended_tools">我确认允许该任务无人值守执行写操作</el-checkbox>
          </el-form-item>
        </template>
        <el-form-item label="每日运行上限">
          <el-input-number v-model="form.daily_run_limit" :min="1" :max="1000" />
        </el-form-item>
      </el-form>
      <div style="display:flex;justify-content:flex-end;gap:8px">
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </div>
    </el-drawer>

    <!-- 事件回放抽屉 -->
    <el-drawer v-model="eventsVisible" title="运行事件回放" size="560px">
      <div v-for="ev in runEventsList" :key="ev.seq" class="event-item">
        <span class="event-seq">#{{ ev.seq }}</span>
        <el-tag size="small" effect="plain">{{ ev.type }}</el-tag>
        <span class="event-payload">{{ summarizeEvent(ev) }}</span>
      </div>
      <el-empty v-if="!runEventsList.length" description="暂无事件" :image-size="60" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  schedulesList, scheduleCreate, scheduleUpdate, scheduleDelete, scheduleToggle,
  scheduleRunNow, scheduleRuns, scheduleValidateCron, teamsList, runEvents,
} from '@/api'
import { get } from '@/api/client'
import { Endpoints } from '@/api/endpoints'
import type { Schedule, RunRecord, RunEventItem, Team, RunStatus } from '@/api/types'
import { useConfigStore } from '@/stores/config'

const route = useRoute()
const config = useConfigStore()

const tasks = ref<Schedule[]>([])
const teams = ref<Team[]>([])
const loading = ref(false)
const saving = ref(false)
const drawerVisible = ref(false)
const eventsVisible = ref(false)
const editing = ref<Schedule | null>(null)
const health = ref<{ role: string; jobs: number } | null>(null)
const runsMap = ref<Record<string, RunRecord[]>>({})
const runsLoading = ref<Record<string, boolean>>({})
const runningNow = ref<Record<string, boolean>>({})
const runEventsList = ref<RunEventItem[]>([])
const cronPreview = ref<{ valid: boolean; error: string | null; next_runs: string[] } | null>(null)

const emptyForm = () => ({
  name: '', prompt: '', schedule_kind: 'interval' as 'cron' | 'interval',
  cron_expr: '', interval_seconds: 3600, timezone: 'Asia/Shanghai',
  mode: 'chat' as 'chat' | 'work', plan_first: false,
  team_id: null as string | null, skills: [] as string[],
  enable_mcp: false, mcp_servers: [] as string[],
  enable_rag: false, enable_web_research: false, enable_reflection: false,
  allow_unattended_tools: false, allow_dangerous_tools: false,
  daily_run_limit: 100, enabled: true,
})
const form = ref(emptyForm())

let cronTimer: ReturnType<typeof setTimeout> | null = null

function statusType(s: string) {
  return s === 'success' ? 'success' : s === 'failed' ? 'danger'
    : s === 'running' || s === 'queued' ? 'warning'
    : s === 'skipped' || s === 'interrupted' ? 'info' : 'info'
}
function statusText(s: string) {
  return ({
    never: '未运行', queued: '排队中', running: '运行中', awaiting_approval: '待审批',
    success: '成功', failed: '失败', skipped: '跳过', interrupted: '中断', rejected: '已拒绝',
  } as Record<string, string>)[s] ?? s
}
function formatTime(ts: string | null) {
  if (!ts) return '-'
  try { return new Date(ts).toLocaleString('zh-CN', { hour12: false }) } catch { return ts }
}
function summarizeEvent(ev: RunEventItem) {
  const p = ev.payload as Record<string, unknown>
  if (typeof p.content === 'string') return p.content.slice(0, 120)
  if (typeof p.tool_name === 'string') return `${p.tool_name}`
  return JSON.stringify(p).slice(0, 120)
}

async function load() {
  loading.value = true
  try {
    tasks.value = await schedulesList()
    health.value = await get<{ role: string; jobs: number }>(Endpoints.scheduleHealth).catch(() => null)
  } finally {
    loading.value = false
  }
}

async function loadRuns(taskId: string) {
  runsLoading.value[taskId] = true
  try {
    const resp = await scheduleRuns(taskId)
    runsMap.value[taskId] = resp.items
  } finally {
    runsLoading.value[taskId] = false
  }
}

onMounted(async () => {
  config.init()
  teams.value = await teamsList().catch(() => [])
  await load()
  // 从工作台"转为定时任务"跳转预填
  if (route.query.prefill) {
    const raw = sessionStorage.getItem('schedule_prefill')
    if (raw) {
      try {
        const prefill = JSON.parse(raw)
        form.value = { ...emptyForm(), ...prefill, name: '', enabled: false }
        drawerVisible.value = true
      } catch { /* */ }
      sessionStorage.removeItem('schedule_prefill')
    }
  }
})

// 展开行时由 el-table 的 expand-change 事件触发 loadRuns

function openCreate() {
  editing.value = null
  form.value = emptyForm()
  cronPreview.value = null
  drawerVisible.value = true
}

function openEdit(row: Schedule) {
  editing.value = row
  form.value = {
    name: row.name, prompt: row.prompt, schedule_kind: row.schedule_kind,
    cron_expr: row.cron_expr ?? '', interval_seconds: row.interval_seconds ?? 3600,
    timezone: row.timezone, mode: row.mode, plan_first: row.plan_first,
    team_id: row.team_id, skills: [...row.skills],
    enable_mcp: row.enable_mcp, mcp_servers: [...row.mcp_servers],
    enable_rag: row.enable_rag, enable_web_research: row.enable_web_research,
    enable_reflection: row.enable_reflection,
    allow_unattended_tools: row.allow_unattended_tools,
    allow_dangerous_tools: row.allow_dangerous_tools,
    daily_run_limit: row.daily_run_limit, enabled: row.enabled,
  }
  drawerVisible.value = true
}

function onCronInput() {
  if (cronTimer) clearTimeout(cronTimer)
  cronTimer = setTimeout(async () => {
    if (!form.value.cron_expr.trim()) { cronPreview.value = null; return }
    cronPreview.value = await scheduleValidateCron(form.value.cron_expr, form.value.timezone).catch(() => null)
  }, 500)
}

async function onSave() {
  saving.value = true
  try {
    const f = form.value
    if (editing.value) {
      const payload: Record<string, unknown> = {
        name: f.name, prompt: f.prompt, mode: f.mode, plan_first: f.plan_first,
        team_id: f.team_id, skills: f.skills, timezone: f.timezone,
        enable_mcp: f.enable_mcp, mcp_servers: f.mcp_servers,
        enable_rag: f.enable_rag, enable_web_research: f.enable_web_research,
        enable_reflection: f.enable_reflection,
        allow_unattended_tools: f.allow_unattended_tools,
        allow_dangerous_tools: f.allow_dangerous_tools,
        daily_run_limit: f.daily_run_limit,
      }
      if (f.schedule_kind === 'cron') payload.cron_expr = f.cron_expr
      else payload.interval_seconds = f.interval_seconds
      await scheduleUpdate(editing.value.id, payload)
      ElMessage.success('已更新')
    } else {
      await scheduleCreate({
        ...f,
        cron_expr: f.schedule_kind === 'cron' ? f.cron_expr : null,
        interval_seconds: f.schedule_kind === 'interval' ? f.interval_seconds : null,
      })
      ElMessage.success('已创建')
    }
    drawerVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function onToggle(row: Schedule, enabled: boolean) {
  try {
    const updated = await scheduleToggle(row.id, enabled)
    Object.assign(row, updated)
    ElMessage.success(enabled ? '已启用' : '已停用')
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

async function onRunNow(row: Schedule) {
  runningNow.value[row.id] = true
  try {
    const resp = await scheduleRunNow(row.id, 0)
    ElMessage.success(`已触发，运行 ID: ${resp.run_id.slice(0, 8)}…`)
    setTimeout(() => loadRuns(row.id), 2000)
    setTimeout(() => load(), 2500)
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    runningNow.value[row.id] = false
  }
}

async function onDelete(row: Schedule) {
  await ElMessageBox.confirm(`删除任务「${row.name}」？运行历史将保留。`, '确认', { type: 'warning' })
  await scheduleDelete(row.id)
  ElMessage.success('已删除')
  await load()
}

async function openRunEvents(runId: string) {
  const page = await runEvents(runId)
  runEventsList.value = page.items
  eventsVisible.value = true
}
</script>

<style scoped>
.schedules-view { padding: 20px 24px; overflow-y: auto; height: 100%; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-head h2 { margin: 0; font-size: 18px; }
.run-history { padding: 8px 24px; }
.cron-preview { font-size: 12px; margin-top: 4px; }
.event-item { display: flex; gap: 8px; align-items: baseline; padding: 4px 0; border-bottom: 1px dashed var(--border); font-size: 12px; }
.event-seq { color: var(--text-dim); width: 40px; flex-shrink: 0; }
.event-payload { color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
