# MCP 协议原理与 stdio 实现（扩充版）

> - **整理日期**：2026-09-15（首发 2026-09-15 扩充）
> - **依据项目**：`apps/agent/backend/app/mcp/servers/{weather,search,xiaohongshu}_server.py` + `services/mcp_manager.py`
> - **资料来源**：Anthropic MCP 官方文档 + FastMCP Python SDK + MCP Python SDK + Claude Desktop MCP + JSON-RPC 2.0

---

# 第一章 MCP 协议原理

## 1.1 什么是 MCP（Model Context Protocol）

MCP = **开放协议**，标准化 LLM 应用与工具/数据源的通信。类似 LSP（Language Server Protocol）对编辑器的作用。

参考：[modelcontextprotocol.io](https://modelcontextprotocol.io/)

### 1.1.1 MCP 解决的问题

```
无 MCP：
┌────────┐    自定义    ┌────────┐    自定义    ┌────────┐
│ LLM    │◄──────────►│ Tool A  │◄──────────►│ Tool B  │
│ 应用   │   协议      │ (天气)  │   协议      │ (搜索)  │
└────────┘            └────────┘            └────────┘
       │                   │                   │
       └────── 每对接一个新工具都要写适配 ─────────┘

有 MCP：
┌────────┐  标准协议  ┌────────┐  标准协议  ┌────────┐
│ LLM    │◄─────────►│ MCP    │◄─────────►│ MCP    │
│ 应用   │  JSON-RPC │ 天气   │  JSON-RPC │ 搜索   │
└────────┘            │ Server │            │ Server │
                      └────────┘            └────────┘
       └────── 一次接入，所有 MCP 工具可用 ───────┘
```

## 1.2 三种角色

```
┌────────────┐   JSON-RPC    ┌────────────┐
│ MCP Client │◄────────────►│ MCP Server │
│ (本项目    │  stdio/HTTP  │  (工具/数据)│
│  Agent)    │              │            │
└────────────┘              └────────────┘
```

- **MCP Client**：调用方（本项目 `mcp_manager.py`）
- **MCP Server**：提供工具/资源的服务（本项目 3 个 Server）
- **Host**：用户侧的 LLM 应用（本项目 FastAPI）

## 1.3 通信协议

| 传输 | 适用 | 文档 |
|------|------|------|
| **stdio** | 本地子进程（**本项目用**） | https://modelcontextprotocol.io/docs/concepts/transports#stdio-transport |
| **HTTP+SSE** | 远程服务 | https://modelcontextprotocol.io/docs/concepts/transports#server-sent-events-sse-transport |

## 1.4 三大能力（Primitives）

| Primitive | 用途 | MCP 方法 |
|-----------|------|---------|
| **Tools** | 可调用函数 | `tools/list`, `tools/call` |
| **Resources** | 数据源（文件、数据库） | `resources/list`, `resources/read` |
| **Prompts** | 模板化提示词 | `prompts/list`, `prompts/get` |

**本项目当前**：3 Server 均提供 Tools。

## 1.5 JSON-RPC 协议

```json
// Request
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_weather", "arguments": {"city": "北京"}}}

// Response
{"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "晴天 25℃"}]}}

// Error
{"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}
```

---

# 第二章 工程实现

## 2.1 三个 MCP Server（实测）

```
backend/app/mcp/servers/
├── weather_server.py      # 工具：get_alerts / get_forecast（真实 NWS API）
├── search_server.py       # 工具：web_search / news_search / weather_search（Serper）
└── xiaohongshu_server.py  # 工具：login / search_notes / post_smart_comment / 等 7 个
```

### 2.1.1 工具清单

| Server | 工具数 | 工具 | 底层 |
|--------|-------|------|------|
| **weather** | 2 | `get_alerts`, `get_forecast` | NWS API（https://api.weather.gov/） |
| **search** | 3 | `web_search`, `news_search`, `weather_search` | Serper API |
| **xiaohongshu** | 7 | `login`, `search_notes`, `post_smart_comment`, ... | Playwright 浏览器自动化 |
| **合计** | **12 个** | — | — |

### 2.1.2 weather_server.py 示例

```python
# mcp/servers/weather_server.py
from fastmcp import FastMCP
import httpx

mcp = FastMCP("weather")


@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get active weather alerts for a US state.
    
    Args:
        state: Two-letter US state code (e.g., "CA", "NY")
    """
    url = f"https://api.weather.gov/alerts/active?area={state.upper()}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=10.0)
        data = response.json()
    
    features = data.get("features", [])
    if not features:
        return f"No active alerts for {state}"
    
    alerts = []
    for feature in features[:3]:
        props = feature["properties"]
        alerts.append(f"- {props['event']}: {props['headline']}")
    
    return "\n".join(alerts)


@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location.
    
    Args:
        latitude: Latitude
        longitude: Longitude
    """
    # NWS API 两步：先获取 gridpoint，再获取 forecast
    async with httpx.AsyncClient() as client:
        points_url = f"https://api.weather.gov/points/{latitude},{longitude}"
        points = (await client.get(points_url)).json()
        forecast_url = points["properties"]["forecast"]
        forecast = (await client.get(forecast_url)).json()
    
    periods = forecast["properties"]["periods"][:7]
    result = []
    for p in periods:
        result.append(f"{p['name']}: {p['temperature']}°F, {p['shortForecast']}")
    return "\n".join(result)


if __name__ == "__main__":
    mcp.run()  # stdio transport
```

## 2.2 MCPManager 实现

```python
# services/mcp_manager.py
class MCPManager:
    """管理 MCP stdio Server 连接池"""
    
    def __init__(self, servers_dir: Path):
        self.servers_dir = servers_dir
        self.servers: dict[str, MCPClient] = {}
    
    async def start(self, server_names: list[str]):
        """启动指定 server（stdio 子进程）"""
        for name in server_names:
            server_path = self.servers_dir / f"{name}_server.py"
            self.servers[name] = await MCPClient.start_stdio(
                "python", str(server_path)
            )
    
    async def list_tools(self, server_name: str) -> list[dict]:
        """列出 server 暴露的工具"""
        client = self.servers[server_name]
        return await client.list_tools()  # → tools/list
    
    async def call_tool(self, server_name: str, tool_name: str, args: dict):
        """调用工具"""
        client = self.servers[server_name]
        return await client.call_tool(tool_name, args)  # → tools/call
    
    def get_all_tool_schemas(self) -> list[dict]:
        """收集所有 server 的工具定义（用于 LLM function calling）"""
        schemas = []
        for name, client in self.servers.items():
            for tool in client.tool_list:
                schemas.append({
                    "type": "function",
                    "function": {
                        "name": f"{name}__{tool['name']}",  # ★ 命名空间前缀
                        "description": tool["description"],
                        "parameters": tool["inputSchema"]
                    }
                })
        return schemas
```

### 2.2.1 工具命名空间

```python
# 避免不同 server 有同名工具（如都叫 search）
# 解决方案：加 server 前缀
{
    "weather__get_alerts": ...,
    "search__web_search": ...,
    "xiaohongshu__search_notes": ...,
}
```

## 2.3 静态反射（无需启动即可发现工具）

```python
# services/mcp_manager.py
import importlib.util

def list_tools_static(servers_dir: Path) -> dict[str, list[dict]]:
    """★ 静态反射：解析源码提取工具列表（无需启动子进程）"""
    result = {}
    for server_path in servers_dir.glob("*_server.py"):
        server_name = server_path.stem.replace("_server", "")
        
        # 用 importlib 加载模块（不执行）
        spec = importlib.util.spec_from_file_location(server_name, server_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # ★ 执行以获取 @mcp.tool() 装饰的工具
        
        # 反射工具列表
        tools = []
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if hasattr(func, "_mcp_tool"):
                tools.append({
                    "name": name,
                    "description": func._mcp_tool.get("description"),
                    "inputSchema": func._mcp_tool.get("parameters"),
                })
        result[server_name] = tools
    
    return result
```

**价值**：`GET /api/v1/mcp_servers` 立即可用，**不依赖 server 启动**。

## 2.4 API 端点

```python
# api/v1/mcp_servers.py
@router.get("/")
async def list_mcp_servers():
    """列出所有 MCP Server（静态反射）"""
    return mcp_manager.list_static()

@router.get("/{name}/tools")
async def list_tools(name: str):
    """列出指定 server 的工具"""
    return await mcp_manager.list_tools(name)
```

---

# 第三章 业界做法调研

## 3.1 MCP 实现方案对比

| 方案 | 来源 | 优缺点 |
|------|------|-------|
| **本项目自研 MCPManager** | — | 直接控制；调试方便 |
| **FastMCP** | https://github.com/jlowin/fastmcp | `@mcp.tool()` 装饰器；极简 |
| **MCP Python SDK（官方）** | https://github.com/modelcontextprotocol/python-sdk | 官方；功能全 |
| **MCP TypeScript SDK** | https://github.com/modelcontextprotocol/typescript-sdk | 官方 |
| **Claude Desktop MCP** | 内置 stdio | 配置即用 |
| **OpenAI Agents SDK MCP** | https://platform.openai.com/docs/agents | 集成度深 |

### 3.1.1 FastMCP 用法（业界主流）

```python
from fastmcp import FastMCP

mcp = FastMCP("weather")

@mcp.tool()
def get_alerts(state: str) -> str:
    """Get weather alerts for a US state."""
    ...

@mcp.resource("weather://current")
def current_weather() -> str:
    """Current weather data."""
    ...

@mcp.prompt("weather_report")
def weather_report_prompt(location: str) -> str:
    """Generate weather report prompt."""
    return f"Provide weather for {location}"

if __name__ == "__main__":
    mcp.run()  # 默认 stdio
```

**对比本项目**：

| 维度 | FastMCP | 本项目 |
|------|---------|-------|
| 代码量 | ~20 行/Server | ~50 行/Server |
| 装饰器 | `@mcp.tool()` | 手写 JSON-RPC |
| 自动反射 | ✅ | ✅（静态） |
| 资源 | ✅ | ❌ |
| 提示词 | ✅ | ❌ |

### 3.1.2 MCP Python SDK（官方）

```python
from mcp.server.fastmcp import FastMCP  # ★ 与 FastMCP 同名不同包
from mcp import types

mcp = FastMCP("weather")

@mcp.tool()
async def get_alerts(state: str) -> list[types.TextContent]:
    """Get active alerts."""
    # ...
    return [types.TextContent(type="text", text=alerts_text)]

# stdio 传输
if __name__ == "__main__":
    mcp.run(transport="stdio")

# HTTP+SSE 传输
# mcp.run(transport="sse", port=8001)
```

## 3.2 3 大能力使用情况

| Server | Tools | Resources | Prompts |
|--------|-------|-----------|---------|
| weather | 2 | ❌ | ❌ |
| search | 3 | ❌ | ❌ |
| xiaohongshu | 7 | ❌ | ❌ |
| **合计** | **12** | 0 | 0 |

**潜在升级**：xiaohongshu Server 可用 Resources 暴露笔记列表；weather Server 可暴露历史数据。

## 3.3 MCP 与传统 Function Call 对比

| 维度 | Function Call | MCP |
|------|---------------|-----|
| **标准化** | 各家不同 | 统一规范 |
| **跨平台** | 紧耦合 | 解耦 |
| **动态发现** | 需手动维护 | `tools/list` 自动 |
| **生态** | 厂商私有 | 开放生态 |
| **工具复用** | 每个项目重写 | 一次实现多项目用 |

---

# 第四章 操作步骤

## 4.1 P1-1：迁移到 FastMCP

```bash
pip install fastmcp
```

```python
# 改造前：手写 JSON-RPC
# 改造后：用 @mcp.tool()
from fastmcp import FastMCP

mcp = FastMCP("weather")

@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get active weather alerts for a US state."""
    # ...
```

**收益**：代码减少 50%+；自动处理 JSON-RPC 协议。

## 4.2 P1-2：支持 HTTP+SSE 远程 MCP Server

```python
# services/mcp_manager.py
class MCPClient:
    """MCP 客户端（支持 stdio + http+sse）"""
    
    @staticmethod
    async def start_stdio(script: str) -> 'MCPClient':
        """启动 stdio 子进程"""
        ...
    
    @staticmethod
    async def connect_sse(url: str) -> 'MCPClient':
        """连接远程 SSE"""
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url) as resp:
                # 解析 SSE 流
                ...
```

## 4.3 P1-3：MCP 权限与沙箱

```python
# services/mcp_manager.py
ALLOWED_TOOLS = {
    "weather": {"get_alerts", "get_forecast"},
    "search": {"web_search", "news_search"},
    "xiaohongshu": {"search_notes", "get_note_detail"},   # ★ 排除 write 类操作
}

async def call_tool(self, server_name, tool_name, args):
    """权限校验"""
    if server_name in ALLOWED_TOOLS:
        if tool_name not in ALLOWED_TOOLS[server_name]:
            raise PermissionError(f"工具 {tool_name} 不在白名单")
    
    return await self._do_call_tool(server_name, tool_name, args)
```

## 4.4 P2-1：MCP Marketplace

```python
# 远程 MCP Server 注册表
class MCPMarketplace:
    """MCP Server 市场"""
    
    @staticmethod
    async def search(query: str) -> list[dict]:
        """搜索远程 MCP Server"""
        return await remote_api.get(f"/mcp/search?q={query}")
    
    @staticmethod
    async def install(server_id: str):
        """安装远程 MCP Server"""
        server = await remote_api.get(f"/mcp/{server_id}")
        # 下载 + 启动
        ...
```

---

## 附录 A：参考文献

| # | 类型 | 标题 | 来源 | 访问日期 |
|---|------|------|------|----------|
| [1] | 官方文档 | Model Context Protocol | https://modelcontextprotocol.io/ | 2026-09-15 |
| [2] | 官方文档 | MCP Transports | https://modelcontextprotocol.io/docs/concepts/transports | 2026-09-15 |
| [3] | 官方文档 | MCP Specification | https://modelcontextprotocol.io/specification/2025-06-18 | 2026-09-15 |
| [4] | OSS 项目 | FastMCP Python SDK | https://github.com/jlowin/fastmcp | 2026-09-15 |
| [5] | OSS 项目 | MCP Python SDK（官方） | https://github.com/modelcontextprotocol/python-sdk | 2026-09-15 |
| [6] | OSS 项目 | MCP TypeScript SDK | https://github.com/modelcontextprotocol/typescript-sdk | 2026-09-15 |
| [7] | 官方文档 | Claude Desktop MCP | https://docs.claude.com/en/docs/claude-code/mcp | 2026-09-15 |
| [8] | 标准 | JSON-RPC 2.0 | https://www.jsonrpc.org/specification | 2026-09-15 |
| [9] | 标准 | LSP（类比） | https://microsoft.github.io/language-server-protocol/ | 2026-09-15 |
| [10] | 官方文档 | NWS API | https://www.weather.gov/documentation/services-web-api | 2026-09-15 |
| [11] | 官方文档 | Serper API | https://serper.dev | 2026-09-15 |
| [12] | 同源文档 | `apps/agent/backend/docs/mcp/` | 项目内能力链文档 | 2026-09-15 |

---

> **本文档结构遵循「五段式」**：当前实现 → 原理剖析 → 业界做法调研 → 操作步骤 → 参考文献附录。
