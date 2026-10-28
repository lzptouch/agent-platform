<template>
  <div class="plugins-view">
    <h2>插件</h2>
    <p class="hint">本地安装第三方扩展包（zip 或目录）。安装前会静态扫描：<b>high/critical 默认拒绝</b>，需显式确认。</p>

    <div class="actions">
      <el-input v-model="installPath" placeholder="本地插件目录路径（含 plugin.json）" style="max-width: 380px" />
      <el-button @click="previewScan" :loading="scanning">扫描</el-button>
      <el-button type="primary" :loading="installing" @click="install">安装</el-button>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="scanResult"
      class="scan"
      :type="alertType"
      :closable="false"
      :title="`扫描等级：${scanResult.level}${scanResult.rejected_by_default ? '（默认拒绝，需显式确认）' : ''}`"
    >
      <div v-if="scanResult.findings?.length">
        <div v-for="(f, i) in scanResult.findings" :key="i" class="finding">
          <el-tag size="small" :type="tagType(f.level)">{{ f.level }}</el-tag>
          {{ f.reason }}<span v-if="f.path" class="dim">（{{ f.path }}）</span>
        </div>
      </div>
      <div v-else>未发现风险项。</div>
    </el-alert>

    <el-table :data="items" size="small" v-loading="loading">
      <el-table-column prop="name" label="名称" width="160" />
      <el-table-column prop="version" label="版本" width="100" />
      <el-table-column label="扫描" width="130">
        <template #default="{ row }">
          <el-tag size="small" :type="tagType(row.scan?.level ?? 'low')">{{ row.scan?.level ?? '-' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column label="内容" min-width="220">
        <template #default="{ row }">
          <span class="dim">{{ contentSummary(row.manifest) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-popconfirm title="确认回滚到上一版本？" @confirm="rollback(row)">
            <template #reference><el-button size="small" text>回滚</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  pluginInstall,
  pluginRollback,
  pluginScan,
  pluginsList,
  type PluginItem,
  type PluginScanResult,
} from '@/api'

const items = ref<PluginItem[]>([])
const loading = ref(false)
const installPath = ref('')
const scanning = ref(false)
const installing = ref(false)
const scanResult = ref<PluginScanResult | null>(null)

const alertType = computed(() => {
  const lv = scanResult.value?.level
  if (lv === 'high' || lv === 'critical') return 'error'
  if (lv === 'medium') return 'warning'
  return 'success'
})

function tagType(level: string): 'success' | 'warning' | 'danger' | 'info' {
  if (level === 'high' || level === 'critical') return 'danger'
  if (level === 'medium') return 'warning'
  return 'success'
}

function contentSummary(manifest: Record<string, unknown> | undefined): string {
  if (!manifest) return '-'
  const parts = Object.entries(manifest)
    .filter(([, v]) => Array.isArray(v) && (v as unknown[]).length)
    .map(([k, v]) => `${k}×${(v as unknown[]).length}`)
  return parts.join(' · ') || '-'
}

async function load(): Promise<void> {
  loading.value = true
  try { items.value = (await pluginsList()).items } finally { loading.value = false }
}

async function previewScan(): Promise<void> {
  if (!installPath.value.trim()) return
  scanning.value = true
  try {
    scanResult.value = await pluginScan(installPath.value.trim())
  } catch (e: unknown) {
    ElMessage.error(`扫描失败：${(e as Error).message}`)
  } finally {
    scanning.value = false
  }
}

async function install(): Promise<void> {
  if (!installPath.value.trim()) return
  installing.value = true
  try {
    const res = await pluginInstall({
      path: installPath.value.trim(),
      confirm: scanResult.value?.rejected_by_default === true,
    })
    if (res.ok) {
      ElMessage.success('已安装')
      scanResult.value = null
      await load()
    } else {
      ElMessage.warning(res.message)
      if (res.scan) scanResult.value = { ...res.scan, findings: res.scan.findings ?? [] } as PluginScanResult
    }
  } catch (e: unknown) {
    ElMessage.error(`安装失败：${(e as Error).message}`)
  } finally {
    installing.value = false
  }
}

async function rollback(row: PluginItem): Promise<void> {
  try {
    const res = await pluginRollback(row.name, row.version)
    if (res.ok) { ElMessage.success(res.message); await load() }
    else ElMessage.warning(res.message)
  } catch (e: unknown) {
    ElMessage.error(`回滚失败：${(e as Error).message}`)
  }
}

onMounted(load)
</script>

<style scoped>
.plugins-view { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.actions { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }
.scan { margin-bottom: 12px; }
.finding { margin: 2px 0; font-size: 12px; }
.dim { color: var(--text-faint); }
</style>
