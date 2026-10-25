/**
 * 特性开关（v3 工作台灰度）。
 *
 * 依据改造计划 §10.4：
 *  - v3 = true  → `/` 走新工作台 `/workspace`
 *  - v3 = false → `/` 走旧页面 `/chat`（回滚开关）
 *  - 持久化到 localStorage，便于灰度与应急回退
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

const KEY = '__ws_v3'

function read(): boolean {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw === null) return true // 默认开启新形态
    return raw === '1' || raw === 'true'
  } catch {
    return true
  }
}

export const useFlagsStore = defineStore('flags', () => {
  const v3 = ref(read())

  function setV3(next: boolean) {
    v3.value = next
    try { localStorage.setItem(KEY, next ? '1' : '0') } catch { /* */ }
  }

  function toggleV3() { setV3(!v3.value) }

  return { v3, setV3, toggleV3 }
})
