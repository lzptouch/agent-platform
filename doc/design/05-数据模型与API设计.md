# 05 · 数据模型与 API 设计（Data & API）

> **依据**：现状取自 `apps/server/src/db/schema.ts`（11 表）与 `apps/server/src/http/routes/`（83 端点）；目标取自仓库根 `文档.md` §11.1/§11.3/§11.5/§11.8/§11.11 与本目录 `00-总体设计.md` §3 概念模型。
> **整理日期**：2026-10-26　**对应基线**：commit `c4dac22`
> **文档性质**：本篇是**表结构与端点契约的唯一来源**。编码时按阶段新增表与端点；前端 `api/endpoints.ts` 必须与本文一致（由 `apps/scripts/ui_probe/contract_check.py` 校验）。

---

## 1. 现状数据模型（22 表）

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

> **为什么不新增 `/runs/active`**：`runs.py` 已先声明 `GET /runs/{run_id}`（`apps/server/src/http/routes/runs.ts:31`），Fastify 按声明顺序匹配，`/runs/active` 会被 `{run_id}` 捕获并返回 404。用**查询参数**扩展既有列表端点既无路由风险，也复用了分页与过滤能力。

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


---

## 附录：03-调度上下文与数据一致性（历史记录 · 整合自 `doc/plan/03-调度上下文与数据一致性.md`，2026-11-01）

# P3 · 调度、上下文与数据一致性

> **批次主题**：把**调度语义**、**上下文预算**与**数据约束**三块收口到「可断言、可回放、可迁移」的状态。
> **依据**：[`../design/09`](../design/09-差距矩阵与整改清单.md) §八 R-11、R-13、R-14、R-25、R-29 ~ R-34、R-42、R-43、G-17、G-18、G-35
> **缺陷来源**：[`../analysis/12`](../analysis/12_能力覆盖与风险台账.md) §2.2 / §2.3
> **优先级**：**P1**（依赖 P1；与 P2 可并行）
> **整理日期**：2026-10-30
>
> **批次边界**：调度 / 上下文 / 数据层三块。**不碰执行引擎主循环**（那是 P2 的范围）。
>
> **批次规模**：15 个工作项 ｜ **工期估算 23.0 人日**（单人净开发时间）
> **2026-10-30 状态**：**15/15 已完成**（P3-02 / P3-03）——15 条全部未动，代码级验证见 [`../design/09`](../design/09-差距矩阵与整改清单.md) §4.5。
> **2026-10-31 状态**：**15/15 已完成**（P3-01 ~ P3-15）——调度与数据一致性全部交付：交互/调度双预算、cron 真实槽位、乐观锁 + trigger 枚举约束、会话软删除、`tasks.jsonl` 追加日志、真流式 LLM、审批恢复持久化、DR 阶段 checkpoint。
> **串行链**：P1-07 → P3-04 → P6-04（槽位语义链）；P1-08 → P3-15（终态语义链）；P2-02 → P3-05（工具装载链）；P3-06 → P3-12

---

## 一、这批的三条主线

| 主线 | 现状 | 目标 |
| --- | --- | --- |
| **调度语义收口** | 槽位算法用「当前分钟」而非真实触发时刻；投递通道无写入口；配额/退避/巡检各自为政 | 槽位精确、投递可配、并发预算分离 |
| **上下文预算闭环** | 截断是硬编码字符数；反思/plan-first 分支不受迭代上限；摘要内容不实 | 预算按 token 动态；所有分支有上限；摘要诚实 |
| **数据约束补齐** | 无乐观锁版本列；`trigger` 无枚举；`cleanup.keep_per_task` 未用；会话物理删除 | 补约束或显式文档化 |

---

## 二、工作项

> 每项按 [`README.md` §5.1](./README.md) 的**七要素**组织；**改动落点**见下方速查表（与 [`README.md` §3.3](./README.md) 总台账一致）。

### 2.0 条目速查表

| # | 工作项 | 优先级 | 工时 | 条目级依赖 | 主要改动落点 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| P3-01 | 交互与调度拆分独立并发上限 | P1 | M | — | `services/run_executor.py`、`core/config.py` | ✅ |
| P3-02 | 投递通道可配置（+ `duration_ms`） | P1 | M | — | `schemas/schedule.py`、`api/v1/schedules.py`、`services/scheduler/delivery.py` | ✅ |
| P3-03 | 反思与 plan-first 分支补迭代上限 | P1 | S | — | `services/agent_service.py` | ✅ |
| P3-04 | cron 幂等槽位改用真实触发时刻 | P1 | M | P1-07 | `services/scheduler_service.py` | ✅ |
| P3-05 | 工具结果按 token 预算动态截断 | P1 | M | P2-02 | `services/agent_service.py`、`services/exec/context.py` | ✅ |
| P3-06 | Deep Research 阶段级 checkpoint | P1 | M | — | `services/research/research_manager.py` | ✅ |
| P3-07 | 补乐观锁版本列 | P2 | M | — | `db/models.py` | ✅ |
| P3-08 | `runs.trigger` 加枚举约束 | P2 | S | — | `db/models.py`、`db/migrations/versions/0009_*.py` | ✅ |
| P3-09 | `cleanup.keep_per_task` 语义落地 | P2 | S | — | `services/run_service.py` | ✅ |
| P3-10 | 会话软删除 | P2 | M | — | `db/models.py`、`services/session_service.py` | ✅ |
| P3-11 | `chat_log_*.json` 双写定位 | P2 | XS | — | `core/config.py`、`services/agent_service.py` | ✅ |
| P3-12 | Deep Research `tasks.json` 增量写 | P2 | M | P3-06 | `services/research/research_manager.py` | ✅ |
| P3-13 | `skills.frontmatter_json` 写入或删列 | P2 | S | P2-06 | `db/models.py`、`services/skill_manager.py` | ✅ |
| P3-14 | LLM 调用改流式 | P1 | L | P1-07 | `services/agent_service.py` | ✅ |
| P3-15 | 审批恢复改为可持久化任务 | P1 | M | P1-08 | `services/run_executor.py` | ✅ |
| | **合计** | | **23.0 人日** | | | **0/15** |

> **建议执行顺序**：
> **第 1 组「调度语义」**——P3-03（补上限）+ P3-02（投递可配，用户可感知）+ P3-01（并发预算分离）
> → **第 2 组「幂等地基」**——P3-04（槽位真实时刻，须先补槽位回归矩阵）→ 这是 P6-04 的前置
> → **第 3 组「执行链路」**——P3-14（流式，风险最高）+ P3-15（可持久化恢复）
> → **第 4 组「上下文与持久化」**——P3-05（依赖 P2-02）+ P3-06 → P3-12
> → **第 5 组「数据约束」**——P3-07~P3-11、P3-13（互不冲突，可并行）

---

### P3-01 · 交互与调度拆分独立并发上限（G-18 / R-11）　<sub>来源：`design/09` **R-11** ／ `analysis/12` **D-53**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | 交互与调度**共用** `BoundedSemaphore(schedule_max_concurrent=2)`——一个长任务即可让所有交互请求返回 `busy` |
| **根因** | S4 引入并发预算时选择「共用预算」以避免交互挤占调度；未预料到长任务会占满全部 2 个槽 |
| **整改** | ① 拆为两个信号量：`interactive_max_concurrent`（新增配置，默认 4）与 `schedule_max_concurrent`（保持 2）；② 交互路径优先用交互槽；③ 两者都满时才返 `busy` |
| **验收断言** | ① 一个占用交互槽的长任务运行时，第 5 个交互请求 → **成功排队而非 `busy`**；② 2 个定时任务同时运行时，第 3 个 → `busy`（调度预算仍生效）；③ 两个预算**互不占用** |
| **测试用例 ID** | `RUN-CONC-01`、`RUN-CONC-02` |
| **回归风险** | 中——总并发上升会同时压 LLM 与 SQLite 写锁 |
| **回滚** | 把 `interactive_max_concurrent` 设为 0 表示「仍共用」 |

### P3-02 · 投递通道可配置（G-35 / R-13）　<sub>来源：`design/09` **R-13** ／ `analysis/12` **D-55**</sub>　<sub>补充：`analysis/12` **D-76**（`execute_sync()` 返回体缺 `duration_ms` → 投递载荷耗时恒为 0）</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | `scheduler/delivery.py` 实现了 local / webhook / mobile 三通道 + 重试，但 `scheduled_tasks.delivery_json` **无任何写入 API** → 投递功能对用户不可用 |
| **根因** | S7 实现了投递层与数据列，却没做配置入口 |
| **整改** | ① `ScheduleCreate` / `ScheduleUpdate` 增加 `delivery` 字段（`{channels:[{type,target,template,enabled}]}`）；② `GET /api/v1/schedules/{id}` 返回该配置；③ 前端定时任务抽屉加「通知通道」配置区；④ `execute_sync()` 返回体补 `duration_ms`（当前 `_deliver` 读到的恒为 0） |
| **验收断言** | ① 通过 HTTP 创建带 webhook 通道的任务 → `delivery_json` **有值**；② 任务完成后 webhook 被真实调用（假服务断言）；③ webhook 返回 500 时**重试 3 次**且任务状态**不受影响** |
| **测试用例 ID** | `SCH-DELIVERY-01`、`SCH-DELIVERY-02` |
| **回归风险** | 低 |
| **回滚** | 字段可空 |

### P3-03 · 反射与 plan-first 分支补迭代上限（G-17 / R-14）　<sub>来源：`design/09` **R-14** ／ `analysis/12` **D-56**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | `enable_reflection=True` 走 `_stream_reflection()`、plan-first 走 `_generate_plan()`——**两条分支都不受 `max_iterations` 约束** |
| **根因** | 上限只在 `_stream_loop()` 的 `for iteration in range(limit)` 里体现；另两条路径没有循环结构 |
| **整改** | ① 反思分支加 `iteration` 计数与上限检查；② plan-first 的计划生成加单次调用上限与超时；③ 超限时产出明确 `error` 事件并落终态 |
| **验收断言** | ① 反思分支连续产工具调用超过上限 → 产出 `error: 达到最大迭代次数 N` 且 run 终态 `failed`；② plan-first 计划生成超时不挂起 |
| **测试用例 ID** | `RUN-LOOP-01`、`RUN-LOOP-02` |
| **回归风险** | 低 |
| **回滚** | 上限设为 0 表示不限制 |

### P3-04 · cron 幂等槽位改用真实触发时刻（G-35 关联 / R-42）　<sub>来源：`design/09` **R-42** ／ `analysis/12` **D-75**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | cron 槽位用「当前分钟截断」而非真实 cron 触发时刻 → 跨分钟补跑时槽位语义与 cron 真实时刻不一致 |
| **根因** | `_compute_slot()` 为求「确定性」而选了最简单的分钟截断 |
| **整改** | ① cron 槽位改用 `CronTrigger.get_next_fire_time()` 计算真实触发时刻（补跑时用原槽位）；② 保留分钟截断作为「同一分钟内多次触发」的二级去重 |
| **验收断言** | ① 一个 `0 9 * * 1-5` 的任务在 09:00:00 触发的槽位是 **09:00:00**，不是任意分钟；② 补跑时槽位 = 原应触发时刻；③ 同一槽位重复触发仍被 `uq_runs_task_slot` 拦截 |
| **测试用例 ID** | `SCH-IDEM-01`、`SCH-IDEM-02` |
| **回归风险** | 中——槽位是幂等的地基，改动需覆盖所有 schedule_kind |
| **回滚** | 保留旧算法为 `slot_mode=minute` 开关 |

### P3-05 · 工具结果按 token 预算动态截断（G-20 关联）　<sub>来源：`design/09` **R-09** ／ `analysis/12` **D-51**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | 工具结果回灌 LLM 是硬编码 `[:8000]` **字符**，发前端是 `[:2000]` 字符，与 token 预算无关联 |
| **根因** | S5 加了上下文预算，但截断仍是独立的字符常量 |
| **整改** | ① 截断长度由 `ContextBudget` 按剩余预算计算（`token_limit - used` 折算字符）；② 保留 8000/2000 为**上限**而非固定值；③ 事件里带上实际截断比例 |
| **验收断言** | ① 大工具结果（> 8000 字符）在小窗口模型下被截得更短；② 大窗口模型下不被过度截断；③ `tool_result` 事件带 `truncated` 标记与比例 |
| **测试用例 ID** | `CTX-TRIM-01`、`CTX-TRIM-02` |
| **回归风险** | 中——过度截断会让模型丢失关键信息 |
| **回滚** | 恢复固定值 |

### P3-06 · Deep Research 阶段级 checkpoint（G-31 关联 / R-25）　<sub>来源：`design/09` **R-25** ／ `analysis/12` **S-07-03**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | Deep Research 任务无阶段级 checkpoint——重启后非终态任务整体标 `failed`，不续跑 |
| **根因** | S1 只做了「写穿 `runs` 表」的整体持久化，没做阶段粒度 |
| **整改** | ① 每个阶段结束把 `{stage, artifacts, elapsed}` 落到 `data/research/<task_id>/checkpoint.json`；② 启动恢复时读 checkpoint，**从最后完成阶段继续**；③ 超过 `max_iterations` 的任务标 failed |
| **验收断言** | ① 在 synthesizing 阶段杀进程 → 重启后任务从 synthesizing 继续（不是从零）；② `meta_*.json` 记录 `resumed_from` |
| **测试用例 ID** | `EXT-DR-01` |
| **回归风险** | 中——续跑需要阶段产物可序列化 |
| **回滚** | 关闭 checkpoint 写入 |

### P3-07 · 补乐观锁版本列（R-29）　<sub>来源：`design/09` **R-29** ／ `analysis/12` **D-68**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | 全库**无 `version_id`**——并发更新同一行是「后写覆盖」，无版本冲突检测 |
| **根因** | 设计时选择了「状态守卫 + 唯一约束」代替版本号 |
| **整改（两选一）** | **路 A**：给易并发更新的表（`runs`、`permission_rules`、`scheduled_tasks`）加 `version_id`（Integer default 1）+ Drizzle `version_id_col`；② **路 B**：**显式文档化「本平台无乐观锁，更新语义为后写覆盖」**并写进 `analysis/04` §4.4（当前已写，但需在 API 契约中标注） |
| **验收断言** | ① 路 A：两个事务更新同一行，后提交者收到 `StaleDataError` 而非静默覆盖；② 路 B：API 文档与 `analysis/04` 明确写出该语义，且**有测试断言**该行为 |
| **测试用例 ID** | `API-LOCK-01` |
| **回归风险** | 路 A 中（需改所有更新路径）；路 B 零 |
| **回滚** | 路 A 去掉 version_id 列 |

### P3-08 · `runs.trigger` 加枚举约束（R-30）　<sub>来源：`design/09` **R-30** ／ `analysis/12` **D-45**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | `runs.trigger` 无 `CheckConstraint`——可写入任意字符串 |
| **根因** | 迁移时只加了默认值没加约束 |
| **整改** | ① 加 `CheckConstraint("trigger IN ('manual','schedule','api','research')")`；② 迁移版本新增该约束；③ 注意 `research` 是 S1 后新增的第 4 种 trigger |
| **验收断言** | ① 写入 `trigger='bogus'` → 约束拒绝；② 4 种合法值均可写入 |
| **测试用例 ID** | `API-CONSTRAINT-01` |
| **回归风险** | 低——但需确认历史数据里没有第 5 种 trigger（先跑一次审计查询） |
| **回滚** | 去掉约束 |

### P3-09 · `cleanup.keep_per_task` 语义落地（R-31）　<sub>来源：`design/09` **R-31** ／ `analysis/12` **D-41**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | `cleanup(retention_days=90, keep_per_task=500)` 的 `keep_per_task` **被声明但从未使用**——只按时间删 |
| **根因** | 实现时只做了时间维度 |
| **整改** | ① 实现「每任务保留最近 N 条终态 run」的语义（超出部分即使未到 90 天也删）；② 或删除该参数并在文档说明「只按时间删」 |
| **验收断言** | ① 某任务有 600 条终态 run → 清理后保留 ≤ 500；② 未到 90 天的其他任务记录**不受影响** |
| **测试用例 ID** | `RUN-CLEANUP-01` |
| **回归风险** | 低 |
| **回滚** | 恢复 |

### P3-10 · 会话软删除（R-32）　<sub>来源：`design/09` **R-32** ／ `analysis/12` **D-44**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | `DELETE /sessions/{id}` 是**物理删除**（`messages` 级联删），无软删除、无回收站 |
| **根因** | S1 实现时选了最简单的删除语义 |
| **整改** | ① 加 `deleted_at` 列；② DELETE 改为写 `deleted_at` + `archived=1`；③ 列表默认过滤已删会话，`include_archived` 可显式包含；④ 提供「永久删除」端点（管理员用） |
| **验收断言** | ① 删除后 `GET /sessions/{id}` → **404**；② `messages` 表**行数不变**（软删）；③ 列表默认不含已删会话 |
| **测试用例 ID** | `API-SESSION-01` |
| **回归风险** | 中——前端有多处依赖会话列表（侧栏、切换、恢复） |
| **回滚** | 改回物理删除 |

### P3-11 · `chat_log_*.json` 双写定位（R-33）　<sub>来源：`design/09` **R-33** ／ `analysis/12` **D-21**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | `settings.save_chat_log`（默认 `False`）开启后，会话内容**同时写 SQLite 与 JSON 文件**——两个真相源 |
| **根因** | 早期调试日志机制未清理 |
| **整改（两选一）** | **路 A**：**删除**该机制及其配置项与 `_save_log()`；② 路 B：保留但**改为纯诊断用途**（只记元数据不记内容，或只写 stderr） |
| **验收断言** | ① 路 A：`save_chat_log` 配置项与相关代码**不存在**；② 路 B：开启后 `data/outputs/` 下**不产生** `chat_log_*.json`；③ 两种情况下 `messages` 表行为一致 |
| **测试用例 ID** | `RUN-LOG-01` |
| **回归风险** | 低 |
| **回滚** | git 恢复 |

### P3-12 · Deep Research `tasks.json` 增量写（R-34）　<sub>来源：`design/09` **R-34** ／ `analysis/12` **S-11-06**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | `tasks.json` 每次 `_save_tasks()` **全量重写整个文件**——任务数增长后 IO 放大 |
| **根因** | 早期任务数少，全量写足够 |
| **整改** | ① 改为**追加型日志**（`tasks.jsonl`，每行一条 + 末行写当前态）或改为 SQLite 表；② 恢复时读日志折叠成当前态 |
| **验收断言** | ① 1000 个任务时单次保存耗时 < 100ms（基线对比）；② 崩溃后恢复的任务数与崩溃前一致 |
| **测试用例 ID** | `RUN-TASKS-01` |
| **回归风险** | 低 |
| **回滚** | 恢复全量写 |

### P3-13 · `skills.frontmatter_json` 有写入方或删列（R-43）　<sub>来源：`design/09` **R-43** ／ `analysis/12` **D-74**</sub>

| 要素 | 内容 |
| --- | --- |
| **现象** | `skills.frontmatter_json` 列已定义，但**全仓无任何写入方** |
| **根因** | S1 建表时预留，后续 frontmatter 改由 `description` 列承载 |
| **整改（两选一）** | **路 A**：`sync_to_db()` 写入 frontmatter JSON（供「按元数据检索 Skill」用）；② **路 B**：删列（需新迁移） |
| **验收断言** | ① 路 A：`skills` 表每行的 `frontmatter_json` **非空且是合法 JSON**；② 路 B：`PRAGMA table_info(skills)` 无该列 |
| **测试用例 ID** | `DB-SCHEMA-02` |
| **回归风险** | 低 |
| **回滚** | — |

### P3-14 · LLM 调用改流式（S-03-01）

| 要素 | 内容 |
| --- | --- |
| **现象** | `chat.completions.create()` 不带 `stream=True`——模型完整响应后才产出 `model_text`。所谓「流式」只是事件逐个下发，**首 token 延迟 = 完整响应时间** |
| **根因** | 主循环按「非流式」实现（`agent_service.py:502-509`），事件层的 `model_text` 是整段一次性下发 |
| **整改** | ① 改 `stream=True`，增量产出 `model_text`；② 保留 `reasoning_delta` 的增量语义；③ **工具调用仍等完整响应**（tool_calls 需要完整 JSON），只对文本部分流式；④ 补 `sse_first_token_seconds` 指标 |
| **验收断言** | ① 首个 `model_text` 事件的到达时间**明显早于**完整响应（假 LLM 服务可断言）；② 增量拼接后的文本与完整响应**逐字相同**；③ 工具调用路径**不受影响**（tool_calls 仍完整解析） |
| **测试用例 ID** | `SSE-FIRSTBYTE-01` |
| **回归风险** | **高**——流式下 `tool_calls` 的增量拼装逻辑不同；错误处理需区分「流中途断」与「完整响应出错」 |
| **回滚** | 去掉 `stream=True` 即可回到非流式 |

### P3-15 · 审批恢复改为可持久化任务（S-03-09）

| 要素 | 内容 |
| --- | --- |
| **现象** | `resume_after_approval()` 用 **daemon 线程**恢复执行，**进程退出即丢失该执行**——定时任务的 plan_first 也依赖此机制 |
| **根因** | S1 把「挂起 + 恢复」实现为进程内线程，没有落库的任务表示 |
| **整改** | ① 恢复时把执行参数写入 `runs.meta_json`（含 `resume_of` 指向）；② 启动恢复时扫描 `status=awaiting_approval` 且已批准的 run，重新起执行；③ 用**受控线程池**替代裸 daemon 线程（便于优雅退出与并发上限） |
| **验收断言** | ① 批准后杀进程 → 重启 → 该 run **继续执行**（不是丢失，也不是重新生成计划）；② 进程正常退出时**等待**在跑的恢复任务完成；③ 恢复任务的并发仍受 `schedule_max_concurrent` 约束 |
| **测试用例 ID** | `SEC-05` |
| **回归风险** | 中——启动路径新增扫描逻辑，须与 `recover_interrupted` 的宽限期协调，避免重复恢复 |
| **回滚** | 恢复 daemon 线程路径（保留旧实现作为回退开关） |


---

## 三、验收总表

| 域 | 工作项 | 关键断言 |
| --- | --- | --- |
| 调度 | P3-01 / P3-02 / P3-03 / P3-04 | 两个并发预算互不占用；投递可配；所有分支有上限；槽位精确 |
| 执行 | P3-14 / P3-15 | 首 token 早于完整响应且文本逐字相同；审批恢复跨进程存活 |
| 上下文 | P3-05 / P3-06 | 截断随预算动态；DR 可续跑；LLM 首 token 流式；审批恢复可持久化 |
| 数据 | P3-07 ~ P3-13 | 约束/软删/清理语义落地或显式文档化 |

**批次出口条件**：

- [ ] 15 个工作项全部关闭
- [ ] 后端 vitest **367 → ≥ 380 passed / 0 failed**
- [ ] e2e **59 → ≥ 61 passed**（新增 SCH-DELIVERY / RUN-CONC 用例）
- [ ] `analysis/12` §2.2 / §2.3 清空
- [ ] `analysis/04` §4.4（乐观锁）与 §6（幂等）同步更新

---

## 四、核对方式

```bash
cd backend

# 1. 并发预算
grep -n "BoundedSemaphore\|_semaphore\|schedule_max_concurrent" app/services/run_executor.py app/core/config.py

# 2. 投递写入口
grep -rn "delivery" app/api/v1/schedules.py app/schemas/schedule.py

# 3. 迭代上限
grep -n "for iteration in range\|_stream_reflection\|_generate_plan" app/services/agent_service.py

# 4. 槽位算法
grep -n "def _compute_slot" -A 10 app/services/scheduler_service.py

# 5. 截断常量
grep -n "\[:8000\]\|\[:2000\]" app/services/agent_service.py

# 6. 版本列
grep -rn "version_id" app/db/models.py

# 7. trigger 约束
grep -n "trigger" app/db/models.py

# 8. keep_per_task
grep -n "keep_per_task" app/services/run_service.py

# 9. 会话软删
grep -n "deleted_at" app/db/models.py app/services/session_service.py

# 10. chat_log 双写
grep -rn "save_chat_log\|chat_log_" app/
```

