"""F-SCH-05 · MCP **SSE 传输腿**（标准 MCP SSE 协议）。

此前 ``TRANSPORTS`` 声明了 ``("stdio", "sse", "http")``，但实现里
``sse`` **走的是 http 腿**（直接 POST 到根路径）——真实 MCP SSE Server
不会这样响应（它要求先 ``GET /sse`` 建立会话，拿到 ``endpoint`` 事件，
再把 JSON-RPC POST 到该 endpoint，响应回到 SSE 流上）。

标准流程：

1. ``GET {base}/sse``（``Accept: text/event-stream``）保持连接；
2. 服务器发 ``event: endpoint`` + ``data: /messages?session_id=xxx``；
3. 客户端把 JSON-RPC **POST** 到该 endpoint（服务器回 202）；
4. 真正的响应通过 SSE 流的 ``event: message`` 回来。

本模块实现这条流程：后台线程读 SSE 流，按 ``id`` 收集响应。
"""
from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request

from .transport import MCPEndpoint, MCPError


class SseSession:
    """一个已建立的 MCP SSE 会话（``GET /sse`` + 消息 endpoint）。"""

    def __init__(
        self,
        endpoint: MCPEndpoint,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._post_url: str | None = None
        self._ready = threading.Event()
        self._responses: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._reader, name="mcp-sse-reader", daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------ #
    # SSE 流读取
    # ------------------------------------------------------------------ #
    def _reader(self) -> None:
        """后台线程：读 SSE 流 → 解析 ``endpoint`` / ``message`` 事件。"""
        url = self._sse_url()
        req = urllib.request.Request(url, headers={
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
            **(self.endpoint.headers or {}),
        })
        event = ""
        data_lines: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=None) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").rstrip("\n")
                    if line == "":
                        # 空行 = 一个事件结束
                        if data_lines:
                            self._handle_event(event, "\n".join(data_lines))
                        event = ""
                        data_lines = []
                        continue
                    if line.startswith(":"):
                        continue  # 注释 / 心跳
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
        except Exception:  # noqa: BLE001 - 连接断开即结束（会话失效）
            pass
        finally:
            self._closed = True
            self._ready.set()
            with self._lock:
                waiting = list(self._responses.values())
                self._responses.clear()
            for q in waiting:
                q.put(None)

    def _handle_event(self, event: str, data: str) -> None:
        if event == "endpoint":
            base = self.endpoint.url.rstrip("/")
            self._post_url = urllib.parse.urljoin(base + "/", data.strip())
            self._ready.set()
            return
        if event in ("message", ""):
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                return
            rid = payload.get("id")
            if rid is None:
                return
            with self._lock:
                q = self._responses.get(int(rid))
            if q is not None:
                q.put(payload)

    # ------------------------------------------------------------------ #
    # 调用
    # ------------------------------------------------------------------ #
    def _sse_url(self) -> str:
        base = self.endpoint.url.rstrip("/")
        if base.endswith("/sse"):
            return base
        return base + "/sse"

    def request(self, method: str, params: dict) -> dict:
        """发一次 JSON-RPC 并等回响应。"""
        if not self._ready.wait(timeout=self.timeout):
            raise MCPError(f"SSE 会话建立超时（{self.timeout}s）: {method}", system=True)
        if self._post_url is None:
            raise MCPError("SSE 服务端未下发 endpoint 事件（不是标准 MCP SSE Server）", system=True)

        rpc_id = _next_id()
        body = json.dumps({
            "jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params,
        }).encode("utf-8")
        q: queue.Queue = queue.Queue(maxsize=1)
        with self._lock:
            self._responses[rpc_id] = q

        req = urllib.request.Request(
            self._post_url, data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                **(self.endpoint.headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            with self._lock:
                self._responses.pop(rpc_id, None)
            raise MCPError(f"SSE POST 失败（HTTP {exc.status}）: {method}", system=True) from exc
        except urllib.error.URLError as exc:
            with self._lock:
                self._responses.pop(rpc_id, None)
            raise MCPError(f"SSE 连接失败: {exc.reason}", system=True) from exc

        try:
            payload = q.get(timeout=self.timeout)
        except queue.Empty:
            with self._lock:
                self._responses.pop(rpc_id, None)
            raise MCPError(f"SSE 响应超时（{self.timeout}s）: {method}", system=True)
        finally:
            with self._lock:
                self._responses.pop(rpc_id, None)

        if payload is None:
            raise MCPError("SSE 连接已断开", system=True)
        if payload.get("error"):
            err = payload["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise MCPError(f"MCP 调用失败（{method}）: {msg}", system=True)
        return payload.get("result") or {}

    def close(self) -> None:
        self._closed = True
        self._ready.set()


_id_lock = threading.Lock()
_id_counter = 0


def _next_id() -> int:
    global _id_counter
    with _id_lock:
        _id_counter += 1
        return _id_counter
