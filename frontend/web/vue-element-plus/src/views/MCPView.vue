<template>
  <div class="mcp-view">
    <h2>MCP 控制台</h2>
    <p class="hint">管理 3 个 MCP Server（weather / search / xiaohongshu）。详情调用失败时渲染 <code>error</code> 字段；工具调用失败 HTTP 200 但 <code>error</code> 非空。</p>

    <div class="actions">
      <el-button @click="refresh" :loading="loading">刷新</el-button>
      <el-button @click="reload" :loading="reloading">重载工具缓存</el-button>
    </div>

    <el-alert v-if="reloadResult" type="success" :closable="false" style="margin: 12px 0">
      重载完成，共 {{ reloadResult.reloaded }} 个 Server（{{ reloadResult.servers.join('、') }}）。
    </el-alert>

    <div class="grid">
      <el-card v-for="s in servers" :key="s.name" class="server-card" shadow="hover">
        <template #header>
          <div class="card-head">
            <div>
              <strong>{{ s.name }}</strong>
              <el-tag class="ml" :type="statusType(s.status)" size="small">{{ s.status }}</el-tag>
            </div>
            <div class="ops">
              <el-button size="small" @click="start(s.name)" :loading="starting === s.name">启动</el-button>
              <el-button size="small" type="danger" plain @click="stop(s.name)" :loading="stopping === s.name">停止</el-button>
            </div>
          </div>
          <div class="stage">{{ s.stage }}</div>
        </template>
        <div class="desc">{{ s.description }}</div>

        <div v-if="detail?.error && detail.name === s.name" class="error-box">
          ⚠ {{ detail.error }}
        </div>

        <div v-if="detail && detail.name === s.name && detail.tools?.length" class="tools">
          <div v-for="t in detail.tools" :key="t.name" class="tool">
            <div class="tool-head">
              <span class="tool-name">{{ t.name }}</span>
              <el-button size="small" link type="primary" @click="openCall(s.name, t)">调用</el-button>
            </div>
            <div class="tool-desc">{{ t.description }}</div>
          </div>
        </div>
        <div v-else-if="detail && detail.name === s.name && !detail.tools?.length && !detail.error" class="empty">
          （该 Server 无工具）
        </div>
      </el-card>
    </div>

    <!-- 工具调用弹窗 -->
    <el-dialog v-model="callDlg.show" :title="`调用 ${callDlg.server} / ${callDlg.tool}`" width="600px">
      <el-form>
        <el-form-item label="参数（JSON）">
          <el-input v-model="callDlg.argsText" type="textarea" :rows="8" placeholder='例如 {"city": "北京"}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="callDlg.show = false">取消</el-button>
        <el-button type="primary" :loading="callDlg.loading" @click="doCall">执行</el-button>
      </template>
    </el-dialog>

    <!-- 调用结果抽屉 -->
    <el-drawer v-model="resultDlg.show" :title="`调用结果：${resultDlg.server} / ${resultDlg.tool}`" size="50%">
      <el-alert v-if="resultDlg.error" type="error" :title="`工具调用失败：${resultDlg.error}`" :closable="false" show-icon style="margin-bottom: 12px" />
      <pre class="result">{{ resultDlg.result }}</pre>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, type MessageBoxData } from 'element-plus'
import { mcpList, mcpDetail, mcpStart, mcpStop, mcpCall, mcpReload } from '@/api'
import type { McpServerInfo, McpServerDetail, McpCallResponse } from '@/api/types'

const servers = ref<McpServerInfo[]>([])
const detail = ref<{ name: string; tools: { name: string; description: string }[]; error?: string } | null>(null)
const loading = ref(false)
const reloading = ref(false)
const reloadResult = ref<{ reloaded: number; servers: string[] } | null>(null)
const starting = ref<string | null>(null)
const stopping = ref<string | null>(null)

const callDlg = ref<{ show: boolean; server: string; tool: string; argsText: string; loading: boolean }>({
  show: false, server: '', tool: '', argsText: '{}', loading: false,
})

const resultDlg = ref<{ show: boolean; server: string; tool: string; result: string; error?: string }>({
  show: false, server: '', tool: '', result: '',
})

onMounted(() => refresh())

async function refresh() {
  loading.value = true
  try { servers.value = (await mcpList()).servers }
  catch (e: unknown) { ElMessage.error(`加载失败：${(e as Error).message}`) }
  finally { loading.value = false }
}

async function reload() {
  reloading.value = true
  try {
    reloadResult.value = await mcpReload()
    detail.value = null
    await refresh()
  } catch (e: unknown) {
    ElMessage.error(`重载失败：${(e as Error).message}`)
  } finally { reloading.value = false }
}

async function loadDetail(name: string) {
  try {
    const d: McpServerDetail = await mcpDetail(name)
    detail.value = { name: d.name, tools: d.tools ?? [], error: d.error }
  } catch (e: unknown) {
    detail.value = { name, tools: [], error: `加载详情失败：${(e as Error).message}` }
  }
}

function statusType(s: string): '' | 'success' | 'warning' | 'danger' {
  if (s === 'ready') return 'success'
  if (s === 'disabled') return 'warning'
  return 'danger'
}

async function start(name: string) {
  starting.value = name
  try {
    await mcpStart(name)
    await refresh()
    await loadDetail(name)
    ElMessage.success(`已启动 ${name}`)
  } catch (e: unknown) {
    ElMessage.error(`启动失败：${(e as Error).message}`)
  } finally { starting.value = null }
}

async function stop(name: string) {
  stopping.value = name
  try {
    await mcpStop(name)
    await refresh()
    ElMessage.success(`已停止 ${name}`)
  } catch (e: unknown) {
    ElMessage.error(`停止失败：${(e as Error).message}`)
  } finally { stopping.value = null }
}

async function ensureDetail(name: string) {
  if (!detail.value || detail.value.name !== name) await loadDetail(name)
}

function openCall(server: string, tool: { name: string; description: string }) {
  callDlg.value = { show: true, server, tool: tool.name, argsText: '{}', loading: false }
}

async function doCall() {
  let args: Record<string, unknown> = {}
  try { args = JSON.parse(callDlg.value.argsText || '{}') }
  catch { ElMessage.error('参数不是合法 JSON'); return }
  callDlg.value.loading = true
  try {
    const r: McpCallResponse = await mcpCall(callDlg.value.server, { tool: callDlg.value.tool, arguments: args })
    resultDlg.value = { show: true, server: r.server, tool: r.tool, result: r.result, error: r.error ?? undefined }
    callDlg.value.show = false
  } catch (e: unknown) {
    ElMessage.error(`调用失败：${(e as Error).message}`)
  } finally { callDlg.value.loading = false }
}
</script>

<style scoped>
.mcp-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.hint code { background: var(--bg-code); padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); }
.actions { display: flex; gap: 8px; margin-bottom: 12px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 12px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.card-head .ml { margin-left: 6px; }
.ops { display: flex; gap: 4px; }
.stage { font-size: 11px; color: var(--text-dim); margin-top: 2px; }
.desc { color: var(--text-dim); font-size: 13px; margin-bottom: 8px; }
.error-box { background: rgba(229, 72, 77, 0.08); color: var(--red); padding: 8px 10px; border-radius: var(--radius-sm); font-size: 12px; margin-bottom: 8px; }
.tools { display: flex; flex-direction: column; gap: 6px; }
.tool { padding: 8px 10px; background: var(--bg-sidebar); border-radius: var(--radius-sm); }
.tool-head { display: flex; justify-content: space-between; align-items: center; }
.tool-name { font-weight: 500; font-family: var(--font-mono); font-size: 12px; }
.tool-desc { color: var(--text-dim); font-size: 12px; margin-top: 2px; }
.empty { color: var(--text-faint); font-size: 12px; }
.result { background: var(--bg-code); padding: 12px; border-radius: var(--radius-sm); font-size: 12px; white-space: pre-wrap; max-height: 60vh; overflow-y: auto; }
</style>