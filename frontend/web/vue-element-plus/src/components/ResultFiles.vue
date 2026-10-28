<template>
  <div class="result-files">
    <div v-if="!files.length" class="empty">工作空间内暂无文件</div>
    <div v-for="f in files" :key="f.path" class="file">
      <el-icon><Folder v-if="f.is_dir" /><Document v-else /></el-icon>
      <span class="name">{{ f.path }}</span>
      <span class="size">{{ f.is_dir ? '—' : `${f.size}B` }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Document, Folder } from '@element-plus/icons-vue'

interface FileEntry { path: string; is_dir: boolean; size: number }

// 本阶段：文件视图展示工作空间内文件（变更 + 产物的并集，后续可接文件树接口）
const props = defineProps<{ runId?: string | null; changes?: unknown[]; artifacts?: unknown[] }>()

const files = computed<FileEntry[]>(() => {
  const out: FileEntry[] = []
  const seen = new Set<string>()
  for (const c of (props.changes as Array<{ path: string }> | undefined) ?? []) {
    if (!seen.has(c.path)) { seen.add(c.path); out.push({ path: c.path, is_dir: false, size: 0 }) }
  }
  for (const a of (props.artifacts as Array<{ path: string; size?: number }> | undefined) ?? []) {
    if (!seen.has(a.path)) { seen.add(a.path); out.push({ path: a.path, is_dir: false, size: a.size ?? 0 }) }
  }
  return out
})
</script>

<style scoped>
.result-files { padding: 8px; }
.empty { color: var(--text-faint); text-align: center; padding: 24px; font-size: 13px; }
.file { display: flex; align-items: center; gap: 8px; padding: 6px 8px; font-size: 13px; }
.name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.size { color: var(--text-faint); font-size: 11px; }
</style>
