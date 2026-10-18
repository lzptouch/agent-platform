"""本地文档 RAG 链路：API Embedding + Milvus 混合检索 + LLM 带引用回答。"""
from app.core.config import settings
from app.core.llm import get_llm_client
from app.services.rag.embedding import embed_texts
from app.services.rag.milvus_store import get_collection, hybrid_search

RAG_PROMPT_TEMPLATE = """你是一个智能助手，负责根据用户的问题和提供的参考内容生成回答。请严格按照以下要求生成回答：
1. 回答必须基于提供的参考内容。
2. 在回答中，每一块内容都必须标注引用的来源，格式为：[引用编号]。例如：[1] 表示引用自第1条参考内容。
3. 如果没有参考内容，请明确说明。如果没有参考知识，根据你自己的知识进行回答

参考内容：
{formatted_references}

用户问题：{query}
"""


def format_list_with_markers(input_list: list[str]) -> str:
    """为列表添加 [1] [2] ... 编号并逐行拼接。"""
    return "".join(f"[{index}] {item}\n" for index, item in enumerate(input_list, 1))


def retrieval(query: str, limit: int = 10) -> list[str]:
    """API 编码 query 后进行稠密+稀疏混合检索。"""
    query_dense = embed_texts([query])[0]
    col = get_collection()
    return hybrid_search(
        col,
        query_text=query,
        query_dense=query_dense,
        sparse_weight=0.7,
        dense_weight=1.0,
        limit=limit,
    )


def rag(query: str) -> tuple[str, str]:
    """
    本地文档 RAG：检索 + LLM 生成带引用回答。

    Returns:
        (formatted_references, answer)
    """
    formatted_references = format_list_with_markers(retrieval(query))
    prompt = RAG_PROMPT_TEMPLATE.format(formatted_references=formatted_references, query=query)

    client = get_llm_client()
    completion = client.chat.completions.create(
        model=settings.rag_model,
        messages=[{"role": "user", "content": prompt}],
    )
    return formatted_references, completion.choices[0].message.content
