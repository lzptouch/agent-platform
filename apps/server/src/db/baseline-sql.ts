/**
 * 基线迁移 DDL（契约冻结）。
 *
 * 等价于 Python 侧 12 个 Alembic 迁移的**净效果**：空库一次建到最终态。
 * 表名 / 列名 / 类型 / 非空 / 默认值 / 唯一约束 / 索引与
 * `contract/tables.sql` + `contract/indexes.sql` **逐字一致**（闸门 3 的判定依据）。
 *
 * 生成来源：backend/app/db/models.py（SQLAlchemy 2.0 metadata.create_all）
 */
export const BASELINE_SQL = `
CREATE TABLE agent_messages (
	id INTEGER NOT NULL, 
	board_id TEXT, 
	from_role TEXT, 
	to_role TEXT, 
	kind TEXT NOT NULL, 
	content TEXT NOT NULL, 
	refs_json TEXT NOT NULL, 
	created_at TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE artifacts (
	id INTEGER NOT NULL, 
	run_id TEXT NOT NULL, 
	workspace_id TEXT, 
	path TEXT NOT NULL, 
	title TEXT, 
	mime TEXT, 
	kind TEXT NOT NULL, 
	size INTEGER, 
	previewable INTEGER NOT NULL, 
	url TEXT, 
	created_at TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE board_items (
	id INTEGER NOT NULL, 
	board_id TEXT NOT NULL, 
	title TEXT NOT NULL, 
	detail TEXT NOT NULL, 
	status TEXT NOT NULL, 
	assignee TEXT, 
	deps_json TEXT NOT NULL, 
	result_json TEXT NOT NULL, 
	created_at TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE changes (
	id INTEGER NOT NULL, 
	run_id TEXT NOT NULL, 
	workspace_id TEXT, 
	path TEXT NOT NULL, 
	op TEXT NOT NULL, 
	before_hash TEXT, 
	after_hash TEXT, 
	snapshot_ref TEXT, 
	tool TEXT NOT NULL, 
	size_before INTEGER, 
	size_after INTEGER, 
	created_at TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE desktop_preferences (
	id INTEGER NOT NULL, 
	workspace_dir TEXT NOT NULL, 
	default_mode TEXT NOT NULL, 
	danger_tools INTEGER NOT NULL, 
	notify_on_run INTEGER NOT NULL, 
	notify_channel TEXT NOT NULL, 
	remote_mode INTEGER NOT NULL, 
	remote_base TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE llm_calls (
	id INTEGER NOT NULL, 
	run_id TEXT, 
	session_id TEXT, 
	model TEXT NOT NULL, 
	provider TEXT NOT NULL, 
	role TEXT NOT NULL, 
	prompt_tokens INTEGER NOT NULL, 
	completion_tokens INTEGER NOT NULL, 
	cached_tokens INTEGER NOT NULL, 
	latency_ms INTEGER NOT NULL, 
	price_snapshot TEXT NOT NULL, 
	cost FLOAT NOT NULL, 
	created_at TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE memory_index (
	id INTEGER NOT NULL, 
	path TEXT NOT NULL, 
	scope TEXT NOT NULL, 
	summary TEXT NOT NULL, 
	tags TEXT NOT NULL, 
	size INTEGER NOT NULL, 
	last_used_at TEXT, 
	created_at TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE messages (
	id TEXT NOT NULL, 
	session_id TEXT NOT NULL, 
	run_id TEXT, 
	seq INTEGER NOT NULL, 
	role TEXT NOT NULL, 
	content TEXT NOT NULL, 
	steps_json TEXT NOT NULL, 
	files_json TEXT NOT NULL, 
	meta_json TEXT NOT NULL, 
	created_at TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_messages_session_seq UNIQUE (session_id, seq), 
	FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES runs (id) ON DELETE SET NULL
);
CREATE TABLE permission_decisions (
	id INTEGER NOT NULL, 
	run_id TEXT, 
	session_id TEXT, 
	tool_name TEXT NOT NULL, 
	request_json TEXT NOT NULL, 
	action TEXT NOT NULL, 
	matched_rule_id INTEGER, 
	reason TEXT NOT NULL, 
	decided_by TEXT, 
	status TEXT NOT NULL, 
	latency_ms INTEGER NOT NULL, 
	created_at TEXT NOT NULL, 
	resolved_at TEXT, 
	PRIMARY KEY (id)
);
CREATE TABLE permission_rules (
	id INTEGER NOT NULL, 
	scope TEXT NOT NULL, 
	pattern TEXT NOT NULL, 
	decision TEXT NOT NULL, 
	risk TEXT NOT NULL, 
	workspace_id TEXT, 
	priority INTEGER NOT NULL, 
	origin TEXT NOT NULL, 
	expires_at TEXT, 
	hit_count INTEGER NOT NULL, 
	last_hit_at TEXT, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_permission_rules_triplet UNIQUE (scope, pattern, workspace_id)
);
CREATE TABLE plugins (
	id INTEGER NOT NULL, 
	name TEXT NOT NULL, 
	version TEXT NOT NULL, 
	source TEXT NOT NULL, 
	status TEXT NOT NULL, 
	scan_result TEXT NOT NULL, 
	manifest_json TEXT NOT NULL, 
	installed_at TEXT, 
	created_at TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_plugins_name_version UNIQUE (name, version)
);
CREATE TABLE rag_documents (
	doc_id TEXT NOT NULL, 
	source_path TEXT NOT NULL, 
	content_hash TEXT NOT NULL, 
	chunk_count INTEGER NOT NULL, 
	collection TEXT NOT NULL, 
	created_at TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (doc_id)
);
CREATE TABLE roles (
	id INTEGER NOT NULL, 
	name TEXT NOT NULL, 
	title TEXT NOT NULL, 
	identity TEXT NOT NULL, 
	expertise TEXT NOT NULL, 
	boundaries TEXT NOT NULL, 
	workflow TEXT NOT NULL, 
	output_style TEXT NOT NULL, 
	tools_json TEXT NOT NULL, 
	skills_json TEXT NOT NULL, 
	model_tier TEXT NOT NULL, 
	builtin INTEGER NOT NULL, 
	enabled INTEGER NOT NULL, 
	created_at TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_roles_name UNIQUE (name)
);
CREATE TABLE run_events (
	id INTEGER NOT NULL, 
	run_id TEXT NOT NULL, 
	seq INTEGER NOT NULL, 
	type TEXT NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_at TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_run_events_run_seq UNIQUE (run_id, seq), 
	FOREIGN KEY(run_id) REFERENCES runs (id) ON DELETE CASCADE
);
CREATE TABLE runs (
	id TEXT NOT NULL, 
	task_id TEXT, 
	session_id TEXT, 
	"trigger" TEXT NOT NULL, 
	scheduled_for TEXT, 
	status TEXT NOT NULL, 
	plan_json TEXT, 
	meta_json TEXT NOT NULL, 
	started_at TEXT, 
	finished_at TEXT, 
	duration_ms INTEGER, 
	result_summary TEXT, 
	error TEXT, 
	files_json TEXT NOT NULL, 
	prompt_tokens INTEGER, 
	completion_tokens INTEGER, 
	llm_calls INTEGER, 
	tool_calls INTEGER, 
	estimated_cost FLOAT, 
	created_at TEXT NOT NULL, 
	version_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_runs_task_slot UNIQUE (task_id, scheduled_for), 
	CONSTRAINT ck_runs_trigger CHECK (trigger IN ('manual','schedule','api','research')), 
	FOREIGN KEY(task_id) REFERENCES scheduled_tasks (id) ON DELETE SET NULL, 
	FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE SET NULL
);
CREATE TABLE scheduled_tasks (
	id TEXT NOT NULL, 
	name TEXT NOT NULL, 
	prompt TEXT NOT NULL, 
	mode TEXT NOT NULL, 
	plan_first INTEGER NOT NULL, 
	team_id TEXT, 
	skills_json TEXT NOT NULL, 
	enable_json TEXT NOT NULL, 
	schedule_kind TEXT NOT NULL, 
	cron_expr TEXT, 
	interval_seconds INTEGER, 
	rrule_expr TEXT, 
	timezone TEXT NOT NULL, 
	enabled INTEGER NOT NULL, 
	allow_unattended_tools INTEGER NOT NULL, 
	allow_dangerous_tools INTEGER NOT NULL, 
	daily_run_limit INTEGER NOT NULL, 
	next_run_at TEXT, 
	last_run_at TEXT, 
	last_status TEXT NOT NULL, 
	last_error TEXT, 
	run_count INTEGER NOT NULL, 
	consecutive_failures INTEGER NOT NULL, 
	backoff_until TEXT, 
	delivery_json TEXT NOT NULL, 
	created_at TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE SET NULL
);
CREATE TABLE sessions (
	id TEXT NOT NULL, 
	mode TEXT NOT NULL, 
	plan_first INTEGER NOT NULL, 
	title TEXT NOT NULL, 
	team_id TEXT, 
	config_json TEXT NOT NULL, 
	owner TEXT, 
	archived INTEGER NOT NULL, 
	deleted_at TEXT, 
	created_at TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE SET NULL
);
CREATE TABLE skills (
	name TEXT NOT NULL, 
	description TEXT NOT NULL, 
	source TEXT NOT NULL, 
	path TEXT NOT NULL, 
	frontmatter_json TEXT NOT NULL, 
	enabled INTEGER NOT NULL, 
	stale INTEGER NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (name)
);
CREATE TABLE system_locks (
	name TEXT NOT NULL, 
	owner TEXT NOT NULL, 
	expires_at TEXT NOT NULL, 
	renewed_at TEXT NOT NULL, 
	PRIMARY KEY (name)
);
CREATE TABLE team_skills (
	team_id TEXT NOT NULL, 
	skill_name TEXT NOT NULL, 
	position INTEGER NOT NULL, 
	PRIMARY KEY (team_id, skill_name), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE
);
CREATE TABLE teams (
	id TEXT NOT NULL, 
	name TEXT NOT NULL, 
	description TEXT NOT NULL, 
	prompt_prefix TEXT NOT NULL, 
	strategy TEXT NOT NULL, 
	enabled INTEGER NOT NULL, 
	created_at TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);
CREATE TABLE workspaces (
	id TEXT NOT NULL, 
	name TEXT NOT NULL, 
	root_path TEXT NOT NULL, 
	status TEXT NOT NULL, 
	manifest_json TEXT NOT NULL, 
	created_at TEXT NOT NULL, 
	updated_at TEXT NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX idx_agent_messages_board ON agent_messages (board_id);
CREATE INDEX idx_agent_messages_to_role ON agent_messages (to_role);
CREATE INDEX idx_artifacts_run ON artifacts (run_id);
CREATE INDEX idx_artifacts_workspace ON artifacts (workspace_id);
CREATE INDEX idx_board_items_board ON board_items (board_id);
CREATE INDEX idx_board_items_status ON board_items (status);
CREATE INDEX idx_changes_run ON changes (run_id);
CREATE INDEX idx_changes_workspace ON changes (workspace_id);
CREATE INDEX idx_llm_calls_run ON llm_calls (run_id);
CREATE INDEX idx_llm_calls_session ON llm_calls (session_id);
CREATE INDEX idx_memory_index_scope ON memory_index (scope);
CREATE INDEX idx_permission_decisions_run ON permission_decisions (run_id);
CREATE INDEX idx_permission_decisions_status ON permission_decisions (status);
CREATE INDEX idx_permission_rules_lookup ON permission_rules (scope, priority);
CREATE INDEX idx_plugins_name ON plugins (name);
CREATE INDEX idx_rag_documents_source ON rag_documents (source_path);
CREATE INDEX idx_roles_enabled ON roles (enabled);
CREATE INDEX idx_run_events_run_seq ON run_events (run_id, seq);
CREATE INDEX idx_runs_status ON runs (status);
CREATE INDEX idx_runs_task_started ON runs (task_id, started_at);
CREATE INDEX idx_sessions_mode_updated ON sessions (mode, updated_at);
CREATE INDEX idx_tasks_enabled_next ON scheduled_tasks (enabled, next_run_at);
CREATE INDEX idx_team_skills_skill ON team_skills (skill_name);
CREATE INDEX idx_workspaces_status ON workspaces (status);
`;
