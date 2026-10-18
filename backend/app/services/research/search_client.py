"""Research 搜索客户端（Bocha 博查为主，Serper 自动降级）。

自 ``deep_research/app/agent/tools.py`` 的 ``SearchClient`` 抽出并增强：
- 密钥从 ``Settings`` 读取（``bocha_api_key``）
- **未配置 Bocha 时自动降级到 Serper**（复用 ``app/services/web/serper_service.py``），
  使研究链路在只有 SERPER_API_KEY 的环境下也能端到端跑通
"""
from __future__ import annotations

import logging
import time

import requests

from app.core.config import settings
from app.services.research.research_config import SEARCH_CONFIG
from app.services.research.utils import SearchResponse, SearchResult

logger = logging.getLogger(__name__)


class SearchClient:
    """网络搜索客户端封装（Bocha → Serper 降级）。"""

    def __init__(self) -> None:
        self.api_key = settings.bocha_api_key or SEARCH_CONFIG.get("api_key", "")
        self.base_url = SEARCH_CONFIG.get("base_url", "https://api.bocha.cn/v1/web-search")
        self.default_count = SEARCH_CONFIG.get("default_count", 10)
        self.summary = SEARCH_CONFIG.get("summary", True)

    # ------------------------------------------------------------------ #
    # 能力探测
    # ------------------------------------------------------------------ #
    @property
    def provider(self) -> str:
        """当前实际使用的搜索提供方。"""
        if self.api_key:
            return "bocha"
        if settings.serper_api_key:
            return "serper"
        return "none"

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #
    def search(self, query: str, count: int | None = None, freshness: str | None = None) -> SearchResponse:
        """执行网络搜索（自动选择可用 provider）。"""
        if self.provider == "none":
            return SearchResponse(
                query=query,
                success=False,
                error_msg="未配置 BOCHA_API_KEY 或 SERPER_API_KEY，无法执行研究检索",
            )
        if self.provider == "serper":
            return self._search_serper(query)
        return self._search_bocha(query, count, freshness)

    def multi_search(self, queries: list[str], count: int | None = None) -> list[SearchResponse]:
        """批量执行搜索（顺序执行，间隔 0.5s 避免限流）。"""
        results: list[SearchResponse] = []
        for query in queries:
            results.append(self.search(query, count))
            time.sleep(0.5)
        return results

    # ------------------------------------------------------------------ #
    # Bocha
    # ------------------------------------------------------------------ #
    def _search_bocha(self, query: str, count: int | None = None, freshness: str | None = None) -> SearchResponse:
        try:
            payload = {
                "query": query,
                "summary": self.summary,
                "count": count or self.default_count,
            }
            if freshness:
                payload["freshness"] = freshness

            response = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30,
            )
            data = response.json()

            if data.get("code") != 200:
                return SearchResponse(
                    query=query,
                    success=False,
                    error_msg=data.get("msg", "博查搜索失败"),
                )

            web_pages = data.get("data", {}).get("webPages", {})
            results = [
                SearchResult(
                    title=item.get("name", ""),
                    url=item.get("url", ""),
                    snippet=item.get("snippet", ""),
                    site_name=item.get("siteName", ""),
                    date=(item.get("dateLastCrawled") or "")[:10],
                )
                for item in web_pages.get("value", [])
            ]
            return SearchResponse(
                query=query,
                results=results,
                total_matches=web_pages.get("totalEstimatedMatches", len(results)),
                success=True,
            )
        except requests.Timeout:
            return SearchResponse(query=query, success=False, error_msg="搜索请求超时")
        except Exception as exc:  # noqa: BLE001 —— 搜索失败不应中断整个研究任务
            return SearchResponse(query=query, success=False, error_msg=str(exc))

    # ------------------------------------------------------------------ #
    # Serper（降级路径）
    # ------------------------------------------------------------------ #
    def _search_serper(self, query: str) -> SearchResponse:
        try:
            from app.services.web.serper_service import SerperClient

            raw = SerperClient().serper(query)
            parts = SerperClient().extract_components(raw)
            results = [
                SearchResult(title=t, url=u, snippet=s)
                for t, u, s in zip(parts["titles"], parts["links"], parts["snippets"])
            ]
            return SearchResponse(
                query=query,
                results=results,
                total_matches=len(results),
                success=True,
            )
        except Exception as exc:  # noqa: BLE001
            return SearchResponse(query=query, success=False, error_msg=f"Serper 降级搜索失败: {exc}")


# ==================== 全局单例 ====================

_search_client: SearchClient | None = None


def get_search_client() -> SearchClient:
    """获取搜索客户端单例。"""
    global _search_client
    if _search_client is None:
        _search_client = SearchClient()
    return _search_client
