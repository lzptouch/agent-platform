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
#: 合法决定集合（P2-15：原在兼容层，现由引擎统一导出）
DECISIONS = (DENY, ASK, ALLOW)
SCOPES = ("tool", "file", "command", "network", "action")
HIGH_RISK_ACTIONS = frozenset({"batch_delete", "system_config_write", "external_script_exec"})

#: 只读工具（L0 信任分层，直接放行）
READONLY_TOOLS = frozenset({"read_file", "list_directory", "search_files"})

#: 危险工具（定时任务需二次开关 ``allow_dangerous_tools`` 才放行）
DANGEROUS_TOOLS = frozenset({"write_file", "execute_python", "execute_bash"})

#: 旧 API 的 scope 别名（旧名 → 现行名）
_SCOPE_ALIASES = {"path": "file"}

#: 权限档位（危险工具集合的聚合态）
LEVELS = ("readonly", "ask", "allow")
LEVEL_TO_DECISION = {"readonly": DENY, "ask": ASK, "allow": ALLOW}

#: 内置权限规则清单（**唯一真相源**）—— ``(scope, pattern, decision, risk, priority)``。
#:
#: **P1-03**：这批数据此前由两个迁移**各写一遍**——``0002_desktop``（普通 INSERT，
#: 8 条）与 ``0004_security``（INSERT OR IGNORE，20 条）——而 SQLite 的唯一约束
#: ``(scope, pattern, workspace_id)`` 对 ``workspace_id IS NULL`` **不去重**
#: （NULL ≠ NULL）→ **新装库上 8 条规则出现两次**（实测 28 条 builtin 中 16 行是
#: 8 对重复）。功能上因「同 scope 取最严」而无害，但规则列表重复、``hit_count``
#: 分裂、改一份留一份易混淆。
#:
#: 现在由 :meth:`PermissionService.ensure_builtin_rules` 在**启动时**统一收敛
#: （去重 + 补齐，幂等）；迁移保持历史不动（避免破坏已部署库的迁移链）。
BUILTIN_RULES: tuple[tuple[str, str, str, str, int], ...] = (
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
    # P2-12：产物登记（只登记元数据，不写文件）→ 放行
    ("tool", "emit_artifact", "allow", "normal", 100),
    # 写类 / 执行类工具（ask）
    ("tool", "write_file", "ask", "normal", 100),
    ("tool", "execute_python", "ask", "elevated", 100),
    ("tool", "execute_bash", "ask", "elevated", 100),
    # 高危动作
    ("action", "batch_delete", "deny", "critical", 1),
    ("action", "system_config_write", "deny", "critical", 1),
    ("action", "external_script_exec", "ask", "elevated", 5),
)


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


def _rule_to_dict(row: "PermissionRuleRow") -> dict:
    """规则行 → 旧 API 形态的 dict（供设置页与兼容层复用）。"""
    return {
        "id": row.id,
        "scope": row.scope,
        "pattern": row.pattern,
        "target": row.pattern,
        "decision": row.decision,
        "risk": row.risk,
        "workspace_id": row.workspace_id,
        "priority": row.priority,
        "origin": row.origin,
        "expires_at": row.expires_at,
        "hit_count": row.hit_count or 0,
        "last_hit_at": row.last_hit_at,
        "updated_at": row.updated_at,
    }


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


#: 读类动作的工具名（用于「只读可信根」的判定）
_READ_TOOLS = ("read_file", "list_directory", "list_files", "read", "grep", "glob")


def _is_read_action(request: PermissionRequest) -> bool:
    """该请求是否为**读类**动作（只读可信根只对读放行）。"""
    tool = (request.tool or "").strip().lower()
    action = (request.action or "").strip().lower()
    if action.startswith("read") or action.startswith("list"):
        return True
    return any(tool == t or tool.startswith(f"{t}_") for t in _READ_TOOLS)


def _under_trusted_read_root(path: str) -> bool:
    """路径是否位于**技能目录**（只读可信根）之下。"""
    try:
        from app.core.config import settings
    except Exception:  # noqa: BLE001
        return False
    roots = []
    for attr in ("skills_dir", "custom_skills_dir"):
        raw = getattr(settings, attr, "") or ""
        if raw:
            roots.append(str(raw))
    if not roots:
        return False
    return any(_is_under(path, root) for root in roots)


def decide(request: PermissionRequest, rules: list[Rule]) -> Decision:
    """纯函数裁决：命中规则则按规则，未命中则按信任分层回落。"""
    ws_root = request.workspace_root or str(get_workspace_dir())
    # 防御纵深：路径在此归一化（即便调用方未归一）
    if request.path is not None:
        # **W1-03 / AUD-H03（判定基准 ≠ 执行基准）**
        # 归一化的基准必须与**执行器**（``code_executor._resolve`` → ``cwd_dir``）
        # **完全一致**。此前未传 ``cwd`` → 相对路径按**后端进程 CWD** 解析，
        # 而执行器按 run 绑定的工作区根解析 → **判定的与操作的不是同一个文件**：
        #   - ``write_file("report.md")`` 被判成「工作区外路径」→ ASK → 无审批通道 → DENY，
        #     而执行器本来就会写到工作区内；
        #   - 反之若进程 CWD 恰在工作区内，则工作区外的写入被误判为 ALLOW。
        cwd = Path(request.workspace_root) if request.workspace_root else None
        request = PermissionRequest(
            tool=request.tool, action=request.action,
            path=policy.normalize_path(request.path, cwd=cwd),
            command=request.command, network=request.network,
            workspace_id=request.workspace_id, workspace_root=request.workspace_root,
        )

    # 0) **工具维度**（W1-01）
    #
    # 此前 ``decide()`` 依次检查 action → file → command → network，
    # **从不检查 ``tool`` scope** → 用户在权限规则里写
    # ``{"scope":"tool","pattern":"write_file","decision":"deny"}``
    # 这类**工具级**规则**永远不会被咨询**（规则可创建、可展示、却不生效）。
    # 内置规则里也有 8 条 ``tool`` scope 规则（read_file/write_file/execute_bash…）
    # → **它们此前全是死规则**。
    #
    # 现在采用如下语义（与 ``F-SEC-11``「工作区内常规读写**零弹窗**」一致）：
    #   - **deny 立即生效**（显式禁止某工具 → 任何维度都不能放行）；
    #   - **ask 只作兜底**：不把「工作区内路径」的 ALLOW 升级成 ASK
    #     （否则内置默认 ``tool:write_file→ask`` 会让工作区内每次写文件都弹审批卡，
    #      直接违反 F-SEC-11）；维度本身没有更具体规则时，ask 即该维度的默认裁决。
    tool_rule = None
    if request.tool:
        tool_rule = _match_rules("tool", request.tool, rules, request.workspace_id)

    def _tool_deny() -> Decision | None:
        """工具级的**显式禁止**（deny）。

        **W1-01**：``decide()`` 此前**从不检查** ``tool`` scope → 内置 8 条 tool 规则
        （含 ``write_file→ask``）与用户写的 ``tool:xxx→deny`` **全是死规则**；
        「权限档位」机制（``set_level`` 写的就是 tool 规则）也因此**完全失效**
        （``effective_level()`` 恒返回 "allow"）。

        **次序**：工具级 deny 在**该维度没有更具体规则时**才生效 ——
        ``file`` 规则（priority=1）比 ``tool`` 规则更具体，应由它胜出。
        **ask 不在此拦截**：否则内置默认 ``tool:write_file→ask`` 会把
        「工作区内路径」的 ALLOW 升级成 ASK，直接违反 ``F-SEC-11``
        「工作区内常规读写**零弹窗**」。
        """
        if tool_rule is not None and tool_rule.decision == DENY:
            return Decision(
                DENY,
                f"工具 {request.tool} 命中禁止规则 {tool_rule.pattern}",
                "tool", request.tool,
                risk=tool_rule.risk, matched_rule=tool_rule,
            )
        return None

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
        # 该维度无更具体规则 → 工具级**显式禁止**生效
        tool_deny = _tool_deny()
        if tool_deny is not None:
            return tool_deny
        # 信任分层：工作区内放行，工作区外写询问
        if _is_under(request.path, ws_root):
            return Decision(ALLOW, "工作区内路径", "file", request.path)
        # P2-23：**技能目录是只读可信根**——SKILL.md 位于源码树（工作区外），
        # 此前一律判 ASK → Web 形态无审批通道 → DENY → 技能读不到自身指令。
        # 这里对**读类**动作放行；写类动作仍然询问（越界写照旧被拦）。
        if _is_read_action(request) and _under_trusted_read_root(request.path):
            return Decision(ALLOW, "技能目录（只读可信根）", "file", request.path)
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
        tool_deny = _tool_deny()
        if tool_deny is not None:
            return tool_deny
        if tool_rule is not None and tool_rule.decision == ASK:
            return Decision(ASK, f"工具 {request.tool} 命中规则 {tool_rule.pattern}",
                            "tool", request.tool, risk=tool_rule.risk,
                            matched_rule=tool_rule)
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
        """失效规则缓存。

        **P2-15**：同时失效**单例**的缓存——若有人通过 ``PermissionService()``
        直接 new 出实例并写规则，单例的缓存不会失效，会读到过期规则集
        （隐蔽的不一致）。这里保证「谁写谁失效，全局一致」。
        """
        with self._cache_lock:
            self._rules_cache = None
        singleton = PermissionService._instance
        if singleton is not None and singleton is not self:
            with singleton._cache_lock:
                singleton._rules_cache = None

    # ------------------------------------------------------------------ #
    # 内置规则收敛（P1-03）
    # ------------------------------------------------------------------ #
    def ensure_builtin_rules(self) -> dict:
        """幂等收敛内置权限规则：**去重 + 补齐**。

        **P1-03**：内置规则此前由 ``0002_desktop`` 与 ``0004_security`` 两个迁移
        **各写一遍**，而 SQLite 的唯一约束 ``(scope, pattern, workspace_id)``
        对 ``workspace_id IS NULL`` **不去重** → 新装库上 8 条规则出现两次。

        本方法在**启动时**调用（见 ``app/core/state.py``）：

        - 按 ``(scope, pattern)`` 分组，每组保留 **priority 最小**的一条
          （= 最先匹配的那条；``0004`` 写的版本 risk/priority 更准确，会被保留），
          其余重复行删除；
        - 补齐 :data:`BUILTIN_RULES` 中缺失的规则；
        - **幂等**：重复调用不产生新增、不再删除。

        :return: ``{"removed": 删除行数, "added": 新增行数}``
        """
        from sqlalchemy import select

        now = utc_now()
        removed = 0
        added = 0
        with db_session() as db:
            rows = list(db.scalars(
                select(PermissionRuleRow).where(PermissionRuleRow.origin == "builtin")
            ).all())

            groups: dict[tuple[str, str], list[PermissionRuleRow]] = {}
            for r in rows:
                groups.setdefault((r.scope, r.pattern), []).append(r)

            for _key, items in groups.items():
                if len(items) <= 1:
                    continue
                # priority 最小者保留（数值小者先匹配）；同 priority 保留 id 最小者
                items.sort(key=lambda r: (r.priority, r.id))
                for dup in items[1:]:
                    db.delete(dup)
                    removed += 1

            existing = {k for k, items in groups.items() if items}
            for scope, pattern, decision, risk, priority in BUILTIN_RULES:
                if (scope, pattern) in existing:
                    continue
                db.add(PermissionRuleRow(
                    scope=scope, pattern=pattern, decision=decision, risk=risk,
                    workspace_id=None, priority=priority, origin="builtin",
                    expires_at=None, hit_count=0, last_hit_at=None, updated_at=now,
                ))
                added += 1

        self.invalidate_cache()
        if removed or added:
            logger.info("内置权限规则收敛：删除重复 %s 条，补齐 %s 条", removed, added)
        return {"removed": removed, "added": added}

    # ------------------------------------------------------------------ #
    # 规则读写与档位聚合（P2-15：从兼容层合并进引擎）
    # ------------------------------------------------------------------ #
    def list_rules(self) -> list[dict]:
        """列出全部规则（旧 API 形态的 dict 列表）。"""
        from sqlalchemy import select

        with db_session() as db:
            rows = db.scalars(select(PermissionRuleRow)).all()
            return [_rule_to_dict(r) for r in rows]

    def set_rule(
        self, scope: str, target: str, decision: str,
        workspace_id: str | None = None,
    ) -> dict:
        """按 ``(scope, pattern, workspace_id)`` 新建或更新一条规则。

        ``scope`` 兼容旧名 ``path``（映射为 ``file``）。

        **P2-17**：``workspace_id`` 此前在引擎里已支持，但 **API 建规则时恒写
        None** → 无法造出「同 pattern 在不同工作空间有不同裁决」。现在按
        ``(scope, pattern, workspace_id)`` 三元组定位规则；``workspace_id``
        为 ``None`` 表示全局规则（行为与改造前一致）。
        """
        from sqlalchemy import select

        scope = _SCOPE_ALIASES.get(scope, scope)
        if scope not in SCOPES:
            raise ValueError(f"未知的规则作用域: {scope}")
        if decision not in DECISIONS:
            raise ValueError(f"未知的决定: {decision}")
        pattern = (target or "").strip()
        if not pattern:
            raise ValueError("规则目标不能为空")

        with db_session() as db:
            row = db.scalar(
                select(PermissionRuleRow).where(
                    PermissionRuleRow.scope == scope,
                    PermissionRuleRow.pattern == pattern,
                    PermissionRuleRow.workspace_id.is_(None)
                    if workspace_id is None
                    else PermissionRuleRow.workspace_id == workspace_id,
                )
            )
            if row is None:
                row = PermissionRuleRow(
                    scope=scope, pattern=pattern, decision=decision,
                    workspace_id=workspace_id,
                )
                db.add(row)
            else:
                row.decision = decision
            row.updated_at = utc_now()
            db.flush()
            result = _rule_to_dict(row)
        self.invalidate_cache()
        return result

    def delete_rule(
        self, scope: str, target: str, workspace_id: str | None = None,
    ) -> bool:
        """删除一条规则；不存在返回 ``False``。

        **P2-17**：支持按 ``workspace_id`` 精确删除（``None`` = 全局规则）。

        **W1-02 / AUD2-H14 修复**：此前**忽略** ``workspace_id`` 形参，
        查询恒用 ``workspace_id.is_(None)`` → 工作空间级规则**只能创建不能删除**，
        而调用方反而会删掉一条**同 pattern 的全局规则**。
        """
        from sqlalchemy import select

        scope = _SCOPE_ALIASES.get(scope, scope)
        with db_session() as db:
            stmt = select(PermissionRuleRow).where(
                PermissionRuleRow.scope == scope,
                PermissionRuleRow.pattern == target,
            )
            # 按传入的 workspace_id 精确匹配（None = 全局规则）
            if workspace_id is None:
                stmt = stmt.where(PermissionRuleRow.workspace_id.is_(None))
            else:
                stmt = stmt.where(PermissionRuleRow.workspace_id == workspace_id)
            row = db.scalar(stmt)
            if row is None:
                return False
            db.delete(row)
        self.invalidate_cache()
        return True

    def record_hit(self, scope: str, target: str) -> None:
        """记录一次规则命中（供设置页展示「命中次数」）。计数失败不影响主流程。"""
        from sqlalchemy import select

        scope = _SCOPE_ALIASES.get(scope, scope)
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
        except Exception as exc:  # noqa: BLE001
            logger.warning("权限命中计数失败: %s", exc)

    def classify(
        self,
        tool: str,
        *,
        action: str | None = None,
        path: str | Path | None = None,
    ) -> Decision:
        """**只判定不落账**的裁决（供设置页预览与只读调用方使用）。

        需要落账 + 阻塞审批时用 :meth:`enforce`。
        """
        request = PermissionRequest(
            tool=tool,
            action=action,
            path=str(path) if path is not None else None,
        )
        return decide(request, self.load_rules())

    def effective_level(self) -> str:
        """危险工具集合的聚合档位（readonly / ask / allow）。"""
        rules = self.load_rules()
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
