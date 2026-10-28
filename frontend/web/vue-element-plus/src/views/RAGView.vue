<template>
  <div class="rag-view">
    <h2>RAG 检索</h2>
    <p class="hint">本地文档问答 / 纯检索 / 入库。需要 DeepSeek Key (<code>LLM_API_KEY</code>) 用于问答，纯检索不依赖 LLM。</p>

    <el-tabs v-model="mode" class="tabs">
      <el-tab-pane label="问答（带引用）" name="query">
        <el-form>
          <el-form-item label="问题">
            <el-input v-model="queryQ" type="textarea" :rows="3" placeholder="例：什么是 Skill" />
          </el-form-item>
          <el-form-item label="返回条数">
            <el-input-number v-model="queryLimit" :min="1" :max="50" />
          </el-form-item>
          <el-button type="primary" :loading="busy" :disabled="!queryQ.trim()" @click="doQuery">查询</el-button>
        </el-form>

        <div v-if="queryAnswer" class="result">
          <el-card shadow="never">
            <template #header><strong>回答</strong></template>
            <pre>{{ queryAnswer }}</pre>
          </el-card>
          <el-card v-if="queryReferences" shadow="never" style="margin-top: 8px">
            <template #header><strong>参考（带 [n] 编号）</strong></template>
            <pre>{{ queryReferences }}</pre>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="纯检索（不调 LLM）" name="retrieval">
        <el-form>
          <el-form-item label="问题">
            <el-input v-model="retrQ" type="textarea" :rows="3" />
          </el-form-item>
          <el-form-item label="返回条数">
            <el-input-number v-model="retrLimit" :min="1" :max="50" />
          </el-form-item>
          <el-button type="primary" :loading="busy" :disabled="!retrQ.trim()" @click="doRetrieval">检索</el-button>
        </el-form>

        <div v-if="retrDocs.length" class="result">
          <el-card v-for="(d, i) in retrDocs" :key="i" shadow="never" style="margin-bottom: 8px">
            <template #header>
              <strong>[{{ i + 1 }}]</strong> {{ d.source ?? d.metadata?.source ?? '文档' }}
              <span v-if="d.score !== undefined" class="score">score: {{ d.score.toFixed(4) }}</span>
            </template>
            <pre>{{ d.text ?? JSON.stringify(d, null, 2) }}</pre>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="入库（解析 data/pdf/）" name="ingest">
        <el-alert type="error" :closable="false" show-icon style="margin-bottom: 12px">
          <strong>危险操作：</strong>勾选「重建 collection」会清空现有向量库！
        </el-alert>
        <el-form>
          <el-form-item label="重建 collection">
            <el-switch v-model="recreate" />
            <span class="desc">
              {{ recreate ? '将 DROP 并重建 collection' : '增量入库（保留现有向量；内容未变的文档自动跳过）' }}
            </span>
          </el-form-item>
          <el-button type="danger" :loading="busy" @click="doIngest">开始入库</el-button>
        </el-form>

        <div v-if="ingestResult" class="result">
          <el-card shadow="never">
            <template #header><strong>入库结果</strong></template>
            <el-descriptions :column="3" border>
              <el-descriptions-item label="chunks">{{ ingestResult.chunks }}</el-descriptions-item>
              <el-descriptions-item label="entities">{{ ingestResult.entities }}</el-descriptions-item>
              <el-descriptions-item label="collection">{{ ingestResult.collection }}</el-descriptions-item>
              <el-descriptions-item label="本次新增文档">{{ ingestResult.ingested ?? 0 }}</el-descriptions-item>
              <el-descriptions-item label="跳过（已入库）">{{ ingestResult.skipped ?? 0 }}</el-descriptions-item>
              <el-descriptions-item label="清理旧版本">{{ ingestResult.removed ?? 0 }}</el-descriptions-item>
            </el-descriptions>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-card v-if="stats" shadow="never" class="stats-card">
      <template #header><strong>collection 统计</strong></template>
      <el-descriptions :column="4" border>
        <el-descriptions-item label="Collection">{{ stats.collection }}</el-descriptions-item>
        <el-descriptions-item label="实体数">
          <el-tag :type="stats.entities === -1 ? 'warning' : 'success'">
            {{ stats.entities === -1 ? '不可用（需先入库）' : stats.entities }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="向量维度">{{ stats.dense_dim }}</el-descriptions-item>
        <el-descriptions-item label="Embedding">{{ stats.embedding_model }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ragQuery, ragRetrieval, ragIngest, ragStats } from '@/api'
import type { RagStatsResp, RagQueryResponse, RagRetrievalDoc } from '@/api/types'

const mode = ref<'query' | 'retrieval' | 'ingest'>('query')

const queryQ = ref('')
const queryLimit = ref(10)
const queryAnswer = ref('')
const queryReferences = ref('')

const retrQ = ref('')
const retrLimit = ref(10)
const retrDocs = ref<RagRetrievalDoc[]>([])

const recreate = ref(false)
const ingestResult = ref<{
  chunks: number
  entities: number
  collection: string
  ingested?: number
  skipped?: number
  removed?: number
} | null>(null)

const stats = ref<RagStatsResp | null>(null)
const busy = ref(false)

onMounted(refreshStats)

async function refreshStats() {
  try { stats.value = await ragStats() } catch { /* */ }
}

async function doQuery() {
  busy.value = true
  queryAnswer.value = ''
  queryReferences.value = ''
  try {
    const r: RagQueryResponse = await ragQuery({ query: queryQ.value, limit: queryLimit.value })
    queryAnswer.value = r.answer
    queryReferences.value = r.references
    refreshStats()
  } catch (e: unknown) {
    ElMessage.error(`查询失败：${(e as Error).message}`)
  } finally { busy.value = false }
}

async function doRetrieval() {
  busy.value = true
  retrDocs.value = []
  try {
    const r = await ragRetrieval({ query: retrQ.value, limit: retrLimit.value })
    retrDocs.value = (r.documents ?? []) as RagRetrievalDoc[]
  } catch (e: unknown) {
    ElMessage.error(`检索失败：${(e as Error).message}`)
  } finally { busy.value = false }
}

async function doIngest() {
  busy.value = true
  try {
    ingestResult.value = await ragIngest(recreate.value)
    await refreshStats()
    const skipped = ingestResult.value.skipped ?? 0
    ElMessage.success(
      skipped > 0
        ? `入库完成（跳过 ${skipped} 个已入库且内容未变的文档）`
        : '入库完成',
    )
  } catch (e: unknown) {
    ElMessage.error(`入库失败：${(e as Error).message}`)
  } finally { busy.value = false }
}
</script>

<style scoped>
.rag-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.hint code { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }
.tabs { background: var(--bg); padding: 8px; }
.result { margin-top: 16px; }
.result pre { background: var(--bg-code); padding: 10px; border-radius: var(--radius-sm); font-size: 12px; white-space: pre-wrap; max-height: 360px; overflow-y: auto; }
.score { font-size: 11px; color: var(--text-dim); margin-left: 6px; }
.desc { color: var(--text-dim); margin-left: 12px; font-size: 12px; }
.stats-card { margin-top: 16px; }
</style>