<template>
  <div class="composer" :class="{ disabled, busy: running }">
    <textarea
      ref="ta"
      v-model="inner"
      class="composer-ta"
      :placeholder="placeholder"
      :disabled="disabled"
      rows="1"
      @keydown="onKeydown"
      @input="onInput"
    />

    <div class="composer-foot">
      <div class="foot-left">
        <button class="round-btn" title="添加附件 / 上下文" :disabled="disabled" @click="emit('attach')">
          <el-icon><Plus /></el-icon>
        </button>
        <button class="round-btn text-btn" title="引用对话 / 文件（@）" :disabled="disabled" @click="emit('at')">
          @
        </button>
      </div>

      <div class="foot-right">
        <ModelSwitcher
          :mode="mode"
          :model="model"
          :models="modelOptions"
          :disabled="disabled"
          @update:mode="v => emit('update:mode', v)"
          @update:model="v => emit('update:model', v)"
        />
        <button class="round-btn" title="语音输入（未启用）" :disabled="disabled">
          <el-icon><Microphone /></el-icon>
        </button>
        <button
          class="send-btn"
          :class="{ stop: running }"
          :title="running ? '停止生成' : '发送（Enter）'"
          :disabled="!running && !canSend"
          @click="running ? emit('stop') : onSend()"
        >
          <el-icon v-if="running" class="is-loading"><Loading /></el-icon>
          <el-icon v-else><Top /></el-icon>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { Plus, Microphone, Top, Loading } from '@element-plus/icons-vue'
import ModelSwitcher from './ModelSwitcher.vue'
import type { WorkspaceMode } from '@/stores/workspace'

const props = withDefaults(defineProps<{
  modelValue: string
  mode: WorkspaceMode
  model: string
  modelOptions?: Array<{ id: string; name: string; provider?: string }>
  disabled?: boolean
  running?: boolean
  placeholder?: string
}>(), {
  modelOptions: () => [],
  disabled: false,
  running: false,
  placeholder: '今天帮你做些什么？ @ 引用对话 / 使用命令和技能',
})

const emit = defineEmits<{
  (e: 'update:modelValue', v: string): void
  (e: 'update:mode', v: WorkspaceMode): void
  (e: 'update:model', v: string): void
  (e: 'send'): void
  (e: 'stop'): void
  (e: 'attach'): void
  (e: 'at'): void
  (e: 'slash', keyword: string): void
}>()

const ta = ref<HTMLTextAreaElement>()
const inner = computed({
  get: () => props.modelValue,
  set: v => emit('update:modelValue', v),
})

const canSend = computed(() => props.modelValue.trim().length > 0)

watch(() => props.modelValue, async () => {
  await nextTick()
  resize()
})

function resize() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    onSend()
  }
}

/** 输入末尾出现 "/" → 唤起命令面板（并移除触发符，避免残留）；"@" → 唤起上下文选择 */
function onInput() {
  const v = inner.value
  if (v.endsWith('/')) {
    inner.value = v.slice(0, -1)
    emit('slash', '')
    return
  }
  const m = /(^|\s)@([^\s@]*)$/.exec(v)
  if (m) emit('at')
}

function onSend() {
  if (!canSend.value || props.running) return
  emit('send')
}
</script>

<style scoped>
.composer {
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  padding: 10px 12px 8px;
  box-shadow: var(--shadow-sm);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.composer:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-light); }
.composer.disabled { opacity: 0.75; }
.composer-ta {
  width: 100%; border: none; outline: none; resize: none; background: transparent;
  color: var(--text); font-family: inherit; font-size: 14px; line-height: 1.6;
  max-height: 200px; min-height: 24px; padding: 2px 2px 6px;
}
.composer-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.foot-left, .foot-right { display: flex; align-items: center; gap: 6px; }
.round-btn {
  width: 28px; height: 28px; border: none; background: transparent; color: var(--text-dim);
  border-radius: 8px; cursor: pointer; display: grid; place-items: center; font-size: 15px;
}
.round-btn:hover:not(:disabled) { background: var(--bg-hover); color: var(--text); }
.round-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.text-btn { font-weight: 600; }
.send-btn {
  width: 30px; height: 30px; border: none; border-radius: 50%;
  background: var(--accent); color: #fff; cursor: pointer; display: grid; place-items: center;
}
.send-btn:hover:not(:disabled) { background: var(--accent-hover); }
.send-btn:disabled { background: var(--bg-hover); color: var(--text-faint); cursor: not-allowed; }
.send-btn.stop { background: var(--red); }
</style>
