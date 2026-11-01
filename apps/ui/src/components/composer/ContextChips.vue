<template>
  <div class="chips">
    <!-- 场景 Chip（空态时展示，对齐 WorkBuddy 的 3 个场景入口） -->
    <div v-if="showScenes" class="row">
      <button
        v-for="s in scenes"
        :key="s.key"
        class="chip scene"
        :title="s.desc"
        @click="emit('scene', s.key)"
      >
        <el-icon><component :is="s.icon" /></el-icon>{{ s.label }}
      </button>
    </div>

    <!-- 能力 Chip（替代旧版顶栏复选框，计划 A6） -->
    <div class="row">
      <button
        v-for="c in capabilities"
        :key="c.key"
        class="chip"
        :class="{ on: model[c.key] }"
        :title="c.desc"
        @click="emit('toggle', c.key)"
      >
        <span class="dot" :style="{ background: c.color }" />
        {{ c.label }}
        <el-icon v-if="model[c.key]" class="tick"><Select /></el-icon>
      </button>
      <button class="chip more" @click="emit('more')">
        更多 <el-icon><ArrowRight /></el-icon>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ChatDotRound, Document, DataAnalysis, Search, MagicStick, Select, ArrowRight } from '@element-plus/icons-vue'

defineProps<{
  model: Record<string, boolean>
  showScenes?: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle', key: string): void
  (e: 'scene', key: string): void
  (e: 'more'): void
}>()

const scenes = [
  { key: 'daily', label: '日报办公', icon: ChatDotRound, desc: '生成日报 / 周报 / 会议纪要' },
  { key: 'code', label: '代码开发', icon: MagicStick, desc: '读代码、改代码、跑测试' },
  { key: 'design', label: '创建设计', icon: Document, desc: '生成演示文稿 / 网页 / 报告' },
]

const capabilities = [
  { key: 'mcp', label: 'MCP 工具', color: 'var(--purple)', desc: '调用外部 MCP Server 工具' },
  { key: 'rag', label: '知识库检索', color: 'var(--green)', desc: '从本地向量库检索资料' },
  { key: 'web', label: '网络检索', color: 'var(--orange)', desc: '联网搜索（需配置搜索密钥）' },
  { key: 'reflection', label: '反思模式', color: 'var(--teal)', desc: '生成答案后自我校验与修正' },
  { key: 'research', label: '深度研究', color: 'var(--accent)', desc: '多阶段深度研究并产出报告' },
]
</script>

<style scoped>
.chips { display: flex; flex-direction: column; gap: 8px; align-items: center; }
.row { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px;
  border-radius: 999px; border: 1px solid var(--border); background: var(--bg);
  color: var(--text); font-size: 13px; cursor: pointer; transition: all 0.12s ease;
}
.chip:hover { border-color: var(--border-strong); background: var(--bg-hover); }
.chip.scene { padding: 7px 14px; font-size: 13.5px; }
.chip.on { border-color: var(--accent); background: var(--accent-light); color: var(--accent); }
.chip .dot { width: 7px; height: 7px; border-radius: 50%; }
.chip .tick { font-size: 12px; }
.chip.more { color: var(--text-dim); }
</style>
