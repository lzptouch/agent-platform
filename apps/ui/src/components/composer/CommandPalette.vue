<template>
  <el-dialog
    v-model="visible"
    class="cmd-dialog"
    width="560px"
    top="12vh"
    :show-close="false"
    append-to-body
  >
    <el-input
      ref="inputRef"
      v-model="keyword"
      placeholder="输入命令或技能名称…"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.enter.prevent="runSelected"
      @keydown.esc="visible = false"
    >
      <template #prefix><el-icon><Search /></el-icon></template>
    </el-input>

    <div class="cmd-list">
      <div v-if="!filtered.length" class="empty">无匹配命令</div>
      <div
        v-for="(c, i) in filtered"
        :key="c.key"
        class="cmd-item"
        :class="{ active: i === activeIndex }"
        @mouseenter="activeIndex = i"
        @click="run(c)"
      >
        <el-icon class="ci"><component :is="c.icon" /></el-icon>
        <span class="c-main">
          <span class="c-title">{{ c.title }}</span>
          <span class="c-desc">{{ c.desc }}</span>
        </span>
        <el-tag v-if="c.tag" size="small" effect="plain">{{ c.tag }}</el-tag>
      </div>
    </div>

    <div class="cmd-foot">
      <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
      <span><kbd>Enter</kbd> 执行</span>
      <span><kbd>Esc</kbd> 关闭</span>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { Search, MagicStick, DataAnalysis, Plus, Switch, CircleCheck } from '@element-plus/icons-vue'
import type { CommandItem } from '@/types/workspace'

const props = defineProps<{ modelValue: boolean; skills?: Array<{ name: string; description?: string }> }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'run', key: string): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

const keyword = ref('')
const activeIndex = ref(0)
const inputRef = ref<{ focus: () => void }>()

const baseCommands = computed<CommandItem[]>(() => [
  {
    key: 'new-task', title: '新建任务', desc: '清空当前会话并开始一个新任务', icon: Plus, tag: '任务',
    run: () => emit('run', 'new-task'),
  },
  {
    key: 'mode-chat', title: '切换到 对话 Ask', desc: '只读模式：检索与问答，不写文件', icon: CircleCheck, tag: '模式',
    run: () => emit('run', 'mode-chat'),
  },
  {
    key: 'mode-plan', title: '切换到 计划 Plan', desc: '先出计划，人工确认后再执行', icon: CircleCheck, tag: '模式',
    run: () => emit('run', 'mode-plan'),
  },
  {
    key: 'mode-work', title: '切换到 工作 Craft', desc: '全自动读写文件与执行', icon: CircleCheck, tag: '模式',
    run: () => emit('run', 'mode-work'),
  },
  {
    key: 'research', title: '发起深度研究', desc: '多阶段检索 + 质量评分，产出报告', icon: DataAnalysis, tag: '能力',
    run: () => emit('run', 'research'),
  },
  {
    key: 'skills', title: '打开 专家·技能·连接器', desc: '管理团队、技能与 MCP 连接器', icon: Switch, tag: '管理',
    run: () => emit('run', 'skills'),
  },
])

const skillCommands = computed<CommandItem[]>(() =>
  (props.skills ?? []).map(s => ({
    key: `skill:${s.name}`,
    title: s.name,
    desc: s.description || '调用该技能',
    icon: MagicStick,
    tag: '技能',
    run: () => emit('run', `skill:${s.name}`),
  })),
)

const all = computed(() => [...baseCommands.value, ...skillCommands.value])

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return all.value
  return all.value.filter(c => (c.title + ' ' + c.desc).toLowerCase().includes(k))
})

watch(filtered, () => { activeIndex.value = 0 })
watch(visible, async v => {
  if (v) {
    keyword.value = ''
    activeIndex.value = 0
    await nextTick()
    inputRef.value?.focus()
  }
})

function move(d: number) {
  const n = filtered.value.length
  if (!n) return
  activeIndex.value = (activeIndex.value + d + n) % n
}
function runSelected() {
  const c = filtered.value[activeIndex.value]
  if (c) run(c)
}
function run(c: CommandItem) {
  visible.value = false
  c.run()
}
</script>

<style scoped>
.cmd-list { margin-top: 12px; max-height: 380px; overflow: auto; }
.cmd-item {
  display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--radius-sm);
  cursor: pointer;
}
.cmd-item:hover, .cmd-item.active { background: var(--bg-hover); }
.ci { color: var(--text-dim); }
.c-main { flex: 1; display: flex; flex-direction: column; line-height: 1.35; min-width: 0; }
.c-title { font-size: 13.5px; }
.c-desc { font-size: 11.5px; color: var(--text-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty { color: var(--text-faint); font-size: 13px; padding: 14px; text-align: center; }
.cmd-foot {
  display: flex; gap: 16px; margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border);
  color: var(--text-faint); font-size: 11.5px;
}
kbd {
  background: var(--bg-code); border: 1px solid var(--border); border-radius: 4px;
  padding: 0 4px; margin-right: 2px; font-size: 10.5px;
}
</style>
