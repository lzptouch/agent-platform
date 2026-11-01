/**
 * 桌面端 REST 封装（/desktop/*）+ 运行控制（/runs/{id}/cancel|steer）。
 *
 * 仅桌面形态下使用；Web 形态调用同样安全（后端端点不区分形态，守卫只在桌面模式启用）。
 */

import { Endpoints } from './endpoints'
import { get, post, put } from './client'
import type {
  DesktopStatus, DesktopPreferences, DesktopWorkspace, DesktopWorkspaceResult,
  DesktopComponents, DesktopPermissions, PermissionDecisionResp, ResumeScanResult,
} from './types'

// ===== 运行态 =====
export const desktopStatus = () => get<DesktopStatus>(Endpoints.desktopStatus)
export const desktopComponents = () => get<DesktopComponents>(Endpoints.desktopComponents)

// ===== 配置 =====
export const desktopPreferencesGet = () => get<DesktopPreferences>(Endpoints.desktopPreferences)
export const desktopPreferencesUpdate = (payload: Partial<DesktopPreferences>) =>
  put<{ ok: boolean; preferences: DesktopPreferences }>(Endpoints.desktopPreferences, payload)

// ===== 工作区 =====
export const desktopWorkspaceGet = () => get<DesktopWorkspace>(Endpoints.desktopWorkspace)
export const desktopWorkspaceSet = (path: string) =>
  put<DesktopWorkspaceResult>(Endpoints.desktopWorkspace, { path })

// ===== 权限 =====
export const desktopPermissionsGet = () => get<DesktopPermissions>(Endpoints.desktopPermissions)
export const desktopPermissionsSet = (payload: { scope: string; target: string; decision: string }) =>
  put<{ ok: boolean; effective_level: string }>(Endpoints.desktopPermissions, payload)
export const desktopPermissionDecision = (payload: { decision: string; scope?: string; target?: string }) =>
  post<PermissionDecisionResp>(Endpoints.desktopPermissionDecision, payload)

// ===== 唤醒补跑 =====
export const desktopResumeScan = (missedSince?: string) =>
  post<ResumeScanResult>(Endpoints.desktopResumeScan, missedSince ? { missed_since: missedSince } : {})

// ===== 运行控制 =====
export const runCancel = (id: string) => post<{ ok: boolean; status: string }>(Endpoints.runCancel(id), {})
export const runSteer = (id: string, instruction: string, mode: 'append' | 'replace_plan' = 'append') =>
  post<{ ok: boolean; status: string; mode: string; note?: string }>(Endpoints.runSteer(id), { instruction, mode })
