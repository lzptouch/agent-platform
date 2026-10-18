"""新增链路（MCP / RAG / Web Research）接口冒烟测试。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_mcp_servers_list():
    resp = client.get("/api/v1/mcp_servers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    names = {s["name"] for s in body["servers"]}
    assert names == {"weather", "search", "xiaohongshu"}


def test_mcp_server_tools_static_reflection():
    """静态反射：未启动子进程也能列出工具。"""
    resp = client.get("/api/v1/mcp_servers/weather/tools")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool_count"] == 2
    names = {t["name"] for t in body["tools"]}
    assert names == {"get_alerts", "get_forecast"}


def test_mcp_server_start_stop():
    resp = client.post("/api/v1/mcp_servers/weather/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    resp = client.post("/api/v1/mcp_servers/weather/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_mcp_server_not_found():
    assert client.get("/api/v1/mcp_servers/not-exist/tools").status_code == 404


def test_rag_stats():
    resp = client.get("/api/v1/rag/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["collection"]
    assert body["dense_dim"] == 1024
    assert body["embedding_model"] == "text-embedding-v3"


def test_web_research_status():
    resp = client.get("/api/v1/web_research/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "serper_available" in body
    assert "openai_model" in body


def test_health_extended_fields():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "rag_collection" in body
    assert "rag_entities" in body
    assert "mcp_servers_available" in body
    assert "llm_available" in body
