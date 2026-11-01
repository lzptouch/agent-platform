/**
 * 三态权限规则 + 审批队列（S2，形态无关）。
 *
 * 数据源：后端 `/permissions/*`（不再区分桌面/Web）；审批队列通过
 * `pollPending()` 拉取待审批列表（也承担"审批通道活性"心跳）。
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  permissionDecisions,
  permissionResolve,
  permissionRuleDelete,
  permissionRuleSet,
  permissionRules,
  permissionSandbox,
} from '@/api'
import type { PendingApproval } from '@/components/PermissionCard.vue'

export type PermissionLevel = 'readonly' | 'ask' | 'allow'

export const usePermissionsStore = defineStore('permissions', () => {
  const rules = ref<Array<Record<string, unknown>>>([])
  const effectiveLevel = ref<PermissionLevel>('ask')
  const sandboxLevel = ref('policy_only')
  const sandboxAvailable = ref(true)
  const loaded = ref(false)
  /** 待审批队列（审批卡的来源） */
  const pendingApprovals = ref<PendingApproval[]>([])

  const ruleMap = computed(() => {
    const map = new Map<string, Record<string, unknown>>()
    for (const r of rules.value) map.set(`${r.scope}:${r.target ?? r.pattern}`, r)
    return map
  })

  async function refresh(): Promise<void> {
    try {
      const data = await permissionRules()
      rules.value = data.rules
      effectiveLevel.value = data.effective_level
      const sb = await permissionSandbox()
      sandboxLevel.value = sb.level
      sandboxAvailable.value = sb.available
    } finally {
      loaded.value = true
    }
  }

  async function setRule(scope: string, pattern: string, decision: string, risk?: string): Promise<void> {
    await permissionRuleSet({ scope, pattern, decision, risk })
    await refresh()
  }

  async function deleteRule(scope: string, pattern: string, workspaceId?: string): Promise<void> {
    // **W4-01**：后端返回 `{ok}` —— 此前**不检查 ok** → 删除失败时用户**看不到任何反馈**
    // （规则还在列表里，看起来像"删了又回来"）。
    const res = await permissionRuleDelete({ scope, pattern, workspace_id: workspaceId })
    if (res && res.ok === false) {
      throw new Error('规则删除失败（可能已被删除或工作空间不匹配）')
    }
    await refresh()
  }

  /** 拉取待审批列表（每次调用都会让后端的"审批通道活性"续期 10s）。 */
  async function pollPending(): Promise<void> {
    try {
      const data = await permissionDecisions({ status: 'pending' })
      pendingApprovals.value = data.items.map((d) => ({
        id: d.id,
        tool_name: d.tool_name,
        reason: d.reason,
        risk: (d.request as Record<string, unknown>)?.risk as string | undefined,
        target: undefined,
        request: d.request,
        created_at: d.created_at,
      }))
    } catch {
      // 拉取失败不阻断主流程
    }
  }

  async function resolveApproval(id: number, choice: 'allow_once' | 'allow_session' | 'allow_workspace' | 'deny'): Promise<void> {
    await permissionResolve({ decision_id: id, choice })
    pendingApprovals.value = pendingApprovals.value.filter((a) => a.id !== id)
  }

  return {
    rules, effectiveLevel, sandboxLevel, sandboxAvailable, loaded, ruleMap,
    pendingApprovals, refresh, setRule, deleteRule, pollPending, resolveApproval,
  }
})
