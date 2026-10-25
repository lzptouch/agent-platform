<template>
  <div class="capabilities">
    <el-tabs v-model="tab" class="cap-tabs">
      <el-tab-pane name="teams" label="团队">
        <TeamsView />
      </el-tab-pane>
      <el-tab-pane name="skills" label="技能">
        <SkillsView />
      </el-tab-pane>
      <el-tab-pane name="mcp" label="连接器（MCP）">
        <MCPView />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import TeamsView from './TeamsView.vue'
import SkillsView from './SkillsView.vue'
import MCPView from './MCPView.vue'

const route = useRoute()
const tab = ref('teams')

onMounted(() => {
  const q = route.query.tab
  if (typeof q === 'string' && ['teams', 'skills', 'mcp'].includes(q)) tab.value = q
})
</script>

<style scoped>
.capabilities { background: var(--bg); }
.cap-tabs :deep(.el-tabs__header) { margin-bottom: 12px; }
</style>
