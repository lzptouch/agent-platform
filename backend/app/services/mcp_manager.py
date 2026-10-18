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
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class MCPManager:
    """管理 app/mcp/servers/ 下的 MCP Server。"""

    SERVER_REGISTRY: dict[str, dict[str, str]] = {
        "weather": {
            "module": "app.mcp.servers.weather_server",
            "stage": "阶段1",
            "description": "天气 MCP Server（美国 NWS API，无需 Key）",
            "read_only": "true",
        },
        "search": {
            "module": "app.mcp.servers.search_server",
            "stage": "阶段2",
            "description": "搜索 MCP Server（Serper.dev，需 SERPER_API_KEY）",
            "read_only": "true",
        },
        "xiaohongshu": {
            "module": "app.mcp.servers.xiaohongshu_server",
            "stage": "阶段3",
            "description": "小红书 MCP Server（Playwright 浏览器自动化）",
            "read_only": "false",
        },
    }

    def __init__(self) -> None:
        self._enabled: set[str] = set()
        self._tools_cache: dict[str, list[dict]] = {}

    def is_read_only(self, name: str) -> bool:
        """对话模式（Ask）下是否允许使用该 Server 的工具。"""
        info = self.SERVER_REGISTRY.get(name)
        return bool(info) and info.get("read_only", "false") == "true"

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def list_servers(self) -> list[dict]:
        return [
            {
                "name": name,
                "stage": info["stage"],
                "description": info["description"],
                "status": "ready" if name in self._enabled or True else "disabled",
            }
            for name, info in self.SERVER_REGISTRY.items()
        ]

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

    def _check_name(self, name: str) -> None:
        if name not in self.SERVER_REGISTRY:
            raise KeyError(f"未知 MCP Server: {name}（可选: {list(self.SERVER_REGISTRY)}）")

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
        """同步获取工具列表（静态反射，结果缓存）。"""
        self._check_name(name)
        if use_cache and name in self._tools_cache:
            return self._tools_cache[name]
        tools = asyncio.run(self._list_tools_async(name))
        self._tools_cache[name] = tools
        return tools

    def list_tools_with_schema(self, name: str) -> list[dict]:
        """列出工具（含 inputSchema，供 Agent 动态注入）。"""
        self._check_name(name)

        async def _fetch() -> list[dict]:
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
    async def _call_tool_async(self, name: str, tool: str, arguments: dict) -> str:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        script = settings.mcp_servers_dir / f"{name}_server.py"
        if not script.is_file():
            raise FileNotFoundError(f"MCP Server 脚本不存在: {script}")

        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(script)],
            env=None,  # 继承当前进程环境（子进程自行 load_dotenv）
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(
                    session.call_tool(tool, arguments),
                    timeout=settings.mcp_call_timeout,
                )
                if result.content:
                    first = result.content[0]
                    return first.text if first.type == "text" else str(first)
                return "工具调用成功但无返回内容"

    def call_tool(self, name: str, tool: str, arguments: dict) -> str:
        """同步调用 MCP 工具（内部用 asyncio.run 新建事件循环）。"""
        self._check_name(name)
        try:
            return asyncio.run(self._call_tool_async(name, tool, arguments))
        except asyncio.TimeoutError:
            return f"MCP 工具调用超时（{settings.mcp_call_timeout}s）: {name}/{tool}"
        except Exception as exc:  # noqa: BLE001 - 工具错误应数据化返回给 LLM
            logger.exception("MCP 工具调用失败: %s/%s", name, tool)
            return f"MCP 工具调用失败: {type(exc).__name__}: {exc}"
