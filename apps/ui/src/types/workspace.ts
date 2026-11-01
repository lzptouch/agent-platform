/**
 * v3 工作台共享类型（独立文件，避免在 <script setup> 中导出类型）。
 */
import type { Component } from 'vue'

/** Plan 审批步骤 */
export interface PlanStep {
  id: number
  title: string
  detail: string
}

/** @ 上下文候选项 */
export interface AtItem {
  key: string
  title: string
  desc?: string
  icon: Component
}

/** "/" 命令面板条目 */
export interface CommandItem {
  key: string
  title: string
  desc: string
  icon: Component
  tag?: string
  run: () => void
}
