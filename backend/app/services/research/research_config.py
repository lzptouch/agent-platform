"""Deep Research 链路配置（与 ``app/core/config.py`` 解耦）。

- ``LLM_CONFIG`` / ``SEARCH_CONFIG`` 的密钥与地址**统一从 Settings 读取**，
  不再各自 ``load_dotenv()``（避免与平台配置分裂）。
- ``AGENT_CONFIG`` 保留为 **可变模块级 dict**：原 deep_research 的
  ``main.py:226-251`` 依赖「临时覆盖 → try/finally 还原」的用法，
  改为 pydantic 扁平字段会破坏该语义，故原样保留。
"""
from __future__ import annotations

from app.core.config import settings

# ==================== LLM 配置（Research 链路专用） ====================
# 说明：Research 使用 DashScope 的 qwen 系列（plus / max / turbo 分工），
# 与平台主 LLM（settings.default_model）同源但模型取向不同，故独立配置。
LLM_CONFIG: dict = {
    "api_key": settings.dashscope_api_key,
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen-plus",        # 默认模型
    "model_smart": "qwen-max",   # 复杂推理
    "model_fast": "qwen-turbo",  # 简单任务
    "max_tokens": 8192,
    "temperature": 0.7,
}

# ==================== 搜索 API 配置（Bocha 博查） ====================
SEARCH_CONFIG: dict = {
    "api_key": settings.bocha_api_key,
    "base_url": settings.bocha_base_url,
    "default_count": settings.bocha_default_count,
    "summary": settings.bocha_summary,
}

# ==================== Agent 配置（18 个顶级字段，原样保留） ====================
AGENT_CONFIG: dict = {
    # ========== Orchestrator (Lead Agent) 配置 ==========
    "max_workers": 6,              # 最大并行 Worker 数
    "max_search_depth": 3,         # 最大搜索深度（迭代次数）
    "timeout_per_worker": 120,     # 单个 Worker 超时时间（秒）

    # ========== 查询类型与子智能体数量配置 ==========
    "worker_count_guidelines": {
        "simple": {"min": 1, "max": 2},
        "standard": {"min": 2, "max": 3},
        "medium": {"min": 3, "max": 5},
        "high": {"min": 5, "max": 10},
    },

    # ========== 研究任务配置 ==========
    "min_sources_per_topic": 3,
    "max_sources_per_topic": 10,

    # ========== 报告配置 ==========
    "report_language": "zh-CN",
    "include_sources": True,
    "include_summary": True,

    # ========== 迭代优化配置 ==========
    "min_iterations": 2,
    "max_iterations": 5,
    "quality_threshold": 80,

    # ========== 智能终止配置 ==========
    "enable_diminishing_returns_check": True,
    "diminishing_returns_threshold": 3,
    "early_termination_min_score": 75,

    # ========== SubAgent (Worker) 配置 ==========
    "worker_max_ooda_cycles": 3,

    "research_budget": {
        "simple": {"max_queries": 3, "max_cycles": 1},
        "medium": {"max_queries": 5, "max_cycles": 2},
        "complex": {"max_queries": 8, "max_cycles": 3},
    },

    "source_quality": {
        "high_quality_domains": [
            ".gov", ".edu", ".org",
            "reuters", "bloomberg", "wsj", "nytimes",
            "nature", "science", "arxiv",
            "statista", "mckinsey", "gartner", "idc",
        ],
        "low_quality_indicators": [
            "forum", "reddit", "quora", "yahoo answers",
            "wiki", "blog", "medium.com",
        ],
        "speculative_language": [
            "可能", "也许", "据说", "传闻", "预计",
            "may", "might", "possibly", "reportedly",
        ],
    },
}

# ==================== 日志配置 ====================
LOG_CONFIG: dict = {
    "level": "INFO",
    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    "show_worker_details": True,
    "show_search_results": False,
    "show_ooda_cycles": True,
    "show_source_quality": True,
}

# ==================== 输出配置 ====================
# output_dir 运行时被 ResearchManager 覆盖为 settings.research_output_abs
OUTPUT_CONFIG: dict = {
    "save_intermediate": True,
    "output_dir": "data/research",
    "formats": ["markdown", "json"],
    "include_ooda_logs": True,
    "include_source_assessment": True,
}


def refresh_from_settings() -> None:
    """Settings 变更后重新绑定密钥（主要用于测试注入）。"""
    LLM_CONFIG["api_key"] = settings.dashscope_api_key
    SEARCH_CONFIG["api_key"] = settings.bocha_api_key
    SEARCH_CONFIG["base_url"] = settings.bocha_base_url
    SEARCH_CONFIG["default_count"] = settings.bocha_default_count
    SEARCH_CONFIG["summary"] = settings.bocha_summary
