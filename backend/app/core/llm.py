"""LLM 客户端工厂（**全平台唯一入口**，S1 / WP-1.7）。

此前存在两个工厂：``app/core/llm.py``（备选 LLM / DeepSeek）与
``app/services/research/llm_client.py``（DashScope qwen 系列），各自读各自的配置，
导致"同一个 OpenAI 兼容客户端有两套来源"。S1 起统一到本模块：

- 按 ``provider`` 选择密钥与 base_url；
- 所有调用方（含 Research 链路）都经 ``get_llm_client()``；
- 保留 Research 侧的 ``LLMResponse`` 返回契约，但不再自建客户端。
"""
from __future__ import annotations

from openai import OpenAI

from app.core.config import settings

#: provider → (取密钥, 取 base_url)。base_url 为空时用 OpenAI 官方地址。
PROVIDERS: dict[str, tuple[str, str]] = {
    "dashscope": ("dashscope_api_key", "dashscope_base_url"),
    "deepseek": ("llm_api_key", "llm_base_url"),
    "openai": ("openai_api_key", ""),
}

DEFAULT_PROVIDER = "deepseek"


def resolve_provider(provider: str | None = None) -> tuple[str, str, str]:
    """返回 ``(provider, api_key, base_url)``。未指定时按"有备选 LLM 用备选，否则用默认模型"的顺序。"""
    name = provider or DEFAULT_PROVIDER
    if name not in PROVIDERS:
        raise ValueError(f"未知 LLM provider: {name}（可用：{', '.join(PROVIDERS)}）")
    key_attr, url_attr = PROVIDERS[name]
    api_key = getattr(settings, key_attr, "") or ""
    base_url = (getattr(settings, url_attr, "") or "") if url_attr else ""
    return name, api_key, base_url


def get_llm_client(
    provider: str | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> OpenAI:
    """返回 OpenAI 兼容客户端。

    :param provider: ``dashscope`` / ``deepseek`` / ``openai``；``None`` 用默认 provider
    :param api_key: 显式覆盖（用于 Research 链路的独立密钥）
    :param base_url: 显式覆盖
    """
    _, resolved_key, resolved_url = resolve_provider(provider)
    key = api_key if api_key is not None else resolved_key
    if not key:
        raise RuntimeError(
            f"未配置 LLM 密钥（provider={provider or DEFAULT_PROVIDER}），请在 .env 中填写"
        )
    return OpenAI(api_key=key, base_url=base_url if base_url is not None else resolved_url)


def get_langchain_chat_model(
    model: str | None = None,
    *,
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    extra: dict | None = None,
):
    """返回 LangChain ``ChatOpenAI``（供 langchain 链路使用，与 ``get_llm_client`` 同源）。

    延迟 import，避免把 langchain-openai 变成核心的硬依赖。
    """
    from langchain_openai import ChatOpenAI

    _, resolved_key, resolved_url = resolve_provider(provider)
    key = api_key if api_key is not None else resolved_key
    if not key:
        raise RuntimeError(
            f"未配置 LLM 密钥（provider={provider or DEFAULT_PROVIDER}），请在 .env 中填写"
        )
    return ChatOpenAI(
        model=model or settings.rag_model,
        api_key=key,
        base_url=base_url if base_url is not None else resolved_url,
        temperature=temperature,
        **(extra or {}),
    )


def chat(
    prompt: str,
    model: str | None = None,
    json_mode: bool = False,
    provider: str | None = None,
) -> str:
    """便捷的非流式聊天调用。"""
    client = get_llm_client(provider)
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
