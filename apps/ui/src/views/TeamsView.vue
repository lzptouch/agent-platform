<template>
  <div class="teams-view">
    <div class="page-head">
      <h2>Skill 团队</h2>
      <el-button type="primary" @click="openCreate">新建团队</el-button>
    </div>

    <el-table :data="teams" v-loading="loading" style="width: 100%">
      <el-table-column prop="name" label="名称" width="180" />
      <el-table-column label="成员 Skill" min-width="220">
        <template #default="{ row }">
          <el-tag v-for="(s, i) in row.skill_names" :key="s" size="small" style="margin-right: 4px">
            {{ row.strategy === 'sequential' ? `${i + 1}. ` : '' }}{{ s }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="策略" width="120">
        <template #default="{ row }">
          <el-tag size="small" :type="strategyType(row.strategy)">{{ strategyText(row.strategy) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="reference_count" label="会话引用" width="90" />
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch :model-value="row.enabled" @change="(v: boolean) => onToggle(row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" @click="onPreview(row)">预览</el-button>
          <el-button size="small" type="danger" plain @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawerVisible" :title="editing ? '编辑团队' : '新建团队'" size="480px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" :disabled="!!editing" placeholder="如：数据分析团队" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="成员 Skill（顺序即 sequential 执行顺序）">
          <el-select v-model="form.skill_names" multiple style="width: 100%" placeholder="选择 Skill">
            <el-option v-for="s in config.skills.filter(x => x.enabled)" :key="s.name" :label="`${s.name} — ${s.description}`" :value="s.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="编排策略">
          <el-radio-group v-model="form.strategy">
            <el-radio value="none">合并（全部注入）</el-radio>
            <el-radio value="sequential">顺序执行</el-radio>
            <el-radio value="router">智能路由（LLM 选 1-2 个）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="团队提示词前缀（可选）">
          <el-input v-model="form.prompt_prefix" type="textarea" :rows="3" placeholder="注入到 system prompt 的团队级指令" />
        </el-form-item>
      </el-form>
      <div style="display:flex;justify-content:flex-end;gap:8px">
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      </div>
    </el-drawer>

    <el-dialog v-model="previewVisible" :title="`预览：${preview?.team_name ?? ''}`" width="720px">
      <el-alert v-if="preview?.degraded" title="LLM 路由失败，已降级为全量成员" type="warning" :closable="false" style="margin-bottom: 8px" />
      <div v-for="w in preview?.warnings ?? []" :key="w" style="color: var(--el-color-warning); font-size: 12px">⚠ {{ w }}</div>
      <div style="margin: 8px 0">
        <el-tag v-for="s in preview?.skills ?? []" :key="s.name" size="small" style="margin-right: 4px">
          {{ s.step_index ? `[步骤 ${s.step_index}] ` : '' }}{{ s.name }}
        </el-tag>
      </div>
      <el-input :model-value="preview?.prompt_preview ?? ''" type="textarea" :rows="14" readonly />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { teamsList, teamCreate, teamUpdate, teamDelete, teamToggle, teamResolve } from '@/api'
import type { Team, TeamResolveResult, TeamStrategy } from '@/api/types'
import { useConfigStore } from '@/stores/config'

const config = useConfigStore()
const teams = ref<Team[]>([])
const loading = ref(false)
const drawerVisible = ref(false)
const previewVisible = ref(false)
const saving = ref(false)
const editing = ref<Team | null>(null)
const preview = ref<TeamResolveResult | null>(null)
const form = ref({ name: '', description: '', skill_names: [] as string[], strategy: 'none' as TeamStrategy, prompt_prefix: '' })

function strategyText(s: TeamStrategy) {
  return { none: '合并', sequential: '顺序', router: '路由' }[s]
}
function strategyType(s: TeamStrategy) {
  return s === 'router' ? 'warning' : s === 'sequential' ? 'success' : 'info'
}

async function load() {
  loading.value = true
  try {
    teams.value = await teamsList()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  config.init()
  load()
})

function openCreate() {
  editing.value = null
  form.value = { name: '', description: '', skill_names: [], strategy: 'none', prompt_prefix: '' }
  drawerVisible.value = true
}

function openEdit(row: Team) {
  editing.value = row
  form.value = {
    name: row.name, description: row.description,
    skill_names: [...row.skill_names], strategy: row.strategy, prompt_prefix: row.prompt_prefix,
  }
  drawerVisible.value = true
}

async function onSave() {
  saving.value = true
  try {
    if (editing.value) {
      await teamUpdate(editing.value.id, {
        description: form.value.description,
        skill_names: form.value.skill_names,
        strategy: form.value.strategy,
        prompt_prefix: form.value.prompt_prefix,
      })
      ElMessage.success('已更新')
    } else {
      await teamCreate(form.value)
      ElMessage.success('已创建')
    }
    drawerVisible.value = false
    await load()
  } catch (e) {
    ElMessage.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function onToggle(row: Team, enabled: boolean) {
  await teamToggle(row.id, enabled)
  row.enabled = enabled
}

async function onDelete(row: Team) {
  await ElMessageBox.confirm(`删除团队「${row.name}」？引用它的会话将解除绑定。`, '确认', { type: 'warning' })
  await teamDelete(row.id)
  ElMessage.success('已删除')
  await load()
}

async function onPreview(row: Team) {
  preview.value = await teamResolve(row.id, '预览', 'work')
  previewVisible.value = true
}
</script>

<style scoped>
.teams-view { padding: 20px 24px; overflow-y: auto; height: 100%; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-head h2 { margin: 0; font-size: 18px; }
</style>
