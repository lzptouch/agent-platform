# Vue 3 极简前端与 SSE 自研消费（扩充版）

> - **整理日期**：2026-09-15（首发 2026-09-15 扩充）
> - **依据项目**：`apps/agent/frontend/src/App.vue` + `frontend/src/api.js` + `frontend/src/components/*.vue`
> - **资料来源**：Vue 3 官方文档 + MDN EventSource + MDN ReadableStream + @microsoft/fetch-event-source

---

# 第一章 8 组件清单

```
frontend/src/
├── App.vue                 (主组件，状态 + SSE 流)
├── api.js                  (~80 行，HTTP + 自研 readSSE)
├── components/
│   ├── SideBar.vue         会话列表 + 工具链开关
│   ├── WelcomeScreen.vue   欢迎页 + 推荐卡片
│   ├── ChatMessage.vue     消息渲染（含 tool_call 步骤）
│   ├── MarkdownText.vue    Markdown 渲染
│   ├── ChatInput.vue       输入框
│   ├── ProcessSteps.vue    步骤可视化
│   ├── SkillModal.vue      Skill 详情弹窗
│   └── ResearchView.vue    深度研究视图
└── style.css               CSS 变量主题
```

**总代码量**：~1500 行 Vue 3 + JS，**极度克制**。

---

# 第二章 状态管理（无 Pinia）

App.vue 用 ref + computed 自管（与 agent 风格一致）：

```vue
<!-- App.vue:11-31 -->
<script setup>
const STORAGE_KEY = 'agent-sessions'
const SKILL_KEY = 'agent-selected-skills'
const MODE_KEY = 'agent-mode'

const mode = ref(localStorage.getItem(MODE_KEY) || 'chat')
const skills = ref([])
const selectedSkills = ref([])
const enableMcp = ref(false)
const enableRag = ref(true)
const enableWeb = ref(false)
const enableReflection = ref(false)
const sessions = ref([])
const currentId = ref(null)

// ★ localStorage 持久化
watch([mode], ([newMode]) => {
  localStorage.setItem(MODE_KEY, newMode)
})
</script>
```

## 2.1 状态结构

```typescript
// 类型推断（手写 .d.ts）
interface AppState {
  mode: 'chat' | 'research'      // 模式
  skills: Skill[]                // 所有 Skill
  selectedSkills: string[]       // 用户选中的 Skill
  enableMcp: boolean              // MCP 链开关
  enableRag: boolean              // RAG 链开关
  enableWeb: boolean              // Web Research 链开关
  enableReflection: boolean       // Reflection 开关
  sessions: Session[]             // 会话列表
  currentId: string | null        // 当前会话 ID
  messages: Message[]             // 当前会话消息
  loading: boolean                 // 是否正在请求
}
```

## 2.2 localStorage 持久化策略

| Key | 内容 | 持久化时机 |
|-----|------|----------|
| `agent-sessions` | 所有会话 | 每次消息变化 |
| `agent-selected-skills` | 选中 Skill | watch 触发 |
| `agent-mode` | 模式（chat/research） | watch 触发 |

---

# 第三章 自研 SSE 消费（核心创新）

## 3.1 为什么自研 readSSE

原生 EventSource 的限制：

| 限制 | 说明 |
|------|------|
| 仅支持 GET | POST 不行 |
| 无法自定义 header | token 只能放 URL（不安全） |
| 自动重连 | 可能产生重复事件 |
| 无超时控制 | 长连接可能挂死 |

**自研 readSSE 的优势**：

```javascript
// ✅ 支持 POST
// ✅ 支持自定义 header（鉴权）
// ✅ 支持 AbortController（中断）
// ✅ 解析 SSE event/data 协议
```

## 3.2 readSSE 完整实现

```javascript
// src/api.js
export async function readSSE(response, onEvent, signal) {
  """fetch + ReadableStream 解析 SSE"""
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  
  while (true) {
    const { done, value } = await reader.read()
    if (done || signal?.aborted) break
    
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''   // ★ 保留不完整行
    
    let event = null, data = null
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data = line.slice(5).trim()
      else if (line === '' && event && data) {
        try {
          onEvent({ event, data: JSON.parse(data) })
        } catch (e) {
          console.warn('SSE 解析失败', e)
        }
        event = null
        data = null
      }
    }
  }
}
```

### 3.2.1 SSE 协议解析

```
event: skills_selected
data: {"skills": ["pdf"]}

event: plan
data: {"plan": [...]}

event: tool_call
data: {"tool": "web_search", "args": {...}}

event: done
data: {}
```

每条消息格式：
- `event: <类型>` — 事件名
- `data: <JSON>` — 数据（JSON 字符串）
- 空行分隔

### 3.2.2 Buffer 累积

```javascript
let buffer = ''

// 接收 chunk
buffer += decoder.decode(value, { stream: true })

// 按行拆分
const lines = buffer.split('\n')

// ★ 保留不完整行（可能在 chunk 边界被截断）
buffer = lines.pop() || ''

// 解析完整的行（以空行结尾）
for (const line of lines) {
  // ...
}
```

## 3.3 streamAgent 主入口

```javascript
// src/api.js
export async function streamAgent(params, onEvent, signal) {
  const response = await fetch('/api/v1/agent/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal,                                          // ★ AbortController
  })
  
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  
  await readSSE(response, onEvent, signal)
}
```

## 3.4 SSE 事件处理器

```javascript
// App.vue
async function send(prompt) {
  messages.value.push({ role: 'user', content: prompt })
  loading.value = true
  
  await streamAgent({
    prompt,
    model: settings.model,
    skills: selectedSkills.value,
    enable_mcp: enableMcp.value,
    enable_rag: enableRag.value,
    enable_web_research: enableWeb.value,
    enable_reflection: enableReflection.value,
  }, (event) => {
    // ★ 10+ 事件类型处理
    switch (event.event) {
      case 'skills_selected':
        skills.value = event.data.skills
        break
      case 'plan':
        reasoningSteps.value.push(`Plan: ${JSON.stringify(event.data.plan)}`)
        break
      case 'tool_call':
        processSteps.value.push({ type: 'tool_call', ...event.data })
        break
      case 'tool_result':
        processSteps.value.push({ type: 'tool_result', ...event.data })
        break
      case 'reasoning_delta':
        reasoningSteps.value.push(event.data.content)
        break
      case 'model_text':
        currentMessage.value += event.data.content
        break
      case 'reflection_plan':
        reasoningSteps.value.push(`[反思] ${JSON.stringify(event.data.plan)}`)
        break
      case 'files':
        files.value.push(...event.data)
        break
      case 'error':
        ElMessage.error(event.data.message)
        break
      case 'done':
        loading.value = false
        break
    }
  })
}
```

---

# 第四章 工具来源着色（设计亮点）

## 4.1 4 链配色方案

```vue
<!-- components/ChatMessage.vue -->
<script setup>
const TOOL_COLORS = {
  builtin: '#00BCD4',   // 内置工具 - 青色
  mcp: '#9C27B0',       // MCP - 紫色
  rag: '#4CAF50',       // RAG - 绿色
  web: '#FF9800',       // Web - 橙色
}

function getTagColor(source) {
  return TOOL_COLORS[source] || '#909399'
}
</script>

<template>
  <div class="tool-tag" :style="{ backgroundColor: getTagColor(tool.source) }">
    {{ tool.name }}
  </div>
</template>
```

## 4.2 ProcessSteps 步骤可视化

```vue
<!-- components/ProcessSteps.vue -->
<script setup>
const props = defineProps<{ steps: any[] }>()

const expanded = ref(true)
const stepEl = ref(null)

watch(() => props.steps.length, async () => {
  await nextTick()
  if (stepEl.value) {
    stepEl.value.scrollTop = stepEl.value.scrollHeight    // ★ 自动滚动
  }
})
</script>

<template>
  <div class="process-steps">
    <el-button @click="expanded = !expanded">
      思考过程 ({{ steps.length }} 步)
    </el-button>
    <div v-if="expanded" ref="stepEl" class="process-steps-content">
      <div v-for="(step, idx) in steps" :key="idx" :class="`step-${step.type}`">
        <span class="step-icon">{{ stepIcon(step.type) }}</span>
        <span class="step-content">{{ step.content }}</span>
      </div>
    </div>
  </div>
</template>
```

---

# 第五章 业界做法对比

## 5.1 SSE 消费方案对比

| 方案 | 优势 | 劣势 |
|------|------|------|
| **自研 readSSE**（本项目） | ✅ POST + header + AbortController | ❌ 需自己解析协议 |
| **原生 EventSource** | 零依赖；自动重连 | ❌ 仅 GET；无 header |
| **@microsoft/fetch-event-source** | ✅ POST + header；自动重连 | ❌ 依赖第三方 |
| **react-markdown + ServerSentEvents** | React 专属 | ❌ React 专属 |

## 5.2 状态管理对比

| 方案 | 适用 | 优势 |
|------|------|------|
| **App.vue ref**（本项目） | 小型（≤5 视图） | 极简；零依赖 |
| **Pinia**（finance-report） | 中大型 | TS 友好；devtools |
| **valtio**（industry-research） | 中型 | Proxy 代理；轻量 |
| **Vuex** | 老项目 | 成熟 |

---

# 第六章 操作步骤

## 6.1 P1-1：AbortController 中断

```javascript
// App.vue
let abortController = null

async function send() {
  abortController = new AbortController()   // ★ 新建
  await streamAgent(params, onEvent, abortController.signal)
}

function stop() {
  abortController?.abort()                  // ★ 中断
}
```

## 6.2 P1-2：错误重试 + 指数退避

```javascript
async function streamAgentWithRetry(params, maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      await streamAgent(params, onEvent, signal)
      return
    } catch (e) {
      if (i === maxRetries - 1) throw e
      const delay = Math.min(1000 * Math.pow(2, i), 10000)  // 1s, 2s, 4s, 8s, 10s
      await new Promise(r => setTimeout(r, delay))
    }
  }
}
```

## 6.3 P1-3：TypeScript 迁移

```typescript
// types/api.ts
export interface RunRequest {
  prompt: string
  model: string
  skills: string[]
  enable_mcp: boolean
  mcp_servers: string[]
  enable_rag: boolean
  enable_web_research: boolean
  enable_reflection: boolean
}

export type StreamEvent =
  | { event: 'skills_selected'; data: { skills: string[] } }
  | { event: 'plan'; data: { plan: any[] } }
  | { event: 'tool_call'; data: { tool: string; args: any } }
  | { event: 'tool_result'; data: { tool: string; result: any } }
  | { event: 'reasoning_delta'; data: { content: string } }
  | { event: 'model_text'; data: { content: string } }
  | { event: 'reflection_plan'; data: { plan: any[] } }
  | { event: 'files'; data: Array<{ path: string; type: string }> }
  | { event: 'error'; data: { message: string } }
  | { event: 'done'; data: {} }
```

## 6.4 P2-1：替换为 fetch-event-source

```bash
npm install @microsoft/fetch-event-source
```

```javascript
import { fetchEventSource } from '@microsoft/fetch-event-source'

export async function streamAgent(params, onEvent, signal) {
  await fetchEventSource('/api/v1/agent/run', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${getToken()}`,   // ★ 自动重试 + header
    },
    body: JSON.stringify(params),
    signal,
    onmessage(event) {
      onEvent({ event: event.event, data: JSON.parse(event.data) })
    },
    onerror(err) {
      throw err   // ★ 自动重连
    }
  })
}
```

---

## 附录 A：参考文献

| # | 类型 | 标题 | 来源 | 访问日期 |
|---|------|------|------|----------|
| [1] | 官方文档 | Vue 3 | https://vuejs.org | 2026-09-15 |
| [2] | 标准 | MDN EventSource | https://developer.mozilla.org/en-US/docs/Web/API/EventSource | 2026-09-15 |
| [3] | 标准 | MDN ReadableStream | https://developer.mozilla.org/en-US/docs/Web/API/ReadableStream | 2026-09-15 |
| [4] | 标准 | MDN AbortController | https://developer.mozilla.org/en-US/docs/Web/API/AbortController | 2026-09-15 |
| [5] | 标准 | MDN fetch | https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API | 2026-09-15 |
| [6] | OSS 项目 | @microsoft/fetch-event-source | https://github.com/Azure/fetch-event-source | 2026-09-15 |
| [7] | 官方文档 | Pinia | https://pinia.vuejs.org | 2026-09-15 |
| [8] | OSS 项目 | valtio | https://github.com/pmndrs/valtio | 2026-09-15 |
| [9] | 同源文档 | `apps/finance-report/doc/knowledge/06_Vue3_Pinia_ElementPlus状态管理实践.md` | Pinia 风格对比 | 2026-09-15 |
| [10] | 同源文档 | `apps/industry-research/frontend/src/store/` | valtio 风格对比 | 2026-09-15 |

---

> **本文档结构遵循「五段式」**：当前实现 → 原理剖析 → 业界做法调研 → 操作步骤 → 参考文献附录。
