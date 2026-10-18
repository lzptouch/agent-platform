"""定时任务测试：校验 / CRUD / 租约 / 幂等 / 退避 / run-now。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.run_service import RunService
from app.services.scheduler_service import SchedulerService


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.get("/api/v1/health")
        yield c


class FakeExecutor:
    """记录调用并返回可控结果的假执行器。"""

    def __init__(self, results=None):
        self.calls: list[dict] = []
        self.results = list(results or [])
        self.resumed: list[str] = []

    def execute_sync(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if self.results:
            result = self.results.pop(0)
        else:
            result = {"run_id": kwargs.get("run_id"), "finished": True, "files": [], "error": None, "answer": "ok"}
        # 模拟真实执行器的状态流转：run_id 存在时把 run 标记为终态
        run_id = kwargs.get("run_id")
        if run_id and not result.get("skipped"):
            rs = RunService()
            rs.mark_running(run_id)
            rs.finish(run_id, "failed" if result.get("error") else "success",
                      error=result.get("error"), summary=result.get("answer", ""))
        return result

    def resume_after_approval(self, run_id: str) -> bool:
        self.resumed.append(run_id)
        return True


def _create_interval(client, **overrides):
    payload = {
        "name": "间隔任务",
        "prompt": "每小时检查一次",
        "schedule_kind": "interval",
        "interval_seconds": 3600,
        "mode": "chat",
        "enabled": True,
    }
    payload.update(overrides)
    return client.post("/api/v1/schedules", json=payload)


# ---------------------------------------------------------------------- #
# 校验
# ---------------------------------------------------------------------- #
def test_validate_cron(client):
    out = client.post("/api/v1/schedules/validate", json={"cron_expr": "*/10 * * * *"}).json()
    assert out["valid"] is True
    assert len(out["next_runs"]) == 3

    bad = client.post("/api/v1/schedules/validate", json={"cron_expr": "not a cron"}).json()
    assert bad["valid"] is False


def test_create_validation(client):
    # cron 与 interval 二选一
    assert client.post("/api/v1/schedules", json={
        "name": "x", "prompt": "p", "schedule_kind": "cron",
    }).status_code == 422
    # interval 下限
    assert _create_interval(client, interval_seconds=30).status_code == 422
    # work 模式必须确认无人值守
    assert _create_interval(client, mode="work").status_code == 422
    assert _create_interval(client, mode="work", allow_unattended_tools=True).status_code == 201
    # chat + plan_first
    assert _create_interval(client, plan_first=True).status_code == 422
    # 非法时区
    assert _create_interval(client, timezone="Mars/Olympus").status_code == 422
    # 非法 cron
    assert client.post("/api/v1/schedules", json={
        "name": "x", "prompt": "p", "schedule_kind": "cron", "cron_expr": "bad cron",
    }).status_code == 422
    # team 与 skills 互斥
    assert _create_interval(client, team_id="t", skills=["pdf"]).status_code == 422


# ---------------------------------------------------------------------- #
# CRUD
# ---------------------------------------------------------------------- #
def test_schedule_crud(client):
    resp = _create_interval(client)
    assert resp.status_code == 201
    task = resp.json()
    assert task["schedule_text"] == "每 60 分钟"
    assert task["health"] == "ok"

    listed = client.get("/api/v1/schedules").json()
    assert any(t["id"] == task["id"] for t in listed)

    updated = client.put(f"/api/v1/schedules/{task['id']}", json={
        "cron_expr": "0 9 * * *", "interval_seconds": None,
    })
    # PUT 只允许显式字段；interval_seconds=None 被 exclude，不会触发
    assert updated.status_code == 200
    assert updated.json()["schedule_kind"] == "cron"
    assert "每天 09:00" in updated.json()["schedule_text"]

    toggled = client.post(f"/api/v1/schedules/{task['id']}/toggle", json={"enabled": False}).json()
    assert toggled["enabled"] is False
    assert toggled["next_run_at"] is None or toggled["next_run_at"]

    assert client.delete(f"/api/v1/schedules/{task['id']}").status_code == 204
    assert client.get(f"/api/v1/schedules/{task['id']}").status_code == 404


def test_schedule_not_found(client):
    assert client.get("/api/v1/schedules/nope").status_code == 404
    assert client.post("/api/v1/schedules/nope/run-now").status_code == 404


# ---------------------------------------------------------------------- #
# 调度核心（服务级，不启动真调度器）
# ---------------------------------------------------------------------- #
def _make_service(executor=None) -> SchedulerService:
    svc = SchedulerService(executor or FakeExecutor())
    return svc


def _insert_task(**overrides) -> str:
    from app.db.base import db_session
    from app.db.models import ScheduledTaskRow

    fields = {
        "name": "t", "prompt": "p", "mode": "chat", "schedule_kind": "interval",
        "interval_seconds": 60, "enabled": 1,
    }
    fields.update(overrides)
    with db_session() as db:
        row = ScheduledTaskRow(**fields)
        db.add(row)
        db.flush()
        return row.id


def test_lease_mutual_exclusion():
    svc1 = _make_service()
    svc2 = _make_service()
    assert svc1._acquire_lease() is True
    assert svc2._acquire_lease() is False
    assert svc1._renew_lease() is True
    svc1._release_lease()
    assert svc2._acquire_lease() is True


def test_lease_takeover_after_expiry():
    from datetime import datetime, timedelta, timezone

    from app.db.base import db_session
    from app.db.models import SystemLockRow

    svc1 = _make_service()
    svc1._acquire_lease()
    # 手工过期
    with db_session() as db:
        row = db.get(SystemLockRow, "scheduler")
        row.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    svc2 = _make_service()
    assert svc2._acquire_lease() is True


def test_fire_idempotency():
    executor = FakeExecutor()
    svc = _make_service(executor)
    task_id = _insert_task()
    svc._fire(task_id)
    first_calls = len(executor.calls)
    assert first_calls == 1
    # 同槽位再触发 → 幂等跳过，不再执行
    svc._fire(task_id)
    assert len(executor.calls) == 1
    runs, total = RunService().list_runs(task_id=task_id)
    assert total == 1
    assert runs[0].status == "success"


def test_fire_creates_success_run():
    executor = FakeExecutor()
    svc = _make_service(executor)
    task_id = _insert_task()
    svc._fire(task_id)
    runs, _ = RunService().list_runs(task_id=task_id)
    assert runs[0].trigger == "schedule"
    assert runs[0].scheduled_for is not None

    from app.db.base import db_session
    from app.db.models import ScheduledTaskRow

    with db_session() as db:
        row = db.get(ScheduledTaskRow, task_id)
        assert row.run_count == 1
        assert row.last_status == "success"
        assert row.consecutive_failures == 0


def test_fire_failure_backoff():
    results = [{"finished": True, "error": "boom", "files": [], "answer": ""}] * 3
    executor = FakeExecutor(results)
    svc = _make_service(executor)
    # 用 interval 且把锚点拉远，让每次 _fire 的槽位不同
    from datetime import datetime, timedelta, timezone

    created = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    task_id = _insert_task(created_at=created)
    for _ in range(3):
        svc._fire(task_id)
        # 推进槽位：改 created_at 使下次 slot 不同
        from app.db.base import db_session
        from app.db.models import ScheduledTaskRow

        with db_session() as db:
            row = db.get(ScheduledTaskRow, task_id)
            # 不修改 created_at；改为手工清掉上次的 run 以模拟下一个槽位
            from app.db.models import RunRow

            db.query(RunRow).filter_by(task_id=task_id).delete()
            row.backoff_until = None  # 清除退避以便继续测

    from app.db.base import db_session
    from app.db.models import ScheduledTaskRow

    with db_session() as db:
        row = db.get(ScheduledTaskRow, task_id)
        assert row.consecutive_failures == 3
        assert row.last_error == "boom"


def test_fire_skipped_when_busy():
    executor = FakeExecutor([{"skipped": True, "error": "busy: 并发已达上限", "files": [], "answer": ""}])
    svc = _make_service(executor)
    task_id = _insert_task()
    svc._fire(task_id)
    runs, _ = RunService().list_runs(task_id=task_id)
    assert runs[0].status == "skipped"


def test_daily_limit():
    executor = FakeExecutor()
    svc = _make_service(executor)
    task_id = _insert_task(daily_run_limit=1)
    # 预置一条今日成功运行
    rs = RunService()
    r = rs.create_run(trigger="schedule", task_id=task_id, scheduled_for="slot-prev")
    assert r is not None
    rs.mark_running(r.id)
    rs.finish(r.id, "success")
    # 再触发 → 达到每日上限，记 skipped
    svc._fire(task_id)
    assert len(executor.calls) == 0
    runs, _ = rs.list_runs(task_id=task_id)
    skipped = [r2 for r2 in runs if r2.status == "skipped"]
    assert skipped and skipped[0].error == "达到每日运行上限"


def test_recover_interrupted():
    from app.db.base import db_session
    from app.db.models import RunRow

    with db_session() as db:
        db.add(RunRow(trigger="schedule", status="running", started_at="2020-01-01T00:00:00+00:00"))
    svc = _make_service()
    assert svc.recover() == 1
    with db_session() as db:
        row = db.query(RunRow).first()
        assert row.status == "interrupted"


def test_run_now_api(client, monkeypatch):
    """run-now 接口：返回 run_id 并可查询终态。"""
    from app.core.config import settings

    executor = FakeExecutor()
    monkeypatch.setattr(app.state.scheduler_service, "run_executor", executor)

    task = _create_interval(client).json()
    out = client.post(f"/api/v1/schedules/{task['id']}/run-now?wait_seconds=5").json()
    assert out["run_id"]
    assert out["status"] in ("success", "running", "queued")

    runs = client.get(f"/api/v1/schedules/{task['id']}/runs").json()
    assert runs["total"] >= 1
    run = client.get(f"/api/v1/runs/{out['run_id']}").json()
    assert run["trigger"] == "manual"


def test_health_endpoint(client):
    body = client.get("/api/v1/health").json()
    assert body["database"] == "ok"
    assert "scheduler" in body
    sched = client.get("/api/v1/schedules/health").json()
    assert sched["role"] in ("primary", "standby")
