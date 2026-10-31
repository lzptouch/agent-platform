"""Deep Research 链路配置（**单一真相在 Settings**，S1 / WP-1.6）。

改造前的三个问题：
1. ``LLM_CONFIG`` / ``SEARCH_CONFIG`` 是 **import 期的快照**（``settings`` 之后再改不会生效），
   且调用方同时读 ``settings.x`` 与快照 → **两份真相**；
2. ``AGENT_CONFIG`` 是**可变模块级 dict**，允许运行时被改写；
3. ``OUTPUT_CONFIG["output_dir"]`` 在 ``research_manager`` 启动时被**改写全局**。

现在的约定：
- 密钥 / 地址 / 数量等**只从 Settings 读**（``llm_config()`` / ``search_config()`` 每次现取）；
- 纯算法参数（并行度、迭代次数、报告格式等）放在**不可变**常量里（``AGENT_CONFIG`` 改为只读视图）；
- 输出目录属于**运行实例状态**，由 ``ResearchManager`` 自己持有，不再写回全局。
"""
from __future__ import annotations

from types import MappingProxyType

from app.core.config import settings


# ==================== LLM 配置（每次现取，避免快照） ====================
def llm_config() -> dict:
    """Research 链路的 LLM 配置（DashScope qwen 系列）。"""
    return {
        "api_key": settings.dashscope_api_key,
        "base_url": settings.dashscope_base_url
        or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",        # 默认模型
        "max_tokens": 8192,
        "temperature": 0.7,
    }


# ==================== 搜索 API 配置（每次现取） ====================
def search_config() -> dict:
    """Research 链路的搜索配置（Bocha 博查）。"""
    return {
        "api_key": settings.bocha_api_key,
        "base_url": settings.bocha_base_url or "https://api.bocha.cn/v1/web-search",
        "default_count": settings.bocha_default_count,
        "summary": settings.bocha_summary,
    }


# ==================== Agent 纯算法参数（只读） ====================
# 说明：这些是「研究流程自身的参数」，与平台配置无关，且**不应在运行期被改写**。
# 需要按任务覆盖时，走构造参数 / 调用参数，不改这里。
AGENT_CONFIG = MappingProxyType(
    {
        # ========== Orchestrator (Lead Agent) 配置 ==========
        "max_workers": 6,              # 最大并行 Worker 数
        "timeout_per_worker": 120,     # 单个 Worker 超时时间（秒）


        "max_sources_per_topic": 10,


        # ========== 迭代优化配置 ==========
        "min_iterations": 2,
        "max_iterations": 5,
        "quality_threshold": 80,

        # ========== 智能终止配置 ==========
        "enable_diminishing_returns_check": True,



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
)


# ==================== 日志配置（只读） ====================
LOG_CONFIG = MappingProxyType(
    {
        "level": "INFO",
        "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "show_worker_details": True,
        "show_search_results": False,
        "show_ooda_cycles": True,
        "show_source_quality": True,
    }
)


# ==================== 输出配置（只读；output_dir 由实例持有） ====================
OUTPUT_CONFIG = MappingProxyType(
    {
        "save_intermediate": True,
        "formats": ["markdown", "json"],
        "include_ooda_logs": True,
        "include_source_assessment": True,
    }
)
