<template>
  <div class="web-view">
    <h2>Web 检索</h2>
    <p class="hint">单次带引用网络检索（Serper + 爬虫 + 引用卡片）。需要 <code>SERPER_API_KEY</code> 或 <code>OPENAI_API_KEY</code>。</p>

    <el-card shadow="never" class="form-card">
      <el-form>
        <el-form-item label="研究问题">
          <el-input v-model="query" type="textarea" :rows="3" placeholder="例：2026 年 LLM 训练成本变化趋势" />
        </el-form-item>
        <el-form-item label="角色（可选）">
          <el-input v-model="profile" placeholder="例：conscientious researcher" />
        </el-form-item>
        <el-form-item label="输出格式（可选）">
          <el-input v-model="outputFormat" placeholder="可留空" />
        </el-form-item>
        <el-button type="primary" :loading="loading" :disabled="!query.trim()" @click="submit">开始检索</el-button>
      </el-form>
    </el-card>

    <el-alert v-if="status && !status.serper_available && !status.openai_available" type="warning" :closable="false" show-icon style="margin-top: 12px">
      未配置 SERPER_API_KEY 与 OPENAI_API_KEY，调用将失败（503）。
    </el-alert>

    <div v-if="answer" class="answer">
      <el-card shadow="never">
        <template #header><strong>答案</strong></template>
        <MarkdownView :text="answer" />
      </el-card>

      <el-card v-if="cards?.length" shadow="never" style="margin-top: 12px">
        <template #header>
          <strong>引用卡片（{{ cards.length }}）</strong>
        </template>
        <div class="ref-list">
          <el-card v-for="(c, i) in cards" :key="i" class="ref-card" shadow="never">
            <div class="ref-title">
              <a v-if="c.url" :href="c.url" target="_blank">{{ c.title || c.url }}</a>
              <span v-else>{{ c.title || '引用' }}</span>
            </div>
            <div v-if="c.snippet" class="snippet">{{ c.snippet }}</div>
            <div v-if="c.quote" class="snippet">{{ c.quote }}</div>
          </el-card>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { webResearch, webResearchStatus } from '@/api'
import type { WebResearchStatusResp, WebResearchResponse } from '@/api/types'
import MarkdownView from '@/components/MarkdownView.vue'

const query = ref('')
const profile = ref('')
const outputFormat = ref('')
const loading = ref(false)
const status = ref<WebResearchStatusResp | null>(null)
const answer = ref('')
const cards = ref<WebResearchResponse['reference_cards']>([])

onMounted(async () => {
  try { status.value = await webResearchStatus() } catch { /* */ }
})

async function submit() {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  answer.value = ''
  cards.value = []
  try {
    const r = await webResearch({
      query: q,
      profile: profile.value || undefined,
      output_format: outputFormat.value || undefined,
    })
    answer.value = r.answer
    cards.value = r.reference_cards
  } catch (e: unknown) {
    ElMessage.error(`检索失败：${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.web-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.hint code { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }
.answer { margin-top: 16px; }
.ref-list { display: flex; flex-direction: column; gap: 8px; }
.ref-card { background: var(--bg-sidebar); }
.ref-title a { color: var(--accent); }
.snippet { font-size: 12px; color: var(--text-dim); margin-top: 4px; line-height: 1.6; }
</style>