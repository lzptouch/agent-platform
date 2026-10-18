# 01_weather-mcp — 项目文档索引

> 最简 MCP Server 骨架，演示 FastMCP + stdio 传输，工具为美国国家气象局（NWS）天气预警与预报。

## 项目特点
- **传输方式**：stdio（标准输入输出）— MCP 协议最常见的本地进程通信方式
- **外部依赖**：仅依赖美国气象局公开 API（无需 API Key），适合做"最小可运行示例"
- **附带工具**：`mcp_logger.py` 实现了一个 STDIO/STDOUT 流量镜像代理，可用于调试 MCP JSON-RPC 报文

## 源码文件清单
| 文件 | 行数 | 作用 |
|------|------|------|
| `weather.py` | 103 | MCP Server 主体，注册 `get_alerts`、`get_forecast` 两个工具 |
| `mcp_logger.py` | 239 | 流量记录代理，子进程 stdin/stdout 镜像到 `mcp_io.log` |
| `pyproject.toml` | 16 | uv 项目配置（Python ≥ 3.13，依赖 `httpx`、`mcp[cli]`） |
| `README.md` | 9 | 仓库作者声明（马克的技术工作坊） |

## 核心 API
```python
@mcp.tool()
async def get_alerts(state: str) -> str            # 州代码 → 天气预警
@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str  # 经纬度 → 天气预报
```

## 启动方式
```bash
uv run weather.py                 # 启动 MCP Server（stdio 模式）
# 或
python mcp_logger.py python weather.py   # 启用流量日志包装
```

## 文档清单
1. [01-系统架构文档.md](./01-系统架构文档.md) — 架构、调用链、设计原理（核心）

## 本章设计原理与依据

1. **核心思想**：MCP 是 LLM 工具调用的标准化协议。
   **本项目中体现**：用 `FastMCP` 装饰器自动暴露工具。
   **佐证来源**：[官方] Anthropic MCP 协议文档。

2. **核心思想**：stdio 是 MCP 最简传输方式。
   **本项目中体现**：无端口、无鉴权，IDE 直接 subprocess。
   **佐证来源**：[官方] MCP Transport Specification。

3. **核心思想**：std JSON RPC 严格要求 stdout 纯净。
   **本项目中体现**：`log_level="ERROR"` 抑制所有 INFO/DEBUG（`weather.py:7`）。
   **佐证来源**：[官方] MCP stdio 规范。

4. **核心思想**：调试代理是排查 MCP 启动问题最有效手段。
   **本项目中体现**：`mcp_logger.py` 用 subprocess.Popen + 守护线程镜像 stdio。
   **佐证来源**：[博客] MCP stdio 调试技巧。

5. **核心思想**：组合外部 API 适合放在 MCP Server 端。
   **本项目中体现**：`get_forecast` 两次串行调用（points → forecast）。
   **佐证来源**：[博客] MCP Server 端 API 组合模式。

## 引用

- [官方] Anthropic Model Context Protocol
- [官方] MCP Python SDK
- [官方] FastMCP 文档
- [官方] 美国国家气象局 API
- [博客] MCP 实战指南
