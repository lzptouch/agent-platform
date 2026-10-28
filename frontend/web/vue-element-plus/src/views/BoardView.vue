<template>
  <div class="board-view">
    <h2>黑板</h2>
    <p class="hint">多 Agent 协作的任务项与依赖图。完成一项即触发重算（不轮询）。</p>

    <div class="actions">
      <el-input v-model="boardId" placeholder="黑板 ID" style="max-width: 200px" @keyup.enter="load" />
      <el-input v-model="newTitle" placeholder="新任务标题" style="max-width: 240px" @keyup.enter="create" />
      <el-button type="primary" @click="create">新增任务</el-button>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-table :data="items" size="small" v-loading="loading">
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="title" label="任务" min-width="180" />
      <el-table-column label="依赖" width="120">
        <template #default="{ row }">
          <span v-if="row.deps.length" class="dim">← {{ row.deps.join(', ') }}</span>
          <span v-else class="dim">—</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="assignee" label="负责人" width="120">
        <template #default="{ row }"><span :class="{ dim: !row.assignee }">{{ row.assignee ?? '（未指派）' }}</span></template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-button
            size="small" text
            :disabled="row.status !== 'ready' && row.status !== 'running'"
            @click="complete(row)"
          >完成</el-button>
        </template>
      </el-table-column>
    </el-table>

    <h3 class="sub-title">消息与通知</h3>
    <el-table :data="messages" size="small">
      <el-table-column prop="kind" label="类型" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="row.is_notification ? 'warning' : 'primary'">
            {{ row.is_notification ? '通知' : '消息' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="content" label="内容" min-width="240" />
      <el-table-column label="引用" width="160">
        <template #default="{ row }">
          <span v-if="row.refs.length" class="dim">{{ row.refs.length }} 条</span>
          <span v-else class="dim">—</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { boardItemComplete, boardItemCreate, boardItems, type BoardItem } from '@/api'

const boardId = ref('default')
const items = ref<BoardItem[]>([])
const messages = ref<Array<Record<string, unknown>>>([])
const loading = ref(false)
const newTitle = ref('')

function statusType(s: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  const map: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'primary'> = {
    done: 'success', ready: 'primary', running: 'warning', blocked: 'danger', failed: 'danger',
  }
  return map[s] ?? 'info'
}

async function load(): Promise<void> {
  loading.value = true
  try {
    items.value = (await boardItems(boardId.value)).items
  } finally {
    loading.value = false
  }
}

async function create(): Promise<void> {
  const title = newTitle.value.trim()
  if (!title) return
  try {
    await boardItemCreate(boardId.value, { title })
    newTitle.value = ''
    await load()
  } catch (e: unknown) {
    ElMessage.error(`创建失败：${(e as Error).message}`)
  }
}

async function complete(row: BoardItem): Promise<void> {
  try {
    const res = await boardItemComplete(row.board_id, row.id, { done: true })
    items.value = res.items
    ElMessage.success('已完成并重算')
  } catch (e: unknown) {
    ElMessage.error(`完成失败：${(e as Error).message}`)
  }
}

onMounted(load)
</script>

<style scoped>
.board-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.actions { display: flex; gap: 8px; margin-bottom: 12px; }
.sub-title { margin: 18px 0 8px; font-size: 15px; }
.dim { color: var(--text-faint); }
</style>
