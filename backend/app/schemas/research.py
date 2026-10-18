"""深度研究链路（Research）请求 / 响应模型。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import settings


class ResearchRequest(BaseModel):
    """提交一次深度研究任务。"""

    task: str = Field(..., min_length=1, description="研究任务描述")
    max_workers: int | None = Field(None, ge=1, le=10, description="最大并行 Worker 数")
    max_iterations: int | None = Field(None, ge=1, le=10, description="最大迭代次数")
    quality_threshold: int | None = Field(None, ge=0, le=100, description="质量通过阈值（0-100）")

    model_config = {
        "json_schema_extra": {
            "example": {
                "task": "2024 年中国新能源汽车市场分析报告",
                "max_workers": 6,
                "max_iterations": 5,
                "quality_threshold": 80,
            }
        }
    }


class ResearchSubmitResponse(BaseModel):
    """提交任务后的即时响应。"""

    task_id: str
    status: Literal["pending", "running", "completed", "failed"]
    message: str
    created_at: str


class ResearchTaskSummary(BaseModel):
    """任务列表中的单条摘要。"""

    task_id: str
    original_task: str
    status: str
    created_at: str
    quality_score: int | None = None


class ResearchTaskList(BaseModel):
    total: int
    tasks: list[ResearchTaskSummary]


class ResearchTaskStatus(BaseModel):
    """任务状态详情。"""

    task_id: str
    status: str
    progress: list[dict] = Field(default_factory=list)
    progress_summary: dict[str, Any] = Field(default_factory=dict)
    original_task: str
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    quality_score: int | None = None
    iteration_count: int | None = None
    error_message: str | None = None


class ResearchTaskResult(BaseModel):
    """任务最终报告。"""

    task_id: str
    status: str
    report: str | None = None
    quality_score: int | None = None
    iteration_count: int | None = None
    duration: float | None = None
    metadata: dict[str, Any] | None = None


class ResearchHealth(BaseModel):
    """Research 链路健康状态。"""

    enabled: bool = True
    search_provider: str = Field(description="实际检索提供方：bocha / serper / none")
    search_configured: bool
    llm_configured: bool
    default_model: str
    max_concurrent_tasks: int
    output_dir: str
    total_tasks: int = 0
    running_tasks: int = 0

    @classmethod
    def build(cls, provider: str, total: int, running: int) -> "ResearchHealth":
        return cls(
            search_provider=provider,
            search_configured=provider != "none",
            llm_configured=settings.has_api_key,
            default_model=settings.default_model,
            max_concurrent_tasks=settings.research_max_concurrent,
            output_dir=str(settings.research_output_abs),
            total_tasks=total,
            running_tasks=running,
        )
