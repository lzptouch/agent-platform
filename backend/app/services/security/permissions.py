"""权限判定引擎（S2 核心，WP-2.2 / WP-2.3 / WP-2.8）。

分两层：
- **纯函数层** ``decide(request, rules)`` —— 输入请求 + 规则集，输出裁决，
  不碰 DB / 不碰全局状态，便于契约测试冻结语义；
- **服务层** ``PermissionService`` —— 单例 + 规则缓存 + 阻塞式审批。

判定语义（与 `doc/design/04-本地数据与安全边界设计.md` §3 一致）：
  1. 归一化（policy.py）；
  2. scope 分流（只在同 scope 内匹配）；
  3. priority 升序匹配，最长前缀/后缀命中；
  4. 同优先级冲突裁决 ``deny > ask > allow``；
  5. 未命中 → 信任分层回落（L0 只读 / L1 工作区内常规读写 / L2 越界写 / L3 破坏性 / L4 禁止路径）。
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.workspace import get_workspace_dir
from app.db.base import db_session
from app.db.models import PermissionDecisionRow, PermissionRuleRow, utc_now
from app.services.security import policy

logger = logging.getLogger(__name__)

DENY, ASK, ALLOW = "deny", "ask", "allow"
SCOPES = ("tool", "file", "command", "network", "action")
HIGH_RISK_ACTIONS = frozenset({"batch_delete", "system_config_write", "external_script_exec"})

#: 只读工具（L0 信任分层，直接放行）
READONLY_TOOLS = frozenset({"read_file", "list_directory", "search_files"})

#: 危险工具（定时任务需二次开关 ``allow_dangerous_tools`` 才放行）
DANGEROUS_TOOLS = frozenset({"write_file", "execute_python", "execute_bash"})


# --------------------------------------------------------------------------- #
# 数据模型（纯数据结构）
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Rule:
    id: int | None
    scope: str
    pattern: str
    decision: str
    risk: str = "normal"
    workspace_id: str | None = None
    priority: int = 100


@dataclass(frozen=True)
class PermissionRequest:
    """一次待判定的工具调用（已归一化）。"""

    tool: str
    action: str | None = None          # batch_delete / system_config_write / external_script_exec
    path: str | None = None            # 已归一化的绝对路径
    command: str | None = None         # 原始命令（内部再拆段）
    network: dict | None = None        # {host, port, is_local}
    workspace_id: str | None = None
    workspace_root: str | None = None


@dataclass(frozen=True)
class Decision:
    decision: str                       # deny | ask | allow
    reason: str                         # 人类可读原因（直接展示在审批卡/审计）
    scope: str
    target: str
    risk: str = "normal"
    matched_rule: Rule | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW

    @property
    def denied(self) -> bool:
        return self.decision == DENY

    @property
    def needs_ask(self) -> bool:
        return self.decision == ASK


# --------------------------------------------------------------------------- #
# 纯函数判定
# --------------------------------------------------------------------------- #
def _match_rules(scope: str, candidate: str, rules: list[Rule], workspace_id: str | None) -> Rule | None:
    """在同 scope 内按 priority 升序 + 最长命中匹配。

    规则适用域：``workspace_id`` 为 NULL 的全局规则恒适用；非空时只在该工作空间适用。
    冲突裁决：同优先级 ``deny > ask > allow``。
    """
    matched: list[Rule] = []
    for rule in rules:
        if rule.scope != scope:
            continue
        if rule.workspace_id is not None and rule.workspace_id != workspace_id:
            continue
        if _pattern_hit(rule, scope, candidate):
            matched.append(rule)
    if not matched:
        return None
    matched.sort(key=lambda r: (r.priority, -len(r.pattern)))
    # 同优先级内：deny > ask > allow
    best_priority = matched[0].priority
    top = [r for r in matched if r.priority == best_priority]
    for d in (DENY, ASK, ALLOW):
        for r in top:
            if r.decision == d:
                return r
    return top[0]


def _pattern_hit(rule: Rule, scope: str, candidate: str) -> bool:
    if scope == "file":
        if "*" in rule.pattern:
            return policy.path_matches_pattern(candidate, rule.pattern)
        # 无通配符 → 目录/文件前缀（归一化 + 分隔符边界）
        pat = policy.normalize_path(rule.pattern) if rule.pattern.startswith("~") else rule.pattern
        pat = os.path.normcase(pat)
        return candidate == pat or candidate.startswith(pat.rstrip("/\\") + os.sep) or candidate.startswith(pat.rstrip("/\\") + "/")
    if scope == "command":
        return candidate.startswith(rule.pattern)
    if scope == "network":
        return candidate == rule.pattern or candidate.endswith(rule.pattern.lstrip("*"))
    # tool / action：前缀匹配
    return candidate == rule.pattern or candidate.startswith(rule.pattern)


def decide(request: PermissionRequest, rules: list[Rule]) -> Decision:
    """纯函数裁决：命中规则则按规则，未命中则按信任分层回落。"""
    ws_root = request.workspace_root or str(get_workspace_dir())
    # 防御纵深：路径在此归一化（即便调用方未归一）
    if request.path is not None:
        request = PermissionRequest(
            tool=request.tool, action=request.action,
            path=policy.normalize_path(request.path),
            command=request.command, network=request.network,
            workspace_id=request.workspace_id, workspace_root=request.workspace_root,
        )

    # 1) 高危动作最先判定（不能被「工作区内 allow」放行）
    if request.action and request.action in HIGH_RISK_ACTIONS:
        rule = _match_rules("action", request.action, rules, request.workspace_id)
        if rule:
            return Decision(rule.decision, f"高危动作 {request.action}（命中规则）", "action", request.action,
                            risk=rule.risk, matched_rule=rule)
        return Decision(DENY if request.action != "external_script_exec" else ASK,
                        f"高危动作 {request.action}（默认）", "action", request.action, risk="critical")

    # 2) 文件维度
    if request.path is not None:
        rule = _match_rules("file", request.path, rules, request.workspace_id)
        if rule:
            if rule.decision == DENY:
                return Decision(DENY, f"路径命中禁止规则 {rule.pattern}", "file", request.path,
                                risk=rule.risk, matched_rule=rule)
            return Decision(rule.decision, f"路径命中规则 {rule.pattern}", "file", request.path,
                            risk=rule.risk, matched_rule=rule)
        # 信任分层：工作区内放行，工作区外写询问
        if _is_under(request.path, ws_root):
            return Decision(ALLOW, "工作区内路径", "file", request.path)
        return Decision(ASK, "工作区外路径", "file", request.path, risk="elevated")

    # 3) 命令维度（串联逐段判定；取各段中最严的裁决）
    if request.command is not None:
        worst: Decision | None = None
        for segment in policy.split_command_segments(request.command):
            norm_text = " ".join(policy.normalize_command(segment)["tokens"])
            rule = _match_rules("command", norm_text, rules, request.workspace_id)
            if rule:
                d = Decision(rule.decision, f"命令前缀命中规则 {rule.pattern}", "command", norm_text,
                             risk=rule.risk, matched_rule=rule)
                if worst is None or _severity(d.decision) > _severity(worst.decision):
                    worst = d
        if worst:
            return worst
        return Decision(ASK, "命令无显式规则", "command", request.command, risk="elevated")

    # 4) 网络维度
    if request.network is not None:
        host = request.network.get("host", "")
        if request.network.get("is_local"):
            return Decision(ALLOW, "本地地址", "network", host)
        rule = _match_rules("network", host, rules, request.workspace_id)
        if rule:
            return Decision(rule.decision, f"网络命中规则 {rule.pattern}", "network", host,
                            risk=rule.risk, matched_rule=rule)
        return Decision(ASK, "未配置的外部网络地址", "network", host, risk="elevated")

    # 5) 工具维度（兜底）
    if request.tool in READONLY_TOOLS:
        return Decision(ALLOW, f"只读工具 {request.tool}", "tool", request.tool)
    rule = _match_rules("tool", request.tool, rules, request.workspace_id)
    if rule:
        return Decision(rule.decision, f"工具命中规则 {rule.pattern}", "tool", request.tool,
                        risk=rule.risk, matched_rule=rule)
    return Decision(ASK, f"工具 {request.tool}（默认）", "tool", request.tool)


def _is_under(path: str, root: str) -> bool:
    """判断 path 是否位于 root 之下（两侧都做 Windows 大小写与分隔符归一）。"""
    p = os.path.normcase(os.path.normpath(path)).replace("\\", "/")
    r = os.path.normcase(os.path.normpath(root)).replace("\\", "/")
    return p == r or p.startswith(r.rstrip("/") + "/")


def _severity(decision: str) -> int:
    return {"allow": 0, "ask": 1, "deny": 2}[decision]


# --------------------------------------------------------------------------- #
# 服务层：单例 + 缓存 + 阻塞审批
# --------------------------------------------------------------------------- #
class PermissionService:
    """权限判定与审批协调（进程内单例）。"""

    _instance: "PermissionService | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, approval_timeout: float = 120.0) -> None:
        self.approval_timeout = approval_timeout
        self._rules_cache: list[Rule] | None = None
        self._cache_lock = threading.Lock()
        # 审批协调：decision_id → (event, result)
        self._pending: dict[int, tuple[threading.Event, dict]] = {}
        self._pending_lock = threading.Lock()
        # 审批通道活性：有人轮询待审批列表（或桌面形态）才算"有人在看"
        self._last_channel_poll: float = 0.0

    @classmethod
    def instance(cls) -> "PermissionService":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_for_test(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    # ------------------------------------------------------------------ #
    # 规则读取（带缓存）
    # ------------------------------------------------------------------ #
    def load_rules(self, *, force: bool = False) -> list[Rule]:
        with self._cache_lock:
            if self._rules_cache is not None and not force:
                return self._rules_cache
        rows: list[Rule] = []
        with db_session() as db:
            for r in db.scalars(
                __import__("sqlalchemy").select(PermissionRuleRow).order_by(PermissionRuleRow.priority)
            ).all():
                if r.expires_at and r.expires_at < utc_now():
                    continue  # 过期规则视为不存在
                rows.append(Rule(
                    id=r.id, scope=r.scope, pattern=r.pattern, decision=r.decision,
                    risk=r.risk, workspace_id=r.workspace_id, priority=r.priority,
                ))
        with self._cache_lock:
            self._rules_cache = rows
        return rows

    def invalidate_cache(self) -> None:
        with self._cache_lock:
            self._rules_cache = None

    # ------------------------------------------------------------------ #
    # 判定（含落账）
    # ------------------------------------------------------------------ #
    def check(
        self,
        request: PermissionRequest,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> Decision:
        rules = self.load_rules()
        return decide(request, rules)

    def enforce(
        self,
        request: PermissionRequest,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> Decision:
        """判定并按需**阻塞等待**用户决策。

        - allow → 直接返回；
        - deny  → 落账并返回；
        - ask   → 有审批通道时阻塞等待（超时按 deny）；**无通道时立即拒绝**。
          「无通道立即拒绝」保证：无人可审批的环境（无头 API、无轮询前端的 Web）
          不会把工具调用卡到超时，同时**绝不静默放行**。
        """
        decision = self.check(request, run_id=run_id, session_id=session_id)
        if not decision.needs_ask:
            return decision
        if self._unattended():
            # 危险工具二次开关（D-29）：定时任务显式允许才放行，否则拒绝并记原因
            if request.tool in DANGEROUS_TOOLS:
                if self._dangerous_tools_allowed():
                    return Decision(
                        ALLOW,
                        f"{decision.reason}（定时任务已显式允许危险工具 allow_dangerous_tools）",
                        decision.scope, decision.target, risk=decision.risk,
                        matched_rule=decision.matched_rule,
                    )
                return Decision(
                    DENY,
                    f"{decision.reason}（无人值守：定时任务未开启危险工具 allow_dangerous_tools，按拒绝处理）",
                    decision.scope, decision.target, risk=decision.risk,
                    matched_rule=decision.matched_rule,
                )
            # 无人值守（定时/调度）：没有人在审批 → ask 直接降级为 deny，记原因
            return Decision(
                DENY,
                f"{decision.reason}（无人值守：按拒绝处理，任务不挂起等待审批）",
                decision.scope, decision.target, risk=decision.risk,
                matched_rule=decision.matched_rule,
            )
        if not self._approval_channel_live():
            return Decision(
                DENY,
                f"{decision.reason}（当前无审批通道，按拒绝处理）",
                decision.scope, decision.target, risk=decision.risk,
                matched_rule=decision.matched_rule,
            )
        return self._await_user_decision(request, decision, run_id=run_id,
                                         session_id=session_id, timeout=timeout)

    def _unattended(self) -> bool:
        """当前是否处于无人值守执行（定时/调度触发）。"""
        try:
            from app.services.scheduler_service import unattended_context

            return bool(unattended_context.get())
        except Exception:  # noqa: BLE001
            return False

    def _dangerous_tools_allowed(self) -> bool:
        """定时任务是否显式允许危险工具（``scheduled_tasks.allow_dangerous_tools``）。"""
        try:
            from app.services.scheduler_service import dangerous_tools_context

            return bool(dangerous_tools_context.get())
        except Exception:  # noqa: BLE001
            return False

    def _approval_channel_live(self) -> bool:
        """是否有人能审批：桌面形态恒真；Web 形态看最近 10s 是否有人拉取待审批列表。"""
        from app.core.config import settings

        if settings.desktop_mode:
            return True
        return (time.monotonic() - self._last_channel_poll) < 10.0

    def note_channel_poll(self) -> None:
        """待审批列表被拉取 → 审批通道活跃。"""
        self._last_channel_poll = time.monotonic()

    # ------------------------------------------------------------------ #
    # 阻塞审批
    # ------------------------------------------------------------------ #
    def _await_user_decision(
        self,
        request: PermissionRequest,
        decision: Decision,
        *,
        run_id: str | None,
        session_id: str | None,
        timeout: float | None,
    ) -> Decision:
        wait_s = timeout if timeout is not None else self.approval_timeout
        started = time.monotonic()
        decision_id = self._create_pending(request, decision, run_id, session_id)
        self._publish_requested(decision_id, request, decision)

        event = threading.Event()
        with self._pending_lock:
            self._pending[decision_id] = (event, {})
        try:
            resolved = event.wait(wait_s)
        finally:
            with self._pending_lock:
                entry = self._pending.pop(decision_id, (None, {}))
        latency_ms = int((time.monotonic() - started) * 1000)

        if not resolved:
            final = Decision(DENY, f"审批超时（{wait_s:.0f}s 未响应，按拒绝处理）", decision.scope,
                             decision.target, risk=decision.risk, matched_rule=decision.matched_rule)
            self._finalize(decision_id, final, decided_by="timeout", latency_ms=latency_ms)
            return final

        result = entry[1]  # {'choice': ..., ...}
        choice = result.get("choice", "deny")
        if choice == "allow_workspace":
            self._persist_workspace_rule(request)
        if choice == "allow_once":
            final = Decision(ALLOW, "用户允许（本次）", decision.scope, decision.target,
                             risk=decision.risk, matched_rule=decision.matched_rule)
        elif choice == "allow_session":
            final = Decision(ALLOW, "用户允许（本次会话）", decision.scope, decision.target,
                             risk=decision.risk, matched_rule=decision.matched_rule)
        elif choice == "allow_workspace":
            final = Decision(ALLOW, "用户允许（本工作空间）", decision.scope, decision.target,
                             risk=decision.risk, matched_rule=decision.matched_rule)
        else:
            final = Decision(DENY, "用户拒绝", decision.scope, decision.target,
                             risk=decision.risk, matched_rule=decision.matched_rule)
        self._finalize(decision_id, final, decided_by="user", latency_ms=latency_ms)
        return final

    def _persist_workspace_rule(self, request: PermissionRequest) -> None:
        """allow_workspace → 落库一条「本工作空间内放行」规则。"""
        scope, pattern = None, None
        if request.path:
            scope, pattern = "file", request.path
        elif request.command:
            scope, pattern = "command", request.command.split()[0]
        elif request.tool:
            scope, pattern = "tool", request.tool
        if not (scope and pattern):
            return
        try:
            with db_session() as db:
                from sqlalchemy import select

                existing = db.scalar(
                    select(PermissionRuleRow).where(
                        PermissionRuleRow.scope == scope,
                        PermissionRuleRow.pattern == pattern,
                        PermissionRuleRow.workspace_id.is_(None),
                    )
                )
                if existing is None:
                    db.add(PermissionRuleRow(
                        scope=scope, pattern=pattern, decision="allow", origin="user",
                    ))
                else:
                    existing.decision = "allow"
                self.invalidate_cache()
        except Exception as exc:  # noqa: BLE001
            logger.warning("allow_workspace 落库失败: %s", exc)

    def resolve_decision(self, decision_id: int, choice: str) -> bool:
        """决策端点：由用户决策唤醒等待中的执行。"""
        with self._pending_lock:
            entry = self._pending.get(decision_id)
            if entry is None:
                return False
            entry[1]["choice"] = choice
            entry[0].set()
            return True

    def pending_decisions(self) -> list[dict]:
        """列出等待中的审批（供前端拉取恢复）。"""
        self.note_channel_poll()
        with db_session() as db:
            rows = db.scalars(
                __import__("sqlalchemy").select(PermissionDecisionRow).where(
                    PermissionDecisionRow.status == "pending"
                )
            ).all()
            return [
                {
                    "id": r.id,
                    "tool_name": r.tool_name,
                    "request": __import__("json").loads(r.request_json),
                    "reason": r.reason,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    # ------------------------------------------------------------------ #
    # 落账
    # ------------------------------------------------------------------ #
    def _create_pending(
        self, request: PermissionRequest, decision: Decision, run_id: str | None, session_id: str | None
    ) -> int:
        import json

        with db_session() as db:
            row = PermissionDecisionRow(
                run_id=run_id,
                session_id=session_id,
                tool_name=request.tool,
                request_json=json.dumps({
                    "tool": request.tool, "action": request.action,
                    "path": request.path, "command": request.command,
                    "network": request.network,
                }, ensure_ascii=False),
                action="ask",
                matched_rule_id=decision.matched_rule.id if decision.matched_rule else None,
                reason=decision.reason,
                status="pending",
            )
            db.add(row)
            db.flush()
            return int(row.id)

    def _finalize(self, decision_id: int, final: Decision, *, decided_by: str, latency_ms: int) -> None:
        with db_session() as db:
            row = db.get(PermissionDecisionRow, decision_id)
            if row is None:
                return
            row.status = "resolved"
            row.action = final.decision
            row.decided_by = decided_by
            row.latency_ms = latency_ms
            row.resolved_at = utc_now()
        try:
            from app.desktop.events import bus

            bus.publish("permission_resolved", decision_id=decision_id,
                        action=final.decision, decided_by=decided_by)
        except Exception as exc:  # noqa: BLE001
            logger.warning("发布审批结果事件失败: %s", exc)

    def _publish_requested(
        self, decision_id: int, request: PermissionRequest, decision: Decision
    ) -> None:
        try:
            from app.desktop.events import bus

            bus.publish(
                "permission_requested",
                decision_id=decision_id,
                tool=request.tool,
                reason=decision.reason,
                risk=decision.risk,
                target=decision.target,
                run_id=None,
            )
        except Exception as exc:  # noqa: BLE001 —— 事件失败不阻断审批
            logger.warning("发布审批事件失败: %s", exc)
