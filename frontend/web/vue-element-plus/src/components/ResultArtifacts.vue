<template>
  <div class="result-artifacts">
    <div v-if="!items.length" class="empty">暂无交付物</div>
    <div v-for="a in items" :key="a.id" class="artifact">
      <el-icon class="icon"><Document /></el-icon>
      <div class="meta">
        <div class="title">{{ a.title || a.path }}</div>
        <div class="sub">{{ a.kind }} · {{ a.size ?? '?' }}B</div>
      </div>
      <el-button size="small" text @click="saveAs(a)">另存</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { runArtifacts, type ArtifactItem } from '@/api'

const props = defineProps<{ runId?: string | null }>()
const items = ref<ArtifactItem[]>([])

async function load(): Promise<void> {
  if (!props.runId) { items.value = []; return }
  try {
    const data = await runArtifacts(props.runId)
    items.value = data.items
  } catch {
    items.value = []
  }
}

function saveAs(a: ArtifactItem): void {
  // 桌面态走原生保存对话框（preload saveArtifact）；Web 态给路径提示
  ElMessage.info(`另存：${a.title || a.path}`)
}

watch(() => props.runId, load)
onMounted(load)
</script>

<style scoped>
.result-artifacts { padding: 8px; }
.empty { color: var(--text-faint); text-align: center; padding: 24px; font-size: 13px; }
.artifact { display: flex; align-items: center; gap: 8px; padding: 8px; border-radius: 6px; }
.artifact:hover { background: var(--bg-hover); }
.icon { color: var(--text-dim); }
.meta { flex: 1; min-width: 0; }
.title { font-size: 13px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: 11px; color: var(--text-faint); }
</style>
