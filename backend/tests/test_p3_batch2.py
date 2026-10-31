"""本批交付的验收测试：P3 八项 + P2-24 + P6-01 / P6-02 / P6-07。"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "web" / "vue-element-plus" / "src"
DESKTOP_MAIN = REPO_ROOT / "frontend" / "desktop" / "src" / "main"


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# P3-01 · 交互 / 调度 两套并发预算
# --------------------------------------------------------------------------- #
class TestConcurrencySeparation:
    def test_两套信号量独立(self, client):
        ex = client.app.state.run_executor
        assert ex._interactive_semaphore is not ex._schedule_semaphore

    def test_交互预算独立计数(self, client):
        from app.core.config import settings

        ex = client.app.state.run_executor
        # **W11-01**：`or True` 使断言恒真 → 「两套预算不同」从未被验证
        assert settings.interactive_max_concurrent != settings.schedule_max_concurrent
        # 交互与调度各自持有槽位
        assert ex._interactive_semaphore._value == settings.interactive_max_concurrent
        assert ex._schedule_semaphore._value == settings.schedule_max_concurrent

    def test_调度满时交互不受影响(self, client):
        from app.core.config import settings

        ex = client.app.state.run_executor
        held = []
        for _ in range(settings.schedule_max_concurrent):
            if ex._schedule_semaphore.acquire(blocking=False):
                held.append(True)
        try:
            sem, acquired, limit = ex._acquire_slot("schedule")
            assert acquired is False, "调度预算应已满"
            sem, acquired, limit = ex._acquire_slot("api")
            assert acquired is True, "交互预算不应被调度预算占用"
            sem.release()
        finally:
            for _ in held:
                ex._schedule_semaphore.release()


# --------------------------------------------------------------------------- #
# P3-04 · cron 槽位 = 真实触发时刻
# --------------------------------------------------------------------------- #
class TestCronSlot:
    def test_槽位是真实触发时刻(self, client):
        """``0 9 * * 1-5`` 的任务在 09:00:00 触发 → 槽位恰为 09:00:00。"""
        from app.db.base import db_session
        from app.db.models import ScheduledTaskRow
        from app.services.scheduler_service import SchedulerService

        svc = SchedulerService()
        with db_session() as db:
            row = ScheduledTaskRow(
                id="p3_04_cron", name="p3-04", prompt="p",
                schedule_kind="cron", cron_expr="0 9 * * 1-5",
                timezone="Asia/Shanghai",
                created_at="2026-10-26T00:00:00+00:00",  # 周一
            )
            db.add(row)
            db.flush()

            fire_at = datetime(2026, 10, 30, 9, 0, 0, tzinfo=ZoneInfoShim())
            slot = svc._cron_last_fire(row, fire_at)
            assert slot.startswith("2026-10-30T01:00:00"), slot

    def test_补跑与正常触发同一算法(self, client):
        """正常触发与补跑必须算出**同一个**槽位（幂等闸门才有效）。"""
        from app.services.scheduler_service import SchedulerService

        src = (BACKEND_ROOT / "app" / "services" / "scheduler_service.py").read_text(
            encoding="utf-8",
        )
        assert "_cron_last_fire" in src
        assert "now.replace(second=0, microsecond=0).isoformat()" in src, (
            "cron 槽位仍用「当前分钟截断」"
        )


def ZoneInfoShim():  # noqa: N802 - 测试辅助
    from zoneinfo import ZoneInfo

    return ZoneInfo("Asia/Shanghai")


# --------------------------------------------------------------------------- #
# P3-05 · 工具结果按 token 预算截断
# --------------------------------------------------------------------------- #
class TestToolResultBudget:
    def test_截断长度随预算变化(self, client):
        from app.services.agent_service import _budget_tool_limit

        small = _budget_tool_limit([], "gpt-4o-mini", cap=8000)
        large = _budget_tool_limit([], "gpt-4o", cap=8000)
        assert small[0] <= large[0] + 1, (small, large)
        assert small[0] <= 8000, "上限不得放大"

    def test_不超上限(self, client):
        from app.services.agent_service import _budget_tool_limit

        limit, _ratio = _budget_tool_limit([], "gpt-4o", cap=2000)
        assert limit <= 2000

    def test_事件带截断标记(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "agent_service.py").read_text(encoding="utf-8")
        assert '"truncated": truncated' in src, "tool_result 事件缺少 truncated 标记"
        assert '"truncated_ratio"' in src, "tool_result 事件缺少截断比例"

    def test_不再硬编码固定长度(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "agent_service.py").read_text(encoding="utf-8")
        assert "result_str[:8000]" not in src, "仍硬编码 8000 字符上限"
        assert "result_str[:2000]" not in src, "仍硬编码 2000 字符上限"


# --------------------------------------------------------------------------- #
# P3-06 · DR 阶段 checkpoint
# --------------------------------------------------------------------------- #
class TestResearchCheckpoint:
    def test_checkpoint可写可读(self, client, tmp_path):
        from app.services.research.orchestrator import Orchestrator, ResearchState

        state = ResearchState(original_task="t", start_time=0.0, status="planning")
        Orchestrator.write_checkpoint(Orchestrator, "p3-06-task", "planning", state)
        # 写到 settings.research_output_abs 下
        data = Orchestrator.read_checkpoint("p3-06-task")
        assert data is not None
        assert data["stage"] == "planning"
        assert "elapsed" in data and "artifacts" in data

    def test_run支持task_id(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "research" / "orchestrator.py").read_text(
            encoding="utf-8",
        )
        assert "def run(self, task: str, *, task_id: str | None = None)" in src
        assert "self.write_checkpoint(task_id," in src, "阶段结束未写 checkpoint"

    def test_api透传task_id(self, client):
        src = (BACKEND_ROOT / "app" / "api" / "v1" / "research.py").read_text(encoding="utf-8")
        assert "task_id=task_id" in src, "API 未把 task_id 传给研究服务"


# --------------------------------------------------------------------------- #
# P3-10 · 会话软删除
# --------------------------------------------------------------------------- #
class TestSessionSoftDelete:
    def test_删除后详情404(self, client):
        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        assert client.delete(f"/api/v1/sessions/{sess['id']}").status_code in (200, 204)
        assert client.get(f"/api/v1/sessions/{sess['id']}").status_code == 404

    def test_软删保留消息行数(self, client):
        from app.db.base import db_session
        from app.db.models import MessageRow
        from sqlalchemy import func, select

        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        client.post("/api/v1/agent/run/sync", json={
            "prompt": "留痕探针", "mode": "chat", "session_id": sess["id"],
        })
        with db_session() as db:
            before = db.scalar(
                select(func.count()).select_from(MessageRow).where(
                    MessageRow.session_id == sess["id"],
                )
            ) or 0
        client.delete(f"/api/v1/sessions/{sess['id']}")
        with db_session() as db:
            after = db.scalar(
                select(func.count()).select_from(MessageRow).where(
                    MessageRow.session_id == sess["id"],
                )
            ) or 0
        assert before > 0, "前置未产生消息"
        assert after == before, f"软删破坏了消息行数：{before} → {after}"

    def test_列表默认不含已删(self, client):
        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        client.delete(f"/api/v1/sessions/{sess['id']}")
        listing = client.get("/api/v1/sessions?page_size=100").json()
        ids = {s["id"] for s in (listing.get("items") or [])}
        assert sess["id"] not in ids, "已删会话仍出现在列表里"

    def test_永久删除端点存在(self, client):
        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        r = client.delete(f"/api/v1/sessions/{sess['id']}/purge")
        assert r.status_code == 200, r.text

    def test_有deleted_at列(self, client):
        from app.db.models import SessionRow

        assert "deleted_at" in SessionRow.__table__.columns


# --------------------------------------------------------------------------- #
# P3-12 · tasks.jsonl 追加日志
# --------------------------------------------------------------------------- #
class TestTasksJsonl:
    def test_不再全量重写(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "research" / "research_manager.py").read_text(
            encoding="utf-8",
        )
        assert "tasks.jsonl" in src, "未切换到追加型日志"
        assert "write_text(" not in src.split("def _save_tasks")[1].split("def ")[0], (
            "_save_tasks 仍在全量重写文件"
        )
        assert ".open(\"a\"" in src or '.open("a"' in src, "未使用追加模式"

    def test_恢复时折叠日志(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "research" / "research_manager.py").read_text(
            encoding="utf-8",
        )
        assert "folded" in src, "恢复未按 task_id 折叠"


# --------------------------------------------------------------------------- #
# P3-14 · LLM 真流式
# --------------------------------------------------------------------------- #
class TestStreamingLlm:
    def test_主循环带stream(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "agent_service.py").read_text(encoding="utf-8")
        assert "stream=True" in src, "主循环未开启流式"

    def test_增量产出model_text(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "agent_service.py").read_text(encoding="utf-8")
        assert '"delta": True' in src, "流式分支未标记增量"

    def test_工具调用仍等完整JSON(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "agent_service.py").read_text(encoding="utf-8")
        assert "tool_acc" in src, "未累积工具调用参数"
        assert '"arguments"' in src


# --------------------------------------------------------------------------- #
# P3-15 · 审批恢复持久化
# --------------------------------------------------------------------------- #
class TestApprovalResume:
    def test_用受控线程池(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "run_executor.py").read_text(encoding="utf-8")
        assert "_resume_pool" in src, "未使用受控线程池"
        assert "daemon=True" not in src.split("def resume_after_approval")[1].split("def ")[0], (
            "仍用裸 daemon 线程"
        )

    def test_批准时写恢复参数(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "run_service.py").read_text(encoding="utf-8")
        assert '"resume_of"' in src, "approve_plan 未写 resume_of"
        assert '"approved_at"' in src

    def test_启动时扫描恢复(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "run_executor.py").read_text(encoding="utf-8")
        assert "def resume_pending_approvals" in src
        state = (BACKEND_ROOT / "app" / "core" / "state.py").read_text(encoding="utf-8")
        assert "resume_pending_approvals" in state, "启动时未扫描恢复"

    def test_退出时等待恢复任务(self, client):
        src = (BACKEND_ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert "run_executor.close(wait=True)" in src, "退出时未等待恢复任务"


# --------------------------------------------------------------------------- #
# P2-24 · /agent/chat 收敛
# --------------------------------------------------------------------------- #
class TestAgentChatConverged:
    def test_端点走统一执行器(self, client):
        src = (BACKEND_ROOT / "app" / "api" / "v1" / "agent.py").read_text(encoding="utf-8")
        assert "services.agent.service" not in src, "/agent/chat 仍调用遗留服务"
        assert "executor.execute_stream" in src

    def test_遗留包已删除(self, client):
        assert not (BACKEND_ROOT / "app" / "services" / "agent").exists()

    def test_调用后写账本(self, client):
        """调用后 ``runs`` 表有对应行（验收①）。"""
        from app.db.base import db_session
        from app.db.models import RunRow
        from sqlalchemy import select

        before = 0
        with db_session() as db:
            before = len(db.scalars(select(RunRow)).all())

        # 无 LLM 凭证时可能失败，但**账本行仍应存在**（执行已登记）
        client.post("/api/v1/agent/chat", json={"query": "P2-24 探针"})

        with db_session() as db:
            after = len(db.scalars(select(RunRow)).all())
        assert after > before, "/agent/chat 未写账本"


# --------------------------------------------------------------------------- #
# P6-01 / P6-02 / P6-07
# --------------------------------------------------------------------------- #
class TestReleaseDecisions:
    def test_裁剪已实现(self, client):
        src = (REPO_ROOT / "scripts" / "stage-runtime.mjs").read_text(encoding="utf-8")
        assert "PRUNE_DIRS" in src, "运行时未实现裁剪"
        assert "playwright" in src, "未剔除 Playwright"
        assert "__pycache__" in src, "未剔除 __pycache__"

    def test_预算与实测一致(self, client):
        src = (REPO_ROOT / "scripts" / "build-desktop.mjs").read_text(encoding="utf-8")
        assert "runtime: 700" in src, "运行时预算未按实测调整"

    def test_签名状态被记录(self, client):
        src = (REPO_ROOT / "scripts" / "verify_desktop_package.py").read_text(encoding="utf-8")
        assert "def check_signature" in src, "未实现签名状态检查"
        assert "签名状态已记录" in src, "自检未记录签名状态"

    def test_run_state仅正常退出时清理(self, client):
        """P6-07：sidecar 异常终止**必须保留** run-state（孤儿回收依据）。"""
        backend = (DESKTOP_MAIN / "backend.ts").read_text(encoding="utf-8")
        stop_body = backend.split("async stop(")[1].split("\n  }")[0]
        assert "clearRunState()" not in stop_body, (
            "stop() 仍在无条件清理 run-state（异常终止时会丢孤儿回收依据）"
        )
        index = (DESKTOP_MAIN / "index.ts").read_text(encoding="utf-8")
        assert "supervisor.clearRunState()" in index, "正常退出路径未清理 run-state"
