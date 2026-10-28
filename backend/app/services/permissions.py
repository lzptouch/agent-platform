"""PermissionService —— 三态分层权限（deny / ask / allow）。

**S2 起本模块是 `app/services/security/` 的兼容适配层**：

- 判定语义由 `app/services/security/permissions.py` 的纯函数 ``decide()`` 提供
  （归一化 → scope 分流 → 最长匹配 → 冲突裁决 → 信任分层回落）；
- 规则存储用 S2 扩展后的 `permission_rules`（`pattern`/`risk`/`workspace_id`/
  `priority`/`origin`/`expires_at`）；旧 API 的 ``scope='path'`` 自动映射为 ``'file'``，
  ``target`` 映射为 ``pattern``；
- 保留旧公开方法（``classify`` / ``set_rule`` / ``list_rules`` / ``record_hit`` /
  ``effective_level`` / ``set_level``），桌面端点与既有测试不受影响。

**判定唯一落点**在 ``ToolRegistry.dispatch()`` 入口（走新引擎的 ``enforce``）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.core.workspace import is_in_workspace
from app.db.base import db_session
from app.db.models import PermissionRuleRow, utc_now
from app.services.security import policy
from app.services.security.permissions import (
    ALLOW,
    ASK,
    DENY,
    HIGH_RISK_ACTIONS,
    PermissionRequest,
    Rule,
    decide,
)
from app.services.security.permissions import PermissionService as _Engine

logger = logging.getLogger(__name__)

DECISIONS = (DENY, ASK, ALLOW)

#: 无显式规则时，高危动作的默认决定
DEFAULT_ACTION_DECISION: dict[str, str] = {
    "batch_delete": DENY,
    "system_config_write": DENY,
    "external_script_exec": ASK,
}

#: 无显式规则时，各工具的默认决定
DEFAULT_TOOL_DECISION: dict[str, str] = {
    "read_file": ALLOW,
    "list_directory": ALLOW,
    "write_file": ASK,
    "execute_python": ASK,
    "execute_bash": ASK,
}

#: 参与「权限档位」聚合的危险工具
DANGEROUS_TOOLS = ("write_file", "execute_python", "execute_bash")

#: 旧 API 的 scope 集合（path 映射为 file）
SCOPES = ("tool", "path", "action", "file", "command", "network")
_SCOPE_MAP = {"path": "file"}

LEVELS = ("readonly", "ask", "allow")
LEVEL_TO_DECISION = {"readonly": DENY, "ask": ASK, "allow": ALLOW}


@dataclass(frozen=True)
class PermissionCheck:
    """一次权限判定的结果（旧 API 形状）。"""

    decision: str
    reason: str
    scope: str
    target: str

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW

    @property
    def denied(self) -> bool:
        return self.decision == DENY

    @property
    def needs_ask(self) -> bool:
        return self.decision == ASK


class PermissionService:
    """三态权限规则的读写与判定（新引擎之上的兼容层）。"""

    # ------------------------------------------------------------------ #
    # 规则读写
    # ------------------------------------------------------------------ #
    def list_rules(self) -> list[dict]:
        with db_session() as db:
            rows = db.scalars(select(PermissionRuleRow)).all()
            return [self._row_to_dict(row) for row in rows]

    def set_rule(self, scope: str, target: str, decision: str) -> dict:
        if scope not in SCOPES:
            raise ValueError(f"未知的规则作用域: {scope}")
        if decision not in DECISIONS:
            raise ValueError(f"未知的决定: {decision}")
        pattern = (target or "").strip()
        if not pattern:
            raise ValueError("规则目标不能为空")
        scope = _SCOPE_MAP.get(scope, scope)

        with db_session() as db:
            row = db.scalar(
                select(PermissionRuleRow).where(
                    PermissionRuleRow.scope == scope,
                    PermissionRuleRow.pattern == pattern,
                    PermissionRuleRow.workspace_id.is_(None),
                )
            )
            if row is None:
                row = PermissionRuleRow(scope=scope, pattern=pattern, decision=decision)
                db.add(row)
            else:
                row.decision = decision
            row.updated_at = utc_now()
            db.flush()
            result = self._row_to_dict(row)
        _Engine.instance().invalidate_cache()
        return result

    def delete_rule(self, scope: str, target: str) -> bool:
        scope = _SCOPE_MAP.get(scope, scope)
        with db_session() as db:
            row = db.scalar(
                select(PermissionRuleRow).where(
                    PermissionRuleRow.scope == scope,
                    PermissionRuleRow.pattern == target,
                    PermissionRuleRow.workspace_id.is_(None),
                )
            )
            if row is None:
                return False
            db.delete(row)
        _Engine.instance().invalidate_cache()
        return True

    # ------------------------------------------------------------------ #
    # 判定（委托新引擎）
    # ------------------------------------------------------------------ #
    def classify(
        self,
        tool: str,
        *,
        action: str | None = None,
        path: str | Path | None = None,
    ) -> PermissionCheck:
        engine = _Engine.instance()
        rules = engine.load_rules()
        request = PermissionRequest(
            tool=tool,
            action=action,
            path=str(path) if path is not None else None,
        )
        d = decide(request, rules)
        return PermissionCheck(d.decision, d.reason, d.scope, d.target)

    def record_hit(self, scope: str, target: str) -> None:
        """记录一次命中（供设置页展示「命中次数」）。"""
        scope = _SCOPE_MAP.get(scope, scope)
        try:
            with db_session() as db:
                row = db.scalar(
                    select(PermissionRuleRow).where(
                        PermissionRuleRow.scope == scope,
                        PermissionRuleRow.pattern == target,
                    )
                )
                if row is None:
                    return
                row.hit_count = (row.hit_count or 0) + 1
                row.last_hit_at = utc_now()
        except Exception as exc:  # noqa: BLE001 —— 计数失败不影响主流程
            logger.warning("权限命中计数失败: %s", exc)

    # ------------------------------------------------------------------ #
    # 档位聚合
    # ------------------------------------------------------------------ #
    def effective_level(self) -> str:
        """危险工具集合的聚合档位（readonly / ask / allow）。"""
        rules = _Engine.instance().load_rules()
        worst = ALLOW
        for tool in DANGEROUS_TOOLS:
            d = decide(PermissionRequest(tool=tool), rules)
            if d.decision == DENY:
                return "readonly"
            if d.decision == ASK:
                worst = ASK
        return "allow" if worst == ALLOW else "ask"

    def set_level(self, level: str) -> dict:
        """按档位批量设置危险工具的规则。"""
        if level not in LEVELS:
            raise ValueError(f"未知的权限档位: {level}")
        decision = LEVEL_TO_DECISION[level]
        for tool in DANGEROUS_TOOLS:
            self.set_rule("tool", tool, decision)
        return {"level": level, "rules": self.list_rules()}

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @staticmethod
    def _row_to_dict(row: PermissionRuleRow) -> dict:
        return {
            "id": row.id,
            "scope": row.scope,
            "target": row.pattern,
            "pattern": row.pattern,
            "decision": row.decision,
            "risk": row.risk,
            "priority": row.priority,
            "origin": row.origin,
            "hit_count": row.hit_count,
            "last_hit_at": row.last_hit_at,
            "updated_at": row.updated_at,
        }
