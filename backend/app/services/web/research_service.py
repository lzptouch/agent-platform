"""Web Research 链路编排：Serper 搜索 -> 爬虫 -> Chroma 召回 -> GPT 带引用回答 -> 引用定位。"""
from app.core.config import settings
from app.services.web.fetch_web_content import WebContentFetcher
from app.services.web.llm_answer import GPTAnswer
from app.services.web.locate_reference import ReferenceLocator
from app.services.web.retrieval import EmbeddingRetriever


def web_research(query: str, profile: str = "", output_format: str = "") -> dict:
    if not settings.serper_api_key:
        raise RuntimeError("未配置 SERPER_API_KEY，网络检索不可用")
    if not settings.openai_api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，Web Research 回答生成不可用")

    fetcher = WebContentFetcher(query)
    web_contents, serper_response = fetcher.fetch()
    if not serper_response:
        raise RuntimeError("Serper 搜索无结果")

    retriever = EmbeddingRetriever()
    relevant_docs = retriever.retrievel_embeddings(web_contents, serper_response["links"], query)

    gpt = GPTAnswer()
    formatted_relevant_docs = gpt.format_reference(relevant_docs, serper_response["links"])
    ai_message = gpt.get_answer(query, formatted_relevant_docs, serper_response["language"], output_format, profile)
    answer = ai_message.content

    cards = ReferenceLocator(answer, serper_response).locate_source()
    return {
        "query": query,
        "answer": answer,
        "reference_cards": cards if cards != -1 else [],
    }
