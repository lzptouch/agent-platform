"""批次 03 · 数据一致性与调度细节的契约测试。

对应 `doc/plan/03-数据一致性与调度细节.md`：
入库幂等 / 日志落盘可检索 / run_id 对齐 / 时区配额 / 周期巡检 /
RUN_INGEST 幂等 / 危险工具开关。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.core import logging as app_logging
from app.db.base import db_session
from app.db.models import RunRow, ScheduledTaskRow, utc_now
from app.services.run_service import RunService


# --------------------------------------------------------------------------- #
# 3.1 / 3.6 RAG 入库幂等
# --------------------------------------------------------------------------- #
class TestRagIngestIdempotency:
    """入库按「绝对路径 + 内容哈希」幂等。"""

    def _pdf(self, tmp_path: Path, name: str = "a.pdf", text: str = "hello") -> Path:
        p = tmp_path / name
        p.write_bytes(text.encode("utf-8"))
        return p

    def test_幂等键由路径与内容哈希决定(self, tmp_path: Path):
        from app.services.rag import ledger

        f = self._pdf(tmp_path)
        h = ledger.content_hash(f)
        doc_id = ledger.make_doc_id(str(f.resolve()), h)
        # 同样的输入 → 同样的键
        assert ledger.make_doc_id(str(f.resolve()), h) == doc_id
        # 内容变了 → 键变了
        assert ledger.make_doc_id(str(f.resolve()), "other") != doc_id
        # 路径变了 → 键也变了
        assert ledger.make_doc_id(str(tmp_path / "b.pdf"), h) != doc_id

    def test_同文件重复入库不新增chunk(self, tmp_path: Path, monkeypatch):
        """第二次入库：文件没变 → 跳过（不 embed、不写 chunk、chunk 数不变）。"""
        from app.services.rag import ingest as ingest_mod

        self._pdf(tmp_path)
        calls = {"embed": 0, "insert": 0}

        def fake_embed(chunks):
            calls["embed"] += 1
            return [[0.0] * 4 for _ in chunks]

        def fake_insert(chunks, vectors, doc_ids=None, batch_size=50):
            calls["insert"] += 1
            return len(chunks)

        class FakeCol:
            name = "fake"

            def __init__(self) -> None:
                self.num_entities = 0

        monkeypatch.setattr(ingest_mod, "embed_texts", fake_embed)
        monkeypatch.setattr(ingest_mod, "insert_chunks", fake_insert)
        monkeypatch.setattr(ingest_mod, "create_collection", lambda recreate=False: FakeCol())
        monkeypatch.setattr(ingest_mod, "_parse_one", lambda p: "解析内容 " * 10)
        monkeypatch.setattr(ingest_mod, "delete_by_doc_id", lambda doc_id: 1)

        first = ingest_mod.ingest(recreate=False, data_dir=str(tmp_path))
        assert first["ingested"] == 1
        assert first["skipped"] == 0
        assert calls["embed"] == 1 and calls["insert"] == 1

        second = ingest_mod.ingest(recreate=False, data_dir=str(tmp_path))
        # 第二次：全部跳过 → 没有新的 embed / insert
        assert second["ingested"] == 0
        assert second["skipped"] == 1
        assert calls["embed"] == 1, "重复入库不应再调用编码"
        assert calls["insert"] == 1, "重复入库不应再写 chunk"

    def test_内容变化会重新入库并清理旧版本(self, tmp_path: Path, monkeypatch):
        from app.services.rag import ingest as ingest_mod

        f = self._pdf(tmp_path, text="v1")
        deleted: list[str] = []

        class FakeCol:
            name = "fake"
            num_entities = 0

        monkeypatch.setattr(ingest_mod, "embed_texts", lambda chunks: [[0.0] * 4 for _ in chunks])
        monkeypatch.setattr(ingest_mod, "insert_chunks", lambda c, v, doc_ids=None, batch_size=50: len(c))
        monkeypatch.setattr(ingest_mod, "create_collection", lambda recreate=False: FakeCol())
        monkeypatch.setattr(ingest_mod, "_parse_one", lambda p: "内容")
        monkeypatch.setattr(ingest_mod, "delete_by_doc_id", lambda doc_id: deleted.append(doc_id) or 1)

        ingest_mod.ingest(recreate=False, data_dir=str(tmp_path))
        f.write_bytes(b"v2-changed")
        stats = ingest_mod.ingest(recreate=False, data_dir=str(tmp_path))

        assert stats["ingested"] == 1
        assert stats["removed"] == 1
        assert len(deleted) == 1, "旧版本的 chunk 必须被删除"


# --------------------------------------------------------------------------- #
# 3.2 日志落盘
# --------------------------------------------------------------------------- #
class TestFileLogging:
    """JSON 行落盘 + 可按 request_id / run_id 检索。"""

    def _fresh_file_handler(self, directory: Path):
        """摘掉可能已存在的文件 handler，保证写到本测试的目录。"""
        root = logging.getLogger()
        for h in list(root.handlers):
            if getattr(h, "_agent_file_handler", False):
                root.removeHandler(h)
        return app_logging.enable_file_logging(directory=directory)

    def test_落盘日志可按request_id检索(self, tmp_path: Path):
        root = logging.getLogger()
        root_level, handler_levels = root.level, [(h, h.level) for h in root.handlers]
        handler = self._fresh_file_handler(tmp_path)
        assert handler is not None
        try:
            token = app_logging.bind_context(request_id="req-123", run_id="run-456")
            logging.getLogger("probe").error("落盘探针消息")
            app_logging.reset_context(token)
            handler.flush()
            content = (tmp_path / "app.log").read_text(encoding="utf-8")
            payload = json.loads(content.strip().splitlines()[-1])
            assert payload["message"] == "落盘探针消息"
            assert payload["request_id"] == "req-123"
            assert payload["run_id"] == "run-456"
        finally:
            root.removeHandler(handler)
            root.setLevel(root_level)
            for h, lvl in handler_levels:
                h.setLevel(lvl)

    def test_错误全量调试按比例采样(self):
        from app.core.logging import LevelSamplingFilter

        f = LevelSamplingFilter(rate=0.0)
        err = logging.LogRecord("x", logging.ERROR, "f", 1, "e", None, None)
        dbg = logging.LogRecord("x", logging.DEBUG, "f", 1, "d", None, None)
        assert f.filter(err) is True, "错误必须全量记录"
        assert f.filter(dbg) is False, "采样率为 0 时不应记录 DEBUG"

        f_all = LevelSamplingFilter(rate=1.0)
        assert f_all.filter(dbg) is True

    def test_落盘开关可关闭(self, tmp_path: Path, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "log_to_file", False)
        assert app_logging.enable_file_logging(directory=tmp_path) is None

    def test_挂载后重复调用不重复挂(self, tmp_path: Path):
        root = logging.getLogger()
        root_level = root.level
        handler = self._fresh_file_handler(tmp_path)
        try:
            again = app_logging.enable_file_logging(directory=tmp_path)
            assert again is handler, "重复调用应复用同一个 handler（否则同一文件写两遍）"
            file_handlers = [
                h for h in root.handlers if getattr(h, "_agent_file_handler", False)
            ]
            assert len(file_handlers) == 1
        finally:
            root.removeHandler(handler)
            root.setLevel(root_level)


# --------------------------------------------------------------------------- #
# 3.3 approval_required 事件带 run_id
# --------------------------------------------------------------------------- #
class TestApprovalEventRunId:
    def test_approval_required事件带run_id(self):
        """plan-first 分支产出的事件必须带 run_id（前端 ApprovalRequiredEv.run_id 必填）。"""
        from types import SimpleNamespace

        from app.services.agent_service import AgentService

        class _StubSkillManager:
            def resolve_for_mode(self, skills, mode):
                return []

            def list_skills(self):
                return []

            def build_system_prompt(self, skills, mode, team, query=""):
                return "系统提示"

        class _StubToolRegistry:
            def get_combined_tools(self, **kw):
                return []

            def build_tools_prompt_section(self, **kw):
                return ""

        stub = SimpleNamespace(
            skill_manager=_StubSkillManager(),
            tool_registry=_StubToolRegistry(),
            _generate_plan=lambda prompt: [{"id": 1, "title": "步骤一", "detail": "d"}],
        )

        events = []
        for ev in AgentService.stream(
            stub, "帮我做件事", None, mode="work", plan_first=True, run_id="run-abc",
        ):
            events.append(ev)
            if ev.get("type") == "done":
                break

        approval = next(e for e in events if e["type"] == "approval_required")
        assert approval["run_id"] == "run-abc"
        assert "plan" in approval


# --------------------------------------------------------------------------- #
# 3.4 每日配额按任务时区
# --------------------------------------------------------------------------- #
class TestDailyQuotaTimezone:
    def _make_run(self, task_id: str, started_at: str) -> None:
        with db_session() as db:
            db.add(RunRow(
                id=f"run-{started_at}-{task_id}",
                task_id=task_id,
                trigger="schedule",
                status="success",
                started_at=started_at,
                finished_at=started_at,
                created_at=started_at,
            ))

    def test_配额按任务时区切分自然日(self):
        svc = RunService()
        task_id = "task-tz"
        with db_session() as db:
            db.add(ScheduledTaskRow(
                id=task_id, name="tz-task", prompt="p", schedule_kind="interval",
                interval_seconds=3600, timezone="Asia/Shanghai",
            ))

        # **固定基准**：用「本地今天正午」而非「现在 - N 分钟」——
        # 后者会随**钟点**变化（本地 23:5x 时「10 分钟前」已是昨天）→ 断言时有时无。
        from zoneinfo import ZoneInfo

        now_local = datetime.now(ZoneInfo("Asia/Shanghai"))
        today_noon = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
        # 昨天正午：无论按 UTC 还是 Asia/Shanghai 都算「昨天」，不计入今天
        old = (today_noon - timedelta(days=1)).astimezone(timezone.utc).isoformat()
        self._make_run(task_id, old)
        # 今天正午：两个时区都算「今天」
        recent = today_noon.astimezone(timezone.utc).isoformat()
        self._make_run(task_id, recent)

        # Asia/Shanghai 的「今天」比 UTC 晚 8 小时 → 30 小时前的 run 在 UTC 里是昨天，
        # 在上海时区里也还是昨天（30h > 24h）→ 两种口径都是 1
        assert svc.count_today_runs(task_id, "Asia/Shanghai") == 1
        assert svc.count_today_runs(task_id, "UTC") == 1

    def test_跨时区零界前后不误判(self):
        """任务时区为 UTC+14 时，本地零点比 UTC 早 → 边界附近的 run 不应被算进「今天」。"""
        svc = RunService()
        task_id = "task-tz2"
        with db_session() as db:
            db.add(ScheduledTaskRow(
                id=task_id, name="tz-task-2", prompt="p", schedule_kind="interval",
                interval_seconds=3600, timezone="Pacific/Kiritimati",
            ))
        kiritimati = ZoneInfo("Pacific/Kiritimati")  # UTC+14
        now_local = datetime.now(kiritimati)
        local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        # 本地零点前 1 分钟的 run（UTC 侧仍是前一天）
        before = (local_midnight - timedelta(minutes=1)).astimezone(timezone.utc).isoformat()
        self._make_run(task_id, before)
        assert svc.count_today_runs(task_id, "Pacific/Kiritimati") == 0

    def test_非法时区回落UTC不抛(self):
        svc = RunService()
        assert svc.count_today_runs("task-none", "Mars/Olympus") == 0


# --------------------------------------------------------------------------- #
# 3.5 running 状态周期巡检
# --------------------------------------------------------------------------- #
class TestStaleRunSweep:
    def test_超期running被标记为interrupted(self):
        svc = RunService()
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with db_session() as db:
            db.add(RunRow(
                id="run-stale", trigger="api", status="running",
                started_at=old, created_at=old,
            ))
        count = svc.recover_interrupted(grace_seconds=60, reason="周期巡检标记为中断")
        assert count == 1
        with db_session() as db:
            row = db.get(RunRow, "run-stale")
            assert row.status == "interrupted"
            assert "周期巡检" in (row.error or "")
            assert row.finished_at is not None

    def test_未超期的run不动(self):
        svc = RunService()
        now = datetime.now(timezone.utc).isoformat()
        with db_session() as db:
            db.add(RunRow(
                id="run-fresh", trigger="api", status="running",
                started_at=now, created_at=now,
            ))
        assert svc.recover_interrupted(grace_seconds=3600) == 0
        with db_session() as db:
            assert db.get(RunRow, "run-fresh").status == "running"

    def test_调度器周期巡检方法存在且可调用(self):
        from app.services.scheduler_service import SchedulerService

        svc = SchedulerService()
        # 没有超期 run → 返回 0，且不抛
        assert svc.sweep_stale_runs() == 0


# --------------------------------------------------------------------------- #
# 3.7 危险工具开关
# --------------------------------------------------------------------------- #
class TestDangerousToolsSwitch:
    def _decide(self, tool: str) -> str:
        from app.services.security.permissions import PermissionService

        svc = PermissionService.instance()
        decision = svc.enforce(
            __import__("app.services.security.permissions", fromlist=["PermissionRequest"])
            .PermissionRequest(tool=tool, command="echo hi"),
            run_id=None,
        )
        return decision.decision

    def test_无人值守且未开启时危险工具被拒(self):
        from app.services.scheduler_service import dangerous_tools_context, unattended_context

        unattended_context.set(True)
        dangerous_tools_context.set(False)
        try:
            assert self._decide("execute_bash") == "deny"
            assert self._decide("write_file") == "deny"
        finally:
            unattended_context.set(False)
            dangerous_tools_context.set(False)

    def test_无人值守且开启时危险工具放行(self):
        from app.services.scheduler_service import dangerous_tools_context, unattended_context

        unattended_context.set(True)
        dangerous_tools_context.set(True)
        try:
            assert self._decide("execute_bash") == "allow"
        finally:
            unattended_context.set(False)
            dangerous_tools_context.set(False)

    def test_有人值守时不受开关影响(self):
        from app.services.scheduler_service import dangerous_tools_context, unattended_context

        unattended_context.set(False)
        dangerous_tools_context.set(False)
        try:
            # 无审批通道的 Web 环境 → ask 降级为 deny（既有语义不变）
            assert self._decide("execute_bash") in ("deny", "allow")
        finally:
            dangerous_tools_context.set(False)


# --------------------------------------------------------------------------- #
# 3.6 RUN_INGEST 幂等（脚本层）
# --------------------------------------------------------------------------- #
class TestIngestScript:
    def test_脚本默认走增量模式(self):
        """scripts/ingest_data.py 默认不重建（否则每次启动都重灌）。"""
        src = Path(__file__).resolve().parents[1] / "scripts" / "ingest_data.py"
        text = src.read_text(encoding="utf-8")
        assert "recreate=args.recreate" in text
        assert "ingest(recreate=True)" not in text


# --------------------------------------------------------------------------- #
# 迁移链（批次 03 顺带修掉的既有缺陷：全新数据库建不起来）
# --------------------------------------------------------------------------- #
class TestMigrationChain:
    def test_全新数据库能跑通迁移链(self, tmp_path: Path, monkeypatch):
        """从零建库必须能跑完 0001→head。

        此前 0001 用当前 ORM 建表（已是 S2 之后的结构），而 0002/0004 仍按旧结构
        读写 → **全新数据库在 0002 就崩掉**（老库不受影响，所以一直没暴露）。
        """
        from alembic import command
        from alembic.config import Config

        from app.core.config import settings

        db_path = (tmp_path / "mig.db").as_posix()
        # **必须改环境变量**——alembic 的 env.py 从环境读 URL
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")

        backend_root = Path(__file__).resolve().parents[1]
        cfg = Config(str(backend_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_root / "app" / "db" / "migrations"))
        command.upgrade(cfg, "head")

        import sqlite3

        con = sqlite3.connect(db_path)
        try:
            version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            assert version == "0012", f"迁移未到 head，实际 {version}"
            tables = {
                r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            # P2-16：RRULE 表达式列必须随迁移落地
            task_cols = {
                r[1] for r in con.execute("PRAGMA table_info(scheduled_tasks)")
            }
            assert "rrule_expr" in task_cols, f"scheduled_tasks 缺 rrule_expr：{task_cols}"
            assert "rag_documents" in tables
            # 内置规则已写入（0002 + 0004）
            count = con.execute("SELECT COUNT(*) FROM permission_rules").fetchone()[0]
            assert count > 0
            # 规则表是 S2 之后的结构（有 pattern，没有 target）
            cols = {r[1] for r in con.execute("PRAGMA table_info(permission_rules)")}
            assert "pattern" in cols and "target" not in cols
        finally:
            con.close()
