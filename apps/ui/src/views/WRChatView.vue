<template>
  <div class="wr-view">
    <h2>WR 范式问答</h2>
    <p class="hint">plan → action → (reflection) → answer 的销售助手范式（来自 webResearch）。非流式，一次返回完整结果。</p>

    <el-card shadow="never" class="form-card">
      <el-form>
        <el-form-item label="问题">
          <el-input v-model="query" type="textarea" :rows="3" placeholder="例：介绍下 agent-platform 项目的核心架构" />
        </el-form-item>
        <el-form-item label="反思（Reflexion）">
          <el-switch v-model="reflection" />
          <span class="desc">{{ reflection ? '5 步循环' : '4 步：plan → action → answer' }}</span>
        </el-form-item>
        <el-button type="primary" :loading="loading" :disabled="!query.trim()" @click="submit">执行</el-button>
      </el-form>
    </el-card>

    <div v-if="result" class="result">
      <el-card shadow="never">
        <template #header>
          <strong>回答</strong>
        </template>
        <div class="answer">{{ result.answer }}</div>
      </el-card>

      <el-card v-if="result.reasoning" shadow="never" style="margin-top: 8px">
        <template #header><strong>推理链</strong></template>
        <pre>{{ result.reasoning }}</pre>
      </el-card>

      <el-card v-if="result.plan?.length" shadow="never" style="margin-top: 8px">
        <template #header><strong>Plan（{{ result.plan.length }} 步）</strong></template>
        <ol>
          <li v-for="(p, i) in result.plan" :key="i"><code>{{ JSON.stringify(p) }}</code></li>
        </ol>
      </el-card>

      <el-card v-if="result.reflection_plan?.length" shadow="never" style="margin-top: 8px">
        <template #header><strong>Reflection Plan（{{ result.reflection_plan.length }} 步）</strong></template>
        <ol>
          <li v-for="(p, i) in result.reflection_plan" :key="i"><code>{{ JSON.stringify(p) }}</code></li>
        </ol>
      </el-card>

      <el-card v-if="result.memory?.length" shadow="never" style="margin-top: 8px">
        <template #header><strong>Memory（{{ result.memory.length }} 条）</strong></template>
        <div v-for="(m, i) in result.memory" :key="i" class="mem">
          <code>{{ JSON.stringify(m) }}</code>
        </div>
      </el-card>
    </div>

    <el-alert v-if="lastError" type="error" :title="`调用失败：${lastError}`" :closable="false" show-icon style="margin-top: 12px" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { agentChat } from '@/api'
import type { AgentChatResponse } from '@/api/types'

const query = ref('')
const reflection = ref(false)
const loading = ref(false)
const result = ref<AgentChatResponse | null>(null)
const lastError = ref('')

async function submit() {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  result.value = null
  lastError.value = ''
  try {
    result.value = await agentChat({ query: q, reflection: reflection.value })
  } catch (e: unknown) {
    lastError.value = (e as Error).message
    ElMessage.error(`WR 调用失败：${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.wr-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.hint code { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }
.desc { color: var(--text-dim); margin-left: 12px; font-size: 12px; }
.result { margin-top: 16px; }
.answer { font-size: 15px; line-height: 1.7; white-space: pre-wrap; }
pre { background: var(--bg-code); padding: 10px; border-radius: var(--radius-sm); font-size: 12px; white-space: pre-wrap; max-height: 280px; overflow-y: auto; }
ol { padding-left: 20px; }
ol li { margin: 4px 0; }
.mem { padding: 4px 0; }
code { font-family: var(--font-mono); }
</style>