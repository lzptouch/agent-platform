<template>
  <div class="system-view">
    <h2>系统状态</h2>
    <p class="hint">五链路健康总览。DashScope 与 DeepSeek 是两套不同的 LLM Key。</p>

    <div v-if="!data" class="loading"><el-icon class="is-loading"><Loading /></el-icon> 加载中…</div>

    <template v-else>
      <el-row :gutter="16">
        <el-col :span="12">
          <el-card shadow="never">
            <template #header><strong>应用基础</strong></template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="应用">{{ data.app }}</el-descriptions-item>
              <el-descriptions-item label="版本">v{{ data.version }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="data.status === 'ok' ? 'success' : 'danger'">{{ data.status }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="已加载 Skill">{{ data.skills_loaded }}</el-descriptions-item>
              <el-descriptions-item label="输出目录"><code>{{ data.output_dir }}</code></el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>

        <el-col :span="12">
          <el-card shadow="never">
            <template #header><strong>LLM Key 状态</strong></template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="DashScope（Agent + Research LLM）">
                <el-tag :type="data.api_key_configured ? 'success' : 'danger'" effect="plain">
                  {{ data.api_key_configured ? '已配置' : '未配置 → 请设置 DASHSCOPE_API_KEY' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="DeepSeek（RAG 问答）">
                <el-tag :type="data.llm_available ? 'success' : 'danger'" effect="plain">
                  {{ data.llm_available ? '已配置' : '未配置 → 请设置 LLM_API_KEY' }}
                </el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="12">
          <el-card shadow="never">
            <template #header><strong>检索 Key 状态</strong></template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="Web Research（Serper）">
                <el-tag :type="data.web_search_available ? 'success' : 'danger'" effect="plain">
                  {{ data.web_search_available ? '已配置（Serper）' : '未配置 → 请设置 SERPER_API_KEY' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="Deep Research">
                <el-tag :type="data.research_configured ? 'success' : 'danger'" effect="plain">
                  {{ data.research_configured ? `已配置（${data.research_search_provider}）` : '未配置 → 请设置 BOCHA_API_KEY 或 SERPER_API_KEY' }}
                </el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>

        <el-col :span="12">
          <el-card shadow="never">
            <template #header><strong>RAG 向量库</strong></template>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="Collection">{{ data.rag_collection }}</el-descriptions-item>
              <el-descriptions-item label="实体数">
                <el-tag :type="data.rag_entities === -1 ? 'warning' : 'success'">
                  {{ data.rag_entities === -1 ? '向量库不可用（需 /rag/ingest 初始化）' : `${data.rag_entities} chunks` }}
                </el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="24">
          <el-card shadow="never">
            <template #header><strong>Deep Research</strong></template>
            <el-descriptions :column="3" border>
              <el-descriptions-item label="启用">{{ data.research_enabled ? '是' : '否' }}</el-descriptions-item>
              <el-descriptions-item label="检索提供方">{{ data.research_search_provider }}</el-descriptions-item>
              <el-descriptions-item label="总任务数 / 运行中">{{ data.research_total_tasks }} / {{ data.research_running_tasks }}</el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-col>
      </el-row>

      <p class="footnote">
        ⚠ <code>/api/v1/health</code> 中 <code>mcp_servers_available</code> 是后端硬编码常量 3，不可作真实可用数；
        真实可用 Server 数请查 <code>/api/v1/mcp_servers</code> 的 <code>total</code>。
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { health } from '@/api'
import type { HealthResp } from '@/api/types'

const data = ref<HealthResp | null>(null)

onMounted(async () => { data.value = await health().catch(() => null) })
</script>

<style scoped>
.system-view { padding: 16px 24px; }
.hint { color: var(--text-dim); }
.loading { padding: 32px; text-align: center; color: var(--text-dim); }
.footnote { color: var(--text-dim); font-size: 12px; margin-top: 16px; }
code { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }
</style>