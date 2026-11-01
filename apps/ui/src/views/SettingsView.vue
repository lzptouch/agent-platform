<template>
  <div class="settings-view">
    <h2>设置</h2>
    <p class="hint">前端基本设置与项目信息。所有 API 地址由 vite proxy 自动转发，无需手动配置。</p>

    <el-card shadow="never" class="card">
      <template #header><strong>外观</strong></template>
      <el-form label-width="140px">
        <el-form-item label="主题">
          <el-radio-group v-model="theme">
            <el-radio-button value="auto">跟随系统</el-radio-button>
            <el-radio-button value="light">浅色</el-radio-button>
            <el-radio-button value="dark">深色</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="动画">
          <el-switch v-model="animation" />
          <span class="desc">（全局开关；当前实现未依赖，保留位）</span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="card">
      <template #header><strong>本地存储</strong></template>
      <p>各实现使用带前缀的 localStorage 键（避免同源多实现串扰）：</p>
      <ul class="kv-list">
        <li><code>ap-vue-ep-skills</code> · Skill 多选</li>
      </ul>
      <el-button @click="clearLocal">清空本实现存储</el-button>
    </el-card>

    <el-card shadow="never" class="card">
      <template #header><strong>关于</strong></template>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="实现">web/vue-element-plus</el-descriptions-item>
        <el-descriptions-item label="版本">v0.1.0</el-descriptions-item>
        <el-descriptions-item label="技术栈">Vue 3 + TS + Element Plus 2 + Pinia + Vue Router + Vite</el-descriptions-item>
        <el-descriptions-item label="契约">
          <a href="/docs" target="_blank">/docs (Swagger UI)</a>
          ·
          <a href="/openapi.json" target="_blank">/openapi.json</a>
        </el-descriptions-item>
        <el-descriptions-item label="上游后端">FastAPI 1.1.0</el-descriptions-item>
        <el-descriptions-item label="前端集合">11 个实现的 P0 标杆</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card shadow="never" class="card">
      <template #header><strong>版本差异（基线 → 本实现）</strong></template>
      <ul class="diff">
        <li><strong>进度重复</strong>：<s>无去重</s> → <code>stage+timestamp</code> 去重</li>
        <li><strong>1800s 断流</strong>：<s>不恢复</s> → 流关闭回查 + 自动续订</li>
        <li><strong>切换任务被阻塞</strong>：<s>streaming 全局守卫</s> → 按 <code>taskId</code> 独立 <code>AbortController</code></li>
        <li><strong>无法取消</strong>：<s>无中断按钮</s> → 全链路 <code>AbortController</code> + 「停止」按钮</li>
        <li><strong>15 种 Agent SSE 事件</strong>：<s>10 种</s> → 全部 15 种（含反思模式）</li>
        <li><strong>Markdown</strong>：<s>自研正则（无消毒）</s> → <code>markdown-it</code> + <code>DOMPurify</code> + <code>highlight.js</code></li>
        <li><strong>Skill 详情</strong>：<s>纯文本 pre-wrap</s> → Markdown 渲染</li>
      </ul>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'

const THEME_KEY = 'ap-vue-ep-theme'
type Theme = 'auto' | 'light' | 'dark'

const theme = ref<Theme>((localStorage.getItem(THEME_KEY) as Theme) ?? 'auto')
const animation = ref(false)

function applyTheme(t: Theme) {
  const root = document.documentElement
  if (t === 'dark') root.classList.add('dark')
  else if (t === 'light') root.classList.remove('dark')
  else root.classList.remove('dark') // 跟随系统：交给 prefers-color-scheme
}
onMounted(() => applyTheme(theme.value))
watch(theme, (v) => { localStorage.setItem(THEME_KEY, v); applyTheme(v) })

function clearLocal() {
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith('ap-vue-ep-')) localStorage.removeItem(k)
  }
  ElMessage.success('已清空本实现存储')
}
</script>

<style scoped>
.settings-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.hint code { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }
.card { margin-bottom: 12px; }
.desc { color: var(--text-dim); margin-left: 12px; font-size: 12px; }
.kv-list { list-style: none; padding: 0; }
.kv-list li { padding: 4px 0; font-family: var(--font-mono); font-size: 13px; }
code { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }
.diff { padding-left: 16px; line-height: 1.8; }
.diff li { margin: 4px 0; }
</style>