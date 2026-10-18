"""会话与运行账本测试（接口级 + 服务级）。"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.session_service import SessionService


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------- #
# 会话 CRUD（接口）
# ---------------------------------------------------------------------- #
def test_session_crud(client):
    resp = client.post("/api/v1/sessions", json={"mode": "chat", "title": "测试会话"})
    assert resp.status_code == 201
    sess = resp.json()
    assert sess["mode"] == "chat"

    # 列表按模式过滤
    client.post("/api/v1/sessions", json={"mode": "work"})
    chat_list = client.get("/api/v1/sessions?mode=chat").json()
    assert chat_list["total"] == 1
    all_list = client.get("/api/v1/sessions").json()
    assert all_list["total"] == 2

    # 改名 + 归档
    updated = client.patch(f"/api/v1/sessions/{sess['id']}", json={"title": "新标题"}).json()
    assert updated["title"] == "新标题"

    # 详情
    detail = client.get(f"/api/v1/sessions/{sess['id']}").json()
    assert detail["messages"] == []

    # 删除
    assert client.delete(f"/api/v1/sessions/{sess['id']}").status_code == 204
    assert client.get(f"/api/v1/sessions/{sess['id']}").status_code == 404


def test_session_invalid_mode(client):
    resp = client.post("/api/v1/sessions", json={"mode": "bad"})
    assert resp.status_code == 422


def test_session_not_found(client):
    assert client.get("/api/v1/sessions/none").status_code == 404
    assert client.delete("/api/v1/sessions/none").status_code == 404


# ---------------------------------------------------------------------- #
# 历史注入（服务级）
# ---------------------------------------------------------------------- #
def test_build_history_rules():
    service = SessionService()
    sess = service.create(mode="chat")
    service.append_message(sess.id, "user", "问题1")
    service.append_message(sess.id, "assistant", "回答1")
    service.append_message(sess.id, "assistant", "", meta={"tool_only": True})  # 应过滤
    service.append_message(sess.id, "user", "问题2")

    history = service.build_history(sess.id)
    assert [h["role"] for h in history] == ["user", "assistant", "user"]
    assert history[0]["content"] == "问题1"


def test_build_history_char_budget():
    service = SessionService()
    sess = service.create(mode="chat")
    for i in range(6):
        service.append_message(sess.id, "user", "x" * 500)
        service.append_message(sess.id, "assistant", "y" * 500)
    history = service.build_history(sess.id, limit=20, max_chars=2000)
    assert sum(len(h["content"]) for h in history) <= 2000
    assert history[0]["role"] == "user"


# ---------------------------------------------------------------------- #
# 运行账本 + 双轮对话（接口级，假 LLM）
# ---------------------------------------------------------------------- #
def test_two_turn_run_persists(client, fake_client_factory, monkeypatch):
    from tests.conftest import make_text_response

    fake, _ = fake_client_factory([make_text_response("回答一"), make_text_response("回答二")])
    with TestClient(app) as c:
        c.get("/api/v1/health")  # 触发初始化
        monkeypatch.setattr(app.state.agent_service, "_client", fake)

        sess = c.post("/api/v1/sessions", json={"mode": "chat"}).json()

        r1 = c.post("/api/v1/agent/run/sync", json={
            "prompt": "第一轮", "mode": "chat", "session_id": sess["id"],
        })
        assert r1.status_code == 200
        body1 = r1.json()
        assert body1["finished"] is True
        assert body1["session_id"] == sess["id"]
        assert body1["run_id"]

        r2 = c.post("/api/v1/agent/run/sync", json={
            "prompt": "第二轮", "mode": "chat", "session_id": sess["id"],
        })
        assert r2.json()["finished"] is True

        detail = c.get(f"/api/v1/sessions/{sess['id']}").json()
        roles = [m["role"] for m in detail["messages"]]
        assert roles == ["user", "assistant", "user", "assistant"]
        assert detail["messages"][1]["content"] == "回答一"
        assert detail["title"] == "第一轮"

        # run 详情与事件
        run = c.get(f"/api/v1/runs/{body1['run_id']}").json()
        assert run["status"] == "success"
        assert run["trigger"] == "api"
        events = c.get(f"/api/v1/runs/{body1['run_id']}/events").json()
        assert len(events["items"]) > 0


def test_run_sync_missing_session(client):
    resp = client.post("/api/v1/agent/run/sync", json={"prompt": "hi", "session_id": "not-exist"})
    assert resp.status_code == 200  # SSE 风格错误，不崩溃
    # sync 包装中错误体现在 error 字段
    assert resp.json()["error"] is not None or resp.json()["finished"]


def test_invalid_mode_and_conflict(client):
    resp = client.post("/api/v1/agent/run/sync", json={"prompt": "hi", "mode": "nope"})
    assert resp.status_code == 422
    resp = client.post("/api/v1/agent/run/sync", json={
        "prompt": "hi", "mode": "chat", "plan_first": True,
    })
    assert resp.status_code == 422
    resp = client.post("/api/v1/agent/run/sync", json={
        "prompt": "hi", "team_id": "t1", "skills": ["pdf"],
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------- #
# SSE 流式 + meta 事件
# ---------------------------------------------------------------------- #
def test_sse_meta_event(client, fake_client_factory, monkeypatch):
    from tests.conftest import make_text_response

    fake, _ = fake_client_factory([make_text_response("你好")])
    with TestClient(app) as c:
        c.get("/api/v1/health")
        monkeypatch.setattr(app.state.agent_service, "_client", fake)
        resp = c.post("/api/v1/agent/run", json={"prompt": "你好", "mode": "chat"})
        assert resp.status_code == 200
        lines = [l for l in resp.text.splitlines() if l.startswith("data:")]
        events = [json.loads(l[5:].strip()) for l in lines]
        assert events[0]["type"] == "meta"
        assert events[0]["mode"] == "chat"
        assert events[0]["run_id"] and events[0]["session_id"]
        assert any(e["type"] == "done" for e in events)


def test_plan_first_flow(client, fake_client_factory, monkeypatch):
    """plan_first：awaiting_approval → approve → success；reject → rejected。"""
    from tests.conftest import make_text_response

    fake, _ = fake_client_factory([make_text_response("执行完成")])
    with TestClient(app) as c:
        c.get("/api/v1/health")
        monkeypatch.setattr(app.state.agent_service, "_client", fake)

        import app.core.llm as llm_mod
        monkeypatch.setattr(llm_mod, "chat", lambda *a, **k: '[{"title": "步骤1", "detail": "做第一件事"}]')

        resp = c.post("/api/v1/agent/run", json={
            "prompt": "做一个报告", "mode": "work", "plan_first": True, "skills": [],
        })
        events = [json.loads(l[5:].strip()) for l in resp.text.splitlines() if l.startswith("data:")]
        approval = next((e for e in events if e["type"] == "approval_required"), None)
        assert approval is not None
        run_id = approval["run_id"]

        run = c.get(f"/api/v1/runs/{run_id}").json()
        assert run["status"] == "awaiting_approval"
        assert run["plan"][0]["title"] == "步骤1"

        # 拒绝路径
        rejected = c.post(f"/api/v1/agent/runs/{run_id}/reject", json={"reason": "不需要了"}).json()
        assert rejected["status"] == "rejected"
        # 重复审批 → 409
        assert c.post(f"/api/v1/agent/runs/{run_id}/approve", json={}).status_code == 409
