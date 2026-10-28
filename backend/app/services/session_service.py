"""SessionService —— 会话与消息持久化（SQLite）。

关键约束：
- 历史回放只取 user / 最终 assistant 文本，**绝不回放 tool 消息与带 tool_calls 的
  assistant 消息**（会破坏 OpenAI 兼容接口的 tool_call 配对）。
- 消息序号 ``seq`` 在事务内生成（max(seq)+1），唯一约束兜底。
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import db_session, retry_on_locked
from app.db.models import MessageRow, RunRow, SessionRow, utc_now
from app.schemas.session import MessageOut, SessionDetail, SessionOut

logger = logging.getLogger(__name__)


def _msg_to_out(m: MessageRow) -> MessageOut:
    return MessageOut(
        id=m.id,
        session_id=m.session_id,
        run_id=m.run_id,
        seq=m.seq,
        role=m.role,
        content=m.content,
        steps=json.loads(m.steps_json or "[]"),
        files=json.loads(m.files_json or "[]"),
        meta=json.loads(m.meta_json or "{}"),
        created_at=m.created_at,
    )


def _session_to_out(db: Session, s: SessionRow) -> SessionOut:
    count = db.scalar(select(func.count()).select_from(MessageRow).where(MessageRow.session_id == s.id)) or 0
    config = json.loads(s.config_json or "{}")
    return SessionOut(
        id=s.id,
        mode=("plan" if (s.mode == "work" and s.plan_first) else s.mode),  # type: ignore[arg-type]
        plan_first=bool(s.plan_first),
        title=s.title,
        team_id=s.team_id,
        skills=config.get("skills"),
        config=config.get("config", {}),
        archived=bool(s.archived),
        message_count=count,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


class SessionService:
    """无状态服务：每个方法内部自开事务。"""

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def create(
        self,
        mode: str = "chat",
        title: str = "",
        skills: list[str] | None = None,
        team_id: str | None = None,
        config: dict | None = None,
        plan_first: bool = False,
    ) -> SessionOut:
        """创建会话。

        ``mode`` 取值统一为 ``chat | plan | work``；``plan`` 归一落库为
        ``work + plan_first=1``（与 ``scheduled_tasks`` 的做法一致）。
        """
        if mode not in ("chat", "plan", "work"):
            raise ValueError(f"非法模式: {mode}")
        stored_mode = "work" if mode == "plan" else mode
        stored_plan_first = 1 if (mode == "plan" or plan_first) else 0
        if stored_mode == "chat":
            stored_plan_first = 0
        with db_session() as db:
            row = SessionRow(
                mode=stored_mode,
                plan_first=stored_plan_first,
                title=title.strip(),
                team_id=team_id,
                config_json=json.dumps({"skills": skills, "config": config or {}}, ensure_ascii=False),
            )
            db.add(row)
            db.flush()
            db.refresh(row)
            return _session_to_out(db, row)

    def list(
        self,
        mode: str | None = None,
        page: int = 1,
        page_size: int = 20,
        include_archived: bool = False,
    ) -> tuple[list[SessionOut], int]:
        with db_session() as db:
            stmt = select(SessionRow)
            if mode == "plan":
                # plan 会话落库为 work + plan_first=1
                stmt = stmt.where(SessionRow.mode == "work", SessionRow.plan_first == 1)
            elif mode:
                stmt = stmt.where(SessionRow.mode == mode)
            if not include_archived:
                stmt = stmt.where(SessionRow.archived == 0)
            total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            rows = db.scalars(
                stmt.order_by(SessionRow.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return [_session_to_out(db, r) for r in rows], total

    def get(
        self,
        session_id: str,
        message_limit: int = 100,
        before_seq: int | None = None,
    ) -> SessionDetail | None:
        with db_session() as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                return None
            stmt = select(MessageRow).where(MessageRow.session_id == session_id)
            if before_seq is not None:
                stmt = stmt.where(MessageRow.seq < before_seq)
            msgs = db.scalars(stmt.order_by(MessageRow.seq.desc()).limit(message_limit + 1)).all()
            has_more = len(msgs) > message_limit
            msgs = list(reversed(msgs[:message_limit]))
            out = _session_to_out(db, row)
            return SessionDetail(**out.model_dump(), messages=[_msg_to_out(m) for m in msgs], has_more=has_more)

    def update(
        self,
        session_id: str,
        *,
        title: str | None = None,
        archived: bool | None = None,
        skills: list[str] | None = None,
        team_id: str | None = None,
        config: dict | None = None,
    ) -> SessionOut | None:
        with db_session() as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                return None
            if title is not None:
                row.title = title.strip()
            if archived is not None:
                row.archived = 1 if archived else 0
            if team_id is not None:
                row.team_id = team_id
            if skills is not None or config is not None:
                cfg = json.loads(row.config_json or "{}")
                if skills is not None:
                    cfg["skills"] = skills
                if config is not None:
                    cfg["config"] = config
                row.config_json = json.dumps(cfg, ensure_ascii=False)
            row.updated_at = utc_now()
            db.flush()
            db.refresh(row)
            return _session_to_out(db, row)

    def delete(self, session_id: str) -> bool:
        with db_session() as db:
            row = db.get(SessionRow, session_id)
            if row is None:
                return False
            db.execute(
                RunRow.__table__.update()
                .where(RunRow.session_id == session_id)
                .values(session_id=None)
            )
            db.delete(row)
            return True

    # ------------------------------------------------------------------ #
    # 消息
    # ------------------------------------------------------------------ #
    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        run_id: str | None = None,
        steps: list | None = None,
        files: list | None = None,
        meta: dict | None = None,
    ) -> MessageOut:
        from sqlalchemy.exc import IntegrityError

        def _write() -> MessageOut:
            with db_session() as db:
                max_seq = db.scalar(
                    select(func.max(MessageRow.seq)).where(MessageRow.session_id == session_id)
                ) or 0
                row = MessageRow(
                    session_id=session_id,
                    run_id=run_id,
                    seq=max_seq + 1,
                    role=role,
                    content=content,
                    steps_json=json.dumps(steps or [], ensure_ascii=False),
                    files_json=json.dumps(files or [], ensure_ascii=False),
                    meta_json=json.dumps(meta or {}, ensure_ascii=False),
                )
                db.add(row)
                sess = db.get(SessionRow, session_id)
                if sess is not None:
                    sess.updated_at = utc_now()
                    if not sess.title and role == "user" and content:
                        sess.title = content.strip()[:30]
                db.flush()
                db.refresh(row)
                return _msg_to_out(row)

        # max(seq)+1 存在并发竞态：唯一约束兜底 + 重试重算
        import random
        import time as _time

        last_exc: Exception | None = None
        for attempt in range(20):
            try:
                return retry_on_locked(_write)
            except IntegrityError as exc:
                last_exc = exc
                _time.sleep(0.005 * (attempt + 1) + random.random() * 0.01)
                continue
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------ #
    # 历史注入（只回放最终问答）
    # ------------------------------------------------------------------ #
    def build_history(
        self,
        session_id: str,
        limit: int | None = None,
        max_chars: int | None = None,
    ) -> list[dict]:
        limit = limit or settings.session_history_limit
        max_chars = max_chars or settings.session_history_max_chars
        with db_session() as db:
            rows = db.scalars(
                select(MessageRow)
                .where(
                    MessageRow.session_id == session_id,
                    MessageRow.role.in_(("user", "assistant")),
                    MessageRow.content != "",
                )
                .order_by(MessageRow.seq.desc())
                .limit(limit * 2)  # 多取一些，给中间态过滤留余量
            ).all()

        items: list[dict] = []
        for m in rows:
            meta = json.loads(m.meta_json or "{}")
            if m.role == "assistant" and meta.get("tool_only"):
                continue
            items.append({"role": m.role, "content": m.content})
            if len(items) >= limit:
                break
        items.reverse()

        # 字符预算：从旧到新裁剪，且首条必须是 user
        while items and sum(len(i["content"]) for i in items) > max_chars:
            items.pop(0)
        while items and items[0]["role"] != "user":
            items.pop(0)
        return items
