/**
 * 数据层契约（22 表，来源：backend/app/db/models.py，DDL 冻结于 contract/tables.sql）。
 *
 * 约定（与 Python 侧逐条一致）：
 * - **布尔统一 `integer`（0/1）**，不启用 boolean mode；
 * - **时间统一 `TEXT`**（UTC ISO8601）；
 * - 表名 / 列名 / 默认值 / 唯一约束 / 索引全部冻结，**不得改动**。
 */
import { randomUUID } from "node:crypto";

/** 生成新 ID（32 位 hex，等价 Python `uuid4().hex`）。 */
export function newId(): string {
  return randomUUID().replace(/-/g, "");
}

/** 当前 UTC 时间（ISO8601，等价 Python `datetime.now(timezone.utc).isoformat()`）。 */
export function utcNow(): string {
  return new Date().toISOString();
}

// --------------------------------------------------------------------------- //
// 行类型
// --------------------------------------------------------------------------- //
export interface SessionRow {
  id: string;
  mode: string;
  plan_first: number;
  title: string;
  team_id: string | null;
  config_json: string;
  owner: string | null;
  archived: number;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageRow {
  id: string;
  session_id: string;
  run_id: string | null;
  seq: number;
  role: string;
  content: string;
  steps_json: string;
  files_json: string;
  meta_json: string;
  created_at: string;
}

export interface TeamRow {
  id: string;
  name: string;
  description: string;
  prompt_prefix: string;
  strategy: string;
  enabled: number;
  created_at: string;
  updated_at: string;
}

export interface TeamSkillRow {
  team_id: string;
  skill_name: string;
  position: number;
}

export interface SkillRecordRow {
  name: string;
  description: string;
  source: string;
  path: string;
  frontmatter_json: string;
  enabled: number;
  stale: number;
  updated_at: string;
}

export interface ScheduledTaskRow {
  id: string;
  name: string;
  prompt: string;
  mode: string;
  plan_first: number;
  team_id: string | null;
  skills_json: string;
  enable_json: string;
  schedule_kind: string;
  cron_expr: string | null;
  interval_seconds: number | null;
  rrule_expr: string | null;
  timezone: string;
  enabled: number;
  allow_unattended_tools: number;
  allow_dangerous_tools: number;
  daily_run_limit: number;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string;
  last_error: string | null;
  run_count: number;
  consecutive_failures: number;
  backoff_until: string | null;
  delivery_json: string;
  created_at: string;
  updated_at: string;
}

export interface RunRow {
  id: string;
  task_id: string | null;
  session_id: string | null;
  trigger: string;
  scheduled_for: string | null;
  status: string;
  plan_json: string | null;
  meta_json: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  result_summary: string | null;
  error: string | null;
  files_json: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  llm_calls: number | null;
  tool_calls: number | null;
  estimated_cost: number | null;
  created_at: string;
  version_id: number;
}

export interface RunEventRow {
  id: number;
  run_id: string;
  seq: number;
  type: string;
  payload_json: string;
  created_at: string;
}

export interface SystemLockRow {
  name: string;
  owner: string;
  expires_at: string;
  renewed_at: string;
}

export interface DesktopPreferenceRow {
  id: number;
  workspace_dir: string;
  default_mode: string;
  danger_tools: number;
  notify_on_run: number;
  notify_channel: string;
  remote_mode: number;
  remote_base: string;
  updated_at: string;
}

export interface PermissionRuleRow {
  id: number;
  scope: string;
  pattern: string;
  decision: string;
  risk: string;
  workspace_id: string | null;
  priority: number;
  origin: string;
  expires_at: string | null;
  hit_count: number;
  last_hit_at: string | null;
  updated_at: string;
}

export interface PermissionDecisionRow {
  id: number;
  run_id: string | null;
  session_id: string | null;
  tool_name: string;
  request_json: string;
  action: string;
  matched_rule_id: number | null;
  reason: string;
  decided_by: string | null;
  status: string;
  latency_ms: number;
  created_at: string;
  resolved_at: string | null;
}

export interface WorkspaceRow {
  id: string;
  name: string;
  root_path: string;
  status: string;
  manifest_json: string;
  created_at: string;
  updated_at: string;
}

export interface RagDocumentRow {
  doc_id: string;
  source_path: string;
  content_hash: string;
  chunk_count: number;
  collection: string;
  created_at: string;
  updated_at: string;
}

export interface ChangeRow {
  id: number;
  run_id: string;
  workspace_id: string | null;
  path: string;
  op: string;
  before_hash: string | null;
  after_hash: string | null;
  snapshot_ref: string | null;
  tool: string;
  size_before: number | null;
  size_after: number | null;
  created_at: string;
}

export interface ArtifactRow {
  id: number;
  run_id: string;
  workspace_id: string | null;
  path: string;
  title: string | null;
  mime: string | null;
  kind: string;
  size: number | null;
  previewable: number;
  url: string | null;
  created_at: string;
}

export interface LlmCallRow {
  id: number;
  run_id: string | null;
  session_id: string | null;
  model: string;
  provider: string;
  role: string;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  latency_ms: number;
  price_snapshot: string;
  cost: number;
  created_at: string;
}

export interface MemoryIndexRow {
  id: number;
  path: string;
  scope: string;
  summary: string;
  tags: string;
  size: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RoleRow {
  id: number;
  name: string;
  title: string;
  identity: string;
  expertise_json: string;
  boundaries_json: string;
  workflow_json: string;
  output_style: string;
  tools_json: string;
  skills_json: string;
  model_tier: string;
  builtin: number;
  enabled: number;
  created_at: string;
  updated_at: string;
}

export interface PluginRow {
  id: number;
  name: string;
  version: string;
  source: string;
  status: string;
  scan_result: string;
  manifest_json: string;
  installed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BoardItemRow {
  id: number;
  board_id: string;
  title: string;
  detail: string;
  status: string;
  assignee: string | null;
  deps_json: string;
  result_json: string;
  created_at: string;
  updated_at: string;
}

export interface AgentMessageRow {
  id: number;
  board_id: string | null;
  from_role: string | null;
  to_role: string | null;
  kind: string;
  content: string;
  refs_json: string;
  created_at: string;
}

/** 22 张业务表的表名（契约冻结，用于迁移与清理）。 */
export const TABLE_NAMES = [
  "agent_messages",
  "artifacts",
  "board_items",
  "changes",
  "desktop_preferences",
  "llm_calls",
  "memory_index",
  "messages",
  "permission_decisions",
  "permission_rules",
  "plugins",
  "rag_documents",
  "roles",
  "run_events",
  "runs",
  "scheduled_tasks",
  "sessions",
  "skills",
  "system_locks",
  "team_skills",
  "teams",
  "workspaces",
] as const;

export type TableName = (typeof TABLE_NAMES)[number];
