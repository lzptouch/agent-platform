<template>
  <div class="ctx-meter">
    <div class="head" @click="expanded = !expanded">
      <span class="label">上下文</span>
      <div class="bar">
        <div class="fill" :class="level" :style="{ width: pct + '%' }" />
      </div>
      <span class="pct">{{ pct }}%</span>
      <el-icon class="caret"><ArrowDown v-if="expanded" /><ArrowRight v-else /></el-icon>
    </div>
    <div v-if="expanded" class="detail">
      <div class="row">窗口 {{ usage.window?.toLocaleString?.() ?? '-' }} tokens · 占用 {{ usage.tokens ?? 0 }} tokens</div>
      <div class="row">压缩阈值 {{ thresholds.compact }} / {{ thresholds.summary }}</div>
      <div v-if="events.length" class="events">
        <div v-for="(e, i) in events" :key="i" class="event">
          {{ e.mode }}：{{ e.before_tokens }} → {{ e.after_tokens }}（省 {{ e.saved_tokens }}）
        </div>
      </div>
      <div v-else class="row dim">本次尚无压缩事件</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import { sessionContext } from '@/api'

const props = defineProps<{ sessionId?: string | null; events?: Array<Record<string, unknown>> }>()

/** 压缩事件（可由父级传入运行事件流里��� `context_compressed`） */
const events = computed<Array<Record<string, unknown>>>(() => props.events ?? [])

const usage = ref<Record<string, unknown>>({})
const window = ref(0)
const thresholds = ref({ compact: 0.7, summary: 0.85 })
const expanded = ref(false)

const pct = computed(() => Math.min(100, Math.round(Number(usage.value.ratio ?? 0) * 100)))
const level = computed(() => {
  const r = Number(usage.value.ratio ?? 0)
  if (r >= 0.85) return 'danger'
  if (r >= 0.7) return 'warn'
  return 'ok'
})

async function load(): Promise<void> {
  if (!props.sessionId) return
  try {
    const data = await sessionContext(props.sessionId)
    usage.value = (data.usage ?? {}) as Record<string, unknown>
    window.value = Number(data.window ?? 0)
    thresholds.value = (data.thresholds ?? thresholds.value) as { compact: number; summary: number }
  } catch {
    // 忽略
  }
}

watch(() => props.sessionId, load)
onMounted(load)
</script>

<style scoped>
.ctx-meter { font-size: 12px; color: var(--text-dim); }
.head { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.label { color: var(--text-faint); }
.bar { flex: 1; height: 6px; background: var(--bg-hover); border-radius: 999px; overflow: hidden; }
.fill { height: 100%; background: var(--el-color-success); }
.fill.warn { background: var(--el-color-warning); }
.fill.danger { background: var(--el-color-danger); }
.pct { min-width: 34px; text-align: right; }
.detail { padding: 6px 0 0 4px; }
.row { color: var(--text-dim); }
.row.dim { color: var(--text-faint); }
.events { margin-top: 4px; }
.event { color: var(--text-faint); font-size: 11px; }
.caret { font-size: 11px; }
</style>
