"""S4 运行中干预与并发治理的契约测试。

按 doc/roadmap/05-阶段S4 的 §5.1 组织：cancel / steer / 并发预算 / 运行中查询。
"""
from __future__ import annotations

import threading
import time

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# 工具调用助手（直接驱动 agent_service.stream，绕过 LLM）
# --------------------------------------------------------------------------- #
def _stream_events(service, fake_client, scripts, **kwargs):
    """跑一次流式执行，返回事件列表。"""
    fake_client.chat.completions.scripts = list(scripts)
    service._client = fake_client
    return list(service.stream("测试指令", "gpt-test", **kwargs))


# --------------------------------------------------------------------------- #
# WP-4.1 cancel 真正中止（工具边界生效）
# --------------------------------------------------------------------------- #
class TestCancel:
    def test_cancel_工具调用后不再发起下一次调用(self, client, monkeypatch):
        """取消在**工具调用后**检查 → 停止后不再调工具。"""
        from tests.conftest import FakeClient, make_tool_call_response, make_text_response

        calls: list[dict] = []

        def make_hooks():
            state = {"rounds": 0}

            def cancel_hook() -> bool:
                state["rounds"] += 1
                return state["rounds"] > 1  # 第一轮后即取消

            return cancel_hook

        svc = app.state.agent_service
        fake = FakeClient([
            make_tool_call_response("read_file", {"file_path": "x.txt"}),
            make_text_response("不该被调用"),
        ])
        svc._client = fake

        events = list(svc.stream(
            "跑一下", "gpt-test",
            cancel_hook=make_hooks(),
        ))
        types = [e["type"] for e in events]
        assert "interrupted" in types, "取消应产生 interrupted 事件"
        assert types.count("tool_call") == 1, "取消后不应再发起第二次工具调用"
        # 第二次 LLM 调用不应发生
        assert len(fake.chat.completions.calls) == 1, "取消后不应再请求模型"

    def test_cancel_流式生成终止(self, client):
        """被取消后流式生成正常结束（不抛异常）。"""
        from tests.conftest import FakeClient, make_text_response

        svc = app.state.agent_service
        fake = FakeClient([make_text_response("ok")])
        svc._client = fake
        events = list(svc.stream("x", "gpt-test", cancel_hook=lambda: True))
        types = [e["type"] for e in events]
        assert "interrupted" in types
        assert types[-1] == "done"

    def test_cancel_端点置位标志(self, client):
        """cancel 端点置位取消标志并把 run 置为 interrupted。"""
        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        run = client.post("/api/v1/agent/run/sync", json={
            "prompt": "你好", "mode": "chat", "session_id": sess["id"],
        }).json()
        run_id = run["run_id"]

        r = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert r.status_code == 200
        assert r.json()["status"] == "interrupted"

        assert app.state.run_executor.is_cancelled(run_id) is True

    def test_cancel_不存在的run返回404(self, client):
        assert client.post("/api/v1/runs/nope/cancel").status_code == 404


# --------------------------------------------------------------------------- #
# WP-4.2 steer 队列与工具边界注入
# --------------------------------------------------------------------------- #
class TestSteer:
    def test_steer_下一轮prompt包含指令(self, client):
        from tests.conftest import FakeClient, make_text_response, make_tool_call_response

        svc = app.state.agent_service
        fake = FakeClient([
            make_tool_call_response("read_file", {"file_path": "probe.txt"}),
            make_text_response("二"),
        ])
        svc._client = fake

        injected = {"calls": 0}

        def steer_hook():
            # 第一次（首轮开始前）不注入；第二次即「第一个工具边界之后」→ 并入下一轮
            injected["calls"] += 1
            if injected["calls"] < 2:
                return []
            return [{"text": "改用表格输出", "mode": "append", "seq": 1}]

        events = list(svc.stream("原始问题", "gpt-test", steer_hook=steer_hook))
        assert any(e["type"] == "steer_injected" for e in events), "应有 steer_injected 事件"

        second_call = fake.chat.completions.calls[1]
        contents = [m.get("content", "") for m in second_call["messages"]]
        assert any("改用表格输出" in (c or "") for c in contents), "下一轮应包含 steer 指令"

    def test_steer_多次保序(self, client):
        from tests.conftest import FakeClient, make_text_response, make_tool_call_response

        svc = app.state.agent_service
        fake = FakeClient([
            make_tool_call_response("read_file", {"file_path": "probe.txt"}),
            *[make_text_response(str(i)) for i in range(6)],
        ])
        svc._client = fake

        pending = [{"text": f"指令{i}", "mode": "append", "seq": i} for i in (1, 2, 3)]
        state = {"calls": 0}

        def steer_hook():
            state["calls"] += 1
            if state["calls"] < 2:
                return []
            return list(reversed(pending))  # 故意乱序返回 → 执行器应按 seq 排好

        list(svc.stream("原始问题", "gpt-test", steer_hook=steer_hook))
        second = fake.chat.completions.calls[1]
        contents = [m.get("content", "") for m in second["messages"]]
        idx = [i for i, c in enumerate(contents) if c and c.startswith("指令")]
        assert idx == sorted(idx), "steer 应按 seq 保序注入"
        assert [contents[i] for i in idx] == ["指令1", "指令2", "指令3"]

    def test_steer_replace_plan回到规划(self, client):
        from tests.conftest import FakeClient, make_text_response, make_tool_call_response

        svc = app.state.agent_service
        fake = FakeClient([
            make_tool_call_response("read_file", {"file_path": "probe.txt"}),
            make_text_response("二"),
        ])
        svc._client = fake

        state = {"calls": 0}

        def steer_hook():
            state["calls"] += 1
            if state["calls"] < 2:
                return []
            return [{"text": "换个方案", "mode": "replace_plan", "seq": 1}]

        events = list(svc.stream("原始问题", "gpt-test", steer_hook=steer_hook))
        assert any(e["type"] == "plan_replaced" for e in events)

    def test_steer_端点接受mode并校验(self, client):
        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        run = client.post("/api/v1/agent/run/sync", json={
            "prompt": "你好", "mode": "chat", "session_id": sess["id"],
        }).json()
        run_id = run["run_id"]

        r = client.post(f"/api/v1/runs/{run_id}/steer", json={"instruction": "改用表格", "mode": "append"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["mode"] == "append"

        bad = client.post(f"/api/v1/runs/{run_id}/steer", json={"instruction": "x", "mode": "不存在的模式"})
        assert bad.status_code == 422

    def test_steer_缺少instruction返回400(self, client):
        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        run = client.post("/api/v1/agent/run/sync", json={
            "prompt": "你好", "mode": "chat", "session_id": sess["id"],
        }).json()
        assert client.post(f"/api/v1/runs/{run['run_id']}/steer", json={}).status_code == 400


# --------------------------------------------------------------------------- #
# WP-4.4 交互路径纳入并发预算
# --------------------------------------------------------------------------- #
class TestConcurrencyBudget:
    def test_调度超限立即返回busy(self, client):
        """P3-01 ②：调度预算（2 个）满 → 第 3 个**立即** busy（不排队）。"""
        from app.core.config import settings

        executor = app.state.run_executor
        held = []
        for _ in range(settings.schedule_max_concurrent):
            if executor._schedule_semaphore.acquire(blocking=False):
                held.append(True)
        try:
            events = list(executor.execute_stream(
                "调度并发测试", mode="work", acquire_slot=True, trigger="schedule",
            ))
            assert events[0]["type"] == "busy"
            assert "并发" in events[0]["content"]
            assert events[-1]["type"] == "done"
        finally:
            for _ in held:
                executor._schedule_semaphore.release()

    def test_交互超限排队而非busy(self, client):
        """P3-01 ①：交互预算满 → **排队等待**（释放槽位后继续执行）。"""
        import threading
        import time

        from app.core.config import settings

        executor = app.state.run_executor
        held = []
        for _ in range(settings.interactive_max_concurrent):
            if executor._interactive_semaphore.acquire(blocking=False):
                held.append(True)
        assert len(held) == settings.interactive_max_concurrent

        result: dict = {}

        def _run() -> None:
            result["events"] = list(executor.execute_stream(
                "交互排队测试", mode="chat", acquire_slot=True,
            ))

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        try:
            # 队列中的请求**不应**立刻返回 busy
            time.sleep(0.6)
            assert worker.is_alive(), "交互请求应排队等待，而不是立刻 busy"
            assert "events" not in result

            # 释放一个槽位 → 排队中的请求应继续执行
            executor._interactive_semaphore.release()
            held.pop()
            worker.join(timeout=20)
            assert not worker.is_alive(), "释放槽位后请求应继续执行"
            events = result.get("events") or []
            assert events and events[0]["type"] != "busy", events[:1]
        finally:
            for _ in held:
                executor._interactive_semaphore.release()

    def test_两套预算互不占用(self, client):
        """P3-01 ③：占满**调度**预算不影响交互请求。"""
        from app.core.config import settings

        executor = app.state.run_executor
        held = []
        for _ in range(settings.schedule_max_concurrent):
            if executor._schedule_semaphore.acquire(blocking=False):
                held.append(True)
        try:
            events = list(executor.execute_stream(
                "预算隔离测试", mode="chat", acquire_slot=True,
            ))
            assert events[0]["type"] != "busy", "交互预算不应被调度预算占用"
        finally:
            for _ in held:
                executor._schedule_semaphore.release()

    def test_交互路径默认占用槽位(self):
        """execute_stream 默认占用预算；execute_sync 自行持有（不重复占）。"""
        import inspect

        from app.services.run_executor import RunExecutor

        sig = inspect.signature(RunExecutor.execute_stream)
        assert sig.parameters["acquire_slot"].default is True


# --------------------------------------------------------------------------- #
# WP-4.5 运行中任务查询（不新增 /runs/active）
# --------------------------------------------------------------------------- #
class TestRunsStatusFilter:
    def test_status_filter_列出运行中任务(self, client):
        # 造一条 running 的 run
        from app.db.base import db_session
        from app.db.models import RunRow, utc_now

        with db_session() as db:
            db.add(RunRow(trigger="api", status="running", meta_json="{}", created_at=utc_now()))

        r = client.get("/api/v1/runs", params={"status": "running"})
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "应至少有一条 running"
        assert all(i["status"] == "running" for i in items)

    def test_status_filter_不含终态(self, client):
        r = client.get("/api/v1/runs", params={"status": "success"})
        assert all(i["status"] == "success" for i in r.json()["items"])

    def test_status_filter_与分页共存(self, client):
        r = client.get("/api/v1/runs", params={"status": "running", "page": 1, "page_size": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 1 and body["page_size"] == 1
        assert len(body["items"]) <= 1

    def test_不存在active端点被run_id捕获(self, client):
        """`/runs/active` 会被 `/{run_id}` 捕获（404）——这正是我们不新增它的原因。"""
        r = client.get("/api/v1/runs/active")
        assert r.status_code == 404
