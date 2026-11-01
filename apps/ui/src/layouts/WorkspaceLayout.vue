<template>
  <div class="ws-layout">
    <SideNav v-if="!composeMode" variant="workspace" @search="searchVisible = true" />
    <main class="ws-main">
      <router-view />
    </main>

    <!-- ⌘K 全局搜索（计划 §6 阶段 4） -->
    <el-dialog v-model="searchVisible" title="搜索" width="520px" class="search-dialog">
      <el-input
        v-model="keyword"
        placeholder="搜索任务 / 空间 / 技能 / 产物"
        clearable
        autofocus
        @keydown.esc="searchVisible = false"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <div class="search-results">
        <div v-if="!keyword" class="hint">输入关键字开始搜索</div>
        <div v-for="t in matchedTasks" :key="t.id" class="row" @click="openTask(t.id)">
          <el-icon><ChatDotRound /></el-icon><span>{{ t.title || '未命名任务' }}</span>
        </div>
        <div v-for="s in matchedSpaces" :key="s.id" class="row">
          <el-icon><Folder /></el-icon><span>{{ s.name }}</span>
        </div>
        <div v-for="k in matchedSkills" :key="k.name" class="row" @click="openSkills">
          <el-icon><MagicStick /></el-icon><span>{{ k.name }}</span>
        </div>
        <div v-if="keyword && !matchedTasks.length && !matchedSpaces.length && !matchedSkills.length" class="hint">
          未找到匹配结果
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Search, ChatDotRound, Folder, MagicStick } from '@element-plus/icons-vue'
import SideNav from '@/components/layout/SideNav.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useConfigStore } from '@/stores/config'

const router = useRouter()
const route = useRoute()
const ws = useWorkspaceStore()
const config = useConfigStore()

/** 速记形态（批次 02）：``?compose=1`` —— 只留输入区，不显示侧栏。 */
const composeMode = computed(() => route.query.compose === '1')

const searchVisible = ref(false)
const keyword = ref('')

const matchedTasks = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return []
  return ws.tasks.filter(t => (t.title || '').toLowerCase().includes(k)).slice(0, 8)
})
const matchedSpaces = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return []
  return ws.spaces.filter(s => s.name.toLowerCase().includes(k)).slice(0, 5)
})
const matchedSkills = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return []
  return config.skills.filter(s => s.name.toLowerCase().includes(k)).slice(0, 5)
})

function openTask(id: string) {
  ws.selectTask(id)
  searchVisible.value = false
  router.push({ path: '/workspace', query: { task: id } })
}
function openSkills() {
  searchVisible.value = false
  router.push('/admin/capabilities')
}

function onKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    searchVisible.value = !searchVisible.value
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  if (!config.ready) void config.init()
  void ws.loadTasks()
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.ws-layout { display: flex; height: 100vh; overflow: hidden; }
.ws-main { flex: 1; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.search-results { margin-top: 12px; max-height: 320px; overflow: auto; }
.search-results .row {
  display: flex; align-items: center; gap: 8px; padding: 7px 8px; border-radius: var(--radius-sm);
  cursor: pointer; font-size: 13px;
}
.search-results .row:hover { background: var(--bg-hover); }
.hint { color: var(--text-faint); font-size: 12px; padding: 8px; }
</style>
