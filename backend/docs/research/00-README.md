# Deep Research Agent 文档集

> **项目定位**：基于 Orchestrator-Workers 架构的多智能体深度研究系统，集成 Lead Agent 任务编排、SubAgent OODA 循环研究、迭代式质量优化与 SSE 流式推送。

## 文档清单

| # | 文档 | 核心回答 |
|---|------|----------|
| 01 | [系统架构文档](./01-系统架构文档.md) | 系统由哪些子系统组成？它们如何协作？整体拓扑是什么？ |
| 02 | [系统设计文档](./02-系统设计文档.md) | 如何设计来满足功能/非功能需求？技术选型是什么？为什么这么选？ |
| 03 | [详细设计文档](./03-详细设计文档.md) | 关键类/函数/数据结构的内部实现细节、关键代码逐行解读 |
| 04 | [接口文档](./04-接口文档.md) | HTTP API、CLI、Python SDK、流式 SSE 接口的完整调用规范 |
| 05 | [模块文档](./05-模块文档.md) | 每个目录/包的职责、依赖关系、扩展点 |
| 06 | [流程文档](./06-流程文档.md) | 端到端主流程 + 各子流程（含时序图、活动图） |

## 阅读顺序建议

- **架构师 / 新人**：先读 01（架构）→ 02（设计）→ 06（流程），快速建立全景。
- **开发贡献者**：读完 01-02 后，重点看 03（详细）→ 05（模块）→ 04（接口）。
- **调用方开发者**：直接看 04（接口文档）和 README 根目录的"快速开始"。
- **学术研究者 / 复现论文**：重点关注 02（设计决策）→ 03（实现）→ 06（流程）的"原理"小节。

## 关键代码地图

| 模块 | 入口 | 主要职责 |
|------|------|----------|
| `deep_research.main.DeepResearchAgent` | `main.py:206` | 对外统一 API：`research()` / `research_stream()` |
| `deep_research.orchestrator.Orchestrator` | `orchestrator.py:116` | Lead Agent：拆解、调度、迭代优化 |
| `deep_research.workers.SearchWorker` | `workers.py:94` | SubAgent：OODA 循环 + 搜索 |
| `deep_research.tools.LLMClient` | `tools.py:54` | LLM 调用（同步 + 流式） |
| `deep_research.tools.SearchClient` | `tools.py:163` | 博查搜索 API 客户端 |
| `deep_research.api.app` | `api.py:195` | FastAPI 服务（REST + SSE） |

## 外部资料来源

本项目设计参考以下公开资料：

- **[论文] ReAct: Synergizing Reasoning and Acting in Language Models** — Yao et al., ICLR 2023 — `https://arxiv.org/abs/2210.03629`
- **[博客] OODA Loop** — Wikipedia — `https://en.wikipedia.org/wiki/OODA_loop`
- **[博客] How we built our multi-agent research system** — Anthropic Engineering, 2025 — `https://www.anthropic.com/engineering/multi-agent-research-system`
- **[博客] [译] Anthropic 是如何构建 Multi-Agent Research 系统的（2025）** — Arthur Chiao — `https://arthurchiao.art/blog/built-multi-agent-research-system-zh/`
- **[博客] LLM Powered Autonomous Agents** — Lilian Weng, 2023 — `https://lilianweng.github.io/posts/2023-06-23-agent/`
- **[官方] FastAPI Custom Response** — `https://fastapi.tiangolo.com/advanced/custom-response/`
- **[官方] concurrent.futures — Python Docs** — `https://docs.python.org/3/library/concurrent.futures.html`
- **[官方] Pydantic Models** — `https://docs.pydantic.dev/latest/concepts/models/`
- **[官方] OpenAI Structured Outputs** — `https://platform.openai.com/docs/guides/structured-outputs`
- **[官方] Prompt Engineering Guide** — `https://www.promptingguide.ai/zh/introduction`
- **[官方] 博查 AI 开放平台** — `https://open.bochaai.com/`

## 版本信息

- 项目版本：`__version__ = "1.0.0"`（见 `__init__.py:17`）
- API 版本：`1.0.0`（见 `api.py:198`）
- Python 版本要求：未显式声明，建议 ≥ 3.10（项目使用了 `Literal[...]` 与 `list[str]` 等 PEP 585/604 类型注解）

## 项目运行入口速查

```bash
# CLI 模式
python -m deep_research "研究任务描述"

# API 服务模式
uvicorn deep_research.api:app --reload --port 8000

# Python SDK 模式
from deep_research import DeepResearchAgent
agent = DeepResearchAgent(verbose=True)
report = agent.research("2024年电动汽车市场分析报告")
```

## 文档版本

- 文档生成时间：基于当前 `deep_research/` 目录下源代码
- 文档对应代码 commit：未指定
- 文档生成工具：人工基于源码逐行精读 + 公开资料检索
