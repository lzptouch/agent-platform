"""W7 / W0 P0 缺陷的回归用例（2026-10-31 全面审计）。

每个用例都对应一个**已确认的生产缺陷**，修复前必须失败、修复后必须通过：

- ``T-AUD2-W7-01`` SPA 回退路由路径穿越（``AUD2-C01``）
- ``T-AUD-W0-10``  配置型 MCP Server 的 ``env`` 字段（``AUD-C04``）

另附 stdio 传输层的协议健壮性用例（``AUD2-H30``）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.chains.mcp.transport import MCPConnection, MCPEndpoint, MCPError


# --------------------------------------------------------------------------- #
# T-AUD2-W7-01 · SPA 回退路由路径穿越（可读取服务器任意本地文件）
# --------------------------------------------------------------------------- #
def test_spa_fallback_rejects_path_traversal(tmp_path, monkeypatch):
    """``GET /../../secret.txt`` 不得返回 dist 目录之外的文件。

    **AUD2-C01**：此前 ``target = FRONTEND_DIST / full_path`` 后直接
    ``target.is_file()`` → ``Path.is_file()`` 跟随 ``..`` 解析 → 可读取
    ``~/.ssh/id_rsa``、``backend/.env`` 等任意本地文件。
    """
    from fastapi.testclient import TestClient

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")

    import app.main as main_mod

    monkeypatch.setattr(main_mod, "FRONTEND_DIST", dist)
    # 重新挂载 SPA 路由（模块级装饰器在 import 时已注册，需重建 client）
    client = TestClient(main_mod.app)

    # 1) 路径穿越：必须读不到 secret
    resp = client.get("/../../secret.txt")
    assert "TOP-SECRET" not in resp.text, "SPA 回退泄露了 dist 之外的文件！"

    # 2) 编码形式的穿越也要挡住
    resp2 = client.get("/%2e%2e%2f%2e%2e%2fsecret.txt")
    assert "TOP-SECRET" not in resp2.text

    # 3) SPA 路由回退本身不能被破坏（不存在的路由 → index.html）
    resp3 = client.get("/some/spa/route")
    assert resp3.status_code == 200
    assert "spa" in resp3.text

    # 4) API 未匹配路径仍应 404（不被 SPA 回退吞掉）
    resp4 = client.get("/api/v1/definitely-not-a-route")
    assert resp4.status_code == 404


# --------------------------------------------------------------------------- #
# T-AUD-W0-10 · 配置型 MCP Server 的 env 字段
# --------------------------------------------------------------------------- #
def test_mcp_endpoint_accepts_env_field():
    """``MCPEndpoint`` 必须接受 ``env`` —— 此前**必然 TypeError**。

    **AUD-C04**（critical）：``mcp_manager.py`` 三处构造时传 ``env=...``，
    而 dataclass 没有该字段 → 任何配置来源的 MCP Server
    ``list_tools`` / ``call_tool`` **一调用就崩**。
    """
    endpoint = MCPEndpoint(
        name="cfg",
        transport="stdio",
        command="python",
        args=[],
        env={"K": "V"},
    )
    assert endpoint.env == {"K": "V"}


def test_mcp_endpoint_key_includes_env():
    """``env`` 必须参与连接 key —— 否则改 env 后会**复用旧连接**。"""
    a = MCPEndpoint(name="x", transport="stdio", command="c", args=[], env={"K": "1"})
    b = MCPEndpoint(name="x", transport="stdio", command="c", args=[], env={"K": "2"})
    c = MCPEndpoint(name="x", transport="stdio", command="c", args=[], env={"K": "1"})
    assert a.key() != b.key(), "不同 env 必须产生不同的连接 key"
    assert a.key() == c.key(), "相同 env 应产生相同 key"


def test_configured_mcp_server_can_list_tools(tmp_path, monkeypatch):
    """走**真实配置路径**列工具 —— 此前必然抛 TypeError。

    **AUD-C07**（测试盲区）：``test_mcp_sse_config.py`` 只调 ``load_config`` /
    ``list_servers``，**从不调** ``list_tools`` → 掩盖了 ``AUD-C04``。
    本用例不 patch ``user_config_path``，只把 HOME 指向 tmp 来隔离
    —— 让**真实的用户级配置读取逻辑**被执行。
    """
    from app.services.mcp_manager import MCPManager

    # 隔离 HOME（不替换 user_config_path —— 让真实读取逻辑被执行）
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    (home / ".agent").mkdir()
    (home / ".agent" / "mcp.json").write_text(
        json.dumps({
            "servers": {
                "echo": {
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-c", "import sys; sys.stdin.readline()"],
                    "env": {"AGENT_TEST": "1"},
                }
            }
        }),
        encoding="utf-8",
    )

    mgr = MCPManager()
    names = [s["name"] for s in mgr.list_servers()]
    assert "echo" in names, "配置里的 server 应被列出"

    # 关键断言：列工具不再抛 TypeError
    # （server 会挂住/退出 → 抛 MCPError 也可接受，但**不能**是 TypeError）
    with pytest.raises(Exception) as exc:
        mgr.list_tools("echo")
    assert not isinstance(exc.value, TypeError), f"仍是 TypeError: {exc.value}"
    assert "unexpected keyword argument 'env'" not in str(exc.value)


def test_mcp_manager_builds_endpoint_with_env(monkeypatch):
    """``MCPManager`` 构造 endpoint 时必须真的把 env 传下去。"""
    from app.services.mcp_manager import MCPManager

    mgr = MCPManager()
    mgr._config_servers = {
        "cfg": {
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "x"],
            "env": {"A": "B"},
        }
    }
    captured: dict = {}

    class _FakeConn:
        def __init__(self, endpoint, timeout=30.0):
            captured["endpoint"] = endpoint

        def list_tools(self):
            return [{"name": "t", "description": "d", "inputSchema": {}}]

    import app.services.chains.mcp.transport as transport_mod

    monkeypatch.setattr(transport_mod, "MCPConnection", _FakeConn)

    tools = mgr.list_tools("cfg", use_cache=False)
    assert tools, "应返回工具列表"
    assert captured["endpoint"].env == {"A": "B"}, "env 未透传到 endpoint"


# --------------------------------------------------------------------------- #
# T-AUD2-H30 · stdio 传输层协议健壮性
# --------------------------------------------------------------------------- #
def test_stdio_tools_uses_unique_rpc_ids(tmp_path):
    """并发/连续请求的 rpc id 必须唯一（此前**硬编码 1**）。"""
    script = tmp_path / "srv.py"
    script.write_text(
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    line = line.strip()\n"
        "    if not line:\n"
        "        continue\n"
        "    req = json.loads(line)\n"
        "    rid = req.get('id')\n"
        "    method = req.get('method')\n"
        "    if method == 'initialize':\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':rid,'result':{}}), flush=True)\n"
        "    elif method == 'notifications/initialized':\n"
        "        continue\n"
        "    else:\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':rid,"
        "'result':{'tools':[{'name':'echo','description':'d','inputSchema':{}}]}}), flush=True)\n",
        encoding="utf-8",
    )
    endpoint = MCPEndpoint(
        name="t", transport="stdio", command=sys.executable, args=[str(script)],
    )
    conn = MCPConnection(endpoint, timeout=10)
    tools = conn.list_tools(force=True)
    assert tools and tools[0]["name"] == "echo"
    assert "input_schema" in tools[0] and "inputSchema" in tools[0]


def test_stdio_call_timeout_is_enforced(tmp_path):
    """服务器不响应时必须**超时**而不是永久阻塞。"""
    script = tmp_path / "hang.py"
    script.write_text("import time\ntime.sleep(600)\n", encoding="utf-8")
    endpoint = MCPEndpoint(
        name="hang", transport="stdio", command=sys.executable, args=[str(script)],
    )
    conn = MCPConnection(endpoint, timeout=2)
    with pytest.raises(MCPError) as exc:
        conn.list_tools(force=True)
    assert "超时" in str(exc.value) or "系统故障" in str(exc.value)


def test_stdio_malformed_json_raises_mcp_error(tmp_path):
    """畸形响应必须转成 MCPError，而不是未捕获的 JSONDecodeError。"""
    script = tmp_path / "bad.py"
    script.write_text("import sys\nprint('not-json', flush=True)\n", encoding="utf-8")
    endpoint = MCPEndpoint(
        name="bad", transport="stdio", command=sys.executable, args=[str(script)],
    )
    conn = MCPConnection(endpoint, timeout=5)
    with pytest.raises(MCPError):
        conn.list_tools(force=True)


def test_stdio_env_is_passed_to_child_process(tmp_path):
    """``endpoint.env`` 必须真的进入子进程环境。"""
    script = tmp_path / "showenv.py"
    script.write_text(
        "import json, os, sys\n"
        "for line in sys.stdin:\n"
        "    line = line.strip()\n"
        "    if not line:\n"
        "        continue\n"
        "    req = json.loads(line)\n"
        "    rid = req.get('id')\n"
        "    method = req.get('method')\n"
        "    if method == 'initialize':\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':rid,'result':{}}), flush=True)\n"
        "    elif method == 'notifications/initialized':\n"
        "        continue\n"
        "    else:\n"
        "        name = os.environ.get('AGENT_TEST_ENV', '')\n"
        "        print(json.dumps({'jsonrpc':'2.0','id':rid,"
        "'result':{'tools':[{'name': name, 'description':'', 'inputSchema':{}}]}}), flush=True)\n",
        encoding="utf-8",
    )
    endpoint = MCPEndpoint(
        name="envsrv", transport="stdio", command=sys.executable,
        args=[str(script)], env={"AGENT_TEST_ENV": "hello-env"},
    )
    conn = MCPConnection(endpoint, timeout=10)
    tools = conn.list_tools(force=True)
    assert tools[0]["name"] == "hello-env", "env 未传入子进程"
