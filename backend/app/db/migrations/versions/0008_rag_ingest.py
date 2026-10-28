"""RAG 入库台账（批次 03 / WP-3.1）。

新增一表 ``rag_documents``：记录每个入库文档的**幂等键**
（文件绝对路径 + 内容哈希的 sha256），用于重复入库时跳过同样的文件，
避免 chunk 重复累积。

可回滚。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _has_table(bind, name: str) -> bool:
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "rag_documents"):
        return
    op.create_table(
        "rag_documents",
        sa.Column("doc_id", sa.Text(), primary_key=True),   # sha256(绝对路径|内容哈希)
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("collection", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_rag_documents_source", "rag_documents", ["source_path"])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "rag_documents"):
        op.drop_table("rag_documents")
