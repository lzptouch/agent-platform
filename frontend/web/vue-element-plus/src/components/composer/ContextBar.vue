<template>
  <div class="context-bar">
    <button class="item" title="选择工作空间（后端 output_dir）" @click="emit('workspace')">
      <el-icon><Folder /></el-icon>
      <span class="label">工作空间</span>
      <span class="value">{{ workspace || '默认输出目录' }}</span>
      <el-icon class="caret"><ArrowDown /></el-icon>
    </button>

    <span class="divider" />

    <button class="item" :class="levelClass" title="默认权限（三态：只读 / 询问 / 可写）" @click="emit('toggle-permission')">
      <el-icon><Lock v-if="level === 'readonly'" /><Warning v-else-if="level === 'ask'" /><Unlock v-else /></el-icon>
      <span class="label">默认权限</span>
      <span class="value">{{ levelLabel }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Folder, ArrowDown, Lock, Unlock, Warning } from '@element-plus/icons-vue'

const props = defineProps<{ workspace?: string; permissive?: boolean; level?: 'readonly' | 'ask' | 'allow' }>()
const level = computed(() => props.level ?? (props.permissive ? 'allow' : 'readonly'))
const levelLabel = computed(() => ({ readonly: '只读', ask: '询问', allow: '可写' }[level.value]))
const levelClass = computed(() => ({ on: level.value === 'allow', ask: level.value === 'ask' }))
const emit = defineEmits<{
  (e: 'workspace'): void
  (e: 'toggle-permission'): void
}>()
</script>

<style scoped>
.context-bar { display: flex; align-items: center; gap: 6px; justify-content: center; margin-top: 8px; }
.item {
  display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px;
  border: 1px solid transparent; background: transparent; color: var(--text-dim);
  border-radius: 999px; font-size: 12px; cursor: pointer;
}
.item:hover { background: var(--bg-hover); color: var(--text); }
.item.on { color: var(--accent); }
.item.ask { color: var(--el-color-warning); }
.label { color: var(--text-faint); }
.value { color: var(--text); }
.divider { width: 1px; height: 12px; background: var(--border); }
.caret { font-size: 11px; }
</style>
