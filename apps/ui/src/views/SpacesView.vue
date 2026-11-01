<template>
  <div class="spaces-view">
    <h2>项目</h2>
    <p class="hint">工作空间（每个任务一套独立目录，运行时锁定）。</p>

    <div class="actions">
      <el-button type="primary" @click="creating = true">新建工作空间</el-button>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>

    <div v-if="!items.length && !loading" class="empty">暂无工作空间</div>

    <div class="grid">
      <el-card v-for="w in items" :key="w.id" class="card" shadow="hover">
        <div class="name">{{ w.name }}</div>
        <div class="id">{{ w.id }}</div>
        <div class="root" :title="w.root_path">{{ w.root_path }}</div>
        <div class="ops">
          <el-button size="small" text @click="switchTo(w.id)">设为当前</el-button>
          <el-popconfirm title="确认归档？" @confirm="archive(w.id)">
            <template #reference><el-button size="small" text type="danger">归档</el-button></template>
          </el-popconfirm>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="creating" title="新建工作空间" width="420px">
      <el-input v-model="newName" placeholder="名称" @keyup.enter="create" />
      <template #footer>
        <el-button @click="creating = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  workspaceArchive,
  workspaceCreate,
  workspaceSwitch,
  workspacesList,
  type WorkspaceItem,
} from '@/api'

const items = ref<WorkspaceItem[]>([])
const loading = ref(false)
const creating = ref(false)
const saving = ref(false)
const newName = ref('')

async function load(): Promise<void> {
  loading.value = true
  try {
    items.value = (await workspacesList()).items
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

async function create(): Promise<void> {
  const name = newName.value.trim()
  if (!name) return
  saving.value = true
  try {
    await workspaceCreate({ name })
    newName.value = ''
    creating.value = false
    ElMessage.success('已创建')
    await load()
  } catch (e: unknown) {
    ElMessage.error(`创建失败：${(e as Error).message}`)
  } finally {
    saving.value = false
  }
}

async function switchTo(id: string): Promise<void> {
  try {
    await workspaceSwitch(id)
    ElMessage.success('已切换当前工作空间')
  } catch (e: unknown) {
    ElMessage.error(`切换失败：${(e as Error).message}`)
  }
}

async function archive(id: string): Promise<void> {
  try {
    await workspaceArchive(id)
    ElMessage.success('已归档')
    await load()
  } catch (e: unknown) {
    ElMessage.error(`归档失败：${(e as Error).message}`)
  }
}

onMounted(load)
</script>

<style scoped>
.spaces-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.actions { display: flex; gap: 8px; margin-bottom: 12px; }
.empty { color: var(--text-faint); text-align: center; padding: 32px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.card .name { font-size: 14px; color: var(--text); }
.card .id { font-size: 11px; color: var(--text-faint); font-family: ui-monospace, monospace; }
.card .root { font-size: 11px; color: var(--text-dim); margin: 4px 0 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ops { display: flex; gap: 4px; }
</style>
