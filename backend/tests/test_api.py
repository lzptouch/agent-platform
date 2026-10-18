"""FastAPI 接口冒烟测试。"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["skills_loaded"] >= 1


def test_list_skills():
    resp = client.get("/api/v1/skills")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == len(body["skills"])
    names = {s["name"] for s in body["skills"]}
    assert "pdf" in names
    for skill in body["skills"]:
        assert skill["description"]
        assert skill["skill_md_path"].endswith("SKILL.md")


def test_skill_detail_and_validate():
    for name in ("pdf", "data-analysis"):
        detail = client.get(f"/api/v1/skills/{name}")
        assert detail.status_code == 200
        assert detail.json()["content"].startswith("---")

        validation = client.post(f"/api/v1/skills/{name}/validate")
        assert validation.status_code == 200
        assert validation.json()["valid"] is True


def test_skill_not_found():
    assert client.get("/api/v1/skills/not-exist").status_code == 404


def test_skill_resource_guard():
    # 路径穿越必须被拦截
    resp = client.get("/api/v1/skills/pdf/files/../../core/config.py")
    assert resp.status_code in (400, 404)


def test_reload_skills():
    resp = client.post("/api/v1/skills/reload")
    assert resp.status_code == 200
    assert resp.json()["reloaded"] >= 1


def test_models_and_status():
    models = client.get("/api/v1/agent/models").json()
    assert models["default_model"] == settings.default_model
    assert any(m["id"] == settings.default_model for m in models["models"])

    status = client.get("/api/v1/agent/status").json()
    assert "ready" in status and "api_key_configured" in status


def test_files_listing():
    resp = client.get("/api/v1/files")
    assert resp.status_code == 200
    assert "files" in resp.json()


def test_agent_run_stream_without_key():
    """未配置 API Key 时，SSE 应返回 error + done 事件而不是崩溃。"""
    if settings.has_api_key:
        # 已配置密钥时跳过（避免真实调用模型）
        return
    resp = client.post("/api/v1/agent/run", json={"prompt": "hi"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert '"type": "error"' in resp.text
    assert '"type": "done"' in resp.text
