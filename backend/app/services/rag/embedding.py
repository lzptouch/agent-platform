"""DashScope text-embedding-v3 API（替代本地 BGE-M3，无需 torch / 本地模型）。

- 稠密向量：DashScope OpenAI 兼容接口 `/embeddings`，1024 维
- 稀疏向量：不在客户端生成，改由 Milvus 2.5 内置 BM25 Function 服务端自动产出
"""
from openai import OpenAI

from app.core.config import settings

EMBEDDING_MODEL = "text-embedding-v3"
EMBEDDING_DIM = 1024
_BATCH_SIZE = 10  # DashScope text-embedding-v3 单批上限（超过报 400: batch size is invalid）

_client: OpenAI | None = None


def get_embedding_client() -> OpenAI:
    """返回 DashScope OpenAI 兼容客户端（懒加载单例）。"""
    global _client
    if _client is None:
        api_key = settings.dashscope_api_key or settings.llm_api_key
        if not api_key:
            raise RuntimeError(
                "未配置 DASHSCOPE_API_KEY / LLM_API_KEY，无法调用 Embedding API"
            )
        # 客户端统一由 app/core/llm.py 工厂提供（dashscope）
        from app.core.llm import get_llm_client

        _client = get_llm_client(
            "dashscope", api_key=api_key, base_url=settings.dashscope_base_url
        )
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量编码文本为 1024 维稠密向量（自动按 25 条分批）。"""
    client = get_embedding_client()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        vectors.extend(item.embedding for item in resp.data)
    return vectors
