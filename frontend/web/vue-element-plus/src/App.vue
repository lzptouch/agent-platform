<template>
  <el-container class="layout">
    <el-aside width="220px" class="sidebar">
      <div class="brand">
        <span class="logo">A</span>
        <span class="name">Agent Platform</span>
      </div>
      <el-menu :default-active="active" :router="true" class="menu">
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>对话</span>
        </el-menu-item>
        <el-menu-item index="/work">
          <el-icon><Suitcase /></el-icon>
          <span>工作</span>
        </el-menu-item>
        <el-menu-item index="/schedules">
          <el-icon><AlarmClock /></el-icon>
          <span>定时任务</span>
        </el-menu-item>
        <el-menu-item index="/teams">
          <el-icon><UserFilled /></el-icon>
          <span>技能团队</span>
        </el-menu-item>
        <el-menu-item index="/research">
          <el-icon><DataAnalysis /></el-icon>
          <span>深度研究</span>
        </el-menu-item>
        <el-divider class="menu-divider" />
        <el-menu-item-group title="能力">
          <el-menu-item index="/skills">
            <el-icon><Files /></el-icon>
            <span>Skill 管理</span>
          </el-menu-item>
          <el-menu-item index="/mcp">
            <el-icon><Connection /></el-icon>
            <span>MCP 控制台</span>
          </el-menu-item>
          <el-menu-item index="/rag">
            <el-icon><Document /></el-icon>
            <span>RAG 检索</span>
          </el-menu-item>
          <el-menu-item index="/web">
            <el-icon><Search /></el-icon>
            <span>Web 检索</span>
          </el-menu-item>
          <el-menu-item index="/files">
            <el-icon><Folder /></el-icon>
            <span>产出文件</span>
          </el-menu-item>
          <el-menu-item index="/wr">
            <el-icon><MagicStick /></el-icon>
            <span>WR 范式</span>
          </el-menu-item>
        </el-menu-item-group>
        <el-divider class="menu-divider" />
        <el-menu-item index="/status">
          <el-icon><Monitor /></el-icon>
          <span>系统状态</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>设置</span>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <a href="/docs" target="_blank">API 文档</a>
        <a href="/openapi.json" target="_blank">OpenAPI</a>
      </div>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div class="tools">
          <el-checkbox v-model="config.enableMcp">MCP</el-checkbox>
          <el-checkbox v-model="config.enableRag">RAG</el-checkbox>
          <el-checkbox v-model="config.enableWeb">Web</el-checkbox>
          <el-checkbox v-model="config.enableReflection">反思</el-checkbox>
          <el-popover v-if="config.enableMcp" placement="bottom" :width="320" trigger="click">
            <template #reference>
              <el-button size="small">MCP Server（{{ config.selectedServers.length }}）</el-button>
            </template>
            <el-checkbox-group v-model="config.selectedServers">
              <el-checkbox v-for="(s, _i) in config.mcpServers" :key="s.name" :value="s.name">
                {{ s.name }} <small style="color: var(--text-dim)">{{ s.status }}</small>
              </el-checkbox>
            </el-checkbox-group>
          </el-popover>
          <el-popover placement="bottom" :width="320" trigger="click">
            <template #reference>
              <el-button size="small">Skill（{{ config.selectedSkills.length }}/{{ config.skills.length }}）</el-button>
            </template>
            <div style="display:flex;gap:4px;margin-bottom:8px">
              <el-button size="small" @click="onSelectAllSkills">全选</el-button>
              <el-button size="small" @click="onClearSkills">清空</el-button>
            </div>
            <el-checkbox-group v-model="config.selectedSkills" @change="config.persistSkills()">
              <el-checkbox v-for="(s, _i) in config.skills" :key="s.name" :value="s.name">{{ s.name }}</el-checkbox>
            </el-checkbox-group>
          </el-popover>
        </div>
        <div class="meta">
          <span class="env">P0 · Vue 3 + Element Plus · v0.1.0</span>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  ChatDotRound, DataAnalysis, Monitor, Setting,
  Files, Connection, Document, Search, Folder, MagicStick,
  Suitcase, AlarmClock, UserFilled,
} from '@element-plus/icons-vue'
import { useConfigStore } from '@/stores/config'

const route = useRoute()
const config = useConfigStore()

const active = computed(() => route.path)

function onSelectAllSkills() {
  config.selectedSkills = config.skills.map(s => s.name)
  config.persistSkills()
}
function onClearSkills() {
  config.selectedSkills = []
  config.persistSkills()
}

onMounted(() => config.init())
</script>

<style scoped>
.layout { height: 100vh; }
.sidebar { background: var(--bg-sidebar); border-right: 1px solid var(--border); display: flex; flex-direction: column; }
.brand { display: flex; align-items: center; gap: 10px; padding: 16px; border-bottom: 1px solid var(--border); }
.brand .logo { width: 28px; height: 28px; background: var(--accent); color: white; border-radius: 6px; display: grid; place-items: center; font-weight: 700; }
.brand .name { font-weight: 600; }
.menu { flex: 1; border-right: none; }
.menu-divider { margin: 4px 0; }
.sidebar-footer { padding: 12px 16px; border-top: 1px solid var(--border); display: flex; gap: 12px; font-size: 12px; }
.sidebar-footer a { color: var(--text-dim); text-decoration: none; }
.sidebar-footer a:hover { color: var(--accent); }
.topbar { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); background: var(--bg); padding: 0 24px; }
.tools { display: flex; gap: 14px; align-items: center; }
.meta { color: var(--text-dim); font-size: 12px; }
.main { padding: 0; height: calc(100vh - 60px); overflow: hidden; }
</style>