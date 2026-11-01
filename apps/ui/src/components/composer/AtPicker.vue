<template>
  <el-dialog
    v-model="visible"
    class="at-dialog"
    width="520px"
    top="14vh"
    :show-close="false"
    append-to-body
  >
    <el-input
      ref="inputRef"
      v-model="keyword"
      placeholder="搜索对话 / 技能 / 产物文件…"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.enter.prevent="runSelected"
      @keydown.esc="visible = false"
    >
      <template #prefix><el-icon><Search /></el-icon></template>
    </el-input>

    <div class="at-list">
      <div v-if="!groups.length" class="empty">未找到匹配结果</div>
      <template v-for="g in groups" :key="g.label">
        <div class="group-label">{{ g.label }}</div>
        <div
          v-for="it in g.items"
          :key="it.key"
          class="at-item"
          :class="{ active: it.key === activeKey }"
          @mouseenter="activeKey = it.key"
          @click="pick(it)"
        >
          <el-icon><component :is="it.icon" /></el-icon>
          <span class="t">{{ it.title }}</span>
          <small v-if="it.desc">{{ it.desc }}</small>
        </div>
      </template>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { Search, ChatDotRound, MagicStick, Document } from '@element-plus/icons-vue'
import type { AtItem } from '@/types/workspace'

const props = defineProps<{
  modelValue: boolean
  sessions?: Array<{ id: string; title?: string; message_count?: number }>
  skills?: Array<{ name: string; description?: string }>
  files?: Array<{ name: string; size?: number }>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'pick', item: AtItem): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

const keyword = ref('')
const activeKey = ref('')
const inputRef = ref<{ focus: () => void }>()

const groups = computed<Array<{ label: string; items: AtItem[] }>>(() => {
  const k = keyword.value.trim().toLowerCase()
  const match = (s: string) => !k || s.toLowerCase().includes(k)
  const out: Array<{ label: string; items: AtItem[] }> = []

  const sess = (props.sessions ?? [])
    .filter(s => match(s.title || '未命名任务'))
    .slice(0, 6)
    .map(s => ({ key: `session:${s.id}`, title: s.title || '未命名任务', desc: `${s.message_count ?? 0} 条`, icon: ChatDotRound }))
  if (sess.length) out.push({ label: '对话', items: sess })

  const sk = (props.skills ?? [])
    .filter(s => match(s.name))
    .slice(0, 6)
    .map(s => ({ key: `skill:${s.name}`, title: s.name, desc: s.description, icon: MagicStick }))
  if (sk.length) out.push({ label: '技能', items: sk })

  const fs = (props.files ?? [])
    .filter(f => match(f.name))
    .slice(0, 6)
    .map(f => ({ key: `file:${f.name}`, title: f.name, desc: '产物文件', icon: Document }))
  if (fs.length) out.push({ label: '产物', items: fs })

  return out
})

const flat = computed(() => groups.value.flatMap(g => g.items))

watch(visible, async v => {
  if (v) {
    keyword.value = ''
    activeKey.value = flat.value[0]?.key ?? ''
    await nextTick()
    inputRef.value?.focus()
  }
})
watch(groups, () => { activeKey.value = flat.value[0]?.key ?? '' })

function move(d: number) {
  const n = flat.value.length
  if (!n) return
  const i = flat.value.findIndex(x => x.key === activeKey.value)
  const next = (i + d + n) % n
  activeKey.value = flat.value[next]?.key ?? ''
}
function runSelected() {
  const it = flat.value.find(x => x.key === activeKey.value)
  if (it) pick(it)
}
function pick(it: AtItem) {
  visible.value = false
  emit('pick', it)
}
</script>

<style scoped>
.at-list { margin-top: 12px; max-height: 360px; overflow: auto; }
.group-label { font-size: 11px; color: var(--text-faint); padding: 8px 8px 4px; }
.at-item {
  display: flex; align-items: center; gap: 8px; padding: 7px 10px;
  border-radius: var(--radius-sm); cursor: pointer; font-size: 13px;
}
.at-item:hover, .at-item.active { background: var(--bg-hover); }
.at-item .t { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.at-item small { color: var(--text-faint); font-size: 11px; }
.empty { color: var(--text-faint); font-size: 13px; padding: 14px; text-align: center; }
</style>
