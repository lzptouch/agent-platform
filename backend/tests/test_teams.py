"""Skill 团队测试：CRUD / 校验 / 编排策略 / 互斥 / 级联。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.get("/api/v1/health")  # 确保初始化
        yield c


def _create(client, **overrides):
    payload = {"name": "数据团队", "skill_names": ["pdf", "data-analysis"], "strategy": "none"}
    payload.update(overrides)
    return client.post("/api/v1/teams", json=payload)


def test_team_crud(client):
    resp = _create(client)
    assert resp.status_code == 201
    team = resp.json()
    assert team["skill_names"] == ["pdf", "data-analysis"]
    assert team["enabled"] is True

    # 重名 → 409
    assert _create(client).status_code == 409
    # 未知成员 → 422
    assert _create(client, name="x", skill_names=["not-exist"]).status_code == 422
    # 空成员 → 422
    assert _create(client, name="y", skill_names=[]).status_code == 422

    # 列表与详情
    teams = client.get("/api/v1/teams").json()
    assert any(t["id"] == team["id"] for t in teams)

    # 更新（成员整体替换，顺序保持）
    updated = client.put(f"/api/v1/teams/{team['id']}", json={
        "skill_names": ["data-analysis", "pdf"], "strategy": "sequential",
    }).json()
    assert updated["skill_names"] == ["data-analysis", "pdf"]
    assert updated["strategy"] == "sequential"

    # 启停用
    toggled = client.post(f"/api/v1/teams/{team['id']}/toggle", json={"enabled": False}).json()
    assert toggled["enabled"] is False

    # 删除
    assert client.delete(f"/api/v1/teams/{team['id']}").status_code == 204
    assert client.get(f"/api/v1/teams/{team['id']}").status_code == 404


def test_resolve_sequential(client):
    team = _create(client, strategy="sequential").json()
    out = client.post(f"/api/v1/teams/{team['id']}/resolve", json={"query": "分析这个 PDF"}).json()
    assert [s["step_index"] for s in out["skills"]] == [1, 2]
    assert "[步骤 1/2]" in out["prompt_preview"]
    assert "数据团队" in out["prompt_preview"]


def test_resolve_none(client):
    team = _create(client).json()
    out = client.post(f"/api/v1/teams/{team['id']}/resolve", json={}).json()
    assert len(out["skills"]) == 2
    assert out["degraded"] is False


def test_resolve_router(client, monkeypatch):
    import app.core.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat", lambda *a, **k: '["pdf"]')

    team = _create(client, name="路由团队", strategy="router").json()
    out = client.post(f"/api/v1/teams/{team['id']}/resolve",
                      json={"query": "帮我提取 PDF 内容"}).json()
    assert [s["name"] for s in out["skills"]] == ["pdf"]
    assert out["degraded"] is False


def test_resolve_router_degrade(client, monkeypatch):
    import app.core.llm as llm_mod

    def _boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(llm_mod, "chat", _boom)
    team = _create(client, name="降级团队", strategy="router").json()
    out = client.post(f"/api/v1/teams/{team['id']}/resolve", json={"query": "q"}).json()
    assert out["degraded"] is True
    assert len(out["skills"]) == 2


def test_resolve_router_hallucination(client, monkeypatch):
    """LLM 返回幻觉 Skill 名 → 与候选集求交后为空 → 降级。"""
    import app.core.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat", lambda *a, **k: '["not-exist"]')
    team = _create(client, name="幻觉团队", strategy="router").json()
    out = client.post(f"/api/v1/teams/{team['id']}/resolve", json={"query": "q"}).json()
    assert out["degraded"] is True
    assert len(out["skills"]) == 2


def test_team_resolve_not_found(client):
    assert client.post("/api/v1/teams/nope/resolve", json={}).status_code == 404


def test_delete_team_clears_session_reference(client):
    team = _create(client).json()
    sess = client.post("/api/v1/sessions", json={"mode": "work", "team_id": team["id"]}).json()
    assert sess["team_id"] == team["id"]
    client.delete(f"/api/v1/teams/{team['id']}")
    sess_after = client.get(f"/api/v1/sessions/{sess['id']}").json()
    assert sess_after["team_id"] is None


def test_run_with_team(client, fake_client_factory, monkeypatch):
    """带 team_id 的运行：meta 事件含团队信息，请求体 skills 为展开成员。"""
    from tests.conftest import make_text_response

    team = _create(client).json()
    fake, calls = fake_client_factory([make_text_response("完成")])
    monkeypatch.setattr(app.state.agent_service, "_client", fake)

    resp = client.post("/api/v1/agent/run/sync", json={
        "prompt": "处理文件", "mode": "work", "team_id": team["id"],
    })
    body = resp.json()
    assert body["finished"] is True
    sent_skills_prompt = calls[0]["messages"][0]["content"]
    assert "pdf" in sent_skills_prompt and "data-analysis" in sent_skills_prompt
