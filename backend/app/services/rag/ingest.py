"""数据入库：解析 data/pdf/ 下的 PDF -> 切块 -> DashScope API 编码 -> 写入 Milvus。

**幂等（批次 03 / WP-3.1）**：按「文件绝对路径 + 内容哈希」做幂等键，
同一文件重复入库**不会新增 chunk**（跳过 + 记台账）；文件内容变了则重新入库，
并清掉旧版本的 chunk。
"""
import logging
from pathlib import Path

import pymupdf4llm

from app.core.config import settings
from app.services.rag import ledger
from app.services.rag.chunking import chunk_text
from app.services.rag.embedding import embed_texts
from app.services.rag.milvus_store import (
    create_collection,
    delete_by_doc_id,
    insert_chunks,
)

logger = logging.getLogger(__name__)


def parse_pdfs(data_dir: str | None = None) -> str:
    """用 pymupdf4llm 将目录下所有 PDF 解析为 markdown 文本并拼接（兼容旧调用）。"""
    data_path = Path(data_dir or settings.pdf_dir)
    pdf_files = sorted(data_path.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"{data_path} 下没有找到 PDF 文件")

    all_doc = ""
    for pdf in pdf_files:
        logger.info("解析 PDF: %s", pdf.name)
        all_doc += pymupdf4llm.to_markdown(str(pdf)) + "\n"
    return all_doc


def _parse_one(path: Path) -> str:
    return pymupdf4llm.to_markdown(str(path))


def ingest(recreate: bool = False, data_dir: str | None = None) -> dict:
    """入库流程（幂等）。返回统计信息。

    参数:
        recreate: True = 重建 collection（同时清空台账，全量重灌）；
            False = 增量（跳过已入库且内容未变的文件）。
    """
    sources = ledger.iter_sources(data_dir)
    if not sources:
        raise FileNotFoundError(f"{data_dir or settings.pdf_dir} 下没有找到 PDF 文件")

    by_source = ledger.ledger_by_source()
    if recreate:
        logger.info("重建模式：清空台账并重建 collection")
        ledger.clear_ledger()
        by_source = {}

    col = create_collection(recreate=recreate)
    collection_name = col.name

    ingested = 0
    skipped = 0
    removed = 0
    total_chunks = 0

    for src in sources:
        known = by_source.get(src.abs_path, [])
        if any(row.doc_id == src.doc_id for row in known):
            # 内容未变 → 幂等跳过（不 embed、不写 chunk）
            logger.info("跳过（已入库，内容未变）: %s", src.path.name)
            skipped += 1
            continue

        # 内容变了 → 旧版本的 chunk 要删掉，否则会残留
        for row in known:
            try:
                delete_by_doc_id(row.doc_id)
                removed += 1
            except Exception as exc:  # noqa: BLE001 —— 删不掉不该阻断入库
                logger.warning("删除旧 chunk 失败 %s: %s", row.doc_id, exc)
            ledger.drop_document(row.doc_id)

        logger.info("解析 PDF: %s", src.path.name)
        text = _parse_one(src.path)
        chunks = chunk_text(text, max_chunk_size=300)
        if not chunks:
            logger.warning("空文档，跳过: %s", src.path.name)
            continue

        dense_vectors = embed_texts(chunks)
        insert_chunks(chunks, dense_vectors, doc_ids=[src.doc_id] * len(chunks))
        ledger.record_document(
            doc_id=src.doc_id,
            source_path=src.abs_path,
            file_hash=src.content_hash,
            chunk_count=len(chunks),
            collection=collection_name,
        )
        ingested += 1
        total_chunks += len(chunks)
        logger.info("已入库 %s：%d 个 chunk", src.path.name, len(chunks))

    logger.info(
        "入库完成：新增 %d 个文档 / %d 个 chunk，跳过 %d，清理旧版本 %d",
        ingested, total_chunks, skipped, removed,
    )
    return {
        "chunks": total_chunks,
        "entities": col.num_entities,
        "collection": collection_name,
        "ingested": ingested,
        "skipped": skipped,
        "removed": removed,
        "documents": len(sources),
    }
