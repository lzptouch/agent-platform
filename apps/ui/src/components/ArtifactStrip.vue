<template>
  <div v-if="files.length" class="artifacts">
    <span class="label">产物</span>
    <div class="items">
      <a
        v-for="f in files"
        :key="f.name"
        class="art"
        :href="fileUrl(f.name)"
        target="_blank"
        :title="f.name"
      >
        <img v-if="f.is_image" :src="fileUrl(f.name)" :alt="f.name" />
        <template v-else>
          <el-icon><Document /></el-icon>
          <span class="n">{{ f.name }}</span>
          <small>{{ formatSize(f.size) }}</small>
        </template>
      </a>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Document } from '@element-plus/icons-vue'

defineProps<{ files: Array<{ name: string; size: number; is_image: boolean }> }>()

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
.artifacts { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.artifacts .label { font-size: 11.5px; color: var(--text-faint); }
.items { display: flex; gap: 8px; flex-wrap: wrap; }
.art {
  display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px;
  background: var(--bg-sidebar); border: 1px solid var(--border); border-radius: var(--radius-sm);
  color: var(--text); text-decoration: none; font-size: 12.5px; max-width: 220px;
}
.art:hover { border-color: var(--border-strong); }
.art img { width: 40px; height: 40px; object-fit: cover; border-radius: 4px; }
.art .n { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.art small { color: var(--text-faint); font-size: 11px; }
</style>
