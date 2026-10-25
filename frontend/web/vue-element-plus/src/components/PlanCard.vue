<template>
  <div class="plan-card" :class="status">
    <div class="plan-head">
      <el-icon class="pi"><Finished v-if="status !== 'pending'" /><Clock v-else /></el-icon>
      <span class="plan-title">执行计划待确认</span>
      <span class="plan-sub">确认后继续执行；可编辑步骤后再确认</span>
    </div>

    <ol class="plan-list">
      <li v-for="(s, i) in editable" :key="s.id" class="plan-step">
        <span class="idx">{{ i + 1 }}</span>
        <div class="body">
          <el-input v-model="s.title" size="small" :disabled="status !== 'pending'" placeholder="步骤标题" />
          <el-input
            v-model="s.detail"
            type="textarea"
            :rows="2"
            size="small"
            :disabled="status !== 'pending'"
            placeholder="步骤说明"
          />
        </div>
      </li>
    </ol>

    <div v-if="status === 'pending'" class="plan-actions">
      <el-button size="small" @click="emit('reject')">拒绝</el-button>
      <el-button size="small" type="primary" :loading="approving" @click="emit('approve', editable)">
        确认执行
      </el-button>
    </div>
    <div v-else class="plan-state">
      {{ status === 'approved' ? '✓ 已确认，正在执行' : '✗ 已拒绝该计划' }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Finished, Clock } from '@element-plus/icons-vue'
import type { PlanStep } from '@/types/workspace'

const props = defineProps<{
  plan: PlanStep[]
  status?: 'pending' | 'approved' | 'rejected'
  approving?: boolean
}>()

const emit = defineEmits<{
  (e: 'approve', plan: PlanStep[]): void
  (e: 'reject'): void
}>()

const editable = ref<PlanStep[]>(props.plan.map(p => ({ ...p })))

watch(() => props.plan, v => { editable.value = v.map(p => ({ ...p })) }, { deep: true })
</script>

<style scoped>
.plan-card {
  border: 1px solid var(--teal); background: var(--bg);
  border-radius: var(--radius); padding: 12px 14px; margin: 0 auto 10px;
  max-width: 640px; box-shadow: var(--shadow-sm);
}
.plan-card.approved { border-color: var(--green); }
.plan-card.rejected { border-color: var(--red); }
.plan-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.pi { color: var(--teal); }
.plan-card.approved .pi { color: var(--green); }
.plan-card.rejected .pi { color: var(--red); }
.plan-title { font-weight: 600; font-size: 13.5px; }
.plan-sub { color: var(--text-faint); font-size: 11.5px; }
.plan-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.plan-step { display: flex; gap: 9px; }
.idx {
  width: 20px; height: 20px; flex: 0 0 20px; border-radius: 50%;
  background: var(--accent-light); color: var(--accent);
  display: grid; place-items: center; font-size: 11px; font-weight: 600; margin-top: 4px;
}
.body { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.plan-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.plan-state { text-align: right; margin-top: 10px; color: var(--text-dim); font-size: 12.5px; }
</style>
