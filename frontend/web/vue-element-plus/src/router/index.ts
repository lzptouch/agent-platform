import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'
import WorkView from '@/views/WorkView.vue'
import ResearchView from '@/views/ResearchView.vue'
import SystemStatusView from '@/views/SystemStatusView.vue'
import FilesView from '@/views/FilesView.vue'
import WebResearchView from '@/views/WebResearchView.vue'
import RAGView from '@/views/RAGView.vue'
import SkillsView from '@/views/SkillsView.vue'
import TeamsView from '@/views/TeamsView.vue'
import SchedulesView from '@/views/SchedulesView.vue'
import MCPView from '@/views/MCPView.vue'
import WRChatView from '@/views/WRChatView.vue'
import SettingsView from '@/views/SettingsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: ChatView },
    { path: '/work', component: WorkView },
    { path: '/schedules', component: SchedulesView },
    { path: '/teams', component: TeamsView },
    { path: '/research', component: ResearchView },
    { path: '/status', component: SystemStatusView },
    { path: '/files', component: FilesView },
    { path: '/web', component: WebResearchView },
    { path: '/rag', component: RAGView },
    { path: '/skills', component: SkillsView },
    { path: '/mcp', component: MCPView },
    { path: '/wr', component: WRChatView },
    { path: '/settings', component: SettingsView },
  ],
})

export default router
