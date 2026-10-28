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
_stdio_procs: dict[str, subprocess.Popen] = {}
_stdio_lock = threading.Lock()


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
    # sse / http:
    url: str = ""
    headers: dict | None = None

    def key(self) -> tuple[str, str, str]:
        return (self.name, self.transport, self.url or f"{self.command} {' '.join(self.args or [])}")


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
        return self._http_tools()

    async def _call_async(self, tool: str, arguments: dict) -> str:
        if self.endpoint.transport == "stdio":
            return self._stdio_call(tool, arguments)
        return self._http_call(tool, arguments)

    # --- STDIO --- #
    def _stdio_tools(self) -> list[dict]:
        proc = self._stdio_proc()
        # 列出工具：通过 stdio 发一个 line-delimited JSON 请求（简化实现）
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode() + b"\n"
        proc.stdin.write(payload)  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]
        line = proc.stdout.readline()  # type: ignore[union-attr]
        data = json.loads(line.decode())
        return data.get("result", {}).get("tools", [])

    def _stdio_call(self, tool: str, arguments: dict) -> str:
        proc = self._stdio_proc()
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }).encode() + b"\n"
        proc.stdin.write(payload)  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]
        line = proc.stdout.readline()  # type: ignore[union-attr]
        data = json.loads(line.decode())
        if "error" in data:
            raise MCPError(data["error"].get("message", "工具调用失败"))
        result = data.get("result", {})
        for item in result.get("content", []):
            if item.get("type") == "text":
                return item.get("text", "")
        return json.dumps(result, ensure_ascii=False)

    def _stdio_proc(self) -> subprocess.Popen:
        key = self.endpoint.key()
        with _stdio_lock:
            proc = _stdio_procs.get(key[0])
            if proc is not None and proc.poll() is None:
                return proc
            cmd = [self.endpoint.command] + list(self.endpoint.args or [])
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            _stdio_procs[key[0]] = proc
            self._proc = proc
            return proc

    # --- SSE / HTTP --- #
    def _http_tools(self) -> list[dict]:
        import json as _json
        import urllib.request

        url = f"{self.endpoint.url.rstrip('/')}/tools"
        req = urllib.request.Request(url, headers=self.endpoint.headers or {})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    def _http_call(self, tool: str, arguments: dict) -> str:
        import json as _json
        import urllib.request
        from urllib.error import HTTPError, URLError

        url = f"{self.endpoint.url.rstrip('/')}/call"
        body = _json.dumps({"tool": tool, "arguments": arguments}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json", **(self.endpoint.headers or {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
                return str(data.get("content", data.get("result", "")))
        except HTTPError as exc:
            if 400 <= exc.status < 500:
                raise MCPError(f"业务失败（HTTP {exc.status}）: {tool}") from exc
            raise MCPError(f"系统故障（HTTP {exc.status}）: {tool}", system=True) from exc
        except URLError as exc:
            raise MCPError(f"连接失败: {exc.reason}", system=True) from exc

    # ------------------------------------------------------------------ #
    # 回收
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """关闭连接（STDIO 回收子进程）。"""
        with _stdio_lock:
            proc = _stdio_procs.pop(self.endpoint.name, None)
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()
        self._proc = None


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
    with _pool_lock:
        return len(_connection_pool)
