"""数据入库：解析 data/pdf/ 下的 PDF -> 切块 -> DashScope API 编码 -> 写入 Milvus。"""
import logging
from pathlib import Path

import pymupdf4llm

from app.core.config import settings
from app.services.rag.chunking import chunk_text
from app.services.rag.embedding import embed_texts
from app.services.rag.milvus_store import create_collection, insert_chunks

logger = logging.getLogger(__name__)


def parse_pdfs(data_dir: str | None = None) -> str:
    """用 pymupdf4llm 将目录下所有 PDF 解析为 markdown 文本并拼接。"""
    data_path = Path(data_dir or settings.pdf_dir)
    pdf_files = sorted(data_path.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"{data_path} 下没有找到 PDF 文件")

    all_doc = ""
    for pdf in pdf_files:
        logger.info("解析 PDF: %s", pdf.name)
        all_doc += pymupdf4llm.to_markdown(str(pdf)) + "\n"
    return all_doc


def ingest(recreate: bool = True) -> dict:
    """完整入库流程，返回统计信息。"""
    all_doc = parse_pdfs()
    chunks = chunk_text(all_doc, max_chunk_size=300)
    logger.info("共切分 %d 个 chunk", len(chunks))

    dense_vectors = embed_texts(chunks)
    logger.info("API 编码完成，共 %d 条向量", len(dense_vectors))

    col = create_collection(recreate=recreate)
    num = insert_chunks(chunks, dense_vectors)
    logger.info("入库完成，collection 共 %d 条数据", num)
    return {"chunks": len(chunks), "entities": num, "collection": col.name}
