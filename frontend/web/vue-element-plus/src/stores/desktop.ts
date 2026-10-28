/**
 * 桌面能力探测与状态（Pinia store）。
 *
 * - ``isDesktop`` 由 ``window.agentDesktop`` 存在性决定（preload 注入）；
 * - 其余能力位由后端 ``/desktop/status`` 与 ``/desktop/components`` 提供；
 * - Web 形态下全部能力为 false，调用方据此降级（不渲染桌面专属入口）。
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { desktopStatus, desktopComponents } from '@/api/desktop'
import type { DesktopStatus, DesktopComponents } from '@/api/types'

export const useDesktopStore = defineStore('desktop', () => {
  const isDesktop = ref<boolean>(typeof window !== 'undefined' && !!window.agentDesktop)
  const status = ref<DesktopStatus | null>(null)
  const components = ref<DesktopComponents | null>(null)
  const loaded = ref(false)

  const capabilities = computed(() => {
    const d = isDesktop.value
    return {
      tray: d,
      globalHotkey: d,
      systemNotify: d,
      nativeSaveAs: d,
      chooseDirectory: d,
      clipboard: d,
      updater: d,
      deepLink: d,
    }
  })

  async function refresh(): Promise<void> {
    if (!isDesktop.value) return
    try {
      status.value = await desktopStatus()
      components.value = await desktopComponents()
    } catch {
      // 后端未就绪时不阻塞
    } finally {
      loaded.value = true
    }
  }

  return { isDesktop, status, components, loaded, capabilities, refresh }
})
