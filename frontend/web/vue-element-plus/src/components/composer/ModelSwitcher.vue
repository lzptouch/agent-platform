<template>
  <el-dropdown trigger="click" :disabled="disabled" @command="onCommand">
    <span class="switcher" :class="{ disabled }">
      <span class="mode-dot" :class="mode" />
      <span class="mode-text">{{ modeLabel }}</span>
      <el-icon class="caret"><ArrowDown /></el-icon>
    </span>

    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="mode:chat">
          <span class="mi"><span class="mode-dot chat" />对话 Ask　<span class="desc">只读，不写文件</span></span>
        </el-dropdown-item>
        <el-dropdown-item command="mode:plan">
          <span class="mi"><span class="mode-dot plan" />计划 Plan　<span class="desc">先出计划，人工确认后执行</span></span>
        </el-dropdown-item>
        <el-dropdown-item command="mode:work">
          <span class="mi"><span class="mode-dot work" />工作 Craft　<span class="desc">全自动读写与执行</span></span>
        </el-dropdown-item>
        <el-dropdown-item v-if="models.length" divided command="model">
          <span class="mi">模型：<b>{{ currentModelName }}</b></span>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>

  <!-- 模型二级选择 -->
  <el-popover v-if="models.length" v-model:visible="modelPopover" placement="bottom-start" :width="280" trigger="click">
    <template #reference>
      <span class="model-trigger" @click.stop="modelPopover = !modelPopover">{{ currentModelName }}</span>
    </template>
    <div class="model-list">
      <div
        v-for="m in models"
        :key="m.id"
        class="model-item"
        :class="{ active: m.id === model }"
        @click="pickModel(m.id)"
      >
        <span>{{ m.name }}</span>
        <small v-if="m.provider">{{ m.provider }}</small>
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { MODE_LABEL, type WorkspaceMode } from '@/stores/workspace'

const props = defineProps<{
  mode: WorkspaceMode
  model: string
  models?: Array<{ id: string; name: string; provider?: string }>
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:mode', v: WorkspaceMode): void
  (e: 'update:model', v: string): void
}>()

const modelPopover = ref(false)
const models = computed(() => props.models ?? [])
const modeLabel = computed(() => MODE_LABEL[props.mode])
const currentModelName = computed(() => models.value.find(m => m.id === props.model)?.name ?? props.model ?? '默认')

function onCommand(cmd: string) {
  if (cmd.startsWith('mode:')) {
    emit('update:mode', cmd.slice(5) as WorkspaceMode)
  } else if (cmd === 'model') {
    modelPopover.value = true
  }
}

function pickModel(id: string) {
  emit('update:model', id)
  modelPopover.value = false
}
</script>

<style scoped>
.switcher {
  display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px;
  border-radius: 999px; font-size: 12.5px; color: var(--text-dim); cursor: pointer;
  border: 1px solid transparent;
}
.switcher:hover:not(.disabled) { background: var(--bg-hover); color: var(--text); }
.switcher.disabled { opacity: 0.5; cursor: not-allowed; }
.mode-dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.mode-dot.chat { background: var(--green); }
.mode-dot.plan { background: var(--teal); }
.mode-dot.work { background: var(--accent); }
.model-trigger { display: none; }
.mi { display: inline-flex; align-items: center; gap: 6px; }
.desc { color: var(--text-faint); font-size: 11px; }
.model-list { max-height: 260px; overflow: auto; }
.model-item {
  display: flex; justify-content: space-between; padding: 6px 8px; border-radius: var(--radius-sm);
  cursor: pointer; font-size: 13px;
}
.model-item:hover { background: var(--bg-hover); }
.model-item.active { color: var(--accent); font-weight: 600; }
.model-item small { color: var(--text-faint); }
</style>
