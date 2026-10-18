# 02_mcp-with-llm — 项目文档索引

> MCP 与大模型（阿里云百炼 Qwen-Plus）的端到端集成，演示**自动工具发现**与**原生 Function Calling** 协作范式。

## 项目特点
- **零工具硬编码**：LLM 客户端不预先知道有哪些工具，运行时从 MCP Server 拉取定义
- **双传输**：v1 用 stdio 子进程；v2 用 streamable_http 远程调用（演示官方高德地图 MCP）
- **多客户端版本**：
  - `llm_client.py` — stdio 版（推荐学习）
  - `simple_demo.py` — 简化版（不依赖 MCP，直接演示 Function Calling 流程）
  - `llm_client_ali_v2.py` — 重构版，支持最多 10 轮工具调用

## 源码文件清单
| 文件 | 行数 | 作用 |
|------|------|------|
| `mcp_server.py` | 248 | FastMCP Server，注册 `web_search`、`news_search`、`weather_search` |
| `llm_client.py` | 415 | LLM + MCP stdio 客户端，自动发现工具 |
| `llm_client_ali_v2.py` | 227 | LLM + 远程 HTTP MCP 客户端（高德地图） |
| `simple_demo.py` | 276 | 不依赖 MCP 的简化 Function Calling 演示 |
| `requirements.txt` | 7 | `mcp`、`openai`、`httpx`、`python-dotenv` |
| `config.example.env` | 9 | 环境变量模板（DASHSCOPE_API_KEY、SERPER_API_KEY） |

## 核心 API（MCP Server）
```python
@mcp.tool() async def web_search(query: str, num_results: int = 10)
@mcp.tool() async def news_search(query: str, num_results: int = 10)
@mcp.tool() async def weather_search(city: str)
```

## 启动方式
```bash
pip install -r requirements.txt
cp config.example.env .env   # 填入 DASHSCOPE_API_KEY、SERPER_API_KEY

# 终端 1
python mcp_server.py
# 终端 2
python llm_client.py

# 或直接演示 Function Calling（无需 MCP Server）
python simple_demo.py
```

## 文档清单
1. [01-系统架构文档.md](./01-系统架构文档.md) — 架构、自动工具发现原理、设计要点

## 本章设计原理与依据

1. **核心思想**：MCP 协议与 OpenAI Function Calling 通过 JSON Schema 字节级兼容。
   **本项目中体现**：MCP 的 `inputSchema` 直接转成 OpenAI 的 `function.parameters`。
   **佐证来源**：[官方] MCP Protocol。

2. **核心思想**：运行时拉取工具优于启动时硬编码。
   **本项目中体现**：`initialize_mcp` 调用 `session.list_tools()`。
   **佐证来源**：[博客] Microkernel Architecture。

3. **核心思想**：两步式 Function Calling 是 OpenAI 官方推荐范式。
   **本项目中体现**：首轮让 LLM 决策，第二轮整合答案。
   **佐证来源**：[官方] OpenAI Function Calling 文档。

4. **核心思想**：MAX_TOOL_CALLS 是工业级防失控关键。
   **本项目中体现**：`MAX_TOOL_CALLS = 10` 防止 ReAct 死循环。
   **佐证来源**：[博客] Anthropic Agent Safety。

5. **核心思想**：优雅降级体现 Postel's Law。
   **本项目中体现**：MCP 启动失败时回退到硬编码默认工具。
   **佐证来源**：[博客] Robustness Principle (RFC 793)。

## 引用

- [官方] Anthropic MCP Protocol
- [官方] OpenAI Function Calling
- [官方] 阿里云百炼 OpenAI 兼容 API
- [官方] Serper.dev API
- [博客] Anthropic Engineering — Agent Safety
