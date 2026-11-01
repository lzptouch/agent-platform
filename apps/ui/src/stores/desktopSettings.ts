/**
 * 壳设置（Boss Key / 开机自启 / 启动最小化）—— 批次 02。
 *
 * 数据源是**壳**（`window.agentDesktop`），Web 形态下该对象不存在 → 本 store
 * 退化为纯前端状态（不报错，切换项保持默认关闭）。
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import type { ShellSettings } from '@/types/agent-desktop'

const DEFAULTS: ShellSettings = {
  bossKey: null,
  autoLaunch: false,
  startMinimized: false,
}

export const useDesktopSettingsStore = defineStore('desktopSettings', () => {
  const settings = ref<ShellSettings>({ ...DEFAULTS })
  const loaded = ref(false)
  const isDesktop = ref(false)

  function bridge() {
    return typeof window !== 'undefined' ? window.agentDesktop : undefined
  }

  async function load(): Promise<void> {
    const api = bridge()
    if (!api) {
      loaded.value = true
      return
    }
    isDesktop.value = true
    try {
      const res = await api.getSettings()
      if (res.ok) settings.value = { ...DEFAULTS, ...res.settings }
    } catch {
      // 读取失败保留默认值
    } finally {
      loaded.value = true
    }
  }

  async function setBossKey(accelerator: string | null): Promise<boolean> {
    const api = bridge()
    if (!api) return false
    const res = await api.setBossKey(accelerator)
    if (!res.ok) {
      ElMessage.error(res.error?.message ?? '快捷键设置失败')
      return false
    }
    settings.value = { ...settings.value, ...res.settings }
    return true
  }

  async function setAutoLaunch(enabled: boolean): Promise<void> {
    const api = bridge()
    if (!api) return
    const res = await api.setAutoLaunch(enabled)
    if (!res.ok) {
      ElMessage.error(res.error?.message ?? '开机自启设置失败')
      return
    }
    settings.value = { ...settings.value, ...res.settings }
  }

  async function setStartMinimized(enabled: boolean): Promise<void> {
    const api = bridge()
    if (!api) return
    const res = await api.setStartMinimized(enabled)
    if (!res.ok) {
      ElMessage.error(res.error?.message ?? '启动最小化设置失败')
      return
    }
    settings.value = { ...settings.value, ...res.settings }
  }

  return {
    settings,
    loaded,
    isDesktop,
    load,
    setBossKey,
    setAutoLaunch,
    setStartMinimized,
  }
})
