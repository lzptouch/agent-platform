<template>
  <div v-if="steps.length" class="timeline">
    <div class="tl-head" @click="open = !open">
      <el-icon class="ci"><Operation /></el-icon>
      <span class="tl-title">执行轨迹</span>
      <span class="tl-count">{{ steps.length }}</span>
      <el-icon class="caret"><ArrowDown v-if="open" /><ArrowRight v-else /></el-icon>
    </div>
    <div v-show="open" class="tl-body">
      <ProcessSteps :steps="steps" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Operation, ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import ProcessSteps from './ProcessSteps.vue'

defineProps<{
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
  running?: boolean
}>()

const open = ref(false)
</script>

<style scoped>
.timeline { border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-sidebar); margin-bottom: 8px; }
.tl-head {
  display: flex; align-items: center; gap: 7px; padding: 6px 10px; cursor: pointer;
  user-select: none; font-size: 12.5px; color: var(--text-dim);
}
.tl-head:hover { color: var(--text); }
.tl-title { font-weight: 500; }
.tl-count {
  background: var(--bg); border: 1px solid var(--border); border-radius: 999px;
  padding: 0 6px; font-size: 11px; color: var(--text-faint);
}
.caret { margin-left: auto; font-size: 11px; }
.tl-body { padding: 0 8px 8px; }
</style>
