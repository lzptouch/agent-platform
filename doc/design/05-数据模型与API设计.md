# 05 · 数据模型与 API 设计（Data & API）

> **依据**：现状取自 `backend/app/db/models.py`（11 表）与 `backend/app/api/v1/`（83 端点）；目标取自仓库根 `文档.md` §11.1/§11.3/§11.5/§11.8/§11.11 与本目录 `00-总体设计.md` §3 概念模型。
> **整理日期**：2026-10-26　**对应基线**：commit `c4dac22`
> **文档性质**：本篇是**表结构与端点契约的唯一来源**。编码时按阶段新增表与端点；前端 `api/endpoints.ts` 必须与本文一致（由 `frontend/scripts/ui_probe/contract_check.py` 校验）。

---

## 1. 现状数据模型（11 表）

| 表 | 归属域 | 关键约束 | 阶段动作 |
| --- | --- | --- | --- |
| `sessions` | 会话 | Index `(mode, updated_at)`；`mode∈{chat,work}` | S1 归一 `plan` |
| `messages` | 会话 | UNIQUE `(session_id, seq)` | S2 seq 改自增 |
| `teams` / `team_skills` | 编排 | `teams.name` unique | S6 拆为 `roles` + 编排策略 |
| `skills` | 扩展 | PK `name`；内容真相在文件系统 | S6 加索引字段 |
| `scheduled_tasks` | 调度 | Index `(enabled, next_run_at)` | S7 加 RRULE 字段 |
| `runs` | 账本 | **UNIQUE `(task_id, scheduled_for)`**；8 态状态机 | S5 补 token/成本写入 |
| `run_events` | 账本 | UNIQUE `(run_id, seq)` | S4 增加 `steer_injected` 等事件类型 |
| `system_locks` | 调度 | PK `name`（固定 `scheduler`） | — |
| `desktop_preferences` | 桌面 | 单行 | S2 增 `default_action` |
| `permission_rules` | 安全 | UNIQUE `(scope, target)` | S2 扩展为 `(scope, pattern, workspace_id)` |

**已知缺陷**（本阶段必须处理）：

1. `0001_init` 用 `Base.metadata.create_all(bind)` 建表 → 新装环境在 0001 阶段就含 0002 的表与列，迁移语义失真；
2. `permission_rules` 的 UNIQUE `(scope, target)` 无法表达"同一 pattern 在不同工作空间不同裁决"；
3. `messages.seq` 由应用层 `max(seq)+1` 分配，存在竞态；
4. `scheduled_tasks.delivery_json` 定义了却无读写；
5. `sessions.mode` 与服务层 `VALID_MODES` 取值集合不一致。

---

## 2. 目标数据模型（按阶段新增）

> 目标终态 **21 表**（11 现状 + 10 新增）。新增表全部带 `created_at/updated_at`（UTC ISO8601 字符串，与现状一致），主键沿用 `uuid4().hex`（现状约定）。

### 2.1 S2 · 安全（+1 表，+1 表结构变更）

> **字段依赖说明**：`permission_rules.workspace_id` 在 S2 落地时 `workspaces` 表尚未存在（S3 才建）。S2 期间该列存**当前工作目录的稳定标识**（`sha1(绝对路径)[:12]`），并在 manifest 之外独立可用；S3 建表后做一次映射迁移（标识 → `workspaces.id`），S2 的规则数据不丢失。
> **迁移编号**：现状为 `0001_init` / `0002_desktop`，之后按阶段顺延：**`0003` = S1 mode 归一、`0004` = S2 安全、`0005` = S3 工作空间、`0006` = S5 上下文、`0007` = S6 扩展、`0008` = S7 调度**。

```sql
-- 扩展现有表（迁移 0004；0003 已被 S1 的 mode 归一占用）
ALTER TABLE permission_rules ADD COLUMN risk TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE permission_rules ADD COLUMN workspace_id TEXT;
ALTER TABLE permission_rules ADD COLUMN priority INTEGER NOT NULL DEFAULT 100;
ALTER TABLE permission_rules ADD COLUMN origin TEXT NOT NULL DEFAULT 'user';
ALTER TABLE permission_rules ADD COLUMN expires_at TEXT;
-- 唯一约束替换：UNIQUE(scope, target) → UNIQUE(scope, pattern, workspace_id)

-- 新表：决策日志
CREATE TABLE permission_decisions (
  id INTEGER PRIMARY KEY,
  run_id TEXT,
  tool_name TEXT NOT NULL,
  request_json TEXT NOT NULL,
  action TEXT NOT NULL,
  matched_rule_id INTEGER,
  reason TEXT NOT NULL,
  decided_by TEXT NOT NULL,
  latency_ms INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_perm_decisions_run ON permission_decisions(run_id);
```

### 2.2 S3 · 工作空间、变更、产物（+3 表）

```sql
CREATE TABLE workspaces (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  root_path TEXT NOT NULL,
  owner_session TEXT,
  default_policy TEXT NOT NULL DEFAULT 'ask',
  model TEXT,
  skills_json TEXT NOT NULL DEFAULT '[]',
  extensions_json TEXT NOT NULL DEFAULT '[]',
  manifest_json TEXT NOT NULL DEFAULT '{}',
  snapshot_budget_mb INTEGER NOT NULL DEFAULT 3000,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE changes (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  path TEXT NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('create','modify','delete','move','rename','revert')),
  before_hash TEXT,
  after_hash TEXT,
  snapshot_ref TEXT,
  tool TEXT NOT NULL,
  size_before INTEGER,
  size_after INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_changes_run ON changes(run_id);
CREATE INDEX idx_changes_ws_path ON changes(workspace_id, path);

CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  path TEXT NOT NULL,
  title TEXT,
  mime TEXT,
  size INTEGER,
  kind TEXT NOT NULL CHECK (kind IN ('doc','sheet','slide','pdf','image','code','data','web','other')),
  previewable INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_artifacts_run ON artifacts(run_id);
```

### 2.3 S5 · 计量与记忆（+2 表）

```sql
CREATE TABLE llm_calls (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL,
  step INTEGER,
  model TEXT NOT NULL,
  provider TEXT,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cached_tokens INTEGER NOT NULL DEFAULT 0,
  price_snapshot TEXT NOT NULL,
  cost REAL NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_llm_calls_run ON llm_calls(run_id);

CREATE TABLE memory_index (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  summary TEXT NOT NULL,
  tags TEXT,
  scope TEXT NOT NULL CHECK (scope IN ('user','workspace','project')),
  updated_at TEXT NOT NULL,
  last_used_at TEXT
);
```

**成本口径**：单价取**调用时刻快照**（`price_snapshot` 存模型与单价），历史 run 的金额不随单价表更新而改变。

### 2.4 S6 · 扩展与协作（+4 表）

```sql
CREATE TABLE roles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  identity TEXT NOT NULL,
  expertise TEXT,
  workflow TEXT,
  style TEXT,
  tool_policy TEXT,
  skill_refs TEXT,
  origin TEXT NOT NULL DEFAULT 'user',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE plugins (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  version TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  source TEXT,
  scan_result TEXT,              -- skill-scanner 结果（等级 + 详情）
  enabled INTEGER NOT NULL DEFAULT 1,
  installed_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE board_items (
  id TEXT PRIMARY KEY,
  board_id TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT,
  status TEXT NOT NULL CHECK (status IN ('pending','ready','running','done','blocked','failed')),
  deps TEXT NOT NULL DEFAULT '[]',
  assignee TEXT,
  capability TEXT,
  result_ref TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_board_ready ON board_items(board_id, status);

CREATE TABLE agent_messages (
  id INTEGER PRIMARY KEY,
  board_id TEXT NOT NULL,
  from_role TEXT NOT NULL,
  to_role TEXT,
  summary TEXT NOT NULL,
  refs TEXT,
  created_at TEXT NOT NULL
);
```

### 2.5 表数量汇总

| 阶段 | 新增表 | 累计表数 |
| --- | --- | --- |
| 现状 | — | 11 |
| S2 | `permission_decisions` | 12 |
| S3 | `workspaces`、`changes`、`artifacts` | 15 |
| S5 | `llm_calls`、`memory_index` | 17 |
| S6 | `roles`、`plugins`、`board_items`、`agent_messages` | **21** |

---

## 3. 端点设计（按阶段新增）

> 命名与现状一致：`/api/v1/<域>`。**现有 83 端点除下列标注外保持不变**——本轮是增量改造，不做端点重排。

### 3.1 S1 · 统一约定（无新增端点，改行为）

| 项 | 约定 |
| --- | --- |
| 请求 ID | 所有响应头带 `X-Request-ID`；错误体含 `request_id` |
| 错误体 | `{"code": "<SCREAMING_SNAKE>", "message": "<人类可读>", "detail": {...}, "request_id": "..."}` |
| 错误码域 | `AUTH_*` `PERM_*` `RUN_*` `WS_*` `MCP_*` `SCHED_*` `FILE_*` `VALIDATION_*` `INTERNAL_*` |
| 状态码 | 400 参数/规则非法；401/403 鉴权与权限；404 资源不存在；409 状态冲突（重复槽位、并发）；422 语义校验；429 配额；5xx 服务故障 |
| 幂等 | 写操作支持 `Idempotency-Key` 头（先在 S7 调度、S2 规则上落地） |

### 3.2 S2 · 权限（+6）

> **与现有端点的关系**：现状权限接口在 `/desktop/permissions`（`GET`/`PUT` 规则、`POST .../decision` 决策），只服务桌面形态。S2 起提升为**形态无关**的 `/permissions/*`，并保留旧路径一个版本做兼容转发（Web 形态此前根本没有权限接口，因此不影响既有调用方）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/permissions/rules` | 列出规则（可按 scope/workspace 过滤） |
| POST | `/permissions/rules` | 新增/更新规则（`scope, pattern, action, risk, priority, workspace_id`） |
| DELETE | `/permissions/rules/{id}` | 删除规则（内置规则不可删） |
| GET | `/permissions/decisions` | 决策日志（可按 `run_id`/时间过滤） |
| POST | `/permissions/decisions/{id}` | 审批决策（`allow_once / allow_session / allow_workspace / deny`） |
| GET | `/permissions/sandbox` | 能力探测：`{available, level, enforced_paths, enforced_commands, message}` |

### 3.3 S3 · 工作空间与产物（+10）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/workspaces` | 列表（含归档过滤） |
| POST | `/workspaces` | 创建（可指定 root 或自动生成） |
| GET | `/workspaces/{id}` | 详情 + manifest |
| PATCH | `/workspaces/{id}` | 改默认策略/模型/技能/扩展 |
| DELETE | `/workspaces/{id}` | 归档（不删磁盘文件） |
| GET | `/runs/{id}/artifacts` | 本次运行的产物 |
| GET | `/runs/{id}/changes` | 本次运行造成的变更 |
| GET | `/changes/{id}/diff` | 单文件 diff |
| POST | `/changes/{id}/revert` | 回退（走权限判定） |
| POST | `/artifacts/{id}/save-as` | 另存到指定位置（桌面态走原生保存对话框） |

### 3.4 S4 · 运行控制（+0，现有 3 个端点改语义）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/runs?status=running` | 运行中的任务列表（供并行观察） |

> **为什么不新增 `/runs/active`**：`runs.py` 已先声明 `GET /runs/{run_id}`（`backend/app/api/v1/runs.py:31`），FastAPI 按声明顺序匹配，`/runs/active` 会被 `{run_id}` 捕获并返回 404。用**查询参数**扩展既有列表端点既无路由风险，也复用了分页与过滤能力。

`POST /runs/{id}/cancel` 与 `POST /runs/{id}/steer` **已存在**，本阶段只改语义：
- `cancel`：真正中止（现有实现仅置标志，需在工具边界生效并终止流式生成）；
- `steer`：增加 `mode ∈ {append, replace_plan}`，并落 `run_events`（`type=steer_injected`），保证多次 steer 顺序不丢。

### 3.5 S5 · 成本与上下文（+3）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/runs/{id}/cost` | token、成本、逐次调用明细、预计区间 |
| GET | `/sessions/{id}/context` | 当前上下文占用、已装载工具、被压缩掉的内容摘要 |
| GET | `/memories` | 记忆索引列表（供管理界面） |

### 3.6 S6 · 扩展与协作（+10）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/roles` | 角色列表 / 创建 |
| GET/PATCH/DELETE | `/roles/{id}` | 详情 / 改 / 删 |
| GET | `/plugins` | 已安装插件 |
| POST | `/plugins/install` | 安装（zip 或目录），返回扫描结果 |
| POST | `/plugins/{id}/rollback` | 回滚到上一版本 |
| DELETE | `/plugins/{id}` | 卸载（保留数据） |
| GET | `/plugins/{id}/scan` | 重新扫描 |
| GET | `/boards/{id}` | 黑板任务项与依赖图 |
| POST | `/boards/{id}/dispatch` | 手动触发一次调度（重新计算就绪集） |
| GET | `/tools/catalog` | 工具目录（名称 + 一句话描述，供延迟加载） |

### 3.7 S7 · 调度、MCP 与可观测（+5）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| PUT | `/schedules/{id}/deliveries` | 配置推送通道 |
| POST | `/schedules/{id}/deliveries/test` | 试推一次 |
| GET | `/mcp_servers/{name}/status` | 真实连接状态与失败原因 |
| POST | `/mcp_servers/{name}/refresh` | 重连并刷新工具清单 |
| GET | `/metrics` | 运行指标（并发、队列深度、成功率、耗时分布、成本） |

### 3.8 端点总数演进

| 阶段 | 端点数（`/api/v1`） | 增量 |
| --- | --- | --- |
| 现状 | 83 | — |
| S1 | 83（行为改，路径不变） | 0 |
| S2 | 89 | +6 |
| S3 | 99 | +10 |
| S4 | 99 | +0（扩展现有列表端点的 `status` 过滤，不新增路径） |
| S5 | 102 | +3 |
| S6 | 112 | +10 |
| S7 | 117 | +5 |
| **终态** | **117** | **+34** |

---

## 4. 迁移策略

| 规则 | 说明 |
| --- | --- |
| 一次一阶段 | 每个阶段一个迁移文件（`0003_security`、`0004_workspace`…），**不合并** |
| 显式 DDL | **废弃 `create_all` 写法**：`0001_init` 保持历史不变，新迁移一律显式 `op.create_table/op.add_column`，并用 `inspector` 判存以兼容既有库 |
| 可回滚 | 每个迁移必须有 `downgrade()`；回滚演练列入阶段出口 |
| 数据迁移 | 规则表扩展时保留既有 `target` → 新 `pattern`，`decision` → `action`；`scope` 取值 `path` → `file`、`tool`/`action` 保留 |
| 幂等槽位 | `runs` 的 UNIQUE `(task_id, scheduled_for)` **不动**——它是幂等的唯一依据 |
| 双写禁令 | 不做长期双写；确需兼容读时用 `COALESCE`/视图，一次性回填后删旧列 |
| 数据留痕 | `mode` 归一：`sessions.mode='plan'` 的行迁为 `mode='work'` 且 `config_json.plan_first=true` |

---

## 5. 契约规则

| # | 规则 | 校验方式 |
| --- | --- | --- |
| C1 | 后端 OpenAPI 注册的路径必须覆盖前端 `endpoints.ts` 常量 | `contract_check.py`（**纳入门禁**） |
| C2 | 前端 `api/` 导出的函数数与端点常量数一一对应（无孤儿常量、无裸 fetch） | 静态检查 + `contract_check.py` |
| C3 | 所有 SSE 事件类型有对应的 TypeScript 类型 | `api/types.ts` 与事件常量对照 |
| C4 | 写操作返回统一错误体 | 契约测试断言错误响应含 `code` 与 `request_id` |
| C5 | 分页统一 `?limit=&after=`（游标），不用 offset | 代码规范 + 抽查 |
| C6 | 时间一律 UTC ISO8601 字符串（与现状一致） | 契约测试 |
| C7 | 新端点必须同时提供前端 api 封装与契约用例 | 评审清单 |

---

## 6. 事件协议扩展（S4/S5/S6）

`run_events.type` 新增（**现有 18 类只增不改**）：

| 事件 | 阶段 | 载荷要点 |
| --- | --- | --- |
| `steer_injected` | S4 | 注入文本、来源、注入轮次 |
| `permission_requested` | S2 | decision_id、工具、参数摘要、risk、选项 |
| `permission_resolved` | S2 | decision_id、裁决、裁决来源 |
| `context_compressed` | S5 | 压缩前后 token、九段摘要条目数 |
| `tools_loaded` | S5 | 本轮装载的工具名列表 |
| `memory_selected` | S5 | 选中的记忆路径（≤5） |
| `board_updated` | S6 | 任务项状态变化、依赖解除情况 |
| `agent_notice` | S6 | 子 Agent 的压缩通知 |
| `delivery_attempt` | S7 | 通道、结果、重试次数 |
