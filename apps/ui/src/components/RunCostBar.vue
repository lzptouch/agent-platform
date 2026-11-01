<template>
  <div class="cost-bar">
    <div class="item">
      <span class="label">消耗</span>
      <span class="value" :class="{ live: running }">
        {{ running ? '进行中…' : actualLabel }}
      </span>
    </div>
    <div class="item" v-if="rangeLabel">
      <span class="label">区间</span>
      <span class="value dim">{{ rangeLabel }}</span>
    </div>
    <div class="item" v-if="tokens">
      <span class="label">Token</span>
      <span class="value dim">{{ tokens }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { costEstimate, runCost } from '@/api'

const props = defineProps<{ runId?: string | null; running?: boolean; model?: string }>()

const cost = ref(0)
const promptTokens = ref(0)
const completionTokens = ref(0)
const p50 = ref<number | null>(null)
const p90 = ref<number | null>(null)

const actualLabel = computed(() => `$${cost.value.toFixed(4)}`)
const tokens = computed(() => promptTokens.value + completionTokens.value)
const rangeLabel = computed(() => {
  if (p50.value == null || p90.value == null) return ''
  return `$${p50.value.toFixed(4)} ~ $${p90.value.toFixed(4)}`
})

async function load(): Promise<void> {
  if (!props.runId) return
  try {
    const detail = await runCost(props.runId)
    cost.value = detail.totals.estimated_cost ?? 0
    promptTokens.value = detail.totals.prompt_tokens ?? 0
    completionTokens.value = detail.totals.completion_tokens ?? 0
  } catch {
    // 取不到就保持原值（不阻断）
  }
}

async function loadEstimate(): Promise<void> {
  try {
    const est = await costEstimate(props.model)
    p50.value = est.percentiles.p50
    p90.value = est.percentiles.p90
  } catch {
    // 无历史样本时无区间
  }
}

watch(() => props.runId, load)
onMounted(() => {
  void load()
  void loadEstimate()
})
</script>

<style scoped>
.cost-bar { display: flex; gap: 12px; align-items: center; font-size: 12px; color: var(--text-dim); }
.item { display: inline-flex; gap: 4px; align-items: center; }
.label { color: var(--text-faint); }
.value { color: var(--text); }
.value.dim { color: var(--text-dim); }
.value.live { color: var(--el-color-primary); }
</style>
