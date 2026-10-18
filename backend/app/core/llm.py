"""LLM 客户端工厂（迁移自 webResearch，OpenAI 兼容接口）。"""
from openai import OpenAI

from app.core.config import settings


def get_llm_client() -> OpenAI:
    """返回备选 LLM 的 OpenAI 兼容客户端（用于 RAG / planner / reflection）。"""
    if not settings.llm_api_key:
        raise RuntimeError("未配置 LLM_API_KEY，请在 .env 中填写")
    return OpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


def chat(prompt: str, model: str | None = None, json_mode: bool = False) -> str:
    """便捷的非流式聊天调用。"""
    client = get_llm_client()
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    completion = client.chat.completions.create(
        model=model or settings.rag_model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        **kwargs,
    )
    return completion.choices[0].message.content
