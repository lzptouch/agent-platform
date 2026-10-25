import { createRouter, createWebHistory } from 'vue-router'
import WorkspaceLayout from '@/layouts/WorkspaceLayout.vue'
import AdminLayout from '@/layouts/AdminLayout.vue'
import WorkspaceView from '@/views/WorkspaceView.vue'
import CapabilitiesView from '@/views/CapabilitiesView.vue'
import ChatView from '@/views/ChatView.vue'
import WorkView from '@/views/WorkView.vue'
import ResearchView from '@/views/ResearchView.vue'
import SystemStatusView from '@/views/SystemStatusView.vue'
import FilesView from '@/views/FilesView.vue'
import WebResearchView from '@/views/WebResearchView.vue'
import RAGView from '@/views/RAGView.vue'
import TeamsView from '@/views/TeamsView.vue'
import SkillsView from '@/views/SkillsView.vue'
import SchedulesView from '@/views/SchedulesView.vue'
import MCPView from '@/views/MCPView.vue'
import WRChatView from '@/views/WRChatView.vue'
import SettingsView from '@/views/SettingsView.vue'

/** v3 灰度开关（与 stores/flags.ts 同源；路由阶段读 localStorage，避免依赖 Pinia 初始化顺序） */
function v3Enabled(): boolean {
  try {
    const raw = localStorage.getItem('__ws_v3')
    if (raw === null) return true
    return raw === '1' || raw === 'true'
  } catch {
    return true
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    // ===== v3 主工作台 =====
    {
      path: '/workspace',
      component: WorkspaceLayout,
      children: [{ path: '', component: WorkspaceView }],
    },
    {
      path: '/',
      redirect: () => (v3Enabled() ? '/workspace' : '/chat'),
    },

    // ===== 能力管理后台（v3 阶段 5 归位）=====
    {
      path: '/admin',
      component: AdminLayout,
      children: [
        { path: '', redirect: '/admin/capabilities' },
        { path: 'capabilities', component: CapabilitiesView },
        { path: 'schedules', component: SchedulesView },
        { path: 'research', component: ResearchView },
        { path: 'artifacts', component: FilesView },
        { path: 'knowledge', component: RAGView },
        { path: 'web', component: WebResearchView },
        { path: 'status', component: SystemStatusView },
        { path: 'settings', component: SettingsView },
        { path: 'lab/wr', component: WRChatView },
      ],
    },

    // ===== 旧版对话 / 工作页（保留可访问，作为灰度回退目标）=====
    {
      path: '/chat',
      component: AdminLayout,
      children: [{ path: '', component: ChatView }],
    },
    {
      path: '/work',
      component: AdminLayout,
      children: [{ path: '', component: WorkView }],
    },

    // ===== 其余旧路径：保留可访问 → 重定向到新归位（计划 §10.4）=====
    { path: '/teams', redirect: '/admin/capabilities?tab=teams' },
    { path: '/skills', redirect: '/admin/capabilities?tab=skills' },
    { path: '/mcp', redirect: '/admin/capabilities?tab=mcp' },
    { path: '/schedules', redirect: '/admin/schedules' },
    { path: '/research', redirect: '/admin/research' },
    { path: '/files', redirect: '/admin/artifacts' },
    { path: '/rag', redirect: '/admin/knowledge' },
    { path: '/web', redirect: '/admin/web' },
    { path: '/status', redirect: '/admin/status' },
    { path: '/settings', redirect: '/admin/settings' },
    { path: '/wr', redirect: '/admin/lab/wr' },
  ],
})

export default router
