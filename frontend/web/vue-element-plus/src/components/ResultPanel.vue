<template>
  <aside class="result-panel" :class="{ collapsed }">
    <div class="panel-head">
      <div class="tabs">
        <button
          v-for="t in tabs" :key="t.key"
          class="tab" :class="{ on: activeTab === t.key }"
          @click="activeTab = t.key"
        >{{ t.label }}</button>
      </div>
      <button class="collapse-btn" :title="collapsed ? '展开' : '折叠'" @click="collapsed = !collapsed">
        <el-icon><ArrowLeft v-if="!collapsed" /><ArrowRight v-else /></el-icon>
      </button>
    </div>
    <div v-show="!collapsed" class="panel-body">
      <ResultArtifacts v-if="activeTab === 'artifacts'" :run-id="runId" />
      <ResultFiles v-else-if="activeTab === 'files'" :run-id="runId" />
      <ResultChanges v-else-if="activeTab === 'changes'" :run-id="runId" :workspace-id="workspaceId" />
      <div v-else class="browser-placeholder">浏览器视图（自动化任务页面/截图，后续接入）</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import ResultArtifacts from './ResultArtifacts.vue'
import ResultChanges from './ResultChanges.vue'
import ResultFiles from './ResultFiles.vue'

defineProps<{ runId?: string | null; workspaceId?: string | null }>()

const tabs = [
  { key: 'artifacts', label: '产物' },
  { key: 'files', label: '文件' },
  { key: 'changes', label: '变更' },
  { key: 'browser', label: '浏览器' },
]
const activeTab = ref('artifacts')
const COLLAPSE_KEY = '__result_panel_collapsed'

function readCollapsed(): boolean {
  try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
}

const collapsed = ref(readCollapsed())

watch(collapsed, (v) => {
  try { localStorage.setItem(COLLAPSE_KEY, v ? '1' : '0') } catch { /* */ }
})

// 窄屏（<1280px）自动折叠右栏
function onResize(): void {
  if (typeof window !== 'undefined' && window.innerWidth < 1280) {
    collapsed.value = true
  }
}
onMounted(() => { onResize(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => { window.removeEventListener('resize', onResize) })
</script>

<style scoped>
.result-panel {
  width: 360px; flex: none; border-left: 1px solid var(--border);
  display: flex; flex-direction: column; background: var(--bg-panel);
}
.result-panel.collapsed { width: 40px; }
.panel-head { display: flex; align-items: center; border-bottom: 1px solid var(--border); }
.tabs { display: flex; flex: 1; }
.tab { padding: 8px 10px; background: none; border: none; color: var(--text-dim); cursor: pointer; font-size: 13px; }
.tab.on { color: var(--text); border-bottom: 2px solid var(--accent); }
.collapse-btn { background: none; border: none; color: var(--text-dim); cursor: pointer; padding: 8px; }
.panel-body { flex: 1; overflow-y: auto; }
.browser-placeholder { padding: 24px; color: var(--text-faint); font-size: 13px; text-align: center; }
</style>
