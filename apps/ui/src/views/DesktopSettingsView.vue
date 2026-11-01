<template>
  <div class="desktop-settings">
    <h2>桌面端设置</h2>
    <p class="hint" v-if="!desktop.isDesktop">
      当前为 Web 形态（未检测到桌面壳）。此页的桌面能力在 Web 形态下不可用。
    </p>

    <!-- 运行态 -->
    <el-card shadow="never" class="card">
      <template #header><strong>运行态</strong></template>
      <el-descriptions v-if="desktop.status" :column="2" border>
        <el-descriptions-item label="版本">{{ desktop.status.app_version }}</el-descriptions-item>
        <el-descriptions-item label="运行时（Node）">{{ desktop.status.runtime.node ?? desktop.status.runtime.python }}</el-descriptions-item>
        <el-descriptions-item label="数据目录"><code>{{ desktop.status.data_dir }}</code></el-descriptions-item>
        <el-descriptions-item label="工作区"><code>{{ desktop.status.workspace_dir }}</code></el-descriptions-item>
        <el-descriptions-item label="鉴权">
          <el-tag size="small" :type="desktop.status.security.auth_required ? 'success' : 'info'">
            {{ desktop.status.security.auth_required ? '已启用' : '未启用' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="权限档位">
          <el-tag size="small">{{ levelLabel }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
      <el-button v-else size="small" @click="refreshAll">加载运行态</el-button>
    </el-card>

    <!-- 工作区 -->
    <el-card shadow="never" class="card">
      <template #header><strong>工作区</strong></template>
      <p class="desc">Agent 的执行目录与产物落地目录。切换后立即生效，无需重启。</p>
      <div class="row">
        <code class="path">{{ workspace.workspace_dir || '（未设置）' }}</code>
        <el-tag size="small" :type="workspace.writable ? 'success' : 'danger'">
          {{ workspace.writable ? '可写' : '不可写' }}
        </el-tag>
      </div>
      <div class="row">
        <el-button size="small" @click="chooseWorkspace" :disabled="!desktop.isDesktop">选择目录…</el-button>
        <el-button size="small" text @click="loadWorkspace">刷新</el-button>
      </div>
    </el-card>

    <!-- 权限 -->
    <el-card shadow="never" class="card">
      <template #header><strong>权限（Agent 能做什么）</strong></template>
      <el-radio-group :model-value="perms.effectiveLevel" @change="onLevelChange">
        <el-radio-button value="readonly">只读</el-radio-button>
        <el-radio-button value="ask">询问</el-radio-button>
        <el-radio-button value="allow">允许</el-radio-button>
      </el-radio-group>
      <p class="desc">
        只读：仅可读工作区内文件，不可执行命令；
        询问：越界或高危操作逐次询问（默认）；
        允许：允许执行命令与读写工作区外文件。
      </p>

      <el-divider content-position="left">高级规则</el-divider>
      <el-table :data="perms.rules" size="small" max-height="280">
        <el-table-column prop="scope" label="对象类型" width="100">
          <template #default="{ row }">{{ scopeLabel(row.scope) }}</template>
        </el-table-column>
        <el-table-column prop="target" label="对象" show-overflow-tooltip />
        <el-table-column label="决定" width="110">
          <template #default="{ row }">
            <el-select
              :model-value="row.decision"
              size="small"
              @change="(v: string) => perms.setRule(row.scope, row.target, v)"
            >
              <el-option label="允许" value="allow" />
              <el-option label="询问" value="ask" />
              <el-option label="拒绝" value="deny" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column prop="hit_count" label="命中" width="70" />
      </el-table>
    </el-card>

    <!-- 通知 -->
    <el-card shadow="never" class="card">
      <template #header><strong>通知</strong></template>
      <el-form label-width="160px">
        <el-form-item label="任务完成时通知">
          <el-switch :model-value="prefs.notify_on_run" @change="(v: boolean) => savePref('notify_on_run', v)" />
        </el-form-item>
        <el-form-item label="通知通道">
          <el-select
            :model-value="prefs.notify_channel"
            style="width: 160px"
            @change="(v: string) => savePref('notify_channel', v)"
          >
            <el-option label="系统通知" value="system" />
            <el-option label="应用内提示" value="toast" />
            <el-option label="关闭" value="off" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 在世交互（批次 02）：Boss Key / 开机自启 / 启动最小化 -->
    <el-card shadow="never" class="card">
      <template #header><strong>在世交互</strong></template>
      <p class="desc" v-if="!shell.isDesktop">
        当前为 Web 形态（未检测到桌面壳），以下设置仅在桌面端生效。
      </p>
      <el-form label-width="160px">
        <el-form-item label="Boss Key">
          <div class="row">
            <el-input
              :model-value="bossKeyInput"
              readonly
              class="boss-input"
              :placeholder="shell.settings.bossKey || '未绑定（点击后按下快捷键）'"
              @keydown="onBossKeyKeydown"
              @click="captureBossKey"
            />
            <el-button size="small" @click="captureBossKey">
              {{ capturing ? '按下快捷键…' : '绑定' }}
            </el-button>
            <el-button size="small" text @click="clearBossKey">解绑</el-button>
          </div>
          <div class="desc">
            用于显隐切换主窗口。<strong>默认不绑定</strong>（避免与系统快捷键冲突），绑定后立即生效并持久化。
          </div>
        </el-form-item>
        <el-form-item label="开机自启">
          <el-switch
            :model-value="shell.settings.autoLaunch"
            :disabled="!shell.isDesktop"
            @change="(v: boolean) => shell.setAutoLaunch(v)"
          />
        </el-form-item>
        <el-form-item label="启动时最小化到托盘">
          <el-switch
            :model-value="shell.settings.startMinimized"
            :disabled="!shell.isDesktop"
            @change="(v: boolean) => shell.setStartMinimized(v)"
          />
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useDesktopStore } from '@/stores/desktop'
import { usePermissionsStore } from '@/stores/permissions'
import { useDesktopSettingsStore } from '@/stores/desktopSettings'
import { desktopWorkspaceGet, desktopWorkspaceSet, desktopPreferencesGet, desktopPreferencesUpdate } from '@/api/desktop'
import type { DesktopWorkspace, DesktopPreferences } from '@/api/types'

const desktop = useDesktopStore()
const perms = usePermissionsStore()
const shell = useDesktopSettingsStore()

/** Boss Key 捕获（批次 02）：默认不绑定，用户按下组合键后写入。 */
const capturing = ref(false)
const bossKeyInput = ref('')

function onBossKeyKeydown(e: KeyboardEvent): void {
  if (!capturing.value) return
  e.preventDefault()
  if (['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) return
  const parts: string[] = []
  if (e.ctrlKey) parts.push('Ctrl')
  if (e.altKey) parts.push('Alt')
  if (e.shiftKey) parts.push('Shift')
  if (e.metaKey) parts.push('Super')
  parts.push(e.key.length === 1 ? e.key.toUpperCase() : e.key)
  const accelerator = parts.join('+')
  capturing.value = false
  bossKeyInput.value = accelerator
  void shell.setBossKey(accelerator)
}

function captureBossKey(): void {
  capturing.value = true
  ElMessage.info('请按下要绑定的快捷键（Esc 取消）')
}

async function clearBossKey(): Promise<void> {
  capturing.value = false
  bossKeyInput.value = ''
  await shell.setBossKey(null)
  ElMessage.success('已解绑 Boss Key')
}

const workspace = ref<DesktopWorkspace>({ workspace_dir: '', exists: false, writable: false })
const prefs = ref<DesktopPreferences>({
  workspace_dir: '', default_mode: 'chat', danger_tools: false,
  notify_on_run: true, notify_channel: 'system', remote_mode: false, remote_base: '', updated_at: '',
})

const levelLabel = computed(() => {
  return { readonly: '只读', ask: '询问', allow: '允许' }[perms.effectiveLevel] ?? perms.effectiveLevel
})

function scopeLabel(scope: string): string {
  return { tool: '工具', path: '路径', action: '动作' }[scope] ?? scope
}

async function refreshAll() {
  await Promise.all([desktop.refresh(), perms.refresh(), loadWorkspace(), loadPrefs(), shell.load()])
  bossKeyInput.value = shell.settings.bossKey ?? ''
}

async function loadWorkspace() {
  try { workspace.value = await desktopWorkspaceGet() } catch { /* 忽略 */ }
}

async function loadPrefs() {
  try { prefs.value = await desktopPreferencesGet() } catch { /* 忽略 */ }
}

async function chooseWorkspace() {
  const res = await window.agentDesktop?.chooseDirectory({ title: '选择工作区目录' })
  if (res && res.ok && res.path) {
    try {
      await desktopWorkspaceSet(res.path)
      ElMessage.success('工作区已切换，立即生效')
      await loadWorkspace()
      await desktop.refresh()
    } catch (e) {
      ElMessage.error((e as Error).message)
    }
  }
}

async function onLevelChange(level: string | number | boolean | undefined) {
  if (typeof level !== 'string') return
  if (level === 'allow') {
    const confirmed = window.confirm(
      '「允许」档下，Agent 可以执行任意命令并读写工作区外的文件。\n高危操作（批量删除 / 改系统配置）仍会被拦。\n\n确认切换？'
    )
    if (!confirmed) return
  }
  // 档位 → 批量设置危险工具规则
  const decision = level === 'readonly' ? 'deny' : level === 'allow' ? 'allow' : 'ask'
  for (const tool of ['write_file', 'execute_python', 'execute_bash']) {
    await perms.setRule('tool', tool, decision)
  }
  ElMessage.success(`权限档位已切换为「${levelLabel.value}」`)
}

async function savePref(key: keyof DesktopPreferences, value: unknown) {
  try {
    const res = await desktopPreferencesUpdate({ [key]: value })
    prefs.value = res.preferences
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.desktop-settings { padding: 16px 24px; overflow-y: auto; height: 100%; }
.hint { color: var(--text-dim); margin: 4px 0 16px; }
.card { margin-bottom: 12px; }
.desc { color: var(--text-dim); font-size: 12px; margin: 6px 0 10px; }
.row { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
.boss-input { width: 240px; }
.path { background: var(--bg-code); padding: 4px 8px; border-radius: 4px; font-family: var(--font-mono); font-size: 12px; }
code { font-family: var(--font-mono); }
</style>
