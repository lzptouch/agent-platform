<template>
  <el-card v-if="item" class="perm-card" shadow="always">
    <div class="head">
      <el-icon class="warn"><WarningFilled /></el-icon>
      <span class="title">操作需要授权</span>
      <span class="risk" :class="item.risk">{{ riskLabel }}</span>
    </div>
    <div class="body">
      <div class="row"><span class="k">工具</span><code>{{ item.tool_name }}</code></div>
      <div class="row"><span class="k">目标</span><code class="target">{{ targetText }}</code></div>
      <div class="row"><span class="k">理由</span><span class="v">{{ item.reason }}</span></div>
    </div>
    <div class="foot">
      <el-button size="small" type="primary" @click="decide('allow_once')">允许本次</el-button>
      <el-button size="small" @click="decide('allow_session')">本次会话允许</el-button>
      <el-button
        v-if="item.risk !== 'critical'"
        size="small"
        @click="decide('allow_workspace')"
      >本工作空间允许</el-button>
      <el-button size="small" type="danger" plain @click="decide('deny')">拒绝</el-button>
      <span class="countdown">{{ countdown }}s</span>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import { permissionResolve } from '@/api'

export interface PendingApproval {
  id: number
  tool_name: string
  reason: string
  risk?: string
  target?: string
  request?: Record<string, unknown>
  created_at?: string
  timeout_s?: number
}

const props = defineProps<{ item: PendingApproval | null }>()
const emit = defineEmits<{ (e: 'resolved', id: number): void }>()

const countdown = ref(props.item?.timeout_s ?? 120)
let timer: ReturnType<typeof setInterval> | null = null

const riskLabel = computed(() => {
  const r = props.item?.risk
  if (r === 'critical') return '高危'
  if (r === 'elevated') return '注意'
  return '常规'
})

const targetText = computed(() => {
  const it = props.item
  if (!it) return ''
  if (it.target) return it.target
  const req = it.request || {}
  return String(req.path || req.command || req.tool || '')
})

async function decide(choice: string): Promise<void> {
  const it = props.item
  if (!it) return
  try {
    await permissionResolve({ decision_id: it.id, choice })
  } finally {
    emit('resolved', it.id)
  }
}

onMounted(() => {
  timer = setInterval(() => {
    if (countdown.value > 0) countdown.value -= 1
  }, 1000)
})
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.perm-card {
  position: fixed; right: 24px; bottom: 24px; width: 380px; z-index: 3000;
  border: 1px solid var(--el-color-warning);
}
.head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.warn { color: var(--el-color-warning); }
.title { font-weight: 600; }
.risk { margin-left: auto; font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--bg-hover); }
.risk.critical { color: var(--el-color-danger); }
.risk.elevated { color: var(--el-color-warning); }
.row { display: flex; gap: 8px; margin: 4px 0; font-size: 13px; }
.row .k { color: var(--text-faint); width: 40px; flex: none; }
.target { word-break: break-all; }
.foot { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
.countdown { margin-left: auto; color: var(--text-faint); font-size: 12px; }
</style>
