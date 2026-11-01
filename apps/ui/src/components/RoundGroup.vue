<template>
  <div v-if="steps.length" class="round-group">
    <button class="rg-head" :title="summary || '本轮无摘要'" @click="onToggle">
      <el-icon class="caret"><ArrowDown v-if="!collapsed" /><ArrowRight v-else /></el-icon>
      <span class="rg-title">第 {{ round }} 轮</span>
      <span class="rg-summary">{{ summary || '（无摘要）' }}</span>
    </button>
    <div v-show="!collapsed" class="rg-body">
      <ProcessSteps :steps="steps" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import ProcessSteps from './ProcessSteps.vue'
import { useRoundsStore } from '@/stores/rounds'

const props = defineProps<{
  runId: string
  round: number
  summary?: string
  steps: Array<{
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
}>()

const rounds = useRoundsStore()

/** 折叠态由 ``stores/rounds`` 统一持有（runId:roundNo → 是否折叠）。 */
const collapsed = computed(() => rounds.isCollapsed(props.runId, props.round))

function onToggle(): void {
  rounds.toggle(props.runId, props.round)
}
</script>

<style scoped>
.round-group { border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-sidebar); margin-bottom: 8px; }
.rg-head {
  display: flex; align-items: center; gap: 8px; width: 100%;
  padding: 6px 10px; cursor: pointer; user-select: none; font-size: 12.5px; color: var(--text-dim);
  background: transparent; border: none; text-align: left;
}
.rg-head:hover { color: var(--text); }
.rg-title { font-weight: 500; color: var(--text); }
.rg-summary { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.caret { font-size: 11px; }
.rg-body { padding: 0 8px 8px; }
</style>
