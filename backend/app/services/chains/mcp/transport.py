"""MCP 传输层（S7 / WP-7.6）。

三种传输：**STDIO**（子进程）/ **SSE** / **HTTP**。

约定：
- 连接**复用**：``MCPConnection`` 常驻，调用不再每次新建（现状的
  ``call_tool`` 每次 ``asyncio.run`` 新建会话）；
- 超时与降级：超时返回可读错误给模型（区分"业务失败"与"系统故障"）；
- STDIO 子进程在应用退出时优雅回收（无孤儿进程）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TRANSPORTS = ("stdio", "sse", "http")

#: 进程级的会话缓存：``(server_name, transport, endpoint)`` → 连接
_connection_pool: dict[tuple[str, str, str], "MCPConnection"] = {}
_pool_lock = threading.Lock()

#: 已拉起的 STDIO 子进程（应用退出时回收）
#: **W0-10**：键改为**完整 endpoint key**（含 env 签名），此前只用 ``key[0]``（name）→
#: 改了 env 之后会复用旧子进程，新环境变量不生效。
_stdio_procs: dict[tuple[str, str, str], subprocess.Popen] = {}
_stdio_lock = threading.Lock()

#: **SSE 会话缓存**（F-SCH-05）：``(name, transport, endpoint)`` → ``SseSession``
_sse_sessions: dict[tuple[str, str, str], object] = {}

#: HTTP JSON-RPC 的请求 id 计数器（MCP 要求请求-响应 id 配对）
_rpc_id = 0
_rpc_id_lock = threading.Lock()


def _next_rpc_id() -> int:
    """下一个 JSON-RPC 请求 id（**不能恒为 1**——否则并发响应无法配对）。"""
    global _rpc_id
    with _rpc_id_lock:
        _rpc_id += 1
        return _rpc_id


class MCPError(RuntimeError):
    """MCP 调用失败（区分业务失败与系统故障）。"""

    def __init__(self, message: str, *, system: bool = False) -> None:
        super().__init__(message)
        self.system = system  # True = 系统故障（超时/连接断）；False = 业务失败（工具报错）


@dataclass
class MCPEndpoint:
    """一个 MCP Server 的连接描述。"""

    name: str
    transport: str              # stdio | sse | http
    # stdio:
    command: str = ""
    args: list[str] | None = None
    #: **stdio 子进程的环境变量覆盖**（W0-10 / AUD-C04）。
    #: 此前本字段**不存在**，而 ``mcp_manager`` 三处构造时都传 ``env=...``
    #: → ``TypeError: __init__() got an unexpected keyword argument 'env'``
    #: → **任何配置来源的 MCP Server 一调用就崩**（``~/.agent/mcp.json`` 的 server 全部不可用）。
    env: dict | None = None
    # sse / http:
    url: str = ""
    headers: dict | None = None

    def key(self) -> tuple[str, str, str]:
        """连接缓存键。

        **W0-10**：``env`` 必须参与 key —— 否则改了 env 之后会**复用旧连接**，
        新环境变量不生效。
        """
        target = self.url or f"{self.command} {' '.join(self.args or [])}"
        if self.env:
            env_sig = ",".join(f"{k}={v}" for k, v in sorted(self.env.items()))
            target = f"{target}#{env_sig}"
        return (self.name, self.transport, target)


class MCPConnection:
    """一个到 MCP Server 的**常驻连接**（调用复用同一会话）。"""

    def __init__(self, endpoint: MCPEndpoint, timeout: float = 30.0) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._lock = threading.Lock()
        self._tools: list[dict] | None = None
        self._proc: subprocess.Popen | None = None

    @property
    def alive(self) -> bool:
        """连接是否仍可用。"""
        if self.endpoint.transport == "stdio":
            return self._proc is not None and self._proc.poll() is None
        return True

    def list_tools(self, *, force: bool = False) -> list[dict]:
        """列出工具（结果缓存，``force`` 强制重连）。"""
        if self._tools is not None and not force:
            return self._tools
        tools = self._fetch_tools()
        self._tools = tools
        return tools

    def call_tool(self, tool: str, arguments: dict) -> str:
        """调用工具（复用同一会话）。"""
        try:
            return asyncio.run(self._call_async(tool, arguments))
        except MCPError:
            raise
        except TimeoutError as exc:
            raise MCPError(f"调用超时（{self.timeout:.0f}s）: {tool}", system=True) from exc
        except Exception as exc:  # noqa: BLE001
            raise MCPError(f"系统故障: {type(exc).__name__}: {exc}", system=True) from exc

    # ------------------------------------------------------------------ #
    # 传输实现
    # ------------------------------------------------------------------ #
    def _fetch_tools(self) -> list[dict]:
        if self.endpoint.transport == "stdio":
            return self._stdio_tools()
        if self.endpoint.transport == "sse":
            # F-SCH-05：SSE 走**标准 MCP SSE 流程**（此前误用 http 腿）
            return self._sse_tools()
        return self._http_tools()

    async def _call_async(self, tool: str, arguments: dict) -> str:
        if self.endpoint.transport == "stdio":
            return self._stdio_call(tool, arguments)
        if self.endpoint.transport == "sse":
            return self._sse_call(tool, arguments)
        return self._http_call(tool, arguments)

    # --- STDIO --- #
    def _stdio_read_line(self, proc: subprocess.Popen) -> bytes:
        """从子进程 stdout 读一行（**带超时**）。

        **AUD2-H30 / AUD-H19**：此前是裸 ``proc.stdout.readline()`` ——
        没有超时 → 服务器不响应时**永久阻塞**，``MCPConnection.timeout`` 对 stdio 完全无效。
        POSIX 下用 ``select`` 实现；Windows 的管道不支持 ``select``，退化为阻塞读。
        """
        stream = proc.stdout
        if stream is None:  # pragma: no cover - 理论上不会发生
            raise MCPError("子进程 stdout 不可用", system=True)
        if os.name == "posix":
            import select

            ready, _, _ = select.select([stream], [], [], self.timeout)
            if not ready:
                raise MCPError(f"读取超时（{self.timeout:.0f}s）", system=True)
        line = stream.readline()
        if not line:
            raise MCPError("子进程已退出或返回空响应", system=True)
        return line

    def _stdio_rpc(self, method: str, params: dict, *, expect_response: bool = True) -> dict:
        """发一条 JSON-RPC 请求并读回响应。

        **AUD2-H30 / AUD-H19 修复**：
        - 请求 id 用 ``_next_rpc_id()``（此前**硬编码 1** → 并发响应无法配对）；
        - 响应解析包 try/except（此前畸形行直接抛未捕获的 ``JSONDecodeError``）。
        """
        proc = self._stdio_proc()
        payload = {
            "jsonrpc": "2.0",
            "id": _next_rpc_id(),
            "method": method,
            "params": params,
        }
        try:
            proc.stdin.write(json.dumps(payload).encode() + b"\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
        except (BrokenPipeError, OSError) as exc:
            raise MCPError(f"子进程通信失败: {exc}", system=True) from exc
        if not expect_response:
            return {}
        line = self._stdio_read_line(proc)
        try:
            data = json.loads(line.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MCPError(f"响应不是合法 JSON: {line[:200]!r}", system=True) from exc
        if not isinstance(data, dict):
            raise MCPError(f"响应格式异常: {type(data).__name__}", system=True)
        if "error" in data:
            err = data.get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise MCPError(str(msg or "MCP 调用失败"))
        return data.get("result") or {}

    def _stdio_handshake(self) -> None:
        """MCP ``initialize`` 握手（**尽力而为**，失败不阻断）。

        **AUD2-H30**：真实 MCP Server 要求先握手；此前直接发 ``tools/list``
        → 严格实现的服务端会拒绝。握手失败时**降级**为直接发业务请求，
        以兼容不强制握手的轻量实现。
        """
        try:
            self._stdio_rpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "agent-platform", "version": "1.1.0"},
                },
            )
            self._stdio_rpc("notifications/initialized", {}, expect_response=False)
        except MCPError:
            logger.debug("MCP initialize 握手失败，降级为直接发送业务请求")

    def _stdio_tools(self) -> list[dict]:
        """列出工具（line-delimited JSON-RPC over stdio）。"""
        self._stdio_handshake()
        result = self._stdio_rpc("tools/list", {})
        tools = result.get("tools") or []
        return [
            {
                "name": str(t.get("name") or ""),
                "description": str(t.get("description", "")),
                # 同时保留两种键名：MCP 原生用 inputSchema，本仓内部用 input_schema
                "inputSchema": t.get("inputSchema") or t.get("input_schema") or {},
                "input_schema": t.get("inputSchema") or t.get("input_schema") or {},
            }
            for t in tools
            if isinstance(t, dict)
        ]

    def _stdio_call(self, tool: str, arguments: dict) -> str:
        self._stdio_handshake()
        result = self._stdio_rpc(
            "tools/call", {"name": tool, "arguments": arguments},
        )
        for item in result.get("content", []) or []:
            if isinstance(item, dict) and item.get("type") == "text":
                return str(item.get("text", ""))
        return json.dumps(result, ensure_ascii=False)

    def _stdio_proc(self) -> subprocess.Popen:
        key = self.endpoint.key()
        with _stdio_lock:
            proc = _stdio_procs.get(key)
            if proc is not None and proc.poll() is None:
                return proc
            cmd = [self.endpoint.command] + list(self.endpoint.args or [])
            # **W0-10**：把 endpoint.env 叠加到子进程环境（此前 env 字段不存在，
            # 配置里的环境变量既无法传入也无法参与连接 key）。
            child_env = None
            if self.endpoint.env:
                child_env = {**os.environ, **self.endpoint.env}
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=child_env,
            )
            _stdio_procs[key] = proc
            self._proc = proc
            return proc

    # --- SSE / HTTP --- #
    # --- SSE ---------------------------------------------------------- #
    def _sse_session(self):
        """取（或建立）本端点的 SSE 会话（**按端点缓存**，避免每次调用重连）。"""
        from ._sse_leg import SseSession

        key = self.endpoint.key()
        with _stdio_lock:
            session = _sse_sessions.get(key)
            if session is not None:
                return session
            session = SseSession(self.endpoint, timeout=self.timeout)
            _sse_sessions[key] = session
            return session

    def _sse_tools(self) -> list[dict]:
        """SSE 腿：``tools/list``。"""
        result = self._sse_session().request("tools/list", {})
        tools = (result or {}).get("tools") or []
        return [
            {
                "name": str(t.get("name") or ""),
                "description": str(t.get("description") or ""),
                "input_schema": t.get("inputSchema") or t.get("input_schema") or {},
            }
            for t in tools
            if isinstance(t, dict)
        ]

    def _sse_call(self, tool: str, arguments: dict) -> str:
        """SSE 腿：``tools/call``。"""
        result = self._sse_session().request(
            "tools/call", {"name": tool, "arguments": arguments},
        )
        content = result.get("content") or []
        if content:
            first = content[0]
            if isinstance(first, dict):
                return str(first.get("text") or first.get("data") or first)
            return str(first)
        return str(result.get("text") or result)

    def _http_tools(self) -> list[dict]:
        """按 **MCP 协议**取工具列表（``tools/list``）。

        **P2-01**：此前是自造 REST（``GET {url}/tools``）——不是 MCP 协议，
        真实 MCP Server 不会响应。现改为 **JSON-RPC over HTTP**。
        """
        result = self._http_rpc("tools/list", {})
        tools = (result or {}).get("tools") or []
        return [
            {
                "name": str(t.get("name") or ""),
                "description": str(t.get("description") or ""),
                "input_schema": t.get("inputSchema") or t.get("input_schema") or {},
            }
            for t in tools
        ]

    def _http_rpc(self, method: str, params: dict) -> dict:
        """一次 MCP JSON-RPC 调用（HTTP POST 到端点根路径）。"""
        import json as _json
        import urllib.request

        url = self.endpoint.url.rstrip("/")
        body = _json.dumps({
            "jsonrpc": "2.0",
            "id": _next_rpc_id(),
            "method": method,
            "params": params,
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(self.endpoint.headers or {}),
        }
        req = urllib.request.Request(url, data=body, headers=headers)
        with _opener_for(url).open(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8")
        # Streamable HTTP 可能返回 SSE 帧
        if raw.lstrip().startswith("event:") or raw.lstrip().startswith("data:"):
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    break
        data = _json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise MCPError(f"MCP 调用失败（{method}）: {msg}", system=True)
        return (data or {}).get("result") or {}

    def _http_call(self, tool: str, arguments: dict) -> str:
        import json as _json
        import urllib.request
        from urllib.error import HTTPError, URLError

        try:
            result = self._http_rpc("tools/call", {"name": tool, "arguments": arguments})
            content = result.get("content") or []
            if content:
                first = content[0]
                if isinstance(first, dict):
                    return str(first.get("text") or first.get("data") or first)
                return str(first)
            return str(result.get("text") or result)
        except HTTPError as exc:
            if 400 <= exc.status < 500:
                raise MCPError(f"业务失败（HTTP {exc.status}）: {tool}") from exc
            raise MCPError(f"系统故障（HTTP {exc.status}）: {tool}", system=True) from exc
        except URLError as exc:
            raise MCPError(f"连接失败: {exc.reason}", system=True) from exc
        except TimeoutError as exc:
            # 连接建立后读响应超时：与"连不上"要区分开，
            # 否则排障时会误判为"服务没起来"。
            raise MCPError(f"连接已建立但读取超时（{self.timeout:.0f}s）: {tool}",
                           system=True) from exc

    # ------------------------------------------------------------------ #
    # 回收
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """关闭连接（STDIO 回收子进程）。"""
        with _stdio_lock:
            # **W0-10**：键已改为完整 endpoint key（含 env 签名），不再只是 name。
            proc = _stdio_procs.pop(self.endpoint.key(), None)
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()
        self._proc = None


#: 回环地址（本地 MCP 服务器）——这些**不应**走系统代理
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _opener_for(url: str):
    """按目标地址构造 urllib opener。

    Why: ``urllib.request.urlopen`` 默认使用**全局 opener**，它会读系统代理设置
    （macOS 的系统代理、Windows 的 IE 代理、``http_proxy`` 环境变量）。
    本地 MCP 服务器（127.0.0.1 / localhost）被代理接管后会出现很误导的现象：
    **连接建立成功但代理不转发 → 读超时**，
    错误信息指向"服务无响应"，而真实原因是"请求根本没到本地服务"。
    远端地址仍尊重代理设置。
    """
    import urllib.parse
    import urllib.request

    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:  # pragma: no cover - 畸形 URL
        host = ""
    if host in _LOOPBACK_HOSTS or host.startswith("127."):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def get_connection(endpoint: MCPEndpoint) -> MCPConnection:
    """取（或建）一个常驻连接（复用）。"""
    key = endpoint.key()
    with _pool_lock:
        conn = _connection_pool.get(key)
        if conn is not None and conn.alive:
            return conn
        conn = MCPConnection(endpoint)
        _connection_pool[key] = conn
        return conn


def close_all() -> None:
    """应用退出时回收全部连接（无孤儿进程）。"""
    with _pool_lock:
        conns = list(_connection_pool.values())
        _connection_pool.clear()
    for conn in conns:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def pool_size() -> int:
    """当前**真实**的 MCP 连接数。

    **P2-01**：此前只统计 transport 自己的池（生产路径从不用它）→ ``/metrics`` 的
    ``mcp_connections`` **恒为 0**。现在合并统计：transport 池 + 常驻 stdio 会话池。
    """
    total = 0
    with _pool_lock:
        total += len(_connection_pool)
    try:
        from app.services.mcp_manager import get_mcp_manager

        total += get_mcp_manager().pool_size()
    except Exception:  # noqa: BLE001 - 指标统计不应失败
        pass
    return total
