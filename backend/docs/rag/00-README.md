# WebResearch 文档集

> **项目定位**：基于 OpenAI + Serper 的轻量级 RAG（检索增强生成）项目，使用 Milvus + BGE-M3 实现稠密+稀疏混合检索，并以 Notebook 形式给出"规划-工具-记忆-输出"四模块 Agent 的端到端销售助手示例。

## 文档清单

| # | 文档 | 核心回答 |
|---|------|----------|
| 01 | [系统架构文档](./01-系统架构文档.md) | 系统由哪些子系统组成？它们如何协作？整体拓扑是什么？ |
| 02 | [系统设计文档](./02-系统设计文档.md) | 如何设计来满足功能/非功能需求？技术选型是什么？为什么这么选？ |
| 03 | [详细设计文档](./03-详细设计文档.md) | 关键类/函数/数据结构的内部实现细节、关键代码逐行解读 |
| 04 | [接口文档](./04-接口文档.md) | SDK、模块 API、Notebook 函数、配置文件的完整使用规范 |
| 05 | [模块文档](./05-模块文档.md) | 每个文件/Notebook cell 的职责、依赖关系、扩展点 |
| 06 | [流程文档](./06-流程文档.md) | 端到端主流程 + 各子流程（含时序图、活动图） |

## 阅读顺序建议

- **快速体验**：直接运行 `RAG(Milvus+BGE).ipynb` 单元格，先看 01（架构）→ 06（流程）。
- **SDK 二次开发**：读完 01-02 后，重点看 03（详细）→ 04（接口）→ 05（模块）。
- **学术研究者 / 复现论文**：重点关注 02（设计决策）→ 03（实现）→ 06（流程）的"原理"小节。

## 关键代码地图

| 模块 | 入口 | 主要职责 |
|------|------|----------|
| `src/fetch_web_content.py` `WebContentFetcher` | `fetch_web_content.py:6` | 串联 Serper + 多线程爬虫，完成"搜索→抓取→正文提取" |
| `src/web_crawler.py` `WebScraper` | `web_crawler.py:5` | 基于 `requests` + `BeautifulSoup` 抽取正文 |
| `src/serper_service.py` `SerperClient` | `serper_service.py:7` | 封装 Serper.dev API，含中英文地域/语言自动判断 |
| `src/retrieval.py` `EmbeddingRetriever` | `retrieval.py:19` | 用 `sentence-transformers` + Chroma 做向量检索 |
| `src/locate_reference.py` `ReferenceLocator` | `locate_reference.py:4` | 正则解析 GPT 答案中的 `[n]` 引用并匹配元数据 |
| `src/llm_answer.py` `GPTAnswer` | `llm_answer.py:11` | 组装 Prompt + ChatOpenAI 流式生成 |
| `RAG(Milvus+BGE).ipynb` | Notebook 主流程 | BGE-M3 稠密+稀疏 + Milvus Hybrid Search + Agent 四模块 |

## 外部资料来源

本项目设计参考以下公开资料：

- **[论文] Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks** — Lewis et al., NeurIPS 2020 — `https://arxiv.org/abs/2005.11401`
- **[论文] BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation** — Chen et al., 2024 — `https://arxiv.org/abs/2402.03216`
- **[官方] Milvus Hybrid Search** — `https://milvus.io/docs/hybrid_search.md`
- **[官方] pymilvus Python SDK** — `https://milvus.io/docs/install-pymilvus.md`
- **[官方] Serper.dev API Docs** — `https://serper.dev/api`
- **[官方] OpenAI Chat Completions** — `https://platform.openai.com/docs/api-reference/chat`
- **[官方] LangChain RecursiveCharacterTextSplitter** — `https://python.langchain.com/docs/modules/data_connection/document_transformers/text_splitters/recursive_text_splitter`
- **[官方] BeautifulSoup Documentation** — `https://www.crummy.com/software/BeautifulSoup/bs4/doc/`
- **[博客] Sentence-Transformers all-MiniLM-L6-v2** — Hugging Face — `https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2`
- **[博客] LlamaParse（Notebook 文档解析）** — LlamaIndex — `https://docs.llamaindex.ai/en/stable/llama_cloud/llama_parse/`
- **[博客] DeepSeek-R1 推理能力与流式输出** — `https://api-docs.deepseek.com/guides/reasoning_model`

## 版本信息

- 项目版本：教学示例项目（未显式声明版本号）
- Python 版本要求：3.10（参见 `README.md:12`，Conda 环境 `agent`）
- 主要依赖版本：见 `requirement.txt`

## 项目运行入口速查

```bash
# 1. 创建 Conda 虚拟环境
conda create -n agent python=3.10
conda activate agent

# 2. 安装依赖
pip install -r requirement.txt

# 3. 填写 API Key（src/config/config.yaml）
# openai_api_key: "..."
# serper_api_key: "..."

# 4. 运行 Notebook（核心演示）
jupyter notebook "RAG(Milvus+BGE).ipynb"

# 5. 直接跑 WebResearch 流水线（命令行）
python src/llm_answer.py
```

## 文档版本

- 文档生成时间：基于当前 `webResearch/` 目录下源代码与 Notebook
- 文档对应代码 commit：未指定
- 文档生成工具：人工基于源码逐行精读 + 公开资料检索
