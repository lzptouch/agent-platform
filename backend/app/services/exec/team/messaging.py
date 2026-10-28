"""Agent 间消息与上下文收费站（S6 / WP-6.8）。

两种通道：
- **定向消息**：``to_role`` 有值；
- **通知**：``to_role`` 为空（广播）。

**上下文收费站**：子 Agent 的完整推理、原始搜索结果、Agent 间原始消息
**不进入主上下文**——主上下文只保留"压缩通知"（结论 / 证据位置 / 约束 / 未决项）
与**结构化引用**（指向消息 / 产物 / 变更）。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from app.db.base import db_session
from app.db.models import AgentMessageRow, utc_now

logger = logging.getLogger(__name__)

#: 压缩通知模板（四段固定）
SUMMARY_TEMPLATE = """结论：{结论}
证据位置：{证据位置}
约束：{约束}
未决项：{未决项}"""


@dataclass
class AgentMessage:
    """一条 Agent 间消息 / 通知。"""

    id: int | None
    board_id: str | None
    from_role: str | None
    to_role: str | None          # None = 通知（广播）
    kind: str                     # message | notification
    content: str
    refs: list[dict] = field(default_factory=list)

    @property
    def is_notification(self) -> bool:
        return self.kind == "notification" or self.to_role is None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "board_id": self.board_id,
            "from_role": self.from_role,
            "to_role": self.to_role,
            "kind": self.kind,
            "content": self.content,
            "refs": list(self.refs),
            "is_notification": self.is_notification,
        }


def _row_to_message(row: AgentMessageRow) -> AgentMessage:
    try:
        refs = json.loads(row.refs_json or "[]")
    except json.JSONDecodeError:
        refs = []
    return AgentMessage(
        id=row.id,
        board_id=row.board_id,
        from_role=row.from_role,
        to_role=row.to_role,
        kind=row.kind,
        content=row.content or "",
        refs=refs if isinstance(refs, list) else [],
    )


def build_summary(
    conclusion: str,
    evidence: str = "",
    constraints: str = "",
    open_items: str = "",
) -> str:
    """按固定四段模板生成压缩通知。"""
    return SUMMARY_TEMPLATE.format(
        结论=conclusion or "（未记录）",
        证据位置=evidence or "（未记录）",
        约束=constraints or "（无）",
        未决项=open_items or "（无）",
    )


class MessageService:
    """消息与通知读写。"""

    def send(
        self,
        content: str,
        *,
        board_id: str | None = None,
        from_role: str | None = None,
        to_role: str | None = None,
        refs: list[dict] | None = None,
        kind: str | None = None,
    ) -> AgentMessage:
        """发消息（``to_role`` 有值=定向；为空=通知）。"""
        if not (content or "").strip():
            raise ValueError("消息内容不能为空")
        if kind is None:
            kind = "notification" if not to_role else "message"
        with db_session() as db:
            row = AgentMessageRow(
                board_id=board_id,
                from_role=from_role,
                to_role=to_role,
                kind=kind,
                content=content,
                refs_json=json.dumps(list(refs or []), ensure_ascii=False),
            )
            db.add(row)
            db.flush()
            return _row_to_message(row)

    def notify(
        self,
        content: str,
        *,
        board_id: str | None = None,
        from_role: str | None = None,
        refs: list[dict] | None = None,
    ) -> AgentMessage:
        """发通知（广播）。通知**必带结构化引用**。"""
        if not refs:
            raise ValueError("通知必须带结构化引用（refs）")
        return self.send(content, board_id=board_id, from_role=from_role,
                          to_role=None, refs=refs, kind="notification")

    def list(
        self,
        board_id: str | None = None,
        *,
        to_role: str | None = None,
        notifications_only: bool = False,
    ) -> list[AgentMessage]:
        with db_session() as db:
            stmt = select(AgentMessageRow).order_by(AgentMessageRow.id)
            if board_id:
                stmt = stmt.where(AgentMessageRow.board_id == board_id)
            if to_role:
                stmt = stmt.where(AgentMessageRow.to_role == to_role)
            if notifications_only:
                stmt = stmt.where(AgentMessageRow.to_role.is_(None))
            return [_row_to_message(r) for r in db.scalars(stmt).all()]

    def inbox(self, role: str, board_id: str | None = None) -> list[AgentMessage]:
        """某角色的收件箱（定向消息 + 广播通知）。"""
        with db_session() as db:
            stmt = select(AgentMessageRow).where(
                (AgentMessageRow.to_role == role) | (AgentMessageRow.to_role.is_(None))
            ).order_by(AgentMessageRow.id)
            if board_id:
                stmt = stmt.where(AgentMessageRow.board_id == board_id)
            return [_row_to_message(r) for r in db.scalars(stmt).all()]


# --------------------------------------------------------------------------- #
# 上下文收费站
# --------------------------------------------------------------------------- #
#: 子 Agent 原始内容**禁止**进入主上下文的标记
RAW_CONTENT_MARKERS = ("[raw-agent-output]", "[raw-search-result]", "[raw-agent-message]")


def tollgate(context_text: str) -> dict:
    """检查主上下文是否只含压缩通知（不含子 Agent 原文）。

    返回 ``{ok, violations, kept}``。
    """
    violations: list[str] = []
    for marker in RAW_CONTENT_MARKERS:
        if marker in context_text:
            violations.append(marker)
    return {
        "ok": not violations,
        "violations": violations,
        "kept": context_text,
    }


def build_main_context_block(
    notifications: list[AgentMessage],
) -> str:
    """构造进入主上下文的**压缩通知块**（只含通知，不含原始消息）。"""
    lines = ["[子任务摘要]"]
    for msg in notifications:
        ref_desc = ", ".join(
            f"{r.get('type', 'ref')}:{r.get('id', '')}" for r in msg.refs
        )
        lines.append(f"- {msg.content}" + (f"（引用：{ref_desc}）" if ref_desc else ""))
    return "\n".join(lines)
