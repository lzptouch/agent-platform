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
      <div v-if="message.error" class="status status-error">⚠ {{ message.error }}</div>
      <div v-else-if="message.running" class="status status-running"><el-icon class="is-loading"><Loading /></el-icon> 正在生成…</div>
      <div v-else-if="message.done" class="status status-done">✓ 已完成</div>
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
}

defineProps<{
  message: ChatMessageModel
  skillsList?: Array<{ name: string }>
}>()

function fileUrl(name: string): string {
  return `/api/v1/files/${encodeURIComponent(name)}`
}
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
</style>