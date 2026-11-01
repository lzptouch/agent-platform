<template>
  <el-dropdown trigger="click" @command="onCommand">
    <button class="picker">
      <el-icon><FolderOpened /></el-icon>
      <span class="cur">{{ currentName }}</span>
      <el-icon class="caret"><ArrowDown /></el-icon>
    </button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item v-for="w in workspaces" :key="w.id" :command="w.id">
          <el-icon v-if="w.id === currentId" color="var(--el-color-primary)"><Check /></el-icon>
          {{ w.name }}
        </el-dropdown-item>
        <el-dropdown-item divided command="__new__">＋ 新建工作空间</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowDown, Check, FolderOpened } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { workspaceCreate, workspaceSwitch, workspacesList, type WorkspaceItem } from '@/api'

const emit = defineEmits<{ (e: 'switch', id: string): void }>()

const workspaces = ref<WorkspaceItem[]>([])
const currentId = ref<string | null>(null)

const currentName = computed(() => workspaces.value.find((w) => w.id === currentId.value)?.name ?? '默认工作区')

async function load(): Promise<void> {
  try {
    const data = await workspacesList()
    workspaces.value = data.items
    currentId.value = data.current
  } catch { /* 后端无工作空间接口时静默 */ }
}

async function onCommand(cmd: string): Promise<void> {
  if (cmd === '__new__') {
    try {
      const { value } = await ElMessageBox.prompt('工作空间名称', '新建工作空间', { confirmButtonText: '创建', cancelButtonText: '取消' })
      await workspaceCreate({ name: value })
      await load()
      ElMessage.success('已创建')
    } catch { /* 取消 */ }
    return
  }
  await workspaceSwitch(cmd)
  currentId.value = cmd
  emit('switch', cmd)
  ElMessage.success('已切换工作空间')
}

onMounted(load)
</script>

<style scoped>
.picker { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border: 1px solid transparent; background: transparent; color: var(--text-dim); border-radius: 999px; font-size: 12px; cursor: pointer; }
.picker:hover { background: var(--bg-hover); color: var(--text); }
.cur { color: var(--text); }
.caret { font-size: 11px; }
</style>
