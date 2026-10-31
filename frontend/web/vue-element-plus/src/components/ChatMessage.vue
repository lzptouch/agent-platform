<template>
  <div class="msg" :class="{ user: message.role === 'user', assistant: message.role === 'assistant' }">
    <div v-if="message.role === 'user'" class="user-bubble">{{ message.content }}</div>

    <div v-else class="assistant-msg">
      <!-- 顶部 Skill 徽标 -->
      <div v-if="message.skills?.length" class="skills-bar">
        <el-tag v-for="s in message.skills" :key="s" type="info" size="small" effect="plain">{{ s }}</el-tag>
      </div>

      <!-- 思考过程 -->
      <details v-if="message.thinking" class="thinking" open>
        <summary>思考过程</summary>
        <pre>{{ message.thinking }}</pre>
      </details>

      <!-- 过程时间线 -->
      <ProcessSteps v-if="message.steps?.length" :steps="message.steps" />

      <!-- 正文 Markdown -->
      <div v-if="message.texts?.length" class="texts">
        <MarkdownView v-for="(t, i) in message.texts" :key="i" :text="t" />
      </div>

      <!-- 产出文件 -->
      <div v-if="message.files?.length" class="files">
        <div class="images">
          <a v-for="f in message.files.filter(x => x.is_image)" :key="f.name" :href="fileUrl(f.name)" target="_blank">
            <img :src="fileUrl(f.name)" :alt="f.name" />
          </a>
        </div>
        <div class="chips">
          <a v-for="f in message.files.filter(x => !x.is_image)" :key="f.name" class="file-chip" :href="fileUrl(f.name)" target="_blank">
            📄 {{ f.name }} <small>({{ formatSize(f.size) }})</small>
          </a>
        </div>
      </div>

      <!-- 状态行 -->
      <div v-if="message.error" class="status status-error">
        ⚠ {{ message.error }}<span v-if="timingLabel" class="elapsed">（{{ timingLabel }}）</span>
      </div>
      <div v-else-if="message.running" class="status status-running">
        <el-icon class="is-loading"><Loading /></el-icon> 正在生成…<span v-if="timingLabel" class="elapsed"> {{ timingLabel }}</span>
      </div>
      <div v-else-if="message.done" class="status status-done">
        ✓ 已完成<span v-if="timingLabel" class="elapsed">（{{ timingLabel }}）</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'
import ProcessSteps from './ProcessSteps.vue'
import MarkdownView from './MarkdownView.vue'

interface ChatMessageModel {
  role: 'user' | 'assistant'
  content?: string
  skills?: string[]
  thinking?: string
  steps?: Array<{
    step_id?: number
    kind: 'tool' | 'plan'
    tool_name?: string
    tool_input?: string
    tool_source?: string
    mcp_server?: string | null
    result?: string
    references?: string
    reference_cards?: Array<{ title?: string; url?: string; quote?: string }>
    title?: string
    text?: string
  }>
  texts?: string[]
  files?: Array<{ name: string; size: number; is_image: boolean }>
  error?: string
  running?: boolean
  done?: boolean
  /** S8：耗时三态（毫秒时间戳） */
  startedAt?: number
  /** P4-12：首个 token 的到达时刻（发送 → 首 token → 完成） */
  firstTokenAt?: number
  finishedAt?: number
}

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{
  message: ChatMessageModel
  skillsList?: Array<{ name: string }>
}>()

function fileUrl(name: string): string {
  return `/api/v1/files/${encodeURIComponent(name)}`
}
// ---- S8：耗时三态（进行中每秒刷新；完成/失败定格） ----
const now = ref(Date.now())
let ticker: ReturnType<typeof setInterval> | null = null

const elapsedMs = computed(() => {
  const started = props.message.startedAt
  if (!started) return 0
  const end = props.message.finishedAt ?? (props.message.running ? now.value : undefined)
  if (!end) return 0
  return Math.max(0, end - started)
})

function formatMs(ms: number): string {
  if (!ms || ms < 0) return ''
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60_000)
  const s = Math.round((ms % 60_000) / 1000)
  return `${m}m${s}s`
}

const elapsedLabel = computed(() => formatMs(elapsedMs.value))

/** P4-12：首 token 之前的等待时长（发送 → 首 token） */
const firstTokenLabel = computed(() => {
  const started = props.message.startedAt
  const first = props.message.firstTokenAt
  if (!started || !first) return ''
  return formatMs(first - started)
})

/** P4-12：三态耗时文案——「首字 x · 总 y」 */
const timingLabel = computed(() => {
  const first = firstTokenLabel.value
  const total = elapsedLabel.value
  if (first && total) return `首字 ${first} · 总 ${total}`
  if (first) return `首字 ${first}`
  if (total) return `总 ${total}`
  return ''
})

onMounted(() => {
  if (props.message.running) {
    ticker = setInterval(() => { now.value = Date.now() }, 1000)
  }
})
onBeforeUnmount(() => { if (ticker) clearInterval(ticker) })

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}
</script>

<style scoped>
.msg { padding: 10px 0; }
.user { text-align: right; }
.user-bubble { display: inline-block; background: var(--bg-bubble-user); padding: 10px 14px; border-radius: var(--radius); max-width: 80%; }
.assistant-msg { padding: 4px 0; }
.skills-bar { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
.thinking { margin: 4px 0 8px; }
.thinking summary { cursor: pointer; color: var(--text-dim); font-size: 12px; padding: 2px 0; }
.thinking pre { background: var(--bg-code); padding: 10px; border-radius: var(--radius-sm); font-size: 12px; max-height: 240px; overflow-y: auto; }
.texts { margin: 8px 0; }
.files { margin-top: 8px; }
.images { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 6px; }
.images img { max-width: 180px; max-height: 180px; border-radius: var(--radius-sm); border: 1px solid var(--border); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.file-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: var(--bg-sidebar); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text); text-decoration: none; }
.status { padding: 6px 0; font-size: 13px; }
.status-error { color: var(--red); }
.status-running { color: var(--text-dim); display: inline-flex; align-items: center; gap: 6px; }
.status-done { color: var(--green); }
.elapsed { color: var(--text-faint); font-size: 11px; margin-left: 4px; }
</style>