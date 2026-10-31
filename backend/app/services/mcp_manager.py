"""MCPManager —— MCP Server 生命周期与工具调用管理。

设计说明：
- **工具列表（静态反射）**：复用 MCP 项目 ``app/main.py:_list_server_tools`` 的
  ``importlib.import_module`` 反射机制，无需启动子进程即可列出工具。
- **工具调用（按需子进程）**：采用 MCP 项目 ``llm_client.py:call_mcp_tool`` 同款
  "每次调用新建 stdio 会话" 的稳妥模式，避免跨事件循环持有 ClientSession 的坑。
- ``start/stop`` 语义为"启用/停用"注册（前端面板可见），实际子进程在调用时按需拉起。
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)



class _StdioSession:
    """一个**常驻**的 MCP stdio 会话（后台线程 + 独立事件循环）。

    **P2-01**：此前每次工具调用都 ``stdio_client(...)`` 新建会话 → 子进程反复
    启动（实测 N 次调用 = N 个子进程）。这里让同一 Server 复用**同一个**会话，
    子进程启动次数 ≤ 1。

    MCP 的 session 与 asyncio 事件循环绑定，因此每个会话自带一个后台线程与
    独立事件循环；同步调用通过 ``run_coroutine_threadsafe`` 投递过去。
    """

    def __init__(self, script: Path, timeout: float = 30.0) -> None:
        self.script = script
        self.timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._session: Any = None
        self._session_cm: Any = None
        self._stdio_cm: Any = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"mcp-stdio-{script.stem}",
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            self.close()
            raise TimeoutError(f"MCP Server 启动超时: {script}")
        if self._error is not None:
            err = self._error
            self.close()
            raise RuntimeError(f"MCP Server 启动失败: {script}: {err}")

    # -- 后台线程 ------------------------------------------------------- #
    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._boot())
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
            self._ready.set()
            return
        self._loop.run_forever()

    async def _boot(self) -> None:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=sys.executable, args=[str(self.script)], env=None,
        )
        self._stdio_cm = stdio_client(params)
        read, write = await self._stdio_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        self._ready.set()

    # -- 调用 ----------------------------------------------------------- #
    async def _call_tool(self, tool: str, arguments: dict) -> Any:
        return await self._session.call_tool(tool, arguments)

    async def _list_tools(self) -> list[dict]:
        result = await self._session.list_tools()
        return [_tool_to_dict(t) for t in getattr(result, "tools", []) or []]

    def call_tool(self, tool: str, arguments: dict, timeout: float | None = None) -> str:
        fut = asyncio.run_coroutine_threadsafe(
            self._call_tool(tool, arguments), self._loop,
        )
        result = fut.result(timeout or self.timeout)
        if getattr(result, "content", None):
            first = result.content[0]
            return first.text if getattr(first, "type", "") == "text" else str(first)
        return "工具调用成功但无返回内容"

    def list_tools(self, timeout: float | None = None) -> list[dict]:
        fut = asyncio.run_coroutine_threadsafe(self._list_tools(), self._loop)
        return fut.result(timeout or self.timeout)

    # -- 回收 ------------------------------------------------------------ #
    def close(self) -> None:
        if self._loop.is_closed():
            return

        async def _cleanup() -> None:
            try:
                if self._session_cm is not None:
                    await self._session_cm.__aexit__(None, None, None)
                if self._stdio_cm is not None:
                    await self._stdio_cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 - 回收失败不阻断
                pass

        try:
            asyncio.run_coroutine_threadsafe(_cleanup(), self._loop).result(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:  # noqa: BLE001
            pass
        self._thread.join(timeout=5)
        try:
            if not self._loop.is_closed():
                self._loop.close()
        except Exception:  # noqa: BLE001
            pass


def _tool_to_dict(tool: Any) -> dict:
    """MCP SDK 的 Tool 对象 → dict。"""
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
    return {
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", "") or "",
        "input_schema": schema,
    }

def _utc_now_iso() -> str:
    """当前 UTC 时间（ISO 字符串）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class MCPManager:
    """管理 app/mcp/servers/ 下的 MCP Server。"""

    SERVER_REGISTRY: dict[str, dict[str, str]] = {
        "weather": {
            "module": "app.mcp.servers.weather_server",
            "script": "weather_server.py",
            "stage": "阶段1",
            "description": "天气 MCP Server（美国 NWS API，无需 Key）",
            "read_only": "true",
        },
        "search": {
            "module": "app.mcp.servers.search_server",
            "script": "search_server.py",
            "stage": "阶段2",
            "description": "搜索 MCP Server（Serper.dev，需 SERPER_API_KEY）",
            "read_only": "true",
        },
        "xiaohongshu": {
            "module": "app.mcp.servers.xiaohongshu_server",
            "script": "xiaohongshu_server.py",
            "stage": "阶段3",
            "description": "小红书 MCP Server（Playwright 浏览器自动化）",
            "read_only": "false",
        },
    }

    def __init__(self) -> None:
        self._enabled: set[str] = set()
        self._tools_cache: dict[str, list[dict]] = {}
        # P4-11：**真实连接状态**（此前只有 ready/disabled 两态，依 ``_enabled`` 集合，
        # 与实际连接无关）——记录每个 Server 的连接状态与可读失败原因。
        self._conn_status: dict[str, dict] = {}
        # F-SCH-06：**两级配置**（用户级 ~/.agent/mcp.json + 项目级 <ws>/.agent/mcp.json）
        self._config_servers: dict[str, dict] = {}
        self._config_errors: list[str] = []
        # 启动时加载**用户级**配置（项目级需要 workspace_root，启动时未知 →
        # 由 ``load_config(workspace_root)`` 或 ``GET /mcp_servers/config`` 补齐）。
        self.load_config()
        # P2-01：常驻 stdio 会话池（server name → 会话）
        self._sessions: dict[str, "_StdioSession"] = {}
        self._sessions_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # 定位（单源：模块路径与脚本路径都在注册表里）
    # ------------------------------------------------------------------ #
    def server_script_path(self, name: str) -> Path:
        """MCP Server 脚本的绝对路径（取自注册表 ``script`` 字段）。"""
        self._check_name(name)
        info = self.SERVER_REGISTRY[name]
        filename = info.get("script")
        if not filename:
            raise ValueError(f"MCP Server 未在注册表声明脚本路径: {name}")
        return settings.mcp_servers_dir / filename

    def is_read_only(self, name: str) -> bool:
        """对话模式（Ask）下是否允许使用该 Server 的工具。"""
        info = self.SERVER_REGISTRY.get(name)
        return bool(info) and info.get("read_only", "false") == "true"

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def list_servers(self) -> list[dict]:
        """列出 MCP Server（含**真实连接状态**与可读原因，P4-11）。

        **F-SCH-06**：追加**配置来源**的 server（内置注册表 + 两级配置）。
        """
        out: list[dict] = []
        registry = dict(self.SERVER_REGISTRY)
        for name, spec in self._config_servers.items():
            if name in registry:
                continue
            registry[name] = {
                "stage": "配置",
                "description": spec.get("description") or f"{name}（来自配置文件）",
                "read_only": "true" if spec.get("read_only") else "false",
                "transport": spec.get("transport", "stdio"),
            }
        for name, info in registry.items():
            conn = self._conn_status.get(name, {})
            if name not in self._enabled:
                status, reason = "disabled", "未启用"
            elif conn.get("state") == "connected":
                status, reason = "connected", conn.get("reason") or "连接正常"
            elif conn.get("state") == "error":
                status, reason = "error", conn.get("reason") or "连接失败"
            else:
                # 启用但尚未建立连接 → 未连接（而不是「ready」这种含糊说法）
                status, reason = "disconnected", "尚未建立连接"
            out.append({
                "name": name,
                "stage": info["stage"],
                "description": info["description"],
                "status": status,
                "reason": reason,
                "read_only": info.get("read_only", "false") == "true",
                "last_ok_at": conn.get("last_ok_at"),
                # F-SCH-06：传输类型与来源（内置 / 配置）
                "transport": info.get("transport")
                or self._config_servers.get(name, {}).get("transport")
                or "stdio",
                "source": "config" if name in self._config_servers else "builtin",
            })
        return out

    def _mark_conn(self, name: str, *, ok: bool, reason: str = "") -> None:
        """记录一次连接结果（P4-11）。"""
        prev = self._conn_status.get(name, {})
        self._conn_status[name] = {
            "state": "connected" if ok else "error",
            "reason": reason or ("连接正常" if ok else "连接失败"),
            "last_ok_at": prev.get("last_ok_at") if not ok else _utc_now_iso(),
        }

    @property
    def enabled_servers(self) -> list[str]:
        return sorted(self._enabled)

    # ------------------------------------------------------------------ #
    # 启停（注册语义）
    # ------------------------------------------------------------------ #
    def start(self, name: str) -> dict:
        self._check_name(name)
        self._enabled.add(name)
        tools = self.list_tools(name)
        return {"name": name, "status": "started", "tools": len(tools)}

    def stop(self, name: str) -> dict:
        self._check_name(name)
        self._enabled.discard(name)
        return {"name": name, "status": "stopped"}

    # ------------------------------------------------------------------ #
    # 两级配置（F-SCH-06）
    # ------------------------------------------------------------------ #
    def load_config(self, workspace_root: str | None = None) -> dict[str, dict]:
        """加载并合并**两级** MCP 配置（项目级覆盖用户级）。

        配置里的 server **不覆盖**内置注册表，而是**追加**（内置始终可用）。
        """
        from app.services.chains.mcp.config import load_merged_servers

        merged, errors = load_merged_servers(workspace_root)
        self._config_servers = merged
        self._config_errors = errors
        for err in errors:
            logger.warning("MCP 配置错误: %s", err)
        return merged

    def config_servers(self) -> dict[str, dict]:
        """当前生效的配置来源 server（项目级已合并进用户级）。"""
        return dict(self._config_servers)

    def config_errors(self) -> list[str]:
        """配置文件的错误列表（非法项被跳过并记录）。"""
        return list(self._config_errors)

    def is_configured(self, name: str) -> bool:
        """该 server 是否来自**配置文件**（而非内置注册表）。"""
        return name in self._config_servers

    def _known_servers(self) -> list[str]:
        return sorted(set(self.SERVER_REGISTRY) | set(self._config_servers))

    def _check_name(self, name: str) -> None:
        if name not in self.SERVER_REGISTRY and name not in self._config_servers:
            raise KeyError(
                f"未知 MCP Server: {name}（可选: {self._known_servers()}）",
            )

    # ------------------------------------------------------------------ #
    # 工具列表（静态反射，无需启动子进程）
    # ------------------------------------------------------------------ #
    async def _list_tools_async(self, name: str) -> list[dict]:
        module = importlib.import_module(self.SERVER_REGISTRY[name]["module"])
        mcp = module.mcp
        # 兼容 fastmcp 2.x（get_tools）与 mcp 1.x SDK 内置 FastMCP（list_tools）
        if hasattr(mcp, "get_tools"):
            tools = list((await mcp.get_tools()).values())
        else:
            tools = await mcp.list_tools()
        return [
            {
                "name": getattr(t, "name", str(t)),
                "description": (getattr(t, "description", "") or "").strip().split("\n")[0],
            }
            for t in tools
        ]

    def list_tools(self, name: str, use_cache: bool = True) -> list[dict]:
        """同步获取工具列表（静态反射，结果缓存）。

        **修复**：此前只支持**注册表** server → 配置来源的 server 调用即 KeyError
        （``SERVER_REGISTRY[name]`` 越界）。现在按来源分派。
        """
        self._check_name(name)
        if use_cache and name in self._tools_cache:
            return self._tools_cache[name]
        if self.is_configured(name):
            # 配置来源：走**传输层**（stdio / sse / http）
            from app.services.chains.mcp.transport import MCPConnection, MCPEndpoint

            spec = self._config_servers[name]
            endpoint = MCPEndpoint(
                name=name,
                transport=spec.get("transport", "stdio"),
                command=spec.get("command", ""),
                args=spec.get("args") or [],
                env=spec.get("env") or {},
                url=spec.get("url"),
                headers=spec.get("headers") or {},
            )
            conn = MCPConnection(endpoint, timeout=settings.mcp_call_timeout)
            tools = conn.list_tools()
        else:
            tools = asyncio.run(self._list_tools_async(name))
        self._tools_cache[name] = tools
        return tools

    def list_tools_with_schema(self, name: str) -> list[dict]:
        """列出工具（含 inputSchema，供 Agent 动态注入）。"""
        self._check_name(name)

        async def _fetch() -> list[dict]:
            # F-SCH-06：配置来源的 server 走**传输层**（stdio / sse / http）
            if self.is_configured(name):
                from app.services.chains.mcp.transport import MCPConnection, MCPEndpoint

                spec = self._config_servers[name]
                endpoint = MCPEndpoint(
                    name=name,
                    transport=spec.get("transport", "stdio"),
                    command=spec.get("command", ""),
                    args=spec.get("args") or [],
                    env=spec.get("env") or {},
                    url=spec.get("url"),
                    headers=spec.get("headers") or {},
                )
                conn = MCPConnection(endpoint, timeout=settings.mcp_call_timeout)
                tools = await asyncio.get_running_loop().run_in_executor(
                    None, conn.list_tools,
                )
                return [
                    {
                        "name": str(t.get("name") or ""),
                        "description": str(t.get("description") or ""),
                        "inputSchema": t.get("inputSchema")
                        or t.get("input_schema")
                        or {"type": "object", "properties": {}},
                    }
                    for t in tools
                ]
            module = importlib.import_module(self.SERVER_REGISTRY[name]["module"])
            mcp = module.mcp
            if hasattr(mcp, "get_tools"):
                tools = list((await mcp.get_tools()).values())
            else:
                tools = await mcp.list_tools()
            return [
                {
                    "name": getattr(t, "name", str(t)),
                    "description": (getattr(t, "description", "") or "").strip(),
                    "inputSchema": getattr(t, "inputSchema", None) or {"type": "object", "properties": {}},
                }
                for t in tools
            ]

        return asyncio.run(_fetch())

    # ------------------------------------------------------------------ #
    # 工具调用（每次调用新建 stdio 会话，稳妥模式）
    # ------------------------------------------------------------------ #
    def _session_for(self, name: str) -> "_StdioSession":
        """取（或建）某 Server 的**常驻** stdio 会话。

        **P2-01**：连续调用同一 Server 时复用同一个会话 → 子进程只启动一次。
        """
        with self._sessions_lock:
            session = self._sessions.get(name)
            if session is not None:
                return session
        script = self.server_script_path(name)
        if not script.is_file():
            raise FileNotFoundError(f"MCP Server 脚本不存在: {script}")
        session = _StdioSession(script, timeout=settings.mcp_call_timeout)
        with self._sessions_lock:
            existing = self._sessions.get(name)
            if existing is not None:
                session.close()
                return existing
            self._sessions[name] = session
        return session

    def pool_size(self) -> int:
        """当前**常驻** MCP 连接数（``/metrics`` 的 ``mcp_connections``）。"""
        with self._sessions_lock:
            return len(self._sessions)

    def close_all_sessions(self) -> None:
        """回收全部常驻会话（shutdown 时调用 → 无僵尸进程）。"""
        with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass

    async def _call_tool_async(self, name: str, tool: str, arguments: dict) -> str:
        # F-SCH-06：配置来源的 server 走**传输层**
        if self.is_configured(name):
            from app.services.chains.mcp.transport import MCPConnection, MCPEndpoint

            spec = self._config_servers[name]
            endpoint = MCPEndpoint(
                name=name,
                transport=spec.get("transport", "stdio"),
                command=spec.get("command", ""),
                args=spec.get("args") or [],
                env=spec.get("env") or {},
                url=spec.get("url"),
                headers=spec.get("headers") or {},
            )
            conn = MCPConnection(endpoint, timeout=settings.mcp_call_timeout)
            return await asyncio.get_running_loop().run_in_executor(
                None, lambda: conn.call_tool(tool, arguments),
            )
        # 脚本路径由**注册表**给出（定位单源）；不再由 name 推导
        script = self.server_script_path(name)
        if not script.is_file():
            raise FileNotFoundError(f"MCP Server 脚本不存在: {script}")

        # P2-01：复用常驻会话（不再每次新建 stdio 会话）
        session = self._session_for(name)
        return await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: session.call_tool(tool, arguments, settings.mcp_call_timeout),
        )

    def call_tool(self, name: str, tool: str, arguments: dict) -> str:
        """同步调用 MCP 工具（内部用 asyncio.run 新建事件循环）。"""
        self._check_name(name)
        try:
            out = asyncio.run(self._call_tool_async(name, tool, arguments))
            self._mark_conn(name, ok=True)
            return out
        except asyncio.TimeoutError:
            self._mark_conn(name, ok=False, reason=f"调用超时（{settings.mcp_call_timeout}s）")
            return f"MCP 工具调用超时（{settings.mcp_call_timeout}s）: {name}/{tool}"
        except Exception as exc:  # noqa: BLE001 - 工具错误应数据化返回给 LLM
            logger.exception("MCP 工具调用失败: %s/%s", name, tool)
            self._mark_conn(name, ok=False, reason=f"{type(exc).__name__}: {exc}")
            return f"MCP 工具调用失败: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------- #
# 进程级单例（P2-01）
# ---------------------------------------------------------------------- #
_manager: MCPManager | None = None
_manager_lock = threading.Lock()


def get_mcp_manager() -> MCPManager:
    """进程级 MCP 管理器单例。

    **P2-01**：常驻 stdio 会话池必须**全局唯一**——否则 ``/metrics`` 的
    ``mcp_connections`` 会漏计，且 shutdown 时无法一次回收全部会话。
    """
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = MCPManager()
    return _manager
