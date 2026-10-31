"""F-SCH-05 / F-SCH-06 的验收测试。

- **F-SCH-05**：MCP **SSE 传输腿**——起一个真实的本地 SSE 服务（标准 MCP SSE 流程：
  ``GET /sse`` → ``event: endpoint`` → ``POST /messages`` → 响应回到 SSE 流），
  验证 ``tools/list`` 与 ``tools/call`` 真的走通。
- **F-SCH-06**：MCP 配置**两级合并**（用户级 + 项目级，项目级覆盖同名）。
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _isolate_manager_config():
    """**还原进程级单例的配置状态**——否则临时配置会泄漏到其他用例。

    ``MCPManager`` 是单例；测试里用 monkeypatch 过的 ``user_config_path``
    调 ``load_config()`` 后，单例里仍留着那些配置（monkeypatch 撤销也没用）
    → 后续用例的 ``list_servers()`` 会多出 server。
    """
    from app.services.mcp_manager import get_mcp_manager

    mgr = get_mcp_manager()
    before_servers = dict(mgr._config_servers)
    before_errors = list(mgr._config_errors)
    try:
        yield
    finally:
        mgr._config_servers = before_servers
        mgr._config_errors = before_errors


# --------------------------------------------------------------------------- #
# 本地 SSE 模拟服务（标准 MCP SSE 协议）
# --------------------------------------------------------------------------- #
class _SseHandler(BaseHTTPRequestHandler):
    """最小标准 MCP SSE Server。

    - ``GET /sse`` → 保持连接，先发 ``event: endpoint``，之后按需发 ``event: message``；
    - ``POST /messages?session_id=…`` → 收下 JSON-RPC，把响应推回 SSE 流。
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: D102 - 静默
        pass

    def do_GET(self):  # noqa: N802
        if not self.path.startswith("/sse"):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        # 0) 注册 SSE 流的 writer（POST 时把响应推回这里）
        with self.server.lock:
            self.server.clients.append((self.wfile,))
        # 1) 下发 endpoint 事件
        self.wfile.write(b"event: endpoint\ndata: /messages?session_id=s1\n\n")
        self.wfile.flush()
        # 2) 保持连接，直到服务端关闭
        self.server.keep_open = True
        while getattr(self.server, "keep_open", True):
            time.sleep(0.05)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400)
            return
        method = payload.get("method")
        if method == "tools/list":
            result = {"tools": [{
                "name": "echo", "description": "回声",
                "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
            }]}
        elif method == "tools/call":
            args = (payload.get("params") or {}).get("arguments") or {}
            result = {"content": [{"type": "text", "text": f"echo:{args.get('text', '')}"}]}
        else:
            result = {}
        rid = payload.get("id")
        frame = (
            "event: message\n"
            f"data: {json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': result})}\n\n"
        ).encode("utf-8")
        with self.server.lock:
            for q in self.server.clients:
                try:
                    q[0].write(frame)
                    q[0].flush()
                except Exception:  # noqa: BLE001
                    pass
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _SseServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = threading.Lock()
        self.clients: list = []


@pytest.fixture()
def sse_server():
    """起一个本地标准 MCP SSE 服务。"""
    server = _SseServer(("127.0.0.1", 0), _SseHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.keep_open = False
        server.shutdown()


class TestMcpSseTransport:
    """F-SCH-05：SSE 走标准 MCP SSE 流程。"""

    def test_传输类型含sse(self, client):
        from app.services.chains.mcp.transport import TRANSPORTS

        assert "sse" in TRANSPORTS

    def test_sse_tools_list走标准流程(self, client, sse_server):
        """``tools/list`` 经 ``GET /sse`` → endpoint → POST → SSE 响应。"""
        from app.services.chains.mcp.transport import MCPConnection, MCPEndpoint

        endpoint = MCPEndpoint(name="sse-demo", transport="sse", url=f"{sse_server}/sse")
        conn = MCPConnection(endpoint, timeout=10)
        tools = conn.list_tools()
        assert tools, "SSE 未取到工具列表"
        assert tools[0]["name"] == "echo", tools

    def test_sse_tools_call走标准流程(self, client, sse_server):
        """``tools/call`` 的响应经 SSE 流返回。"""
        from app.services.chains.mcp.transport import MCPConnection, MCPEndpoint

        endpoint = MCPEndpoint(name="sse-demo", transport="sse", url=f"{sse_server}/sse")
        conn = MCPConnection(endpoint, timeout=10)
        out = conn.call_tool("echo", {"text": "hi"})
        assert "echo:hi" in out, out

    def test_sse不再误用http腿(self, client):
        """``sse`` **不得**走 http 腿（此前误用 → 真实 SSE Server 不响应）。"""
        src = (BACKEND_ROOT / "app" / "services" / "chains" / "mcp" / "transport.py").read_text(
            encoding="utf-8",
        )
        fetch = src.split("def _fetch_tools")[1].split("def ")[0]
        assert '"sse"' in fetch, "SSE 未在 _fetch_tools 中分派"
        assert "_sse_tools()" in fetch
        call = src.split("async def _call_async")[1].split("def ")[0]
        assert "_sse_call(" in call, "SSE 未在调用路径分派"


class TestMcpTwoLevelConfig:
    """F-SCH-06：用户级 + 项目级合并（项目级覆盖同名）。"""

    def _write(self, path: Path, servers: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"servers": servers}, ensure_ascii=False), encoding="utf-8")

    def test_项目级覆盖同名(self, client, tmp_path, monkeypatch):
        from app.services.chains.mcp import config as cfg

        user = tmp_path / "user" / "mcp.json"
        project = tmp_path / "ws" / ".agent" / "mcp.json"
        self._write(user, {"demo": {"transport": "stdio", "command": "user-cmd"}})
        self._write(project, {"demo": {"transport": "http", "url": "http://x/mcp"}})

        monkeypatch.setattr(cfg, "user_config_path", lambda: user)
        merged, errors = cfg.load_merged_servers(tmp_path / "ws")

        assert not errors, errors
        assert merged["demo"]["transport"] == "http", merged
        assert merged["demo"]["url"] == "http://x/mcp", merged

    def test_不同名都保留(self, client, tmp_path, monkeypatch):
        from app.services.chains.mcp import config as cfg

        user = tmp_path / "user" / "mcp.json"
        project = tmp_path / "ws" / ".agent" / "mcp.json"
        self._write(user, {"u1": {"transport": "stdio", "command": "c1"}})
        self._write(project, {"p1": {"transport": "stdio", "command": "c2"}})

        monkeypatch.setattr(cfg, "user_config_path", lambda: user)
        merged, errors = cfg.load_merged_servers(tmp_path / "ws")

        assert not errors, errors
        assert set(merged) == {"u1", "p1"}, merged

    def test_字段级合并(self, client, tmp_path, monkeypatch):
        """项目级未给出的字段沿用用户级。"""
        from app.services.chains.mcp import config as cfg

        user = tmp_path / "user" / "mcp.json"
        project = tmp_path / "ws" / ".agent" / "mcp.json"
        self._write(user, {
            "d1": {"transport": "stdio", "command": "c", "description": "用户级描述"},
        })
        self._write(project, {"d1": {"transport": "stdio", "command": "c"}})

        monkeypatch.setattr(cfg, "user_config_path", lambda: user)
        merged, errors = cfg.load_merged_servers(tmp_path / "ws")

        assert not errors, errors
        assert merged["d1"]["description"] == "用户级描述", merged

    def test_非法项被跳过并记录(self, client, tmp_path, monkeypatch):
        from app.services.chains.mcp import config as cfg

        user = tmp_path / "user" / "mcp.json"
        self._write(user, {
            "bad": {"transport": "carrier-pigeon"},
            "good": {"transport": "stdio", "command": "c"},
        })
        monkeypatch.setattr(cfg, "user_config_path", lambda: user)
        merged, errors = cfg.load_merged_servers(tmp_path / "ws")

        assert "bad" not in merged, merged
        assert any("bad" in e for e in errors), errors

    def test_端点返回合并结果(self, client, tmp_path, monkeypatch):
        from app.services.chains.mcp import config as cfg

        user = tmp_path / "user" / "mcp.json"
        self._write(user, {"api-demo": {"transport": "stdio", "command": "c"}})
        monkeypatch.setattr(cfg, "user_config_path", lambda: user)

        r = client.get("/api/v1/mcp_servers/config")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "api-demo" in data["servers"], data
        assert {s["level"] for s in data["sources"]} == {"user", "project"}

    def test_配置server出现在列表(self, client, tmp_path, monkeypatch):
        from app.services.chains.mcp import config as cfg

        user = tmp_path / "user" / "mcp.json"
        self._write(user, {"listed-demo": {"transport": "stdio", "command": "c"}})
        monkeypatch.setattr(cfg, "user_config_path", lambda: user)

        from app.services.mcp_manager import get_mcp_manager

        mgr = get_mcp_manager()
        mgr.load_config()
        names = {s["name"] for s in mgr.list_servers()}
        assert "listed-demo" in names, names
        item = next(s for s in mgr.list_servers() if s["name"] == "listed-demo")
        assert item["source"] == "config", item
        assert item["transport"] == "stdio", item
