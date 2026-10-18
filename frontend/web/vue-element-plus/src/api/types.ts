/**
 * 后端接口的 TypeScript 类型（机器可读契约）。
 * 唯一事实源见 backend/app/schemas/*.py 与 frontend/docs/api-contract.md
 */

// ===== 通用 =====

export type ToolSource = 'builtin' | 'mcp' | 'rag' | 'web'
export type ReflectionMode = 'plan_action_reflection_answer'
export type McpServerStatus = 'ready' | 'disabled' | 'error'

// ===== Agent =====

export type AgentMode = 'chat' | 'work'

export interface RunRequest {
  prompt: string
  model: string
  /** null = work 全部 / chat 不加载；[] = 不加载；列表 = 仅选中 */
  skills: string[] | null
  enable_mcp: boolean
  mcp_servers: string[]
  enable_rag: boolean
  enable_web_research: boolean
  enable_reflection: boolean
  mode?: AgentMode
  session_id?: string | null
  team_id?: string | null
  plan_first?: boolean
}

export interface RunResult {
  model: string
  prompt: string
  rounds: number
  finished: boolean
  files: string[]
  error: string | null
  run_id?: string | null
  session_id?: string | null
  mode?: AgentMode
  answer?: string
}

export interface ModelInfo {
  id: string
  name: string
  provider: string
}

export interface ModelsResp {
  default_model: string
  models: ModelInfo[]
}

export interface AgentStatusResp {
  ready: boolean
  api_key_configured: boolean
  default_model: string
  max_iterations: number
}

// ===== Skill =====

export interface SkillMeta {
  name: string
  description: string
  path: string
  skill_md_path: string
  skill_md_rel: string
  resources: string[]
  source: 'builtin' | 'custom'
  enabled: boolean
}

export interface SkillDetail extends SkillMeta {
  content: string
}

export interface SkillListResp {
  total: number
  skills: SkillMeta[]
}

export interface ValidationResult {
  valid: boolean
  message: string
  name: string | null
}

// ===== File =====

export interface FileItem {
  name: string
  size: number
  is_image: boolean
  url: string
}

export interface FileListResp {
  total: number
  files: FileItem[]
}

// ===== MCP =====

export interface McpToolInfo {
  name: string
  description: string
}

export interface McpServerInfo {
  name: string
  stage: string
  description: string
  status: McpServerStatus
}

export interface McpServerDetail extends McpServerInfo {
  tools: McpToolInfo[]
  /** 启动失败时降级返回 */
  error?: string
}

export interface McpServerListResp {
  total: number
  servers: McpServerInfo[]
}

export interface McpCallRequest {
  tool: string
  arguments: Record<string, unknown>
}

export interface McpCallResponse {
  server: string
  tool: string
  /** 失败时此字段非空（HTTP 仍是 200） */
  error: string | null
  result: string
}

// ===== RAG =====

export interface RagQueryRequest {
  query: string
  /** 1-50，默认 10 */
  limit?: number
}

export interface RagQueryResponse {
  query: string
  /** 带 [n] 编号的参考内容 */
  references: string
  answer: string
}

/** /rag/retrieval 返回的 document 项（具体字段后端可能调整） */
export interface RagRetrievalDoc {
  text?: string
  score?: number
  source?: string
  metadata?: Record<string, unknown>
  [key: string]: unknown
}

export interface RagStatsResp {
  collection: string
  /** -1 = Milvus 不可用 */
  entities: number
  dense_dim: number
  embedding_model: string
  /** 指 DeepSeek Key */
  llm_available: boolean
}

// ===== Web Research =====

export interface WebResearchRequest {
  query: string
  profile?: string
  output_format?: string
}

export interface WebResearchResponse {
  query: string
  answer: string
  reference_cards: Array<{
    title?: string
    url?: string
    quote?: string
    [key: string]: unknown
  }>
}

export interface WebResearchStatusResp {
  serper_available: boolean
  openai_available: boolean
  openai_model: string
}

// ===== Deep Research =====

export type ResearchProvider = 'bocha' | 'serper' | 'none'
export type ResearchStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface ResearchHealthResp {
  /** ⚠️ 硬编码 true */
  enabled: boolean
  search_provider: ResearchProvider
  /** = provider !== 'none' */
  search_configured: boolean
  /** 指 DashScope Key */
  llm_configured: boolean
  default_model: string
  max_concurrent_tasks: number
  output_dir: string
  total_tasks: number
  running_tasks: number
}

export interface ResearchSubmit {
  task: string
  max_workers?: number | null
  max_iterations?: number | null
  quality_threshold?: number | null
}

export interface ResearchSubmitResp {
  task_id: string
  status: ResearchStatus
  message: string
  created_at: string
}

export interface ResearchTaskSummary {
  task_id: string
  /** ⚠️ 后端已截断到 50 字符 + "..." */
  original_task: string
  status: ResearchStatus
  created_at: string
  quality_score?: number
}

export interface ResearchTaskListResp {
  total: number
  tasks: ResearchTaskSummary[]
}

export interface AgentChatRequest {
  query: string
  reflection?: boolean
}

export interface AgentChatResponse {
  query: string
  plan: unknown[]
  reflection_plan: unknown[] | null
  memory: unknown[]
  reasoning: string
  answer: string
}

/** 单条 progress 事件载荷（来自 research_manager.py:144） */
export interface ResearchProgressItem {
  stage: string
  data: Record<string, unknown>
  /** ISO 时间戳；去重键的一部分（research_manager.py:144） */
  timestamp: string
}

export interface ResearchTaskStatusResp {
  task_id: string
  status: ResearchStatus
  /** ⚠️ 仅最近 20 条 */
  progress: ResearchProgressItem[]
  progress_summary: Record<string, unknown>
  original_task: string
  created_at: string
  started_at: string | null
  completed_at: string | null
  quality_score?: number
  iteration_count?: number
  error_message?: string
}

export interface ResearchTaskResultResp {
  task_id: string
  status: ResearchStatus
  report: string | null
  quality_score?: number
  iteration_count?: number
  duration?: number
  metadata: { error: string } | null
}

// ===== Health（聚合） =====

export interface HealthResp {
  status: 'ok'
  app: string
  version: string
  skills_loaded: number
  api_key_configured: boolean
  output_dir: string
  /** ⚠️ 硬编码 3，不可信 */
  mcp_servers_available: number
  rag_collection: string
  /** ⚠️ -1 = 向量库不可用 */
  rag_entities: number
  web_search_available: boolean
  /** 指 DeepSeek */
  llm_available: boolean
  /** ⚠️ 硬编码 true */
  research_enabled: boolean
  research_search_provider: ResearchProvider
  research_configured: boolean
  research_total_tasks: number
  research_running_tasks: number
}

// ===== SSE 事件（Agent /run） =====

export interface BaseAgentEvent {
  type: string
}

export interface SkillsSelectedEv extends BaseAgentEvent {
  type: 'skills_selected'
  skills: string[]
  all_skills: string[]
  total: number
}

export interface SystemPromptEv extends BaseAgentEvent {
  type: 'system_prompt'
  content: string
}

export interface UserInputEv extends BaseAgentEvent {
  type: 'user_input'
  content: string
}

export interface RoundStartEv extends BaseAgentEvent {
  type: 'round_start'
  round: number
}

export interface RoundInputEv extends BaseAgentEvent {
  type: 'round_input'
  messages: Array<{ index: number; role: string; preview: string }>
}

export interface ModelTextEv extends BaseAgentEvent {
  type: 'model_text'
  content: string
  /** 默认模式有，反思模式无 */
  round?: number
}

export interface ToolCallEv extends BaseAgentEvent {
  type: 'tool_call'
  tool_name: string
  /** JSON 字符串（已脱敏） */
  tool_input: string
  /** 默认模式有，反思模式无 */
  round?: number
  tool_source?: ToolSource | string
  mcp_server?: string | null
}

export interface ReferenceCard {
  title?: string
  url?: string
  quote?: string
  [key: string]: unknown
}

export interface ToolResultEv extends BaseAgentEvent {
  type: 'tool_result'
  tool_name: string
  /** 已截断到 2000 字符（agent_service.py:310） */
  result: string
  /** 默认模式有，反思模式无 */
  round?: number
  tool_source?: ToolSource | string
  mcp_server?: string | null
  references?: string
  reference_cards?: ReferenceCard[]
}

export interface FilesEv extends BaseAgentEvent {
  type: 'files'
  files: Array<{ name: string; size: number; is_image: boolean }>
}

export interface ErrorEv extends BaseAgentEvent {
  type: 'error'
  content: string
}

export interface DoneEv extends BaseAgentEvent {
  type: 'done'
}

export interface ReflectionStartEv extends BaseAgentEvent {
  type: 'reflection_start'
  mode: ReflectionMode
}

export interface PlanEv extends BaseAgentEvent {
  type: 'plan' | 'reflection_plan'
  actions: Array<{ tool?: string; input?: unknown }>
}

export interface ReasoningDeltaEv extends BaseAgentEvent {
  type: 'reasoning_delta'
  content: string
}

export interface MetaEv extends BaseAgentEvent {
  type: 'meta'
  run_id: string
  session_id: string
  mode: AgentMode
  team: { id: string; name: string; strategy: string } | null
  resolved_skills: string[]
}

export interface ApprovalRequiredEv extends BaseAgentEvent {
  type: 'approval_required'
  run_id: string
  plan: Array<{ id: number; title: string; detail: string }>
}

export interface NoticeEv extends BaseAgentEvent {
  type: 'notice'
  content: string
}

export type AgentEvent =
  | SkillsSelectedEv
  | SystemPromptEv
  | UserInputEv
  | RoundStartEv
  | RoundInputEv
  | ModelTextEv
  | ToolCallEv
  | ToolResultEv
  | FilesEv
  | ErrorEv
  | DoneEv
  | ReflectionStartEv
  | PlanEv
  | ReasoningDeltaEv
  | MetaEv
  | ApprovalRequiredEv
  | NoticeEv

// ===== 会话 =====

export interface SessionMessage {
  id: string
  session_id: string
  run_id: string | null
  seq: number
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  steps: Array<Record<string, unknown>>
  files: Array<{ name: string; size: number; is_image?: boolean }>
  meta: Record<string, unknown>
  created_at: string
}

export interface Session {
  id: string
  mode: AgentMode
  title: string
  team_id: string | null
  skills: string[] | null
  config: Record<string, unknown>
  archived: boolean
  message_count: number
  created_at: string
  updated_at: string
}

export interface SessionDetail extends Session {
  messages: SessionMessage[]
  has_more: boolean
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ===== Skill 团队 =====

export type TeamStrategy = 'none' | 'sequential' | 'router'

export interface Team {
  id: string
  name: string
  description: string
  skill_names: string[]
  prompt_prefix: string
  strategy: TeamStrategy
  enabled: boolean
  reference_count: number
  created_at: string
  updated_at: string
}

export interface TeamResolveResult {
  team_id: string
  team_name: string
  strategy: TeamStrategy
  skills: Array<{ name: string; description: string; enabled: boolean; step_index: number | null }>
  prompt_preview: string
  degraded: boolean
  warnings: string[]
}

// ===== 定时任务 =====

export type RunStatus =
  | 'queued' | 'running' | 'awaiting_approval' | 'success'
  | 'failed' | 'skipped' | 'interrupted' | 'rejected'

export interface Schedule {
  id: string
  name: string
  prompt: string
  mode: AgentMode
  plan_first: boolean
  team_id: string | null
  skills: string[]
  enable_mcp: boolean
  mcp_servers: string[]
  enable_rag: boolean
  enable_web_research: boolean
  enable_reflection: boolean
  schedule_kind: 'cron' | 'interval'
  cron_expr: string | null
  interval_seconds: number | null
  timezone: string
  enabled: boolean
  allow_unattended_tools: boolean
  allow_dangerous_tools: boolean
  daily_run_limit: number
  schedule_text: string
  next_run_at: string | null
  last_run_at: string | null
  last_status: string
  last_error: string | null
  run_count: number
  consecutive_failures: number
  health: 'ok' | 'warning' | 'degraded'
  created_at: string
  updated_at: string
}

export interface RunRecord {
  id: string
  task_id: string | null
  session_id: string | null
  trigger: 'manual' | 'schedule' | 'api'
  scheduled_for: string | null
  status: RunStatus
  plan: Array<{ id: number; title: string; detail: string }> | null
  meta: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  result_summary: string | null
  error: string | null
  files: Array<{ name: string; size: number; is_image?: boolean }>
  created_at: string
}

export interface RunEventItem {
  seq: number
  type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface RunEventPage {
  items: RunEventItem[]
  last_seq: number
  status: RunStatus
  has_more: boolean
}

// ===== SSE 事件（Research stream） =====

export interface ResearchProgressEv extends ResearchProgressItem {
  type: 'progress'
}

export interface ResearchFinalEv {
  type: 'final'
  status: ResearchStatus
  quality_score?: number
  iteration_count?: number
  error?: string
}

export type ResearchEvent = ResearchProgressEv | ResearchFinalEv

// ===== API 错误 =====

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public path: string,
  ) {
    super(`${status} ${path}: ${detail}`)
  }
}