# 🔬 Deep Research Agent

基于 **Orchestrator-Workers** 架构的高级深度研究智能体系统。

## 📋 概述

Deep Research Agent 是一个多智能体协作系统，能够自动化执行复杂的深度研究任务。系统采用经典的 Orchestrator-Workers 架构模式，并融入了先进的 **OODA 循环**、**查询类型分类**、**动态调度** 和 **来源质量评估** 等高级特性：

```
                    ┌─────────────────┐
                    │  用户研究需求   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   Orchestrator  │
                    │   (研究主管)     │
                    │                 │
                    │ • 任务理解      │
                    │ • 任务拆解      │
                    │ • 结果汇总      │
                    │ • 报告生成      │
                    └────────┬────────┘
                             │
           ┌─────────────────┼─────────────────┐
           │                 │                 │
    ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
    │  Worker 1   │   │  Worker 2   │   │  Worker N   │
    │  搜索任务1  │   │  搜索任务2  │   │  搜索任务N  │
    └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
           │                 │                 │
           └─────────────────┼─────────────────┘
                             │
                    ┌────────▼────────┐
                    │   最终研究报告   │
                    └─────────────────┘
```

## ✨ 特性

### 核心能力
- **🎯 智能任务拆解**: 自动将复杂研究任务分解为可并行执行的子任务
- **⚡ 并行执行**: 多个 Worker 同时执行搜索任务，大幅提升研究效率
- **🔍 深度搜索**: 集成网络搜索 API，获取最新、最全面的信息
- **📝 专业报告**: 自动生成结构化的 Markdown 研究报告
- **✅ 质量控制**: 内置质量检查机制，确保报告质量
- **🔄 迭代优化**: 自动多轮迭代，持续改进报告质量直到达标
- **📚 引用来源**: 报告自动包含参考来源，支持学术引用格式
- **📊 进度追踪**: 实时显示研究进度和状态

### 高级研究智能体特性

#### 🧠 Lead Agent (Orchestrator) 增强
- **查询类型分类**: 自动识别查询类型（depth_first/breadth_first/simple）
  - `depth_first`: 需要多角度深入探索单一主题
  - `breadth_first`: 需要覆盖多个独立子主题
  - `simple`: 单一焦点的简单查询
- **动态 Worker 调度**: 根据查询复杂度自动调整 Worker 数量（1-10个）
- **收益递减检测**: 智能识别研究收益递减，避免无效迭代
- **研究范围边界**: 明确定义研究范围，避免偏离主题

#### 🔄 SubAgent (Worker) 增强
- **OODA 循环**: 采用军事决策模型进行研究执行
  - **Observe（观察）**: 执行搜索，收集原始信息
  - **Orient（定向）**: 分析信息，识别关键洞察
  - **Decide（决策）**: 评估信息缺口，决定下一步
  - **Act（行动）**: 执行补充搜索或完成任务
- **研究预算管理**: 根据任务复杂度分配搜索次数和循环次数
- **来源质量评估**: 自动评估信息来源可靠性（高/中/低）
- **投机性内容识别**: 区分事实性内容和推测性内容

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置环境变量

创建 `.env` 文件：

```bash
# 阿里云通义千问 API Key
DASHSCOPE_API_KEY=sk-your-api-key

# Bocha 搜索 API Key
BOCHA_API_KEY=sk-your-bocha-key
```

### 基础使用

```python
from app.agent import DeepResearchAgent

# 创建 Agent
agent = DeepResearchAgent()

# 执行研究
report = agent.research("2024年电动汽车市场分析报告")

# 打印报告
print(report)
```

### 命令行使用

```bash
# 直接运行研究任务
python -m app.agent.research_agent "人工智能发展趋势分析"

# 指定 Worker 数量
python -m app.agent.research_agent "区块链技术应用" --workers 6

# 指定输出目录
python -m app.agent.research_agent "新能源行业研究" --output ./my_reports

# 安静模式
python -m app.agent.research_agent "医疗AI应用" --quiet
```

## 📁 项目结构

```
deep_research/                  # 项目根目录（FastAPI 标准结构）
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 服务入口（uvicorn app.main:app）
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py           # 配置文件（含高级智能体配置）
│   └── agent/                  # 智能体核心包
│       ├── __init__.py
│       ├── research_agent.py   # DeepResearchAgent 主程序 + CLI 入口
│       ├── orchestrator.py     # Orchestrator/Lead Agent 协调者
│       ├── workers.py          # Workers/SubAgent 工作者（含 OODA 循环）
│       ├── tools.py            # 工具层（LLM、搜索）
│       └── prompts.py          # Prompt 模板（Lead Agent + SubAgent）
├── docs/                       # 详细设计文档
├── assets/
│   ├── architecture.svg        # 系统架构图
│   └── prompt_dataflow.svg     # Prompt 数据流转图
├── .env                        # 环境变量（API Key）
├── .env.example                # 环境变量示例
├── requirements.txt            # 依赖清单
└── README.md                   # 说明文档
```

## 🏗️ 架构详解

### Orchestrator (Lead Agent / 协调者)

负责整体研究流程的协调和管理：

1. **查询分析**: 分析用户需求，识别查询类型（depth_first/breadth_first/simple）
2. **任务拆解**: 将复杂任务分解为独立的子任务，包含研究目标和范围边界
3. **动态调度**: 根据查询复杂度动态决定 Worker 数量（1-10个）
4. **Worker 调度**: 并行分发任务给多个 Worker
5. **结果汇总**: 收集并整合所有 Worker 的研究成果（含 OODA 循环日志和来源评估）
6. **报告生成**: 生成最终的结构化研究报告（含引用来源）
7. **质量控制**: 对报告进行质量评估
8. **收益递减检测**: 智能识别研究收益递减，避免无效迭代
9. **迭代优化**: 质量不达标时自动补充研究并修订报告

### Workers (SubAgent / 工作者)

执行具体的研究子任务，采用 OODA 循环模型：

- **SearchWorker**: 执行网络搜索，提取关键信息
  - 支持 OODA 循环（观察-定向-决策-行动）
  - 研究预算管理（根据任务复杂度分配资源）
  - 来源质量评估（高/中/低可靠性分级）
  - 信息缺口识别和补充搜索
- **WriterWorker**: 将研究数据转化为报告章节
- **AnalysisWorker**: 执行数据分析任务
- **VisualizationWorker**: 生成可视化建议

### OODA 循环流程

```
┌─────────────────────────────────────────────────────────────┐
│                    OODA 循环 (SubAgent)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────┐ │
│   │ Observe  │───▶│  Orient  │───▶│  Decide  │───▶│ Act  │ │
│   │  观察    │    │   定向   │    │   决策   │    │ 行动 │ │
│   └──────────┘    └──────────┘    └──────────┘    └──────┘ │
│        │                                              │     │
│        │              循环直到满足条件                  │     │
│        └──────────────────────────────────────────────┘     │
│                                                             │
│   • Observe: 执行搜索查询，收集原始搜索结果                   │
│   • Orient:  分析结果，提取关键信息和洞察                     │
│   • Decide:  评估信息缺口，决定是否需要补充搜索               │
│   • Act:     执行补充搜索或生成最终研究结果                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## ⚙️ 配置说明

### LLM 配置

```python
LLM_CONFIG = {
    "model": "qwen-plus",        # 默认模型
    "model_smart": "qwen-max",   # 复杂推理模型
    "model_fast": "qwen-turbo",  # 快速模型
    "max_tokens": 8192,
    "temperature": 0.7,
}
```

### Agent 配置

```python
AGENT_CONFIG = {
    # ========== Orchestrator (Lead Agent) 配置 ==========
    "max_workers": 6,              # 最大并行 Worker 数
    "max_search_depth": 3,         # 最大搜索深度
    "timeout_per_worker": 120,     # Worker 超时时间（秒）

    # ========== 查询类型与子智能体数量配置 ==========
    "worker_count_guidelines": {
        "simple": {"min": 1, "max": 2},      # 简单/直接查询
        "standard": {"min": 2, "max": 3},    # 标准复杂度查询
        "medium": {"min": 3, "max": 5},      # 中等复杂度查询
        "high": {"min": 5, "max": 10},       # 高复杂度查询
    },

    # ========== 研究任务配置 ==========
    "min_sources_per_topic": 3,    # 每主题最少信息源
    "max_sources_per_topic": 10,   # 每主题最多信息源

    # ========== 迭代优化配置 ==========
    "min_iterations": 2,           # 最少迭代次数
    "max_iterations": 5,           # 最大迭代次数
    "quality_threshold": 80,       # 质量通过阈值（0-100）

    # ========== 智能终止配置 ==========
    "enable_diminishing_returns_check": True,   # 启用收益递减检测
    "diminishing_returns_threshold": 3,         # 连续 N 次提升小于 5 分则触发
    "early_termination_min_score": 75,          # 提前终止的最低分数要求

    # ========== SubAgent (Worker) 配置 ==========
    "worker_max_ooda_cycles": 3,   # 每个 Worker 最大 OODA 循环次数

    # 研究预算配置（根据任务复杂度自动调整）
    "research_budget": {
        "simple": {"max_queries": 3, "max_cycles": 1},
        "medium": {"max_queries": 5, "max_cycles": 2},
        "complex": {"max_queries": 8, "max_cycles": 3},
    },

    # 来源质量评估配置
    "source_quality": {
        "high_quality_domains": [
            ".gov", ".edu", ".org",
            "reuters", "bloomberg", "nature", "arxiv",
        ],
        "low_quality_indicators": [
            "forum", "reddit", "quora", "blog",
        ],
    },
}
```

### 迭代优化策略

系统采用"评估-改进"循环，确保报告质量：

- **最少迭代**: 即使首次质量达标，也会至少迭代 2 次以确保深度
- **最大迭代**: 防止无限循环，最多迭代 5 次
- **质量阈值**: 评分达到 80 分且满足最少迭代次数后结束
- **收益递减检测**: 连续 3 次质量提升小于 5 分时提前终止

每次迭代流程：
1. 质量检查 → 2. 差距分析 → 3. 补充研究 → 4. 报告修订

### 查询类型说明

| 类型 | 说明 | Worker 数量 | 适用场景 |
|------|------|-------------|----------|
| `simple` | 单一焦点查询 | 1-2 | 简单问答、定义查询 |
| `depth_first` | 深度优先探索 | 3-10 | 需要多角度深入分析单一主题 |
| `breadth_first` | 广度优先覆盖 | 3-10 | 需要覆盖多个独立子主题 |

## 📖 高级用法

### 自定义进度回调

```python
def my_progress_handler(stage: str, data: dict):
    if stage == "worker_completed":
        print(f"✅ 完成: {data['task_name']}")
    elif stage == "quality_checked":
        print(f"📊 质量分: {data['score']}")

agent = DeepResearchAgent(verbose=False)
report = agent.research(
    task="你的研究任务",
    callback=my_progress_handler
)
```

### 流式输出

```python
agent = DeepResearchAgent(verbose=False)

for event_type, event_data in agent.research_stream("研究任务"):
    if event_type == "progress":
        print(f"进度: {event_data['stage']}")
    elif event_type == "result":
        print(f"完成! 质量分: {event_data['quality_score']}")
        report = event_data["report"]
```

## 🌐 API 服务

### 启动服务

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务（在 deep_research 项目根目录下执行）
uvicorn app.main:app --reload --port 8000

# 或者使用模块方式启动（默认端口 18000，可用 DEEP_RESEARCH_PORT 覆盖）
python -m app.main
```

服务启动后访问 http://localhost:8000/docs 查看 Swagger 文档。

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/research` | 提交研究任务 |
| GET | `/research` | 列出所有任务 |
| GET | `/research/{task_id}` | 获取任务状态 |
| GET | `/research/{task_id}/result` | 获取研究报告 |
| GET | `/research/{task_id}/stream` | SSE 流式进度 |
| DELETE | `/research/{task_id}` | 删除任务 |

### 完整使用流程

#### Step 1: 提交研究任务

**POST** `http://localhost:8000/research`

**Headers:**
```
Content-Type: application/json
```

**Body (JSON):**
```json
{
  "task": "2024年中国新能源汽车市场分析",
  "max_workers": 6,
  "max_iterations": 5,
  "quality_threshold": 80
}
```

**curl 命令:**
```bash
curl -X POST "http://localhost:8000/research" \
  -H "Content-Type: application/json" \
  -d '{"task": "2024年中国新能源汽车市场分析"}'
```

**响应示例 (200 OK):**
```json
{
  "task_id": "acde739c",
  "status": "pending",
  "message": "研究任务已提交，正在启动...",
  "created_at": "2025-11-30T18:30:20.421756"
}
```

---

#### Step 2: 查询任务状态

**GET** `http://localhost:8000/research/{task_id}`

**curl 命令:**
```bash
curl "http://localhost:8000/research/acde739c"
```

**响应示例 (200 OK):**
```json
{
  "task_id": "acde739c",
  "status": "running",
  "progress": {
    "current_stage": "iteration_evaluated",
    "iteration": 1,
    "score": 75
  },
  "original_task": "2024年中国新能源汽车市场分析",
  "created_at": "2025-11-30T18:30:20.421756",
  "started_at": "2025-11-30T18:30:21.123456",
  "completed_at": null,
  "quality_score": null,
  "iteration_count": null,
  "error_message": null
}
```

**状态说明：**
| status | 说明 |
|--------|------|
| `pending` | 任务已创建，等待启动 |
| `running` | 任务执行中 |
| `completed` | 任务完成，可获取报告 |
| `failed` | 任务失败 |

---

#### Step 3: 获取研究报告

**GET** `http://localhost:8000/research/{task_id}/result`

**curl 命令:**
```bash
curl "http://localhost:8000/research/acde739c/result"
```

**响应示例 (200 OK) - 任务完成:**
```json
{
  "task_id": "acde739c",
  "status": "completed",
  "report": "# 2024年中国新能源汽车市场分析报告\n\n## 执行摘要\n...",
  "quality_score": 85,
  "iteration_count": 2,
  "duration": 245.6,
  "metadata": {
    "original_task": "2024年中国新能源汽车市场分析",
    "created_at": "2025-11-30T18:30:20.421756",
    "completed_at": "2025-11-30T18:34:25.987654"
  }
}
```

**响应示例 (202 Accepted) - 任务进行中:**
```json
{
  "detail": "任务正在执行中"
}
```

---

#### Step 4: 列出所有任务

**GET** `http://localhost:8000/research`

**curl 命令:**
```bash
curl "http://localhost:8000/research"
```

**响应示例 (200 OK):**
```json
{
  "total": 2,
  "tasks": [
    {
      "task_id": "acde739c",
      "original_task": "2024年中国新能源汽车市场分析",
      "status": "completed",
      "created_at": "2025-11-30T18:30:20.421756",
      "quality_score": 85
    },
    {
      "task_id": "b1f2e3d4",
      "original_task": "人工智能发展趋势研究...",
      "status": "running",
      "created_at": "2025-11-30T19:00:00.000000",
      "quality_score": null
    }
  ]
}
```

---

#### Step 5: 删除任务

**DELETE** `http://localhost:8000/research/{task_id}`

**curl 命令:**
```bash
curl -X DELETE "http://localhost:8000/research/acde739c"
```

**响应示例 (200 OK):**
```json
{
  "message": "任务 acde739c 已删除"
}
```

---

### Postman 测试配置

| 接口 | Method | URL | Body |
|------|--------|-----|------|
| 提交任务 | POST | `http://localhost:8000/research` | `{"task": "研究主题"}` |
| 查询状态 | GET | `http://localhost:8000/research/{task_id}` | - |
| 获取报告 | GET | `http://localhost:8000/research/{task_id}/result` | - |
| 任务列表 | GET | `http://localhost:8000/research` | - |
| 实时进度 | GET | `http://localhost:8000/research/{task_id}/stream` | - |
| 删除任务 | DELETE | `http://localhost:8000/research/{task_id}` | - |

### SSE 流式进度（实时监听）

```javascript
// 前端实时监听进度
const eventSource = new EventSource('http://localhost:8000/research/acde739c/stream');

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(`[${data.stage}]`, data.data);

    // 任务完成时关闭连接
    if (data.stage === 'final') {
        console.log('研究完成！');
        console.log('质量分:', data.data.quality_score);
        console.log('迭代次数:', data.data.iteration_count);
        eventSource.close();
    }
};

eventSource.onerror = (error) => {
    console.error('SSE 连接错误:', error);
    eventSource.close();
};
```

**进度事件类型：**
| stage | 说明 |
|-------|------|
| `decomposed` | 任务拆解完成 |
| `worker_completed` | Worker 完成搜索 |
| `iteration_start` | 开始新一轮迭代 |
| `iteration_evaluated` | 迭代评估完成 |
| `quality_passed` | 质量检查通过 |
| `final` | 任务最终完成 |

## 🔧 扩展开发

### 添加新的 Worker 类型

```python
from app.agent.workers import BaseWorker

class MyCustomWorker(BaseWorker):
    def execute(self, task) -> dict:
        # 实现你的任务逻辑
        result = self.llm.chat(...)
        return {
            "task_id": task.id,
            "result": result,
            "success": True,
        }
```

### 自定义 Prompt

修改 `app/agent/prompts.py` 中的 Prompt 模板以适应特定场景。

## 📊 适用场景

- 📈 **市场研究**: 行业分析、竞品研究、市场趋势
- 🔬 **技术调研**: 技术选型、方案对比、最佳实践
- 📚 **学术综述**: 文献综述、研究现状、发展趋势
- 💼 **商业分析**: 投资研究、尽职调查、风险评估
- 📰 **新闻追踪**: 事件梳理、舆情分析、热点追踪

## 📊 Prompt 数据流转

系统中各 Prompt 之间的数据流转关系：

```
用户输入
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: TASK_DECOMPOSITION_PROMPT                           │
│   输入: {task}                                               │
│   输出: query_type, subtasks[], research_objective          │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: SEARCH_WORKER_TASK_PROMPT (并行执行)                 │
│   输入: {task_name}, {search_queries}, {context}            │
│   执行: OODA 循环 (Observe → Orient → Decide → Act)          │
│   输出: findings, sources[], ooda_cycles[], quality_assessment │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 3: SYNTHESIS_PROMPT                                    │
│   输入: {task}, {all_findings}                              │
│   输出: 初始研究报告 (Markdown)                              │
└─────────────────────────────────────────────────────────────┘
    │
    ▼ (迭代循环)
┌─────────────────────────────────────────────────────────────┐
│ STEP 4: QUALITY_CHECK_PROMPT                                │
│   输入: {task}, {report}                                    │
│   输出: score (0-100), passed (bool), suggestions           │
├─────────────────────────────────────────────────────────────┤
│ STEP 5: GAP_ANALYSIS_PROMPT                                 │
│   输入: {task}, {report}, {quality_feedback}                │
│   输出: {gap_analysis} - 信息缺口和补充建议                   │
├─────────────────────────────────────────────────────────────┤
│ STEP 6: 补充搜索 (SearchWorker)                              │
│   输入: gap_analysis 中的补充查询                            │
│   输出: supplementary_findings                               │
├─────────────────────────────────────────────────────────────┤
│ STEP 7: REPORT_REFINEMENT_PROMPT                            │
│   输入: {task}, {current_report}, {gap_analysis},           │
│         {supplementary_findings}                             │
│   输出: 优化后的研究报告                                      │
└─────────────────────────────────────────────────────────────┘
    │
    ▼ (循环直到质量通过或达到最大迭代次数)
最终研究报告
```

详细的数据流转图请参考 `assets/prompt_dataflow.svg`。

## ⚠️ 注意事项

1. 确保 API Key 配置正确
2. 网络搜索需要稳定的网络连接
3. 复杂任务可能需要较长时间
4. 建议为重要研究保存输出文件
5. OODA 循环和来源质量评估会增加一定的处理时间，但能显著提升研究质量


## 🤝 版权所有

深维学院，侵权必究（转卖，私自转发等均属于侵权行为）