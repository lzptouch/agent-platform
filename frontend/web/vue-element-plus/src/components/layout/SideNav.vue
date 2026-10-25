<template>
  <aside class="sidenav" :class="{ collapsed }">
    <!-- 顶部工具条 -->
    <div class="nav-top">
      <button class="icon-btn" title="折叠/展开" @click="onToggle">
        <el-icon><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
      </button>
      <button class="icon-btn" title="搜索（⌘K）" @click="emit('search')">
        <el-icon><Search /></el-icon>
      </button>
    </div>

    <!-- 工作台形态：能力入口 + 任务流 -->
    <template v-if="variant === 'workspace'">
      <div class="brand">
        <span class="logo">A</span>
        <span v-if="!collapsed" class="name">Agent Platform</span>
      </div>

      <nav class="nav-list">
        <button class="nav-item primary" :class="{ active: isWorkspace }" @click="goWorkspace">
          <el-icon><Plus /></el-icon>
          <span v-if="!collapsed">新建任务</span>
        </button>
        <button class="nav-item" @click="go('/assistant')">
          <el-icon><ChatDotRound /></el-icon>
          <span v-if="!collapsed">助理</span>
        </button>
        <button class="nav-item" @click="go('/spaces')">
          <el-icon><Folder /></el-icon>
          <span v-if="!collapsed">项目</span>
        </button>
        <button class="nav-item" @click="go('/admin/capabilities')">
          <el-icon><Connection /></el-icon>
          <span v-if="!collapsed">专家·技能·连接器</span>
        </button>
        <button class="nav-item" @click="go('/admin/schedules')">
          <el-icon><AlarmClock /></el-icon>
          <span v-if="!collapsed">自动化</span>
        </button>
        <button class="nav-item" @click="go('/admin/artifacts')">
          <el-icon><Files /></el-icon>
          <span v-if="!collapsed">产物</span>
        </button>
      </nav>

      <!-- 任务流（计划 A2：常驻主区左侧） -->
      <div v-if="!collapsed" class="group">
        <div class="group-head" @click="tasksOpen = !tasksOpen">
          <span>任务 ({{ ws.tasks.length }})</span>
          <el-icon class="caret"><ArrowDown v-if="tasksOpen" /><ArrowRight v-else /></el-icon>
        </div>
        <div v-show="tasksOpen" class="group-body">
          <div
            v-for="t in ws.tasks"
            :key="t.id"
            class="task-item"
            :class="{ active: t.id === ws.currentTaskId }"
            @click="selectTask(t.id)"
          >
            <span class="task-title">{{ t.title || '未命名任务' }}</span>
            <span class="task-meta">{{ t.message_count }}</span>
          </div>
          <div v-if="!ws.tasks.length" class="empty-hint">暂无任务</div>
        </div>
      </div>

      <!-- 空间（计划 A7：空间即文件夹） -->
      <div v-if="!collapsed" class="group">
        <div class="group-head" @click="spacesOpen = !spacesOpen">
          <span>空间 ({{ ws.spaces.length }})</span>
          <el-icon class="caret"><ArrowDown v-if="spacesOpen" /><ArrowRight v-else /></el-icon>
        </div>
        <div v-show="spacesOpen" class="group-body">
          <div v-for="s in ws.spaces" :key="s.id" class="task-item">
            <el-icon><Folder /></el-icon>
            <span class="task-title">{{ s.name }}</span>
            <span class="task-meta">{{ s.sessionIds.length }}</span>
          </div>
          <div v-if="!ws.spaces.length" class="empty-hint">暂无空间</div>
        </div>
      </div>
    </template>

    <!-- 后台形态：沿用 13 个功能入口 -->
    <template v-else>
      <div class="brand">
        <span class="logo">A</span>
        <span v-if="!collapsed" class="name">Agent Platform</span>
      </div>
      <nav class="nav-list">
        <button
          v-for="it in adminItems"
          :key="it.path"
          class="nav-item"
          :class="{ active: route.path === it.path }"
          @click="go(it.path)"
        >
          <el-icon><component :is="it.icon" /></el-icon>
          <span v-if="!collapsed">{{ it.label }}</span>
        </button>
      </nav>
    </template>

    <!-- 底部账号区 -->
    <div class="nav-bottom">
      <div v-if="!collapsed" class="account">
        <span class="avatar">A</span>
        <span class="acc-text">
          <span class="acc-name">本地用户</span>
          <span class="acc-ver">v0.1.0 · 单机版</span>
        </span>
      </div>
      <el-tooltip content="切换 v3 工作台（灰度开关）" placement="right">
        <button class="icon-btn" :class="{ on: flags.v3 }" @click="flags.toggleV3()">
          <el-icon><Switch /></el-icon>
        </button>
      </el-tooltip>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Fold, Expand, Search, Plus, ChatDotRound, Folder, Connection,
  AlarmClock, Files, Switch, ArrowDown, ArrowRight,
  Document, MagicStick, Monitor, Setting, DataAnalysis, UserFilled, Suitcase,
} from '@element-plus/icons-vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { useFlagsStore } from '@/stores/flags'

const props = defineProps<{ variant?: 'workspace' | 'admin' }>()
const emit = defineEmits<{ (e: 'search'): void }>()

const route = useRoute()
const router = useRouter()
const ws = useWorkspaceStore()
const flags = useFlagsStore()

const variant = computed(() => props.variant ?? 'workspace')
const collapsed = computed(() => ws.sidebarCollapsed)
const isWorkspace = computed(() => route.path === '/workspace')

const tasksOpen = ref(true)
const spacesOpen = ref(false)

const adminItems = [
  { path: '/chat', label: '对话（旧）', icon: ChatDotRound },
  { path: '/work', label: '工作（旧）', icon: Suitcase },
  { path: '/admin/capabilities', label: '专家·技能·连接器', icon: UserFilled },
  { path: '/admin/schedules', label: '自动化', icon: AlarmClock },
  { path: '/admin/research', label: '深度研究', icon: DataAnalysis },
  { path: '/admin/artifacts', label: '我的产物', icon: Files },
  { path: '/admin/knowledge', label: 'RAG 知识库', icon: Document },
  { path: '/admin/web', label: 'Web 检索', icon: Search },
  { path: '/admin/lab/wr', label: 'WR 范式', icon: MagicStick },
  { path: '/admin/status', label: '系统状态', icon: Monitor },
  { path: '/admin/settings', label: '设置', icon: Setting },
]

function go(path: string) { router.push(path) }
function goWorkspace() { router.push('/workspace') }
function onToggle() { ws.toggleSidebar() }
function selectTask(id: string) {
  ws.selectTask(id)
  router.push({ path: '/workspace', query: { task: id } })
}
</script>

<style scoped>
.sidenav {
  width: 240px;
  flex: 0 0 240px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.15s ease, flex-basis 0.15s ease;
}
.sidenav.collapsed { width: 56px; flex-basis: 56px; }
.nav-top { display: flex; gap: 2px; padding: 10px 10px 4px; }
.icon-btn {
  width: 28px; height: 28px; border: none; background: transparent; color: var(--text-dim);
  border-radius: var(--radius-sm); cursor: pointer; display: grid; place-items: center;
}
.icon-btn:hover { background: var(--bg-hover); color: var(--text); }
.icon-btn.on { background: var(--accent-light); color: var(--accent); }
.brand { display: flex; align-items: center; gap: 8px; padding: 6px 14px 12px; }
.brand .logo {
  width: 24px; height: 24px; background: var(--accent); color: #fff; border-radius: 6px;
  display: grid; place-items: center; font-weight: 700; font-size: 13px; flex: 0 0 24px;
}
.brand .name { font-weight: 600; font-size: 14px; white-space: nowrap; }
.nav-list { padding: 0 8px; display: flex; flex-direction: column; gap: 1px; }
.nav-item {
  display: flex; align-items: center; gap: 9px; width: 100%;
  padding: 7px 8px; border: none; background: transparent; color: var(--text);
  border-radius: var(--radius-sm); cursor: pointer; font-size: 13.5px; text-align: left;
}
.nav-item:hover { background: var(--bg-hover); }
.nav-item.active { background: var(--bg-hover); font-weight: 600; }
.nav-item.primary { color: var(--text); }
.group { margin-top: 14px; padding: 0 8px; }
.group-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 8px; font-size: 12px; color: var(--text-dim); cursor: pointer; user-select: none;
}
.group-head:hover { color: var(--text); }
.group-body { display: flex; flex-direction: column; gap: 1px; }
.task-item {
  display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-radius: var(--radius-sm);
  cursor: pointer; font-size: 13px; color: var(--text);
}
.task-item:hover { background: var(--bg-hover); }
.task-item.active { background: var(--bg-hover); font-weight: 600; }
.task-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-meta { color: var(--text-faint); font-size: 11px; }
.empty-hint { padding: 6px 8px; font-size: 12px; color: var(--text-faint); }
.nav-bottom {
  margin-top: auto; border-top: 1px solid var(--border); padding: 10px 12px;
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
}
.account { display: flex; align-items: center; gap: 8px; min-width: 0; }
.avatar {
  width: 26px; height: 26px; border-radius: 50%; background: var(--accent); color: #fff;
  display: grid; place-items: center; font-size: 12px; flex: 0 0 26px;
}
.acc-text { display: flex; flex-direction: column; line-height: 1.25; min-width: 0; }
.acc-name { font-size: 12.5px; }
.acc-ver { font-size: 10.5px; color: var(--text-faint); }
</style>
