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
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  runArtifactDownloadUrl,
  runArtifactSaveAs,
  runArtifacts,
  type ArtifactItem,
} from '@/api'

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

async function saveAs(a: ArtifactItem): Promise<void> {
  // P2-21：此前只 `ElMessage.info` 后**不调端点、不调原生对话框** → 按钮永不生效。
  // 现在：桌面态走**原生保存对话框**；Web 态让用户输入目标路径后调 save-as 端点。
  if (!props.runId) {
    ElMessage.warning('缺少 run id，无法另存')
    return
  }
  const bridge = window.agentDesktop
  if (bridge?.saveArtifact) {
    const res = await bridge.saveArtifact({
      url: runArtifactDownloadUrl(props.runId, a.id),
      suggestedName: a.title || a.path,
    })
    if (res?.ok) ElMessage.success('已保存到所选位置')
    else ElMessage.error(res?.error?.message || '另存失败')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt('请输入保存到的目标路径', '另存产物', {
      inputValue: a.title || a.path,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    await runArtifactSaveAs(props.runId, a.id, value)
    ElMessage.success('已保存')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error('另存失败')
  }
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
