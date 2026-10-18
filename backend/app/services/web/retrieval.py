"""网页内容向量召回：切块 -> DashScope API 编码 -> Chroma 内存库检索。"""
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.services.rag.embedding import EMBEDDING_MODEL
from app.services.web.fetch_web_content import WebContentFetcher


def _get_embedding() -> OpenAIEmbeddings:
    """DashScope OpenAI 兼容接口的 Embedding（替代本地 all-MiniLM-L6-v2）。"""
    api_key = settings.dashscope_api_key or settings.llm_api_key
    if not api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY / LLM_API_KEY，无法调用 Embedding API")
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        api_key=api_key,
        base_url=settings.dashscope_base_url,
    )


class EmbeddingRetriever:
    TOP_K = 20  # Number of top K documents to retrieve

    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=0
        )

    def retrievel_embeddings(self, contents_list: list, link_list: list, query: str):
        metadatas = [{'url': link} for link in link_list]
        texts = self.text_splitter.create_documents(contents_list, metadatas=metadatas)

        db = Chroma.from_documents(
            documents=texts,
            embedding=_get_embedding(),
        )

        retriever = db.as_retriever(search_kwargs={"k": min(self.TOP_K, len(texts))})
        return retriever.invoke(query)


def web_retrieval(query):
    web_contents_fetcher = WebContentFetcher(query)
    web_contents, serper_response = web_contents_fetcher.fetch()

    retriever = EmbeddingRetriever()
    relevant_docs_list = retriever.retrievel_embeddings(web_contents, serper_response['links'], query)
    return relevant_docs_list
