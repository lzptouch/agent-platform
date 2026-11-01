<template>
  <div class="roles-view">
    <h2>角色</h2>
    <p class="hint">角色定义身份、边界、工作流程、输出风格与工具集。<b>名称创建后不可改</b>；轻档角色必须 0 工具。</p>

    <div class="actions">
      <el-button type="primary" @click="creating = true">新建角色</el-button>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>

    <el-table :data="items" size="small" v-loading="loading">
      <el-table-column prop="name" label="名称" width="150" />
      <el-table-column prop="title" label="标题" width="160" />
      <el-table-column label="模型档" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.model_tier === 'light' ? 'info' : row.model_tier === 'strong' ? 'danger' : 'primary'">
            {{ row.model_tier }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="工具集" min-width="180">
        <template #default="{ row }">
          <code v-if="row.tools.length">{{ row.tools.join(', ') }}</code>
          <span v-else class="dim">（0 工具）</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.builtin" size="small" type="warning">内置</el-tag>
          <el-tag v-else size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-popconfirm title="确认删除？" :disabled="row.builtin" @confirm="remove(row)">
            <template #reference><el-button size="small" text type="danger" :disabled="row.builtin">删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="creating" title="新建角色" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="创建后不可改名" /></el-form-item>
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="模型档">
          <el-select v-model="form.model_tier">
            <el-option label="轻（筛选/分类）" value="light" />
            <el-option label="标准（规划/执行）" value="standard" />
            <el-option label="强（主 Agent）" value="strong" />
          </el-select>
        </el-form-item>
        <el-form-item label="工具集"><el-input v-model="form.tools" placeholder="逗号分隔；轻档必须为空" /></el-form-item>
        <el-form-item label="擅长领域"><el-input v-model="form.expertise" placeholder="逗号分隔" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="creating = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { roleCreate, roleDelete, rolesList, type RoleItem } from '@/api'

const items = ref<RoleItem[]>([])
const loading = ref(false)
const creating = ref(false)
const saving = ref(false)
const form = reactive({ name: '', title: '', model_tier: 'standard' as const, tools: '', expertise: '' })

async function load(): Promise<void> {
  loading.value = true
  try { items.value = (await rolesList()).items } finally { loading.value = false }
}

function split(csv: string): string[] {
  return csv.split(',').map((s) => s.trim()).filter(Boolean)
}

async function create(): Promise<void> {
  saving.value = true
  try {
    await roleCreate({
      name: form.name.trim(),
      title: form.title.trim(),
      model_tier: form.model_tier,
      tools: split(form.tools),
      expertise: split(form.expertise),
    })
    ElMessage.success('已创建')
    creating.value = false
    form.name = form.title = form.tools = form.expertise = ''
    await load()
  } catch (e: unknown) {
    ElMessage.error(`创建失败：${(e as Error).message}`)
  } finally {
    saving.value = false
  }
}

async function remove(row: RoleItem): Promise<void> {
  try {
    await roleDelete(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e: unknown) {
    ElMessage.error(`删除失败：${(e as Error).message}`)
  }
}

onMounted(load)
</script>

<style scoped>
.roles-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.actions { display: flex; gap: 8px; margin-bottom: 12px; }
.dim { color: var(--text-faint); }
</style>
