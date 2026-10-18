/**
 * 各业务模块的 REST 封装（基于 client.ts）。
 * 35 个端点的便捷方法。
 */

import { Endpoints } from './endpoints'
import { get, post, put, patch, del, upload } from './client'
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
export const skillValidate = (name: string) => get<ValidationResult>(Endpoints.skillValidate(name))
export const skillsReload = () => post<{ reloaded: number; skills: string[] }>(Endpoints.skillsReload, {})

// ===== Files =====
export const filesList = () => get<FileListResp>(Endpoints.filesList)
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
  post<{ chunks: number; entities: number; collection: string }>(
    Endpoints.ragIngest, undefined, { query: { recreate }, timeoutMs: 300_000 })

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