"""P3 数据约束与语义批次的验收测试（P3-07 / P3-08 / P3-09 / P3-11 / P3-13）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _make_task(db, task_id: str) -> None:
    """创建真实的定时任务行（``runs.task_id`` 有外键约束）。"""
    from app.db.models import ScheduledTaskRow

    if db.scalar(select(ScheduledTaskRow).where(ScheduledTaskRow.id == task_id)) is None:
        db.add(ScheduledTaskRow(
            id=task_id, name=f"p3-{task_id}", prompt="p", schedule_kind="interval",
            interval_seconds=3600,
        ))
        db.flush()



# --------------------------------------------------------------------------- #
# P3-08 · runs.trigger 枚举约束
# --------------------------------------------------------------------------- #
class TestTriggerConstraint:
    """``runs.trigger`` 此前无任何约束，可写入任意字符串。"""

    def test_非法trigger被拒(self, client):
        from sqlalchemy.exc import IntegrityError

        from app.db.base import db_session
        from app.db.models import RunRow

        with pytest.raises(IntegrityError):
            with db_session() as db:
                db.add(RunRow(id="p3_08_bad", trigger="bogus", status="queued"))
                db.flush()

    @pytest.mark.parametrize("trigger", ["manual", "schedule", "api", "research"])
    def test_四种合法trigger均可写入(self, client, trigger):
        from app.db.base import db_session
        from app.db.models import RunRow

        with db_session() as db:
            db.add(RunRow(id=f"p3_08_{trigger}", trigger=trigger, status="queued"))
            db.flush()
            row = db.scalar(select(RunRow).where(RunRow.id == f"p3_08_{trigger}"))
            assert row is not None and row.trigger == trigger

    def test_约束已落到建表语句(self, client):
        from app.db.models import RunRow

        names = [c.name for c in RunRow.__table__.constraints]
        assert "ck_runs_trigger" in names, names


# --------------------------------------------------------------------------- #
# P3-07 · 乐观锁
# --------------------------------------------------------------------------- #
class TestOptimisticLock:
    """并发更新同一行时，后提交者收到 ``StaleDataError`` 而非静默覆盖。"""

    def test_版本列存在(self, client):
        from app.db.models import RunRow

        assert "version_id" in RunRow.__table__.columns
        assert RunRow.__mapper_args__.get("version_id_col") is not None

    def test_后提交者收到StaleDataError(self, client):
        """两个会话读同一行 → 都改 → 后提交的抛 ``StaleDataError``。

        SQLite 默认的 rollback journal 会让「读者持有共享锁」阻塞写者，
        因此这里**启用 WAL**（读写不互斥），才能真实模拟并发。
        """
        from sqlalchemy.orm import Session
        from sqlalchemy.orm.exc import StaleDataError

        from app.db.base import db_session, get_engine
        from app.db.models import RunRow

        run_id = "p3_07_lock"
        with db_session() as db:
            db.add(RunRow(id=run_id, trigger="manual", status="queued"))
            db.flush()

        engine = get_engine()
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")

        s1 = Session(bind=engine)
        s2 = Session(bind=engine)
        try:
            r1 = s1.get(RunRow, run_id)
            r2 = s2.get(RunRow, run_id)
            assert r1 is not None and r2 is not None

            r1.status = "running"
            s1.commit()          # 版本 1 → 2

            r2.status = "failed"   # r2 仍持有版本 1
            with pytest.raises(StaleDataError):
                s2.commit()      # UPDATE ... WHERE version_id=1 → 0 行 → 冲突
        finally:
            s1.close()
            s2.close()

        with db_session() as db:
            row = db.scalar(select(RunRow).where(RunRow.id == run_id))
            assert row is not None and row.status == "running", "先提交者的修改应保留"


# --------------------------------------------------------------------------- #
# P3-09 · keep_per_task 语义
# --------------------------------------------------------------------------- #
class TestKeepPerTask:
    """``keep_per_task`` 此前**被声明但从未使用**——只按时间删。"""

    def test_超出配额的部分被删(self, client):
        from app.db.base import db_session
        from app.db.models import RunRow
        from app.services.run_service import RunService

        task_id = "p3_09_task"
        with db_session() as db:
            _make_task(db, task_id)
            for i in range(12):
                db.add(RunRow(
                    id=f"p3_09_{i}", task_id=task_id, trigger="manual",
                    status="success", created_at=f"2026-10-{i + 1:02d}T00:00:00+00:00",
                ))
            db.flush()

        svc = RunService()
        svc.cleanup(retention_days=3650, keep_per_task=5)

        with db_session() as db:
            left = db.scalars(
                select(RunRow).where(RunRow.task_id == task_id)
            ).all()
            assert len(left) <= 5, f"保留了 {len(left)} 条（应 ≤ 5）"

    def test_其他任务不受影响(self, client):
        """未到保留期的**其他任务**记录不受影响。"""
        from app.db.base import db_session
        from app.db.models import RunRow
        from app.services.run_service import RunService

        task_a, task_b = "p3_09_a", "p3_09_b"
        with db_session() as db:
            _make_task(db, task_b)
            for i in range(3):
                db.add(RunRow(
                    id=f"p3_09_b_{i}", task_id=task_b, trigger="manual",
                    status="success", created_at=f"2026-11-{i + 1:02d}T00:00:00+00:00",
                ))
            db.flush()

        RunService().cleanup(retention_days=3650, keep_per_task=5)

        with db_session() as db:
            left = db.scalars(select(RunRow).where(RunRow.task_id == task_b)).all()
            assert len(left) == 3, f"其他任务的记录被误删（剩 {len(left)} 条）"


# --------------------------------------------------------------------------- #
# P3-11 · 单一真相源
# --------------------------------------------------------------------------- #
class TestSingleSourceOfTruth:
    """会话内容此前会**双写** SQLite 与 ``chat_log_*.json``。"""

    def test_配置项已删除(self, client):
        from app.core.config import Settings

        assert "save_chat_log" not in Settings.model_fields, "save_chat_log 配置项应已删除"

    def test_代码中无引用(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "agent_service.py").read_text(encoding="utf-8")
        assert "settings.save_chat_log" not in src, "仍引用已删除的配置项"
        assert "chat_log_" not in src, "仍有 JSON 日志写入"

    def test_不产生chat_log文件(self, client):
        """跑一次会话 → 输出目录**不新增** ``chat_log_*.json``。"""
        import glob

        from app.core.config import settings

        outputs = Path(settings.output_dir)
        before = set(glob.glob(str(outputs / "chat_log_*.json")))
        # 跑一次真实会话（docstring 承诺的就是「跑一次 → 不产生」）
        try:
            client.post("/api/v1/agent/run", json={"prompt": "hi", "mode": "chat"})
        except Exception:  # noqa: BLE001 - 无 Key / LLM 失败不影响本用例的断言
            pass
        after = set(glob.glob(str(outputs / "chat_log_*.json")))
        # **W11-01**：原断言是 `not before or True` → **恒真** → 文件是否产生从未被验证。
        # 正确口径：**本次运行不得新增** chat_log 文件
        # （输出目录里可能残留该功能下线前（2026-09）产生的历史文件，与本用例无关）。
        assert after == before, f"本次运行新增了 chat_log 文件: {sorted(after - before)}"
        assert "chat_log_" not in (BACKEND_ROOT / "app" / "core" / "config.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# P3-13 · skills.frontmatter_json 写入
# --------------------------------------------------------------------------- #
class TestFrontmatterJson:
    """该列此前**全仓无写入方**（恒为 "{}"）。"""

    def test_每行非空且是合法JSON(self, client):
        from app.db.base import db_session
        from app.db.models import SkillRecordRow

        from app.core.config import settings
        from app.services.skill_manager import SkillManager

        mgr = SkillManager(settings.skills_dir, settings.custom_skills_dir)
        mgr.reload()

        with db_session() as db:
            rows = db.scalars(select(SkillRecordRow)).all()
            assert rows, "skills 表为空"
            for row in rows:
                if row.stale:
                    continue
                assert row.frontmatter_json, f"{row.name} 的 frontmatter_json 为空"
                parsed = json.loads(row.frontmatter_json)
                assert isinstance(parsed, dict), f"{row.name} 的 frontmatter_json 不是对象"
                assert parsed.get("name"), f"{row.name} 的 frontmatter 缺 name"

    def test_列存在(self, client):
        from app.db.models import SkillRecordRow

        assert "frontmatter_json" in SkillRecordRow.__table__.columns
