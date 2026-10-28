/**
 * 轮次折叠状态（S8 / WP-8.3）。
 *
 * 用途：把"某轮对话的工具轨迹是否折叠"存起来（``runId:roundNo`` → 折叠态），
 * run 结束后自动折叠该轮；展开可回原文（不丢内容）。
 *
 * S1 曾把它当死代码删除；S8 重建为**真实使用**的折叠状态存储。
 */
import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useRoundsStore = defineStore('rounds', () => {
  /** 折叠态：key = `${runId}:${roundNo}`，true = 已折叠 */
  const collapsed = ref<Record<string, boolean>>({})

  function key(runId: string, roundNo: number): string {
    return `${runId}:${roundNo}`
  }

  function isCollapsed(runId: string, roundNo: number): boolean {
    return collapsed.value[key(runId, roundNo)] ?? false
  }

  function setCollapsed(runId: string, roundNo: number, value: boolean): void {
    collapsed.value = { ...collapsed.value, [key(runId, roundNo)]: value }
  }

  function toggle(runId: string, roundNo: number): void {
    setCollapsed(runId, roundNo, !isCollapsed(runId, roundNo))
  }

  /** run 结束自动折叠该轮 */
  function collapseRound(runId: string, roundNo: number): void {
    setCollapsed(runId, roundNo, true)
  }

  /** 清理某 run 的全部折叠状态 */
  function clearRun(runId: string): void {
    const prefix = `${runId}:`
    const next: Record<string, boolean> = {}
    for (const [k, v] of Object.entries(collapsed.value)) {
      if (!k.startsWith(prefix)) next[k] = v
    }
    collapsed.value = next
  }

  return { collapsed, isCollapsed, setCollapsed, toggle, collapseRound, clearRun }
})
