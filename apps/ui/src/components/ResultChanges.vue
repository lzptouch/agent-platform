<template>
  <div class="result-changes">
    <div v-if="!items.length" class="empty">暂无变更</div>
    <div v-for="c in items" :key="c.id" class="change">
      <div class="row" @click="toggle(c.id)">
        <span class="op" :class="c.op">{{ opLabel(c.op) }}</span>
        <span class="path">{{ c.path }}</span>
        <el-icon class="caret"><ArrowDown v-if="expanded.has(c.id)" /><ArrowRight v-else /></el-icon>
      </div>
      <div v-if="expanded.has(c.id)" class="detail">
        <pre v-if="diffs[c.id]?.kind === 'text'" class="diff">{{ diffs[c.id]?.diff }}</pre>
        <div v-else class="binary">{{ diffs[c.id]?.summary }}</div>
        <el-button size="small" type="warning" plain :disabled="!c.snapshot_ref" @click="revert(c.id)">回退</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { changeDiff, changeRevert, runChanges, type ChangeItem } from '@/api'

const props = defineProps<{ runId?: string | null; workspaceId?: string | null }>()
const items = ref<ChangeItem[]>([])
const expanded = reactive(new Set<number>())
const diffs = reactive<Record<number, { kind: string; diff?: string; summary?: string }>>({})

function opLabel(op: string): string {
  return { create: '新增', modify: '修改', delete: '删除', revert: '回退' }[op] ?? op
}

async function load(): Promise<void> {
  if (!props.runId) { items.value = []; return }
  try {
    const data = await runChanges(props.runId)
    items.value = data.items
  } catch {
    items.value = []
  }
}

async function toggle(id: number): Promise<void> {
  if (expanded.has(id)) { expanded.delete(id); return }
  expanded.add(id)
  if (!diffs[id]) {
    try { diffs[id] = await changeDiff(id) } catch { diffs[id] = { kind: 'text', diff: '(diff 不可用)' } }
  }
}

async function revert(id: number): Promise<void> {
  try {
    await ElMessageBox.confirm('确认回退该文件到修改前内容？', '回退变更', { type: 'warning' })
    await changeRevert(id, props.workspaceId ?? undefined)
    ElMessage.success('已回退')
    await load()
  } catch { /* 用户取消 */ }
}

watch(() => props.runId, load)
onMounted(load)
</script>

<style scoped>
.result-changes { padding: 8px; }
.empty { color: var(--text-faint); text-align: center; padding: 24px; font-size: 13px; }
.change { border-radius: 6px; margin-bottom: 4px; }
.row { display: flex; align-items: center; gap: 8px; padding: 6px 8px; cursor: pointer; }
.row:hover { background: var(--bg-hover); }
.op { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: var(--bg-code); }
.op.create { color: var(--el-color-success); }
.op.modify { color: var(--el-color-warning); }
.op.delete { color: var(--el-color-danger); }
.path { flex: 1; font-size: 12px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail { padding: 6px 8px 8px 28px; }
.diff { font-size: 11px; background: var(--bg-code); padding: 8px; border-radius: 6px; overflow: auto; max-height: 240px; white-space: pre-wrap; }
.binary { font-size: 12px; color: var(--text-dim); }
</style>
