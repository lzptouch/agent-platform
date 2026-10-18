<template>
  <div class="steps">
    <div v-for="(step, i) in steps" :key="step.step_id ?? i" class="step" :class="`src-${step.tool_source || (step.kind === 'plan' ? 'plan' : 'builtin')}`">
      <div class="step-head" @click="toggle(i)">
        <span class="dot" />
        <span class="title">
          <template v-if="step.kind === 'plan'">{{ step.title || '计划步骤' }}</template>
          <template v-else>{{ step.tool_name }}</template>
        </span>
        <span class="src-label">{{ step.tool_source || (step.kind === 'plan' ? 'plan' : 'builtin') }}</span>
        <span class="caret">{{ open.has(i) ? '▾' : '▸' }}</span>
      </div>
      <div v-show="open.has(i)" class="step-body">
        <div v-if="step.tool_input && step.kind === 'tool'" class="block">
          <div class="block-label">入参</div>
          <pre>{{ formatJson(step.tool_input) }}</pre>
        </div>
        <div v-if="step.text && step.kind === 'plan'" class="block">
          <pre>{{ step.text }}</pre>
        </div>
        <div v-if="step.result !== undefined" class="block">
          <div class="block-label">结果</div>
          <pre>{{ step.result }}</pre>
        </div>
        <div v-if="step.references" class="block">
          <div class="block-label">参考</div>
          <pre>{{ step.references }}</pre>
        </div>
        <div v-if="step.reference_cards?.length" class="block">
          <div class="block-label">引用卡片</div>
          <el-card v-for="(c, j) in step.reference_cards" :key="j" class="ref-card" shadow="never">
            <a v-if="c.url" :href="c.url" target="_blank">{{ c.title || c.url }}</a>
            <span v-else>{{ c.title || '引用' }}</span>
            <div v-if="c.quote" class="quote">{{ c.quote }}</div>
          </el-card>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

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
}>()

const open = ref(new Set<number>())

function toggle(i: number) {
  if (open.value.has(i)) open.value.delete(i)
  else open.value.add(i)
  // 触发响应
  open.value = new Set(open.value)
}

function formatJson(s: string): string {
  // tool_input 已是 JSON 字符串；尝试 pretty
  try { return JSON.stringify(JSON.parse(s), null, 2) }
  catch { return s }
}
</script>

<style scoped>
.steps { margin: 6px 0; display: flex; flex-direction: column; gap: 4px; }
.step { border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-sidebar); }
.step-head { display: flex; align-items: center; gap: 8px; padding: 6px 10px; cursor: pointer; user-select: none; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
.src-mcp .dot { background: var(--purple); }
.src-rag .dot { background: var(--green); }
.src-web .dot { background: var(--orange); }
.src-plan .dot { background: var(--teal); }
.title { flex: 1; font-weight: 500; }
.src-label { font-size: 11px; color: var(--text-dim); padding: 1px 6px; border-radius: 4px; background: var(--bg); }
.caret { color: var(--text-dim); font-size: 10px; }
.step-body { padding: 4px 10px 10px; border-top: 1px dashed var(--border); }
.block { margin-top: 6px; }
.block-label { font-size: 11px; color: var(--text-dim); margin-bottom: 2px; }
.block pre { background: var(--bg-code); padding: 8px 10px; border-radius: 6px; margin: 0; font-size: 12px; max-height: 320px; overflow: auto; white-space: pre-wrap; }
.ref-card { margin: 4px 0; }
.ref-card a { color: var(--accent); }
.ref-card .quote { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
</style>