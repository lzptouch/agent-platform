<template>
  <div class="admin-layout">
    <SideNav variant="admin" />
    <div class="admin-body">
      <!-- 能力开关顶栏：仅后台形态保留（计划 §5.1） -->
      <header class="admin-top">
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
              <el-checkbox v-for="s in config.mcpServers" :key="s.name" :value="s.name">
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
              <el-checkbox v-for="s in config.skills" :key="s.name" :value="s.name">{{ s.name }}</el-checkbox>
            </el-checkbox-group>
          </el-popover>
        </div>
        <el-button size="small" @click="router.push('/workspace')">
          <el-icon><FullScreen /></el-icon>&nbsp;回到工作台
        </el-button>
      </header>

      <el-alert v-if="config.banner" :title="config.banner" type="warning" :closable="false" show-icon class="banner" />

      <main class="admin-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { FullScreen } from '@element-plus/icons-vue'
import SideNav from '@/components/layout/SideNav.vue'
import { useConfigStore } from '@/stores/config'

const router = useRouter()
const config = useConfigStore()

function onSelectAllSkills() {
  config.selectedSkills = config.skills.map(s => s.name)
  config.persistSkills()
}
function onClearSkills() {
  config.selectedSkills = []
  config.persistSkills()
}

onMounted(() => { if (!config.ready) void config.init() })
</script>

<style scoped>
.admin-layout { display: flex; height: 100vh; overflow: hidden; }
.admin-body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.admin-top {
  display: flex; justify-content: space-between; align-items: center;
  padding: 0 20px; height: 56px; border-bottom: 1px solid var(--border); background: var(--bg);
}
.tools { display: flex; gap: 14px; align-items: center; }
.banner { margin: 12px 20px 0; }
.admin-main { flex: 1; overflow: auto; padding: 20px; }
</style>
