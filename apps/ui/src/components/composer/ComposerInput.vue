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
      @paste="onPaste"
    />

    <div v-if="attachments?.length" class="attachments">
      <span
        v-for="(a, i) in attachments"
        :key="`${a.name}-${i}`"
        class="att-chip"
        :title="a.name"
      >
        <el-icon><Paperclip /></el-icon>
        <span class="att-name">{{ a.name }}</span>
        <span class="att-size">{{ formatSize(a.size) }}</span>
        <button class="att-remove" title="移除附件" @click="emit('remove-attachment', i)">×</button>
      </span>
    </div>

    <!-- 长粘贴折叠（>3000 字符）：不撑爆输入区，可展开 -->
    <div v-if="foldedPaste" class="paste-fold">
      <span class="pf-text">已折叠 {{ foldedPaste.chars }} 字符的粘贴内容</span>
      <button class="pf-btn" @click="expandPaste">展开</button>
      <button class="pf-btn" @click="foldedPaste = null">丢弃</button>
    </div>

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
import { Plus, Microphone, Top, Loading, Paperclip } from '@element-plus/icons-vue'
import ModelSwitcher from './ModelSwitcher.vue'
import type { WorkspaceMode } from '@/stores/workspace'

/** 单个附件（批次 02）。 */
export interface ComposerAttachment {
  name: string
  size: number
}

const props = withDefaults(defineProps<{
  modelValue: string
  mode: WorkspaceMode
  model: string
  modelOptions?: Array<{ id: string; name: string; provider?: string }>
  disabled?: boolean
  running?: boolean
  placeholder?: string
  attachments?: ComposerAttachment[]
}>(), {
  modelOptions: () => [],
  disabled: false,
  running: false,
  placeholder: '今天帮你做些什么？ @ 引用对话 / 使用命令和技能',
  attachments: () => [],
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
  (e: 'remove-attachment', index: number): void
}>()

/** 超过该字符数的粘贴内容折叠为可展开条目（批次 02）。 */
const LONG_PASTE_THRESHOLD = 3000
const PASTE_MARKER = '【折叠粘贴内容】'

/** 已折叠的长粘贴内容 */
const foldedPaste = ref<{ chars: number; text: string } | null>(null)

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

/** 长粘贴折叠：超过阈值不直接灌进输入区，改为可展开条目（批次 02）。 */
function onPaste(e: ClipboardEvent) {
  const text = e.clipboardData?.getData('text') ?? ''
  if (text.length <= LONG_PASTE_THRESHOLD) return
  e.preventDefault()
  foldedPaste.value = { chars: text.length, text }
  if (!inner.value.includes(PASTE_MARKER)) {
    inner.value = inner.value ? `${inner.value}\n${PASTE_MARKER}` : PASTE_MARKER
  }
}

/** 展开折叠内容：把全文放回输入区。 */
function expandPaste() {
  const folded = foldedPaste.value
  if (!folded) return
  inner.value = inner.value.includes(PASTE_MARKER)
    ? inner.value.replace(PASTE_MARKER, folded.text)
    : `${inner.value}\n${folded.text}`
  foldedPaste.value = null
}

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
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
.attachments { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.att-chip {
  display: inline-flex; align-items: center; gap: 5px; max-width: 220px;
  padding: 2px 6px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--bg-sidebar); font-size: 11.5px; color: var(--text-dim);
}
.att-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.att-size { color: var(--text-faint); }
.att-remove {
  border: none; background: transparent; color: var(--text-faint); cursor: pointer;
  font-size: 13px; line-height: 1; padding: 0 2px;
}
.att-remove:hover { color: var(--red); }
.paste-fold {
  display: flex; align-items: center; gap: 8px; margin-bottom: 6px;
  font-size: 11.5px; color: var(--text-dim);
}
.pf-btn {
  border: 1px solid var(--border); background: var(--bg-sidebar); color: var(--text);
  border-radius: 5px; font-size: 11px; padding: 1px 6px; cursor: pointer;
}
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
