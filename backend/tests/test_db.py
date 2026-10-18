"""数据层测试：迁移 / PRAGMA / 约束 / 并发写。"""
import threading

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.base import db_session, get_engine
from app.db.models import (
    MessageRow,
    RunRow,
    SessionRow,
)


def test_tables_exist():
    inspector = inspect(get_engine())
    tables = set(inspector.get_table_names())
    expected = {
        "sessions", "messages", "teams", "team_skills", "skills",
        "scheduled_tasks", "runs", "run_events", "system_locks",
    }
    assert expected <= tables


def test_sqlite_pragma():
    with db_session() as db:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert db.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"


def test_cascade_delete_session_messages():
    with db_session() as db:
        sess = SessionRow(mode="chat", title="t")
        db.add(sess)
        db.flush()
        db.add(MessageRow(session_id=sess.id, seq=1, role="user", content="hi"))
        db.add(MessageRow(session_id=sess.id, seq=2, role="assistant", content="hello"))
        sid = sess.id
    with db_session() as db:
        db.delete(db.get(SessionRow, sid))
    with db_session() as db:
        remaining = db.query(MessageRow).filter_by(session_id=sid).count()
    assert remaining == 0


def test_unique_session_seq():
    with db_session() as db:
        sess = SessionRow(mode="chat")
        db.add(sess)
        db.flush()
        db.add(MessageRow(session_id=sess.id, seq=1, role="user", content="a"))
        sid = sess.id
    with pytest.raises(IntegrityError), db_session() as db:
        db.add(MessageRow(session_id=sid, seq=1, role="user", content="dup"))
        db.flush()


def test_unique_task_slot_idempotency():
    from app.db.models import ScheduledTaskRow

    with db_session() as db:
        db.add(ScheduledTaskRow(name="t", prompt="p", schedule_kind="interval", interval_seconds=60))
        db.flush()
        task_id = db.query(ScheduledTaskRow).first().id
    # 同 (task_id, slot) 冲突（幂等闸门）
    with db_session() as db:
        db.add(RunRow(trigger="schedule", scheduled_for="2026-10-19T09:00:00+00:00",
                      status="success", task_id=task_id))
    with pytest.raises(IntegrityError), db_session() as db:
        db.add(RunRow(trigger="schedule", scheduled_for="2026-10-19T09:00:00+00:00",
                      status="success", task_id=task_id))
        db.flush()
    # NULL slot 不冲突（手动运行可多次；SQLite 唯一索引不约束 NULL）
    with db_session() as db:
        db.add(RunRow(trigger="manual", scheduled_for=None, status="success", task_id=task_id))
        db.add(RunRow(trigger="manual", scheduled_for=None, status="success", task_id=task_id))


def test_concurrent_message_appends():
    """8 线程 × 20 条并发写入：无锁错误逃逸、seq 唯一连续。"""
    from app.services.session_service import SessionService

    service = SessionService()
    sess = service.create(mode="chat")
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            for i in range(20):
                service.append_message(sess.id, "user", f"t{n}-{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"并发写失败: {errors[:3]}"
    with db_session() as db:
        seqs = sorted(
            r[0] for r in db.query(MessageRow.seq).filter_by(session_id=sess.id).all()
        )
    assert len(seqs) == 160
    assert seqs == list(range(1, 161))


def test_retry_on_locked_succeeds():
    from app.db.base import retry_on_locked

    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            from sqlalchemy.exc import OperationalError

            raise OperationalError("x", {}, Exception("database is locked"))
        return "ok"

    assert retry_on_locked(flaky) == "ok"
