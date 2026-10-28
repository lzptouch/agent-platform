"""权限引擎扩展（S2 / WP-2.1）。

背景：`permission_rules` 现状只有 `scope / target / decision` 三列、唯一约束
`UNIQUE(scope, target)`、`scope ∈ {tool, path, action}`。S2 需要：

- 规则模型扩展：`pattern`（取代 `target`）、`risk`、`workspace_id`、`priority`、
  `origin`、`expires_at`；
- 唯一约束改为 `UNIQUE(scope, pattern, workspace_id)`；
- `scope` 取值迁移：`path` → `file`，新增 `command` / `network`；
- 新增 `permission_decisions` 决策日志表；
- 写入内置规则集（新装即有可用策略）。

SQLite 不支持在线改约束，因此用「建新表 → 搬数据 → 删旧表 → 改名」重建。
"""
from __future__ import annotations

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return name in sa.inspect(bind).get_table_names()


def _has_column(bind, table: str, column: str) -> bool:
    if not _has_table(bind, table):
        return False
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _workspace_id_of(path: str) -> str:
    """工作目录标识（S3 建 workspaces 表后映射为 workspaces.id）。"""
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]


def upgrade() -> None:
    bind = op.get_bind()

    # -------------------------------------------------------------- #
    # 1) 重建 permission_rules（扩展列 + 新唯一约束 + scope 迁移）
    #
    # 新装环境（0001 用当前 ORM 建表）**已经是目标结构**（有 pattern、没有 target），
    # 此时不需要重建；只有老库（还是 target 结构）才走搬迁。
    # -------------------------------------------------------------- #
    if _has_table(bind, "permission_rules") and _has_column(bind, "permission_rules", "target"):
        op.create_table(
            "permission_rules_new",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("scope", sa.Text(), nullable=False),       # tool | file | command | network | action
            sa.Column("pattern", sa.Text(), nullable=False),     # 原 target
            sa.Column("decision", sa.Text(), nullable=False),    # deny | ask | allow
            sa.Column("risk", sa.Text(), nullable=False, server_default="normal"),
            sa.Column("workspace_id", sa.Text(), nullable=True),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("origin", sa.Text(), nullable=False, server_default="user"),
            sa.Column("expires_at", sa.Text(), nullable=True),
            sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_hit_at", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.UniqueConstraint("scope", "pattern", "workspace_id", name="uq_permission_rules_triplet"),
        )
        # 搬数据（scope path→file；target→pattern）
        bind.execute(
            sa.text(
                """
                INSERT INTO permission_rules_new
                  (id, scope, pattern, decision, risk, workspace_id, priority, origin,
                   expires_at, hit_count, last_hit_at, updated_at)
                SELECT id,
                       CASE scope WHEN 'path' THEN 'file' ELSE scope END,
                       target, decision, 'normal', NULL, 100, 'user',
                       NULL, hit_count, last_hit_at, updated_at
                FROM permission_rules
                """
            )
        )
        op.drop_table("permission_rules")
        op.rename_table("permission_rules_new", "permission_rules")
        op.create_index("idx_permission_rules_lookup", "permission_rules", ["scope", "priority"])

    # -------------------------------------------------------------- #
    # 2) 新建 permission_decisions（决策日志）
    # -------------------------------------------------------------- #
    if not _has_table(bind, "permission_decisions"):
        op.create_table(
            "permission_decisions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.Text(), nullable=True),
            sa.Column("session_id", sa.Text(), nullable=True),
            sa.Column("tool_name", sa.Text(), nullable=False),
            sa.Column("request_json", sa.Text(), nullable=False),
            sa.Column("action", sa.Text(), nullable=False),          # allow | ask | deny
            sa.Column("matched_rule_id", sa.Integer(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("decided_by", sa.Text(), nullable=True),       # user | policy | timeout
            sa.Column("status", sa.Text(), nullable=False, server_default="resolved"),  # pending | resolved
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("resolved_at", sa.Text(), nullable=True),
        )
        op.create_index("idx_permission_decisions_run", "permission_decisions", ["run_id"])
        op.create_index("idx_permission_decisions_status", "permission_decisions", ["status"])

    # -------------------------------------------------------------- #
    # 3) 内置规则集（origin=builtin；新装即有可用策略）
    # -------------------------------------------------------------- #
    from app.db.models import utc_now

    now = utc_now()
    builtins = [
        # 禁止路径（直接 deny，不询问）
        ("file", "~/.ssh/**", "deny", "critical", 1),
        ("file", "~/.gnupg/**", "deny", "critical", 1),
        ("file", "~/.aws/**", "deny", "critical", 1),
        ("file", "~/.kube/**", "deny", "critical", 1),
        # 危险命令前缀（deny）
        ("command", "rm -rf /", "deny", "critical", 1),
        ("command", "mkfs", "deny", "critical", 1),
        ("command", "shutdown", "deny", "critical", 1),
        ("command", "reboot", "deny", "critical", 1),
        ("command", "format", "deny", "critical", 1),
        ("command", "reg delete", "deny", "elevated", 2),
        ("command", "taskkill /f", "deny", "elevated", 2),
        # 只读工具（allow）
        ("tool", "read_file", "allow", "normal", 100),
        ("tool", "list_directory", "allow", "normal", 100),
        ("tool", "search_files", "allow", "normal", 100),
        # 写类 / 执行类工具（ask）
        ("tool", "write_file", "ask", "normal", 100),
        ("tool", "execute_python", "ask", "elevated", 100),
        ("tool", "execute_bash", "ask", "elevated", 100),
        # 高危动作
        ("action", "batch_delete", "deny", "critical", 1),
        ("action", "system_config_write", "deny", "critical", 1),
        ("action", "external_script_exec", "ask", "elevated", 5),
    ]
    for scope, pattern, decision, risk, priority in builtins:
        bind.execute(
            sa.text(
                """
                INSERT OR IGNORE INTO permission_rules
                  (scope, pattern, decision, risk, workspace_id, priority, origin,
                   expires_at, hit_count, last_hit_at, updated_at)
                VALUES (:scope, :pattern, :decision, :risk, NULL, :priority, 'builtin',
                        NULL, 0, NULL, :now)
                """
            ),
            {"scope": scope, "pattern": pattern, "decision": decision,
             "risk": risk, "priority": priority, "now": now},
        )


def downgrade() -> None:
    bind = op.get_bind()

    # 删决策表
    if _has_table(bind, "permission_decisions"):
        op.drop_table("permission_decisions")

    # 规则表回滚：删内置规则 + 重建旧结构（scope/target 两列 + 旧唯一约束）
    if _has_table(bind, "permission_rules"):
        bind.execute(sa.text("DELETE FROM permission_rules WHERE origin = 'builtin'"))
        op.create_table(
            "permission_rules_old",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("scope", sa.Text(), nullable=False),
            sa.Column("target", sa.Text(), nullable=False),
            sa.Column("decision", sa.Text(), nullable=False),
            sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_hit_at", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.UniqueConstraint("scope", "target", name="uq_permission_rules_scope_target"),
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO permission_rules_old (id, scope, target, decision, hit_count, last_hit_at, updated_at)
                SELECT id,
                       CASE scope WHEN 'file' THEN 'path' ELSE scope END,
                       pattern, decision, hit_count, last_hit_at, updated_at
                FROM permission_rules
                """
            )
        )
        op.drop_table("permission_rules")
        op.rename_table("permission_rules_old", "permission_rules")
