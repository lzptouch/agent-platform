"""
Workers - 研究任务执行者 (SubAgent)

基于高级研究智能体设计优化：
- OODA 循环（观察-定向-决策-行动）
- 研究预算控制
- 来源质量批判性评估
- 智能终止（收益递减检测）

包含多种类型的 Worker：
1. SearchWorker: 执行网络搜索和信息提取
2. WriterWorker: 将研究数据转化为报告章节
3. AnalysisWorker: 执行数据分析任务
4. VisualizationWorker: 生成可视化建议
"""

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Literal

from app.services.research.llm_client import get_llm_client
from app.services.research.search_client import get_search_client
from app.services.research.utils import SearchResult, extract_json, format_search_context
from app.services.research.prompts import (
    SEARCH_WORKER_SYSTEM_PROMPT,
    SEARCH_WORKER_TASK_PROMPT,
    WRITER_WORKER_SYSTEM_PROMPT,
    WRITER_SECTION_PROMPT,
    QUERY_EXPANSION_PROMPT,
)
from app.services.research.research_config import AGENT_CONFIG


# ==================== 数据结构 ====================

@dataclass
class OODACycle:
    """OODA 循环记录"""
    cycle: int
    observe: str  # 观察到的信息和状态
    orient: str   # 分析和方向调整
    decide: str   # 做出的决定
    act: str      # 执行的行动和结果


@dataclass
class SourceQualityAssessment:
    """来源质量评估"""
    high_quality_sources: List[str] = field(default_factory=list)
    questionable_sources: List[str] = field(default_factory=list)
    source_conflicts: List[str] = field(default_factory=list)


@dataclass
class ResearchBudget:
    """研究预算"""
    max_queries: int = 5
    max_analysis_cycles: int = 3
    queries_used: int = 0
    cycles_used: int = 0

    @property
    def queries_remaining(self) -> int:
        return max(0, self.max_queries - self.queries_used)

    @property
    def budget_exhausted(self) -> bool:
        return self.queries_used >= self.max_queries


# ==================== 基础 Worker 类 ====================

class BaseWorker(ABC):
    """Worker 基类"""

    def __init__(self, worker_id: str = None):
        self.worker_id = worker_id or f"worker_{int(time.time()*1000)}"
        self.llm = get_llm_client()

    @abstractmethod
    def execute(self, task) -> dict:
        """执行任务的抽象方法"""
        pass


# ==================== 搜索 Worker (增强版) ====================

class SearchWorker(BaseWorker):
    """
    搜索研究 Worker (SubAgent) - 增强版

    核心能力：
    1. OODA 循环执行
    2. 研究预算管理
    3. 来源质量批判性评估
    4. 智能终止（收益递减检测）

    负责：
    1. 执行网络搜索
    2. 提取关键信息
    3. 评估来源可靠性
    4. 区分事实与推测
    5. 整理研究发现
    """

    def __init__(
        self,
        worker_id: str = None,
        max_queries: int = 5,
        max_analysis_cycles: int = 3,
    ):
        super().__init__(worker_id)
        self.search_client = get_search_client()
        self.max_queries = max_queries
        self.max_analysis_cycles = max_analysis_cycles

        # 研究预算
        self.budget = ResearchBudget(
            max_queries=max_queries,
            max_analysis_cycles=max_analysis_cycles,
        )

        # OODA 循环记录
        self.ooda_cycles: List[OODACycle] = []

        # 来源质量评估
        self.source_assessment = SourceQualityAssessment()

        # 收集到的所有结果
        self.all_results: List[SearchResult] = []

        # 终止原因
        self.termination_reason = ""

    def execute(self, subtask) -> dict:
        """
        执行搜索研究任务（增强版 - OODA 循环）

        参数:
            subtask: SubTask 对象，包含任务信息

        返回:
            dict: 研究结果
        """
        # 初始化
        self.ooda_cycles = []
        self.all_results = []
        self.termination_reason = ""
        self.budget.queries_used = 0
        self.budget.cycles_used = 0

        # 确定研究预算
        task_complexity = self._assess_task_complexity(subtask)
        self._adjust_budget(task_complexity)

        # 获取搜索查询词
        search_queries = subtask.search_queries
        if not search_queries:
            search_queries = self._expand_queries(
                subtask.description,
                getattr(subtask, 'research_objective', ''),
            )

        # OODA 循环执行研究
        cycle_num = 0
        while not self._should_terminate():
            cycle_num += 1

            # === 观察 (Observe) ===
            observe_result = self._observe(search_queries, subtask)

            # === 定向 (Orient) ===
            orient_result = self._orient(observe_result, subtask)

            # === 决策 (Decide) ===
            decide_result = self._decide(orient_result, subtask)

            # === 行动 (Act) ===
            act_result = self._act(decide_result, search_queries, subtask)

            # 记录 OODA 循环
            self.ooda_cycles.append(OODACycle(
                cycle=cycle_num,
                observe=observe_result.get("summary", ""),
                orient=orient_result.get("direction", ""),
                decide=decide_result.get("decision", ""),
                act=act_result.get("action_result", ""),
            ))

            # 检查是否应该终止
            if decide_result.get("should_terminate", False):
                self.termination_reason = decide_result.get("termination_reason", "决策终止")
                break

            # 更新搜索查询词（如果需要）
            if decide_result.get("new_queries"):
                search_queries = decide_result["new_queries"]

        # 去重和排序
        unique_results = self._deduplicate_results(self.all_results)

        # 使用 LLM 分析搜索结果
        result = self._analyze_results(subtask, unique_results)

        # 添加 OODA 循环记录和元信息
        result["ooda_cycles"] = [
            {
                "cycle": c.cycle,
                "observe": c.observe,
                "orient": c.orient,
                "decide": c.decide,
                "act": c.act,
            }
            for c in self.ooda_cycles
        ]
        result["research_budget_used"] = f"{self.budget.queries_used}/{self.budget.max_queries} 查询"
        result["termination_reason"] = self.termination_reason or "研究完成"

        return result

    def _assess_task_complexity(self, subtask) -> Literal["simple", "medium", "complex"]:
        """评估任务复杂度"""
        description = subtask.description.lower()

        # 简单任务指标
        simple_indicators = ["是什么", "what is", "查找", "find", "简单", "basic"]

        # 复杂任务指标
        complex_indicators = [
            "比较", "compare", "分析", "analyze", "深入", "deep",
            "全面", "comprehensive", "多个", "multiple", "趋势", "trend"
        ]

        simple_score = sum(1 for ind in simple_indicators if ind in description)
        complex_score = sum(1 for ind in complex_indicators if ind in description)

        if complex_score >= 2:
            return "complex"
        elif simple_score >= 2 or len(description) < 50:
            return "simple"
        else:
            return "medium"

    def _adjust_budget(self, complexity: Literal["simple", "medium", "complex"]):
        """根据复杂度调整研究预算"""
        if complexity == "simple":
            self.budget.max_queries = 3
            self.budget.max_analysis_cycles = 1
        elif complexity == "medium":
            self.budget.max_queries = 5
            self.budget.max_analysis_cycles = 2
        else:  # complex
            self.budget.max_queries = 8
            self.budget.max_analysis_cycles = 3

    def _should_terminate(self) -> bool:
        """判断是否应该终止研究"""
        # 预算耗尽
        if self.budget.budget_exhausted:
            self.termination_reason = "研究预算耗尽"
            return True

        # OODA 循环次数上限
        if len(self.ooda_cycles) >= self.budget.max_analysis_cycles:
            self.termination_reason = "达到最大分析轮次"
            return True

        return False

    def _observe(self, search_queries: List[str], subtask) -> dict:
        """OODA - 观察阶段"""
        # 执行搜索
        new_results = []
        queries_to_use = search_queries[:self.budget.queries_remaining]

        for query in queries_to_use:
            if self.budget.budget_exhausted:
                break

            response = self.search_client.search(query)
            if response.success:
                new_results.extend(response.results)
                self.all_results.extend(response.results)

            self.budget.queries_used += 1
            time.sleep(0.3)

        return {
            "new_results_count": len(new_results),
            "total_results_count": len(self.all_results),
            "queries_used": len(queries_to_use),
            "summary": f"执行了 {len(queries_to_use)} 次搜索，获得 {len(new_results)} 条新结果",
            "results": new_results,
        }

    def _orient(self, observe_result: dict, subtask) -> dict:
        """OODA - 定向阶段"""
        results = observe_result.get("results", [])

        # 评估来源质量
        high_quality = []
        questionable = []

        for result in results:
            quality = self._assess_source_quality(result)
            if quality == "high":
                high_quality.append(result.site_name or result.url)
            elif quality == "low":
                questionable.append(f"{result.site_name or result.url}: 可靠性存疑")

        self.source_assessment.high_quality_sources.extend(high_quality)
        self.source_assessment.questionable_sources.extend(questionable)

        # 识别信息空白
        info_gaps = self._identify_information_gaps(results, subtask)

        return {
            "high_quality_count": len(high_quality),
            "questionable_count": len(questionable),
            "info_gaps": info_gaps,
            "direction": f"发现 {len(high_quality)} 个优质来源，{len(questionable)} 个可疑来源。信息空白: {', '.join(info_gaps) if info_gaps else '无明显空白'}",
        }

    def _decide(self, orient_result: dict, subtask) -> dict:
        """OODA - 决策阶段"""
        info_gaps = orient_result.get("info_gaps", [])

        # 判断是否需要继续搜索
        if not info_gaps or self.budget.queries_remaining < 2:
            return {
                "should_terminate": True,
                "termination_reason": "信息充足" if not info_gaps else "预算不足",
                "decision": "终止研究，开始分析",
            }

        # 生成新的搜索查询
        new_queries = []
        for gap in info_gaps[:2]:  # 最多填补 2 个空白
            new_queries.append(gap[:50])  # 使用空白描述作为搜索词

        return {
            "should_terminate": False,
            "new_queries": new_queries,
            "decision": f"继续搜索以填补空白: {', '.join(info_gaps[:2])}",
        }

    def _act(self, decide_result: dict, search_queries: List[str], subtask) -> dict:
        """OODA - 行动阶段"""
        if decide_result.get("should_terminate"):
            return {"action_result": "准备进入分析阶段"}

        new_queries = decide_result.get("new_queries", [])
        if new_queries:
            return {"action_result": f"将执行 {len(new_queries)} 个新查询"}

        return {"action_result": "继续处理现有结果"}

    def _assess_source_quality(self, result: SearchResult) -> Literal["high", "medium", "low"]:
        """评估单个来源的质量"""
        url = result.url.lower()
        site_name = (result.site_name or "").lower()
        snippet = (result.snippet or "").lower()

        # 高质量指标
        high_quality_domains = [
            ".gov", ".edu", ".org",
            "reuters", "bloomberg", "wsj", "nytimes",
            "nature", "science", "arxiv",
            "statista", "mckinsey", "gartner",
        ]

        # 低质量指标
        low_quality_indicators = [
            "forum", "reddit", "quora", "yahoo answers",
            "wiki", "blog", "medium.com",
            "可能", "也许", "据说", "传闻",
        ]

        # 检查高质量
        for indicator in high_quality_domains:
            if indicator in url or indicator in site_name:
                return "high"

        # 检查低质量
        for indicator in low_quality_indicators:
            if indicator in url or indicator in site_name or indicator in snippet:
                return "low"

        return "medium"

    def _identify_information_gaps(self, results: List[SearchResult], subtask) -> List[str]:
        """识别信息空白"""
        # 简化实现：检查预期输出中的关键词是否在结果中出现
        expected_output = getattr(subtask, 'expected_output', '') or ''
        research_objective = getattr(subtask, 'research_objective', '') or ''

        all_text = expected_output + " " + research_objective
        keywords = [word for word in all_text.split() if len(word) > 3]

        results_text = " ".join([
            (r.title or "") + " " + (r.snippet or "")
            for r in results
        ]).lower()

        gaps = []
        for keyword in keywords[:5]:  # 检查前 5 个关键词
            if keyword.lower() not in results_text:
                gaps.append(f"缺少关于 '{keyword}' 的信息")

        return gaps[:3]  # 返回前 3 个空白

    def _expand_queries(self, task_description: str, research_objective: str = "") -> list[str]:
        """使用 LLM 扩展搜索查询词"""
        prompt = QUERY_EXPANSION_PROMPT.format(
            task=task_description + ("\n研究目标: " + research_objective if research_objective else ""),
            query_type="未指定",
        )

        response = self.llm.chat(
            prompt=prompt,
            temperature=0.5,
        )

        if response.success:
            result = extract_json(response.content)
            queries = result.get("queries", [])
            return [q.get("query", "") for q in queries if q.get("query")]

        # 如果 LLM 调用失败，使用简单的关键词提取
        return [task_description[:50]]

    def _deduplicate_results(self, results: list[SearchResult]) -> list[SearchResult]:
        """去重搜索结果"""
        seen_urls = set()
        unique = []
        for result in results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                unique.append(result)
        return unique

    def _analyze_results(self, subtask, results: list[SearchResult]) -> dict:
        """使用 LLM 分析搜索结果（增强版）"""
        # 格式化搜索结果为上下文
        search_context = format_search_context(
            results,
            max_results=AGENT_CONFIG["max_sources_per_topic"],
        )

        # 获取增强字段（兼容旧版 SubTask）
        research_objective = getattr(subtask, 'research_objective', '') or subtask.expected_output
        expected_sources = getattr(subtask, 'expected_sources', [])
        scope_boundaries = getattr(subtask, 'scope_boundaries', '')

        prompt = SEARCH_WORKER_TASK_PROMPT.format(
            task_id=subtask.id,
            task_name=subtask.name,
            task_description=subtask.description,
            research_objective=research_objective,
            search_queries=", ".join(subtask.search_queries),
            expected_sources=", ".join(expected_sources) if expected_sources else "未指定",
            expected_output=subtask.expected_output,
            scope_boundaries=scope_boundaries or "未指定",
            search_results=search_context,
        )

        response = self.llm.chat(
            prompt=prompt,
            system_prompt=SEARCH_WORKER_SYSTEM_PROMPT,
            temperature=0.3,
        )

        if response.success:
            result = extract_json(response.content)
            if result:
                # 添加来源质量评估
                result["source_quality_assessment"] = {
                    "high_quality_sources": list(set(self.source_assessment.high_quality_sources)),
                    "questionable_sources": list(set(self.source_assessment.questionable_sources)),
                    "source_conflicts": self.source_assessment.source_conflicts,
                }
                return result

        # 如果解析失败，返回基础结果
        return {
            "task_id": subtask.id,
            "task_name": subtask.name,
            "key_findings": [
                {
                    "finding": r.snippet[:200] if r.snippet else r.title,
                    "source": r.site_name or r.url,
                    "source_url": r.url,
                    "source_type": "unknown",
                    "reliability": self._assess_source_quality(r),
                    "reliability_reasoning": "基于域名和内容自动评估",
                    "is_verified": False,
                }
                for r in results[:5]
            ],
            "summary": f"搜索到 {len(results)} 条相关结果",
            "data_points": [],
            "insights": [],
            "source_quality_assessment": {
                "high_quality_sources": list(set(self.source_assessment.high_quality_sources)),
                "questionable_sources": list(set(self.source_assessment.questionable_sources)),
                "source_conflicts": [],
            },
            "speculative_vs_factual": {
                "verified_facts": [],
                "speculative_claims": [],
            },
            "information_gaps": [],
            "limitations": "LLM 分析失败，仅返回基础搜索结果",
            "confidence_level": "low",
            "confidence_reasoning": "分析过程未能完成",
        }


# ==================== 写作 Worker (增强版) ====================
# ==================== 分析 Worker ====================
# ==================== 可视化建议 Worker ====================
# ==================== Worker 工厂 ====================
def search_worker_factory() -> SearchWorker:
    """默认的搜索 Worker 工厂函数"""
    return SearchWorker()
