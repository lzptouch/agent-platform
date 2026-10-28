import { createRouter, createWebHistory } from 'vue-router'
import WorkspaceLayout from '@/layouts/WorkspaceLayout.vue'
import AdminLayout from '@/layouts/AdminLayout.vue'
import WorkspaceView from '@/views/WorkspaceView.vue'
import CapabilitiesView from '@/views/CapabilitiesView.vue'
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
import DesktopSettingsView from '@/views/DesktopSettingsView.vue'
import RolesView from '@/views/RolesView.vue'
import SpacesView from '@/views/SpacesView.vue'
import NotFoundView from '@/views/NotFoundView.vue'
import PluginsView from '@/views/PluginsView.vue'
import BoardView from '@/views/BoardView.vue'

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
      redirect: '/workspace',
    },

    // ===== 侧栏入口对应的路由（此前缺失 → 点击白屏）=====
    {
      path: '/assistant',
      component: WorkspaceLayout,
      children: [{ path: '', component: WorkspaceView }],
    },
    {
      path: '/spaces',
      component: AdminLayout,
      children: [{ path: '', component: SpacesView }],
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
        { path: 'roles', component: RolesView },
        { path: 'plugins', component: PluginsView },
        { path: 'boards', component: BoardView },
        { path: 'desktop', component: DesktopSettingsView },
        { path: 'lab/wr', component: WRChatView },
      ],
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

    // ===== 兜底：未知路径不再白屏（S8 修复）=====
    { path: '/:pathMatch(.*)*', component: NotFoundView },
  ],
})

export default router
