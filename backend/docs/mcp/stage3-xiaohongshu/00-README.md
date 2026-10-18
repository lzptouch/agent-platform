# 03_xiaohongshu-mcp — 项目文档索引

> 真实互联网平台（小红书）的 MCP Server，通过 Playwright 浏览器自动化实现登录态持久化、笔记搜索、内容/评论抓取、智能评论生成。

## 项目特点
- **真实平台集成**：把"反爬严格"的真实网站包装成标准 MCP 工具
- **持久化登录**：`launch_persistent_context` 把浏览器 Cookie 落到 `browser_data/`，二次启动免登录
- **多层兜底选择器**：每个 DOM 字段都有 3-5 种提取策略，适应小红书频繁的样式更新
- **LLM 协作评论**：服务器只返回"笔记上下文 + 评论风格指南"，由 LLM 客户端（如 Claude）生成评论后再调 `post_comment`
- **Docker 化部署**：自带 `Dockerfile`，一键容器化

## 源码文件清单
| 文件 | 行数 | 作用 |
|------|------|------|
| `xiaohongshu_mcp.py` | 1495 | MCP Server 主体，7 个工具 |
| `test_mcp.py` | 18 | 简易登录+抓取测试脚本 |
| `Dockerfile` | 49 | 镜像构建（含 Chromium 系统依赖） |
| `requirements.txt` | 13 | playwright / mcp / pandas / schedule 等 |

## 核心 API
```python
@mcp.tool() async def login() -> str
@mcp.tool() async def search_notes(keywords: str, limit: int = 5) -> str
@mcp.tool() async def get_note_content(url: str) -> str
@mcp.tool() async def get_note_comments(url: str) -> str
@mcp.tool() async def analyze_note(url: str) -> dict
@mcp.tool() async def post_smart_comment(url: str, comment_type: str = "引流") -> dict
@mcp.tool() async def post_comment(url: str, comment: str) -> str
```

## 启动方式
```bash
# 本地运行
pip install -r requirements.txt
playwright install chromium
python xiaohongshu_mcp.py

# Docker 部署
docker build -t xhs-mcp .
docker run -it -v $(pwd)/browser_data:/app/browser_data xhs-mcp
```

## 文档清单
1. [01-系统架构文档.md](./01-系统架构文档.md) — 架构、持久化原理、多层选择器、LLM 协作评论

## 本章设计原理与依据

1. **核心思想**：浏览器持久化上下文复用 Cookie 是处理登录态最高效方式。
   **本项目中体现**：`launch_persistent_context(user_data_dir=./browser_data)`。
   **佐证来源**：[官方] Playwright Browser Context 文档。

2. **核心思想**：反爬网站的 DOM 选择器必须用多路冗余策略。
   **本项目中体现**：每个字段 3-5 种选择器。
   **佐证来源**：[博客] Web Scraping Robustness Patterns。

3. **核心思想**：LLM 决策与浏览器执行应分离。
   **本项目中体现**：`post_smart_comment` 只返回上下文，不直接发评论。
   **佐证来源**：[官方] Anthropic Tool Use Design。

4. **核心思想**：Docker 显式列出 Chromium 系统依赖是部署必备。
   **本项目中体现**：`Dockerfile` 列出 fonts-liberation / libnss3 / libgbm1。
   **佐证来源**：[官方] Playwright Docker Template。

5. **核心思想**：headful 模式是真实平台集成的必然选择。
   **本项目中体现**：`headless=False` 让用户可扫码登录。
   **佐证来源**：[博客] Real Platform MCP Integration Patterns。

## 引用

- [官方] Anthropic MCP Protocol
- [官方] Playwright Browser Context
- [官方] Playwright Docker
- [博客] Web Scraping Robustness
