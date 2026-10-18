"""Research 链路数据结构与纯函数工具（自 ``deep_research/app/agent/tools.py`` 抽出）。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


# ==================== 数据结构 ====================

@dataclass
class SearchResult:
    """搜索结果数据结构。"""
    title: str
    url: str
    snippet: str
    site_name: str = ""
    date: str = ""

    def to_context(self) -> str:
        """转换为上下文字符串。"""
        return (
            f"【{self.title}】\n来源: {self.site_name or self.url}\n"
            f"日期: {self.date or '未知'}\n内容: {self.snippet}\n"
        )


@dataclass
class SearchResponse:
    """搜索响应数据结构。"""
    query: str
    results: list[SearchResult] = field(default_factory=list)
    total_matches: int = 0
    success: bool = True
    error_msg: str = ""


# ==================== 辅助函数 ====================

def extract_xml(text: str, tag: str) -> str:
    """从文本中提取指定 XML 标签的内容。"""
    match = re.search(f"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_json(text: str) -> dict:
    """从文本中提取 JSON 对象（兼容 ```json 代码块与裸 JSON）。"""
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass

    return {}


def format_search_context(results: list[SearchResult], max_results: int = 5) -> str:
    """将搜索结果格式化为上下文字符串。"""
    if not results:
        return "未找到相关搜索结果。"
    parts = [f"[来源{i}] {r.to_context()}" for i, r in enumerate(results[:max_results], 1)]
    return "\n---\n".join(parts)
