<template>
  <div class="research-view">
    <div class="res-header">
      <h2>深度研究</h2>
      <div class="right">
        <el-tag v-if="health" :type="health.search_configured ? 'success' : 'danger'" effect="plain">
          检索源：{{ providerLabel }}
        </el-tag>
      </div>
    </div>

    <el-alert v-if="health && !health.search_configured" type="warning" :closable="false" show-icon style="margin: 12px 0">
      未配置检索服务（BOCHA_API_KEY 或 SERPER_API_KEY），无法提交研究任务。请在 backend/.env 中配置后重启后端。
    </el-alert>

    <div class="res-grid">
      <!-- 提交表单 -->
      <el-card shadow="never" class="form-card">
        <template #header><strong>提交新任务</strong></template>
        <el-form>
          <el-form-item label="研究任务">
            <el-input v-model="task" type="textarea" :rows="3" placeholder="例：2026 年中国新能源汽车市场竞争格局…" />
          </el-form-item>
          <el-form-item label="并行 Worker">
            <el-input-number v-model="maxWorkers" :min="1" :max="10" />
          </el-form-item>
          <el-form-item label="最大迭代">
            <el-input-number v-model="maxIterations" :min="1" :max="10" />
          </el-form-item>
          <el-form-item label="质量阈值">
            <el-input-number v-model="qualityThreshold" :min="0" :max="100" />
          </el-form-item>
          <el-button type="primary" :disabled="!canSubmit" :loading="submitting" @click="submit">
            {{ submitting ? '提交中…' : '开始研究' }}
          </el-button>
        </el-form>
      </el-card>

      <!-- 任务列表 -->
      <el-card shadow="never" class="list-card">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <strong>任务列表（{{ tasks.length }}）</strong>
            <el-button size="small" @click="refresh">刷新</el-button>
          </div>
        </template>
        <div v-if="!tasks.length" class="empty">暂无研究任务</div>
        <div v-else class="task-list">
          <div v-for="t in tasks" :key="t.task_id" class="task-item" :class="{ active: t.task_id === currentId }" @click="open(t.task_id)">
            <div class="row1">
              <el-tag size="small" :type="statusType(t.status)">{{ t.status }}</el-tag>
              <span v-if="t.quality_score != null" class="score">质量 {{ t.quality_score }}</span>
              <span class="ts">{{ formatTime(t.created_at) }}</span>
              <el-button class="del" size="small" link type="danger" :disabled="t.status === 'running' || t.status === 'pending'" @click.stop="remove(t.task_id)">删除</el-button>
            </div>
            <div class="task-text">{{ t.original_task }}</div>
          </div>
        </div>
      </el-card>

      <!-- 详情 -->
      <el-card shadow="never" class="detail-card">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>
              <el-tag :type="statusType(current?.status)">{{ current?.status ?? '—' }}</el-tag>
              <span v-if="current?.quality_score != null" class="score">质量 {{ current.quality_score }}</span>
              <span v-if="streaming" class="hint">流连接中…
                <el-icon class="is-loading"><Loading /></el-icon>
              </span>
              <span v-else-if="reconnecting" class="hint warn">流中断，正在续订…</span>
            </span>
          </div>
        </template>
        <div v-if="!current" class="empty">选择左侧任务查看进度与报告</div>
        <div v-else>
          <div class="question">{{ current.original_task }}</div>
          <el-alert v-if="current.error_message" type="error" :title="current.error_message" :closable="false" show-icon style="margin: 12px 0" />

          <div v-if="events.length" class="timeline">
            <div v-for="(ev, i) in events" :key="i" class="event">
              <span class="dot" :class="ev.stage" />
              <span class="stage">{{ stageLabel(ev.stage) }}</span>
              <span class="text">{{ stageText(ev) }}</span>
            </div>
          </div>

          <div v-if="report" class="report">
            <h3>研究报告</h3>
            <MarkdownView :text="report" />
          </div>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { researchHealth, researchSubmit, researchList, researchStatus, researchResult, researchDelete } from '@/api'
import type { ResearchHealthResp, ResearchTaskSummary, ResearchTaskStatusResp, ResearchProgressItem, ResearchStatus } from '@/api/types'
import { Endpoints } from '@/api/endpoints'
import { streamResearchWithReconnect } from '@/api/sse'
import MarkdownView from '@/components/MarkdownView.vue'

const health = ref<ResearchHealthResp | null>(null)
const tasks = ref<ResearchTaskSummary[]>([])
const currentId = ref<string | null>(null)
const current = ref<ResearchTaskStatusResp | null>(null)
const report = ref<string>('')
const events = ref<ResearchProgressItem[]>([])
const submitting = ref(false)
const streaming = ref(false)
const reconnecting = ref(false)

const task = ref('')
const maxWorkers = ref(6)
const maxIterations = ref(5)        // 与后端 AGENT_CONFIG["max_iterations"]=5 对齐
const qualityThreshold = ref(80)

const providerLabel = computed(() => {
  const p = health.value?.search_provider
  if (p === 'bocha') return '博查 Bocha'
  if (p === 'serper') return 'Serper（降级）'
  return '未配置'
})
const canSubmit = computed(() => !!health.value?.search_configured && !!task.value.trim() && !submitting.value)

// 24 个 stage（与 frontend/docs/sse-protocol.md 对齐）
const STAGE_LABEL: Record<string, string> = {
  decomposing: '分析任务', decomposed: '拆解完成', dispatching: '分发 Worker',
  worker_started: 'Worker 启动', worker_completed: 'Worker 完成', worker_failed: 'Worker 失败',
  synthesizing: '生成报告', synthesized: '报告生成', quality_checking: '质量检查',
  quality_checked: '质量评分', iteration_start: '迭代开始', iteration_evaluated: '迭代评估',
  quality_passed: '质量通过', iteration_continue: '继续优化', analyzing_gaps: '分析差距',
  gaps_analyzed: '差距分析完成', dispatching_supplementary: '分发补充任务',
  supplementary_worker_started: '补充任务启动', supplementary_worker_completed: '补充任务完成',
  refining_report: '修订报告', report_refined: '报告修订完成',
  no_supplementary_tasks: '无需补充', completed: '研究完成', failed: '研究失败',
}
function stageLabel(s: string): string { return STAGE_LABEL[s] ?? s }
function stageText(ev: ResearchProgressItem): string {
  const d = (ev.data ?? {}) as Record<string, unknown>
  switch (ev.stage) {
    case 'decomposed': return `${d.subtask_count ?? '?'} 个子任务 · ${d.query_type ?? ''}`
    case 'dispatching': return `${d.worker_count ?? '?'} 个 Worker`
    case 'worker_started':
    case 'worker_completed':
    case 'supplementary_worker_started':
    case 'supplementary_worker_completed':
      return String(d.task_name ?? '')
    case 'worker_failed': return `${d.task_name ?? ''} ${d.error ?? ''}`.trim()
    case 'quality_checked':
    case 'iteration_evaluated': return `${d.score ?? ''} 分 / 阈值 ${d.threshold ?? ''}`
    case 'completed': return `${d.quality_score ?? ''} 分 · ${(typeof d.duration === 'number' ? d.duration.toFixed(1) : '')}s`
    case 'failed': return String(d.error ?? '')
    case 'gaps_analyzed': return `${d.gap_count ?? 0} 个差距 / ${d.task_count ?? 0} 个补充任务`
    default: return ''
  }
}

let ctl: AbortController | null = null

onMounted(async () => {
  try { health.value = await researchHealth() } catch { /* */ }
  await refresh()
})

async function refresh() {
  try {
    const res = await researchList()
    tasks.value = res.tasks
  } catch { /* */ }
}

async function submit() {
  const text = task.value.trim()
  if (!text) return
  submitting.value = true
  report.value = ''
  events.value = []
  try {
    const res = await researchSubmit({
      task: text,
      max_workers: maxWorkers.value || null,
      max_iterations: maxIterations.value || null,
      quality_threshold: qualityThreshold.value || null,
    })
    task.value = ''
    await refresh()
    if (res.status === 'failed') {
      ElMessage.warning(`提交失败：${res.message}`)
    } else {
      await open(res.task_id)
    }
  } catch (e: unknown) {
    ElMessage.error(`提交失败：${(e as Error).message}`)
  } finally {
    submitting.value = false
  }
}

async function open(taskId: string) {
  // 取消上一个任务的订阅（关键：避免切换被阻塞）
  ctl?.abort()
  ctl = new AbortController()
  currentId.value = taskId
  report.value = ''
  events.value = []
  reconnecting.value = false
  try {
    current.value = await researchStatus(taskId)
    // 用已拿到的最近 20 条初始化（这些会被后续 SSE 因去重而忽略重复）
    events.value = [...(current.value.progress ?? [])]
  } catch (e: unknown) {
    ElMessage.error(`加载任务失败：${(e as Error).message}`)
    return
  }
  const c = current.value
  if (!c) return
  if (c.status === 'completed') {
    await loadReport(taskId)
  } else if (c.status === 'running' || c.status === 'pending') {
    subscribe(taskId)
  }
}

async function loadReport(taskId: string) {
  try {
    const r = await researchResult(taskId)
    report.value = r.report ?? ''
  } catch (e: unknown) {
    if ((e as { status?: number }).status === 202) {
      report.value = ''
    } else {
      ElMessage.warning(`报告加载失败：${(e as Error).message}`)
    }
  }
}

async function subscribe(taskId: string) {
  streaming.value = true
  try {
    await streamResearchWithReconnect(
      Endpoints.researchStream(taskId),
      Endpoints.researchStatus(taskId),
      (ev) => {
        // 去重已在 sse.ts 内部完成，这里直接追加
        events.value.push(ev)
      },
      (ev) => {
        // final：终态
        current.value = {
          ...(current.value ?? ({} as ResearchTaskStatusResp)),
          status: ev.status,
          quality_score: ev.quality_score,
          iteration_count: ev.iteration_count,
          error_message: ev.error,
        }
        if (ev.status === 'completed') loadReport(taskId)
        else ElMessage.warning(ev.error || '研究任务失败')
        refresh()
      },
      ctl!.signal,
    )
  } catch (e: unknown) {
    if ((e as { name?: string }).name !== 'AbortError') {
      ElMessage.error(`进度流中断：${(e as Error).message}`)
    }
  } finally {
    streaming.value = false
  }
}

async function remove(taskId: string) {
  try {
    await researchDelete(taskId)
    if (currentId.value === taskId) {
      currentId.value = null
      current.value = null
      report.value = ''
      events.value = []
    }
    await refresh()
  } catch (e: unknown) {
    ElMessage.error(`删除失败：${(e as Error).message}`)
  }
}

function statusType(s: ResearchStatus | undefined): '' | 'primary' | 'success' | 'warning' | 'danger' | 'info' {
  switch (s) {
    case 'completed': return 'success'
    case 'failed': return 'danger'
    case 'running': return 'warning'
    case 'pending': return 'info'
    default: return ''
  }
}

function formatTime(iso: string): string {
  return String(iso).replace('T', ' ').slice(5, 19)
}
</script>

<style scoped>
.research-view { padding: 16px 24px; }
.res-header { display: flex; justify-content: space-between; align-items: center; }
.res-header h2 { margin: 0; }
.right .el-tag { font-weight: 500; }
.res-grid { display: grid; grid-template-columns: 1fr 1fr 2fr; gap: 16px; margin-top: 16px; }
@media (max-width: 1100px) { .res-grid { grid-template-columns: 1fr; } }
.empty { color: var(--text-dim); padding: 18px 0; text-align: center; }
.task-list { display: flex; flex-direction: column; gap: 6px; max-height: 360px; overflow-y: auto; }
.task-item { padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); cursor: pointer; background: var(--bg); }
.task-item.active { border-color: var(--accent); }
.task-item:hover { background: var(--bg-hover); }
.task-item .row1 { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--text-dim); }
.task-item .score { color: var(--green); }
.task-item .ts { margin-left: auto; }
.task-item .del { margin-left: 6px; }
.task-text { margin-top: 4px; font-size: 13px; }
.question { font-size: 15px; margin-bottom: 12px; }
.hint { color: var(--text-dim); margin-left: 8px; font-size: 12px; display: inline-flex; align-items: center; gap: 4px; }
.hint.warn { color: var(--orange); }
.timeline { margin: 12px 0; max-height: 360px; overflow-y: auto; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px; background: var(--bg-sidebar); }
.event { display: flex; gap: 8px; align-items: center; padding: 4px 0; font-size: 13px; }
.event .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); }
.event .stage { font-weight: 500; }
.event .text { color: var(--text-dim); font-size: 12px; }
.report h3 { margin: 16px 0 8px; }
</style>