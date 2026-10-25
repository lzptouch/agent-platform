# Orchestrator-Workers 多智能体架构（扩充版）

> - **整理日期**：2026-09-15（首发 2026-09-15 扩充）
> - **依据项目**：`apps/agent/backend/app/services/research/`（Deep Research 链路）+ `doc/knowledge/04_质量评分迭代与任务持久化.md`
> - **资料来源**：Anthropic《Building Effective Agents》(2024-12) + Anthropic《How we built our multi-agent research system》(2025-06) + OpenAI Deep Research + AutoGen + CrewAI + LangGraph Supervisor

---

# 第一章 原理

## 1.1 Orchestrator-Workers 模式

```
              ┌─────────────────────┐
              │   Orchestrator      │
              │  (Lead Agent)        │
              └─────────┬───────────┘
                        │ 任务拆解
        ┌───────────┬───┴────┬───────────┐
        ▼           ▼        ▼           ▼
   ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
   │Worker 1│  │Worker 2│  │Worker 3│  │Worker N│
   │(OODA)  │  │(OODA)  │  │(OODA)  │  │(OODA)  │
   └────────┘  └────────┘  └────────┘  └────────┘
        │           │        │           │
        └───────────┴────────┴───────────┘
                        │ 结果合并
              ┌─────────▼───────────┐
              │  Quality Score      │
              │  + Iteration        │
              └─────────────────────┘
```

参考：[Anthropic: Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)

## 1.2 OODA 子循环（Worker 内部）

```
Observe（观察检索结果）→ Orient（理解+分析）→ Decide（决定下一步）→ Act（再检索 / 报告）
```

源自军事决策理论（John Boyd），在 Agent 场景下：
- **O**bserve：分析当前 search results
- **O**rient：评估相关性和缺口
- **D**ecide：决定补充检索 or 继续
- **A**ct：执行再检索 / 生成报告

## 1.3 6 阶段 Prompt 流转

| # | 阶段 | Prompt | 输出 |
|---|------|--------|------|
| 1 | TASK_DECOMPOSITION | 拆解任务为子任务 | `subtasks[]` |
| 2 | SEARCH_WORKER_TASK | 并行执行搜索 | Worker results |
| 3 | SYNTHESIS | 汇总为初步报告 | `initial_report` |
| 4 | QUALITY_CHECK | 评分（0-100） | `score, needs_refinement` |
| 5 | GAP_ANALYSIS | 分析缺口 | `gaps[]` |
| 6 | REPORT_REFINEMENT | 迭代优化 | `final_report` |

## 1.4 Anthropic 2025 公开架构要点

1. **Orchestrator-Workers**（本项目一致）
2. **Prompt 隔离**：每个 Worker 独立 prompt，避免 context 污染
3. **评估/反思**：Worker 间传递 evaluation，而非单纯拼接结果
4. **工具选择性**：避免给所有 Agent 全部工具，按需注入
5. **同步 + 异步结合**：Orchestrator 异步、Worker 可同步

---

# 第二章 工程实现

## 2.1 Research 链路架构（实测）

```
backend/app/services/research/
├── __init__.py
├── llm_client.py          # LLM 客户端封装
├── search_client.py        # 博查搜索客户端
├── prompts.py              # 6 个阶段 Prompt 模板
├── research_config.py      # AGENT_CONFIG / OUTPUT_CONFIG
├── orchestrator.py         # Orchestrator：Lead Agent
├── workers.py              # Worker：OODA 子循环
├── research_manager.py     # 任务生命周期 + JSON 持久化
└── service.py / utils.py
```

## 2.2 关键配置

```python
# config.py
# Research 链路（Bocha 博查搜索）
bocha_api_key: str = ""
bocha_base_url: str = "https://api.bocha.cn/v1/web-search"
bocha_default_count: int = 10
bocha_summary: bool = True

# Research Manager（线程池并发 + JSON 持久化）
research_output_dir: str = "data/research"
research_max_concurrent: int = 3   # ★ 线程池大小
research_persist: bool = True
```

## 2.3 Orchestrator 实现

```python
# services/research/orchestrator.py
@dataclass
class SubTask:
    """子任务数据结构"""
    id: str
    name: str
    description: str
    search_queries: list[str]
    priority: str = "medium"
    expected_output: str = ""
    status: str = "pending"
    result: Optional[dict] = None
    # ★ 新增字段
    research_objective: str = ""
    expected_sources: list[str] = field(default_factory=list)
    scope_boundaries: str = ""


@dataclass
class QueryTypeAnalysis:
    """查询类型分析"""
    query_type: Literal["depth_first", "breadth_first", "simple"]
    reasoning: str
    recommended_approach: str
    recommended_worker_count: int


@dataclass
class TaskPlan:
    task_understanding: dict
    subtasks: list[SubTask]
    report_structure: dict
    query_type: QueryTypeAnalysis = None
    research_plan: dict = field(default_factory=dict)
    worker_count: dict = field(default_factory=dict)
```

### 2.3.1 Orchestrator.run() 完整工作流

```python
async def run(self, task: str) -> Dict:
    """Orchestrator 主流程"""
    
    # 阶段 1：任务拆解（深度/广度判断）
    plan = await self.decompose_task(task)
    
    # 阶段 2：Worker 并发执行
    all_findings = []
    for iteration in range(self.max_iterations):
        findings = await asyncio.gather(*[
            self.run_worker(subtask) for subtask in plan.subtasks
        ])
        all_findings.extend(findings)
        
        # 阶段 3：质量评分
        score = self.score_quality(task, all_findings)
        if score >= THRESHOLD:
            break
        
        # 阶段 4：缺口分析 + 补充检索
        gaps = self.analyze_gaps(task, all_findings)
        plan = self.refine_subtasks(plan, gaps)
    
    # 阶段 5：综合报告
    report = await self.synthesize_report(task, all_findings)
    
    return {
        "report": report,
        "findings_count": len(all_findings),
        "iterations": iteration + 1,
        "final_score": score,
    }
```

## 2.4 Worker OODA 子循环

```python
# services/research/workers.py
async def ooda_loop(worker_id, task):
    """单 Worker 的 OODA 子循环"""
    context = {"findings": [], "visited_urls": set()}
    
    for step in range(MAX_OODA_STEPS):
        # Observe：分析当前结果
        observations = analyze(context["findings"])
        
        # Orient：评估缺口
        gap = identify_gap(task, observations)
        
        # Decide：下一步动作
        if not gap:
            break
        next_query = formulate_query(gap, task)
        
        # Act：执行检索
        result = await bocha_search(next_query)
        context["findings"].append(result)
    
    return synthesize(task, context["findings"])
```

## 2.5 ResearchManager（任务调度）

```python
# services/research/research_manager.py
class ResearchManager:
    """管理所有深度研究任务"""
    
    TERMINAL_STATES = {"completed", "failed"}
    
    def __init__(self, persist=True):
        self.output_dir = Path(settings.research_output_abs)
        self.executor = ThreadPoolExecutor(max_workers=settings.research_max_concurrent)
        self.tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._load_tasks()    # ★ 启动恢复
    
    def create_task(self, task_text, max_workers=None, max_iterations=None, quality_threshold=None):
        """创建新任务"""
        task_id = str(uuid.uuid4())[:8]
        self.tasks[task_id] = {
            "task_id": task_id,
            "original_task": task_text,
            "status": "pending",
            "progress": [],
            "progress_summary": {},
            "config": {
                "max_workers": max_workers or AGENT_CONFIG["max_workers"],
                "max_iterations": max_iterations or AGENT_CONFIG["max_iterations"],
                "quality_threshold": quality_threshold or AGENT_CONFIG["quality_threshold"],
            },
            "created_at": datetime.now().isoformat(),
        }
        self._save_tasks()
        return task_id
    
    def submit(self, task_id):
        """★ 提交到线程池"""
        self.executor.submit(self._run_task, task_id)
    
    def shutdown(self):
        """优雅关闭"""
        self.executor.shutdown(wait=True)
```

---

# 第三章 业界做法调研

## 3.1 Deep Research 框架横向对比

| 方案 | 来源 | 特点 | 适用 |
|------|------|------|------|
| **本项目 Research** | 自研 OODA + Orchestrator-Workers | 简洁；JSON 持久化 | 单机生产 |
| **Anthropic 多 Agent 研究** | https://www.anthropic.com/engineering/building-effective-agents | 2025-06 公开 | 大型研究 |
| **OpenAI Deep Research** | https://openai.com/index/deep-research/ | 商业化；2025-02 | 商业产品 |
| **AutoGen GroupChat** | https://microsoft.github.io/autogen/ | 多 Agent 消息路由 | 研究 |
| **CrewAI Crew** | https://docs.crewai.com/ | 角色 + 任务模型 | 研究 |
| **LangGraph Supervisor** | https://langchain-ai.github.io/langgraph/concepts/multi_agent/ | 状态机 Supervisor | 复杂流程 |
| **OpenAI Swarm** | https://github.com/openai/swarm | 轻量 handoffs | 教学/原型 |
| **Gemini Deep Research** | Google | 2024-12 公开 | 商业产品 |

## 3.2 Anthropic 2025 多 Agent 研究系统详解

参考：https://www.anthropic.com/engineering/building-effective-agents

### 3.2.1 架构

```
Lead Agent (Orchestrator)
   │
   ├→ Subagent 1 (Research focus A)
   ├→ Subagent 2 (Research focus B)
   └→ Subagent 3 (Research focus C)
       │
       ↓
   Evaluation Agent（评估）
       │
       ↓
   Report Synthesizer
```

### 3.2.2 关键设计

| 设计 | 价值 |
|------|------|
| **Token 隔离** | 每个 Worker 独立 context；避免主 context 膨胀 |
| **任务隔离** | 不同 Worker 跑不同 prompt；防止 prompt 污染 |
| **评估隔离** | 评估 Agent 与研究 Agent 独立；评分更客观 |
| **工具选择** | 按需注入工具；避免「全工具」导致 LLM 困惑 |
| **同步 + 异步** | Orchestrator 异步；Worker 可同步 |

### 3.2.3 Token 成本对比

| 模式 | Token 消耗 |
|------|-----------|
| **单 Agent + 全部 context** | 100% |
| **Orchestrator-Workers** | 70-90%（节省 10-30%） |

---

# 第四章 操作步骤

## 4.1 P1-1：升级到 LangGraph Supervisor

```python
from langgraph.graph import StateGraph, START, END

def build_research_graph():
    g = StateGraph(ResearchState)
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("worker", worker_node)
    g.add_node("scoring", scoring_node)
    g.add_edge(START, "orchestrator")
    g.add_edge("orchestrator", "worker")
    g.add_edge("worker", "scoring")
    g.add_conditional_edges(
        "scoring",
        lambda s: "orchestrator" if s["score"] < THRESHOLD else END
    )
    return g.compile()
```

**收益**：可视化执行；checkpoint 持久化；可恢复。

## 4.2 P1-2：Worker 评估机制（Anthropic 风格）

```python
async def evaluate(findings):
    """Worker 输出后，Orchestrator 让另一个 LLM 评估"""
    prompt = f"""评估以下研究发现的完整性和准确性（0-100）：

{findings}

返回 JSON：{{"score": 0-100, "gaps": ["..."]}}"""
    return await llm_call(prompt, response_format={"type": "json_object"})
```

## 4.3 P1-3：动态 Worker 数量

```python
def get_recommended_worker_count(task_complexity):
    """根据任务复杂度动态调整 Worker 数"""
    if task_complexity == "simple":
        return 1
    elif task_complexity == "medium":
        return 3
    else:  # complex
        return 6
```

## 4.4 P2-1：工具选择性注入

```python
def get_worker_tools(subtask):
    """按子任务类型选择性注入工具"""
    if subtask.type == "data_lookup":
        return ["bocha_search", "rag_query"]
    elif subtask.type == "analysis":
        return ["bocha_search", "python_executor"]
    else:
        return ["bocha_search"]
```

## 4.5 P2-2：评估器集成 Langfuse

```python
from langfuse.decorators import observe

@observe(name="research_evaluation")
async def evaluate_quality(task, findings):
    """带 Langfuse 追踪的质量评估"""
    return await llm_call(f"评估 {task} 的 findings...")
```

---

## 附录 A：参考文献

| # | 类型 | 标题 | 来源 | 访问日期 |
|---|------|------|------|----------|
| [1] | 博客 | Anthropic: Building Effective Agents | https://www.anthropic.com/research/building-effective-agents | 2026-09-15 |
| [2] | 博客 | Anthropic: How we built our multi-agent research system | https://www.anthropic.com/engineering/building-effective-agents | 2026-09-15 |
| [3] | 官方文档 | OpenAI Deep Research | https://openai.com/index/deep-research/ | 2026-09-15 |
| [4] | 官方博客 | Google Gemini Deep Research | https://deepmind.google/technologies/gemini-deep-research/ | 2026-09-15 |
| [5] | OSS 项目 | AutoGen GroupChat | https://github.com/microsoft/autogen | 2026-09-15 |
| [6] | OSS 项目 | CrewAI | https://github.com/crewAIInc/crewAI | 2026-09-15 |
| [7] | 官方文档 | LangGraph Multi-Agent | https://langchain-ai.github.io/langgraph/concepts/multi_agent/ | 2026-09-15 |
| [8] | OSS 项目 | OpenAI Swarm | https://github.com/openai/swarm | 2026-09-15 |
| [9] | 论文 | ReAct (Yao et al. 2022) | https://arxiv.org/abs/2210.03629 | 2026-09-15 |
| [10] | 维基 | OODA Loop | https://en.wikipedia.org/wiki/OODA_loop | 2026-09-15 |
| [11] | 同源文档 | `apps/industry-research/doc/knowledge/02_深度研究DeepResearch模块原理.md` | 6 专家 Agent | 2026-09-15 |
| [12] | 同源文档 | `apps/agent/backend/docs/research/` | 项目内能力链文档 | 2026-09-15 |

---

> **本文档结构遵循「五段式」**：当前实现 → 原理剖析 → 业界做法调研 → 操作步骤 → 参考文献附录。
