"""Research 链路 LLM 客户端（DashScope qwen 系列）。

自 ``deep_research/app/agent/tools.py`` 的 ``LLMClient`` 抽出，密钥改从 ``Settings`` 读取。

> 为什么不直接用 ``app/core/llm.py``？
> ``app/core/llm.py`` 面向**备选 LLM**（DeepSeek，用于 RAG / planner / reflection）；
> Research 链路按原设计使用 **DashScope qwen-plus / qwen-max / qwen-turbo**，
> 且需要 ``LLMResponse(content, success, error_msg)`` 这一返回契约，
> 故保留为独立适配器，避免与反思循环互相污染配置。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from openai import OpenAI

from app.core.config import settings
from app.services.research.research_config import LLM_CONFIG


@dataclass
class LLMResponse:
    """LLM 响应数据结构。"""
    content: str
    model: str
    usage: dict = field(default_factory=dict)
    success: bool = True
    error_msg: str = ""


class LLMClient:
    """LLM 客户端封装（同步 + 流式）。"""

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=settings.dashscope_api_key or LLM_CONFIG.get("api_key", ""),
            base_url=LLM_CONFIG["base_url"],
        )
        self.default_model = LLM_CONFIG["model"]

    def chat(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """同步调用 LLM。"""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = self.client.chat.completions.create(
                model=model or self.default_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return LLMResponse(
                content=response.choices[0].message.content,
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                success=True,
            )
        except Exception as exc:  # noqa: BLE001 —— 失败以 LLMResponse 返回，由调用方决定降级
            return LLMResponse(
                content="",
                model=model or self.default_model,
                success=False,
                error_msg=str(exc),
            )

    def chat_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        """流式调用 LLM（生成器）。"""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = self.client.chat.completions.create(
                model=model or self.default_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta_content = chunk.choices[0].delta.content
                    if delta_content:
                        yield delta_content
        except Exception as exc:  # noqa: BLE001
            yield f"\n[错误: {exc}]"


# ==================== 全局单例 ====================

_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """获取（惰性创建的）LLM 客户端单例。"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def reset_llm_client() -> None:
    """清空单例（密钥变更或测试时使用）。"""
    global _llm_client
    _llm_client = None
