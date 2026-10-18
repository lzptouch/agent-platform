"""向 ResearchManager 写入一条「已完成」任务，用于前端报告渲染验证 + 持久化回归。

用法::

    .venv/bin/python -m scripts.seed_research_demo
"""
from __future__ import annotations

from app.core.config import settings
from app.services.research.research_manager import ResearchManager
from app.services.research.orchestrator import (
    IterationRecord,
    QueryTypeAnalysis,
    ResearchState,
    SubTask,
    TaskPlan,
)

REPORT = """# 2026 年中国新能源汽车市场竞争格局分析

## 执行摘要

本报告基于多源检索结果，对中国新能源汽车市场的竞争格局、技术路线与头部厂商表现进行了系统梳理。
整体判断：**市场已从「增量扩张」转向「存量博弈」**，价格战趋缓，技术差异化成为核心变量。

## 一、市场总体格局

- 2026 年上半年新能源渗透率约 **57%**，同比提升 6 个百分点
- 头部三家合计份额约 **48%**，集中度较去年提升 3 个百分点
- 出口占比提升至 **22%**，东南亚与欧洲为主要增量市场

## 二、头部厂商技术路线对比

| 厂商 | 主攻路线 | 补能方案 | 智驾方案 |
| --- | --- | --- | --- |
| 星辰电动 | 纯电 + 增程 | 800V 高压快充 | 端到端城区 NOA |
| 比亚迪 | 纯电 + DM 混动 | 双枪快充 | 天神之眼 |
| 特斯拉 | 纯电 | 超充网络 | FSD |

## 三、关键结论

1. **技术路线收敛**：纯电 + 增程/混动的「双动力」成为主流配置
2. **补能体验成为差异化重点**：800V 平台下放到 20 万级车型
3. **智驾进入「端到端」阶段**：城区 NOA 成为 25 万以上车型标配

## 参考来源

- [来源1] 中国汽车工业协会月度产销数据（2026-08）
- [来源2] 乘联会新能源市场分析报告（2026-07）
- [来源3] 头部厂商 2026 年半年度业绩说明会纪要
"""


def main() -> None:
    manager = ResearchManager()

    task_id = manager.create_task(
        "2026 年中国新能源汽车市场竞争格局与头部厂商技术路线对比分析",
        max_workers=4,
        max_iterations=3,
        quality_threshold=80,
    )
    manager.set_running(task_id)

    for stage, data in [
        ("decomposing", {"task": "新能源汽车市场分析"}),
        ("decomposed", {"subtask_count": 3, "query_type": "breadth_first", "recommended_workers": 3}),
        ("dispatching", {"worker_count": 3, "query_type": "breadth_first"}),
        ("worker_completed", {"task_name": "市场规模与渗透率"}),
        ("worker_completed", {"task_name": "头部厂商份额"}),
        ("worker_completed", {"task_name": "技术路线对比"}),
        ("synthesizing", {}),
        ("synthesized", {"report_length": len(REPORT)}),
        ("quality_checking", {}),
        ("quality_checked", {"score": 88, "needs_revision": False}),
        ("iteration_start", {"iteration": 1, "max_iterations": 3}),
        ("iteration_evaluated", {"iteration": 1, "score": 88, "threshold": 80, "passed": True}),
        ("quality_passed", {"score": 88}),
        ("completed", {"duration": 96.4, "quality_score": 88, "iterations": 1}),
    ]:
        manager.update_progress(task_id, stage, data)

    plan = TaskPlan(
        task_understanding={"core_question": "新能源车竞争格局", "domain": "汽车"},
        subtasks=[
            SubTask(id="task_1", name="市场规模与渗透率", description="", search_queries=["新能源渗透率"]),
            SubTask(id="task_2", name="头部厂商份额", description="", search_queries=["厂商份额"]),
            SubTask(id="task_3", name="技术路线对比", description="", search_queries=["技术路线"]),
        ],
        report_structure={"sections": ["执行摘要", "市场格局", "技术路线", "结论"]},
        query_type=QueryTypeAnalysis(
            query_type="breadth_first", reasoning="需广度覆盖", recommended_approach="并行检索", recommended_worker_count=3
        ),
    )
    state = ResearchState(
        original_task="2026 年中国新能源汽车市场竞争格局与头部厂商技术路线对比分析",
        task_plan=plan,
        worker_results=[{"task": "市场规模与渗透率"}, {"task": "头部厂商份额"}, {"task": "技术路线对比"}],
        final_report=REPORT,
        quality_score=88,
        status="completed",
        start_time=0.0,
        end_time=96.4,
        iteration_count=1,
        query_type="breadth_first",
        iteration_history=[
            IterationRecord(iteration=1, report=REPORT, quality_score=88, quality_result={"overall_score": 88})
        ],
    )
    manager.set_completed(task_id, state)

    print(f"✅ 已写入完成任务: {task_id}")
    print(f"   质量分: 88 | 报告 {len(REPORT)} 字符")
    print(f"   输出目录: {manager.output_dir}")
    print(f"   任务总数: {len(manager.tasks)}")


if __name__ == "__main__":
    main()
