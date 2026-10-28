"""RAG 入库台账（批次 03 / WP-3.1）。

**幂等键**：``doc_id = sha256(文件绝对路径 | 文件内容哈希)``。

- 同一路径 + 同一内容 → 同一个 ``doc_id`` → 重复入库**跳过**，chunk 不累积；
- 同一路径 + 内容变了 → ``doc_id`` 变了 → 重新入库，并把旧 ``doc_id`` 的 chunk 删掉；
- 台账落 DB（``rag_documents`` 表），进程重启后仍然有效 → ``RUN_INGEST`` 幂等。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.db.base import db_session
from app.db.models import RagDocumentRow, utc_now

logger = logging.getLogger(__name__)

#: 幂等键长度（sha256 前 40 位，够用且短）
DOC_ID_LENGTH = 40


def content_hash(path: str | Path) -> str:
    """文件内容哈希（sha256 十六进制）。"""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_doc_id(abs_path: str, file_hash: str) -> str:
    """幂等键：绝对路径 + 内容哈希 → 稳定 id。"""
    raw = f"{Path(abs_path).as_posix()}|{file_hash}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:DOC_ID_LENGTH]


@dataclass(frozen=True)
class SourceDocument:
    """待入库的一个源文件（已算出幂等键）。"""

    path: Path
    abs_path: str
    content_hash: str
    doc_id: str


def iter_sources(data_dir: str | Path | None = None) -> list[SourceDocument]:
    """扫描目录下的 PDF，算出每个文件的幂等键（**不解析内容**，解析很贵）。"""
    from app.core.config import settings

    root = Path(data_dir) if data_dir else Path(settings.pdf_dir)
    sources: list[SourceDocument] = []
    for pdf in sorted(root.glob("*.pdf")):
        abs_path = str(pdf.resolve())
        try:
            file_hash = content_hash(pdf)
        except OSError:
            logger.warning("读取失败，跳过: %s", pdf)
            continue
        sources.append(
            SourceDocument(
                path=pdf,
                abs_path=abs_path,
                content_hash=file_hash,
                doc_id=make_doc_id(abs_path, file_hash),
            )
        )
    return sources


# --------------------------------------------------------------------------- #
# 台账读写
# --------------------------------------------------------------------------- #
def load_ledger() -> dict[str, RagDocumentRow]:
    """读台账：``doc_id`` → 行。"""
    with db_session() as db:
        rows = db.scalars(select(RagDocumentRow)).all()
        return {row.doc_id: row for row in rows}


def ledger_by_source() -> dict[str, list[RagDocumentRow]]:
    """按源路径分组（一个文件可能有多个历史版本 → 需要清理旧 chunk）。"""
    out: dict[str, list[RagDocumentRow]] = {}
    for row in load_ledger().values():
        out.setdefault(row.source_path, []).append(row)
    return out


def record_document(
    doc_id: str,
    source_path: str,
    file_hash: str,
    chunk_count: int,
    collection: str = "",
) -> None:
    """写入/更新一条台账。"""
    now = utc_now()
    with db_session() as db:
        row = db.get(RagDocumentRow, doc_id)
        if row is None:
            row = RagDocumentRow(
                doc_id=doc_id,
                source_path=source_path,
                content_hash=file_hash,
                chunk_count=chunk_count,
                collection=collection,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        else:
            row.source_path = source_path
            row.content_hash = file_hash
            row.chunk_count = chunk_count
            row.collection = collection
            row.updated_at = now


def drop_document(doc_id: str) -> None:
    """删除一条台账（对应 chunk 已删）。"""
    with db_session() as db:
        row = db.get(RagDocumentRow, doc_id)
        if row is not None:
            db.delete(row)


def clear_ledger() -> int:
    """清空台账（collection 被重建时调用）。"""
    with db_session() as db:
        rows = db.scalars(select(RagDocumentRow)).all()
        count = len(rows)
        for row in rows:
            db.delete(row)
        return count
