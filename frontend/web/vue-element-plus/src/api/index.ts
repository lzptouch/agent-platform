/**
 * 各业务模块的 REST 封装（基于 client.ts）。
 * 35 个端点的便捷方法。
 */

import { Endpoints } from './endpoints'
import { get, post, put, patch, del, upload, request, delWithBody} from './client'
import type {
  HealthResp, ModelsResp, AgentStatusResp, RunResult, AgentEvent,
  SkillListResp, SkillDetail, ValidationResult, SkillMeta,
  FileListResp,
  McpServerListResp, McpServerDetail, McpCallResponse,
  RagStatsResp, RagQueryResponse, RagQueryRequest,
  WebResearchStatusResp, WebResearchResponse, WebResearchRequest,
  ResearchHealthResp, ResearchSubmitResp, ResearchSubmit, ResearchTaskListResp,
  ResearchTaskStatusResp, ResearchTaskResultResp,
  AgentChatRequest, AgentChatResponse,
  Session, SessionDetail, Page, Team, TeamResolveResult, TeamStrategy,
  Schedule, RunRecord, RunEventPage, AgentMode,
} from './types'

// ===== System =====
export const health = () => get<HealthResp>(Endpoints.health)
export const agentStatus = () => get<AgentStatusResp>(Endpoints.agentStatus)

// ===== Agent =====
export const agentModels = () => get<ModelsResp>(Endpoints.agentModels)
export const agentRunSync = (payload: import('./types').RunRequest) =>
  post<RunResult>(Endpoints.agentRunSync, payload, { timeoutMs: 180_000 })
export const agentChat = (payload: AgentChatRequest) =>
  post<AgentChatResponse>(Endpoints.agentChat, payload)

// ===== Skills =====
export const skillsList = () => get<SkillListResp>(Endpoints.skillsList)
export const skillDetail = (name: string) => get<SkillDetail>(Endpoints.skillDetail(name))
// 后端仅注册 POST /skills/{name}/validate（GET 会 404）
export const skillValidate = (name: string) => post<ValidationResult>(Endpoints.skillValidate(name))
export const skillsReload = () => post<{ reloaded: number; skills: string[] }>(Endpoints.skillsReload, {})

// ===== Files =====
export const filesList = () => get<FileListResp>(Endpoints.filesList)

export const filesUpload = (fd: FormData) =>
  upload<{ name: string; size: number; url: string }>(Endpoints.filesUpload, fd)
export const skillExport = (name: string) => get<Blob>(Endpoints.skillExport(name))
export const scheduleHealth = () => get<{ status: string }>(Endpoints.scheduleHealth)

// 权限引擎（S2，形态无关）
export interface PermissionDecisionItem {
  id: number
  run_id: string | null
  tool_name: string
  request: Record<string, unknown>
  action: string
  reason: string
  decided_by: string | null
  status: string
  latency_ms: number
  created_at: string
  resolved_at: string | null
}
export interface PermissionRulesResp {
  rules: Array<Record<string, unknown>>
  effective_level: 'readonly' | 'ask' | 'allow'
}
export const permissionRules = () => get<PermissionRulesResp>(Endpoints.permissionRules)
export const permissionRuleSet = (payload: { scope: string; pattern: string; decision: string; risk?: string }) =>
  put<{ ok: boolean; effective_level: string }>(Endpoints.permissionRules, payload)
export const permissionRuleDelete = (payload: { scope: string; pattern: string; workspace_id?: string }) =>
  // **W4-01**：此前用 `del(path, payload as never)` —— `del` 的第二参是 RequestOptions
  // 而非请求体 → body 为 undefined → 后端收到空 body → 规则永远删不掉。
  // `as never` 把这个**编译期错误**静音了。现改用 `delWithBody`。
  delWithBody<{ ok: boolean }>(Endpoints.permissionRules, payload)
export const permissionDecisions = (params?: { status?: string; run_id?: string }) =>
  get<{ items: PermissionDecisionItem[] }>(
    Endpoints.permissionDecisions + (params ? '?' + new URLSearchParams(params as Record<string, string>) : ''),
  )
export const permissionResolve = (payload: { decision_id: number; choice: string }) =>
  post<{ ok: boolean }>(Endpoints.permissionDecisions, payload)
// 工作空间与产物（S3）
export interface WorkspaceItem { id: string; name: string; root_path: string; status: string; created_at: string }
export interface ChangeItem { id: number; path: string; op: string; before_hash: string | null; after_hash: string | null; snapshot_ref: string | null; tool: string; size_before: number | null; size_after: number | null; created_at: string }
export interface ArtifactItem { id: number; path: string; title: string | null; mime: string | null; kind: string; size: number | null; previewable: boolean; created_at: string; /** F-UX-02：浏览器类产物的来源页面地址 */ url?: string | null }
export const workspacesList = (includeArchived = false) =>
  get<{ items: WorkspaceItem[]; current: string | null }>(Endpoints.workspaces + (includeArchived ? '?include_archived=true' : ''))
export const workspaceCreate = (payload: { name: string; root_path?: string }) =>
  post<WorkspaceItem>(Endpoints.workspaces, payload)
export const workspaceSwitch = (id: string) => post<{ ok: boolean; current: string }>(Endpoints.workspaceSwitch(id), {})
export const workspaceArchive = (id: string) => post<{ ok: boolean }>(Endpoints.workspaceArchive(id), {})
export const runChanges = (runId: string) => get<{ items: ChangeItem[] }>(Endpoints.runChanges(runId))
export const runArtifacts = (runId: string) => get<{ items: ArtifactItem[] }>(Endpoints.runArtifacts(runId))
// P2-21：产物另存（Web 态）
export const runArtifactSaveAs = (runId: string, artifactId: number, dest: string) =>
  post<{ ok: boolean; path?: string }>(Endpoints.runArtifactSaveAs(runId, artifactId), { dest })
// P2-21：产物下载 URL（桌面态原生对话框用）
export const runArtifactDownloadUrl = (runId: string, artifactId: number): string =>
  Endpoints.runArtifactDownload(runId, artifactId)
export const changeDiff = (id: number) => get<{ kind: string; diff?: string; summary?: string; path: string }>(Endpoints.changeDiff(id))
export const changeRevert = (id: number, workspaceId?: string) =>
  post<{ reverted: string }>(Endpoints.changeRevert(id), workspaceId ? { workspace_id: workspaceId } : {})

export const permissionSandbox = () =>
  get<{ level: string; available: boolean; message: string }>(Endpoints.permissionSandbox)
export const skillResource = (name: string, resourcePath: string) =>
  get<unknown>(Endpoints.skillResource(name, resourcePath))
export const deleteFile = (name: string) => del<{ deleted: string }>(Endpoints.file(name))

// ===== MCP =====
export const mcpList = () => get<McpServerListResp>(Endpoints.mcpList)
export const mcpDetail = (name: string) => get<McpServerDetail>(Endpoints.mcpDetail(name))
export const mcpStart = (name: string) => post<{ status: string }>(Endpoints.mcpStart(name), {})
export const mcpStop = (name: string) => post<{ status: string }>(Endpoints.mcpStop(name), {})
export const mcpTools = (name: string) => get<{ server: string; tool_count: number; tools: import('./types').McpToolInfo[] }>(Endpoints.mcpTools(name))
export const mcpCall = (name: string, payload: import('./types').McpCallRequest) =>
  post<McpCallResponse>(Endpoints.mcpCall(name), payload)
export const mcpReload = () => post<{ reloaded: number; servers: string[] }>(Endpoints.mcpReload, {})

// ===== RAG =====
export const ragStats = () => get<RagStatsResp>(Endpoints.ragStats)
export const ragQuery = (req: RagQueryRequest) => post<RagQueryResponse>(Endpoints.ragQuery, req)
export const ragRetrieval = (req: RagQueryRequest) =>
  post<{ query: string; documents: unknown[]; references: string }>(Endpoints.ragRetrieval, req)
/** ⚠️ recreate 是 URL query 参数 */
export const ragIngest = (recreate = false) =>
  post<{
    chunks: number
    entities: number
    collection: string
    /** 批次 03：幂等入库统计（新增 / 跳过 / 清理旧版本 / 源文件数） */
    ingested?: number
    skipped?: number
    removed?: number
    documents?: number
  }>(Endpoints.ragIngest, undefined, { query: { recreate }, timeoutMs: 300_000 })

// ===== Web Research =====
export const webResearchStatus = () => get<WebResearchStatusResp>(Endpoints.webResearchStatus)
export const webResearch = (req: WebResearchRequest) =>
  post<WebResearchResponse>(Endpoints.webResearch, req)

// ===== Deep Research =====
export const researchHealth = () => get<ResearchHealthResp>(Endpoints.researchHealth)
export const researchSubmit = (payload: ResearchSubmit) =>
  post<ResearchSubmitResp>(Endpoints.researchSubmit, payload)
export const researchList = () => get<ResearchTaskListResp>(Endpoints.researchList)
export const researchStatus = (taskId: string) => get<ResearchTaskStatusResp>(Endpoints.researchStatus(taskId))
/** ⚠️ 202 = 未完成（业务上不是错误） */
export const researchResult = async (taskId: string): Promise<ResearchTaskResultResp> =>
  get<ResearchTaskResultResp>(Endpoints.researchResult(taskId), { timeoutMs: 30_000 })
export const researchDelete = (taskId: string) =>
  del<{ task_id: string; deleted: boolean; deleted_at: string }>(Endpoints.researchDelete(taskId))

// ===== Sessions =====
export const sessionsList = (params: { mode?: AgentMode; page?: number; page_size?: number; include_archived?: boolean } = {}) =>
  get<Page<Session>>(Endpoints.sessions, { query: params as Record<string, string | number | boolean | undefined> })
export const sessionCreate = (payload: { mode: AgentMode; title?: string; team_id?: string | null; skills?: string[] | null; config?: Record<string, unknown> }) =>
  post<Session>(Endpoints.sessions, payload)
export const sessionDetail = (id: string, beforeSeq?: number) =>
  get<SessionDetail>(Endpoints.session(id), { query: { before_seq: beforeSeq } })
export const sessionUpdate = (id: string, payload: { title?: string; archived?: boolean; team_id?: string | null }) =>
  patch<Session>(Endpoints.session(id), payload)
export const sessionDelete = (id: string) => del<void>(Endpoints.session(id))

// ===== Runs =====
export const runDetail = (id: string) => get<RunRecord>(Endpoints.run(id))
export const runEvents = (id: string, afterSeq = 0, limit = 500) =>
  get<RunEventPage>(Endpoints.runEvents(id), { query: { after_seq: afterSeq, limit } })
export const runApprove = (id: string, editedPlan?: Array<{ id: number; title: string; detail: string }>) =>
  post<RunRecord>(Endpoints.runApprove(id), editedPlan ? { edited_plan: editedPlan } : {})
export const runReject = (id: string, reason = '') =>
  post<RunRecord>(Endpoints.runReject(id), { reason })

// ===== Teams =====
export const teamsList = () => get<Team[]>(Endpoints.teams)
export const teamCreate = (payload: { name: string; skill_names: string[]; description?: string; prompt_prefix?: string; strategy?: TeamStrategy }) =>
  post<Team>(Endpoints.teams, payload)
export const teamUpdate = (id: string, payload: Partial<{ name: string; skill_names: string[]; description: string; prompt_prefix: string; strategy: TeamStrategy }>) =>
  put<Team>(Endpoints.team(id), payload)
export const teamDelete = (id: string) => del<void>(Endpoints.team(id))
export const teamToggle = (id: string, enabled: boolean) =>
  post<Team>(Endpoints.teamToggle(id), { enabled })
export const teamResolve = (id: string, query = '', mode: AgentMode = 'work') =>
  post<TeamResolveResult>(Endpoints.teamResolve(id), { query, mode })

// ===== Schedules =====
export const schedulesList = () => get<Schedule[]>(Endpoints.schedules)
export const scheduleCreate = (payload: Record<string, unknown>) =>
  post<Schedule>(Endpoints.schedules, payload)
export const scheduleUpdate = (id: string, payload: Record<string, unknown>) =>
  put<Schedule>(Endpoints.schedule(id), payload)
export const scheduleDelete = (id: string) => del<void>(Endpoints.schedule(id))
export const scheduleToggle = (id: string, enabled: boolean) =>
  post<Schedule>(Endpoints.scheduleToggle(id), { enabled })
export const scheduleRunNow = (id: string, waitSeconds = 0) =>
  post<{ run_id: string; status: string }>(Endpoints.scheduleRunNow(id), undefined, { query: { wait_seconds: waitSeconds }, timeoutMs: 120_000 })
export const scheduleRuns = (id: string, page = 1, pageSize = 20) =>
  get<Page<RunRecord>>(Endpoints.scheduleRuns(id), { query: { page, page_size: pageSize } })
export const scheduleValidateCron = (cronExpr: string, timezone = 'Asia/Shanghai') =>
  post<{ valid: boolean; error: string | null; next_runs: string[] }>(Endpoints.scheduleValidate, { cron_expr: cronExpr, timezone })

// ===== Desktop（桌面端） =====
export {
  desktopStatus, desktopComponents,
  desktopPreferencesGet, desktopPreferencesUpdate,
  desktopWorkspaceGet, desktopWorkspaceSet,
  desktopPermissionsGet, desktopPermissionsSet, desktopPermissionDecision,
  desktopResumeScan, runCancel, runSteer,
} from './desktop'

// ===== Skill 管理 =====
export const skillCreate = (payload: { name: string; description: string; content: string }) =>
  post<SkillMeta>(Endpoints.skillsList, payload)
export const skillUpdate = (name: string, payload: { description?: string; content?: string }) =>
  put<SkillMeta>(Endpoints.skillUpdate(name), payload)
export const skillToggle = (name: string, enabled: boolean) =>
  post<SkillMeta>(Endpoints.skillToggle(name), { enabled })
export const skillDelete = (name: string) =>
  del<{ deleted: string; trash_path: string }>(Endpoints.skillDelete(name))
export const skillImport = (file: File, overwrite = false) => {
  const fd = new FormData()
  fd.append('file', file)
  return upload<SkillMeta>(Endpoints.skillImport, fd, { query: { overwrite } })
}

// 重导出类型便于使用方
export type {
  AgentEvent,
  ResearchTaskStatusResp,
  ResearchTaskResultResp,
  ResearchProgressItem,
  ResearchFinalEv,
  ResearchHealthResp,
  ResearchTaskSummary,
  ResearchTaskListResp,
  ResearchStatus,
  HealthResp,
  ModelsResp,
  SkillMeta,
  SkillDetail,
  ValidationResult,
  FileItem,
  FileListResp,
  McpServerInfo,
  McpServerDetail,
  McpCallResponse,
  RagStatsResp,
  RagQueryResponse,
  WebResearchStatusResp,
  WebResearchResponse,
  ResearchSubmit,
  ResearchSubmitResp,
  RunRequest,
  RunResult,
  ReferenceCard,
  ToolSource,
  AgentMode,
  Session,
  SessionDetail,
  SessionMessage,
  Page,
  Team,
  TeamStrategy,
  TeamResolveResult,
  Schedule,
  RunRecord,
  RunEventItem,
  RunEventPage,
  RunStatus,
} from './types'
// 运行中任务查询（S4）：GET /runs?status=running（不新增 /runs/active，见 design/05 §3.4）
export const runsByStatus = (status: string, pageSize = 20) =>
  get<{ items: Array<Record<string, unknown>>; total: number }>(
    `${Endpoints.runsList}?status=${encodeURIComponent(status)}&page_size=${pageSize}`,
  )

// 上下文经济性与成本（S5）
export interface RunCostItem {
  id: number; model: string; provider: string; role: string
  prompt_tokens: number; completion_tokens: number; cached_tokens: number
  latency_ms: number; cost: number; price_snapshot: Record<string, number>
  created_at: string
}
export interface RunCostResp {
  items: RunCostItem[]
  totals: { llm_calls: number; prompt_tokens: number; completion_tokens: number; estimated_cost: number }
  percentiles: { p50: number | null; p90: number | null; samples: number }
  pricing: Array<Record<string, unknown>>
}
export const runCost = (runId: string) => get<RunCostResp>(Endpoints.runCost(runId))
export const costEstimate = (model?: string) =>
  get<{ percentiles: { p50: number | null; p90: number | null; samples: number }; pricing: Array<Record<string, unknown>> }>(
    Endpoints.costEstimate + (model ? `?model=${encodeURIComponent(model)}` : ''),
  )
export const sessionContext = (id: string) =>
  get<{ session_id: string; turns: number; window: number; usage: Record<string, number>; thresholds: { compact: number; summary: number } }>(
    Endpoints.sessionContext(id),
  )
export const memoriesList = (scope?: string) =>
  get<{ items: Array<Record<string, unknown>>; max_injected: number; enabled: boolean }>(
    Endpoints.memories + (scope ? `?scope=${encodeURIComponent(scope)}` : ''),
  )
export const memoryCreate = (payload: { scope: string; name: string; content: string; tags?: string[] }) =>
  post<Record<string, unknown>>(Endpoints.memories, payload)
export const memoryDelete = (payload: { scope: string; path: string }) =>
  request<{ ok: boolean }>(Endpoints.memories, { method: 'DELETE', body: payload })

// 扩展三层与多 Agent（S6）
export interface RoleItem {
  id: number; name: string; title: string; identity: string
  expertise: string[]; boundaries: string[]; workflow: string[]
  output_style: string; tools: string[]; skills: string[]
  model_tier: 'light' | 'standard' | 'strong'; builtin: boolean; enabled: boolean
}
export const rolesList = () => get<{ items: RoleItem[] }>(Endpoints.roles)
export const roleCreate = (payload: Partial<RoleItem> & { name: string }) =>
  post<RoleItem>(Endpoints.roles, payload)
export const roleUpdate = (id: number, payload: Partial<RoleItem>) =>
  request<RoleItem>(Endpoints.role(id), { method: 'PATCH', body: payload })
export const roleDelete = (id: number) => del<{ ok: boolean }>(Endpoints.role(id))

export interface PluginScanResult {
  level: 'low' | 'medium' | 'high' | 'critical'
  findings: Array<{ rule: string; level: string; reason: string; path: string }>
  scanned_files: number; total_bytes: number
  requires_confirmation: boolean; rejected_by_default: boolean
}
export interface PluginItem {
  id: number; name: string; version: string; status: string
  scan: Partial<PluginScanResult>; manifest: Record<string, unknown>; installed_at: string | null
}
export const pluginsList = () => get<{ items: PluginItem[] }>(Endpoints.plugins)
export const pluginScan = (path: string) => post<PluginScanResult>(Endpoints.pluginScan, { path })
export const pluginInstall = (payload: { path?: string; content_b64?: string; confirm?: boolean }) =>
  post<{ ok: boolean; name: string; version: string; scan: PluginScanResult | null; message: string }>(
    Endpoints.pluginInstall, payload,
  )
export const pluginRollback = (name: string, version: string) =>
  post<{ ok: boolean; message: string }>(Endpoints.pluginRollback, { name, version })

export interface BoardItem {
  id: number; board_id: string; title: string; detail: string
  status: 'pending' | 'ready' | 'running' | 'done' | 'blocked' | 'failed'
  assignee: string | null; deps: number[]; result: Record<string, unknown>
}
export const boardItems = (boardId: string) => get<{ items: BoardItem[] }>(Endpoints.boardItems(boardId))
export const boardItemCreate = (boardId: string, payload: { title: string; detail?: string; deps?: number[] }) =>
  post<BoardItem>(Endpoints.boardItems(boardId), payload)
export const boardItemComplete = (boardId: string, itemId: number, result?: Record<string, unknown>) =>
  post<{ items: BoardItem[] }>(Endpoints.boardItemComplete(boardId, itemId), { result })
