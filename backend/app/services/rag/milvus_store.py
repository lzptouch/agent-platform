"""Milvus Lite 向量库：API 稠密向量 + 服务端 BM25 稀疏向量混合检索。

- 稠密向量：客户端经 DashScope API 编码后写入
- 稀疏向量：Milvus 2.5 内置 BM25 Function，在写入/查询时由服务端对 ``text`` 字段自动分词产出，
  无需本地分词器或本地模型
"""
import logging

from pymilvus import (
    AnnSearchRequest,
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    Function,
    FunctionType,
    WeightedRanker,
    connections,
    utility,
)

from app.core.config import settings
from app.services.rag.embedding import EMBEDDING_DIM

logger = logging.getLogger(__name__)

_col: Collection | None = None
_connected = False


def _connect() -> None:
    global _connected
    if not _connected:
        connections.connect(uri=settings.milvus_db_abs)
        _connected = True


def create_collection(recreate: bool = False) -> Collection:
    """创建（或按需重建）混合检索 collection 并载入内存。"""
    global _col
    _connect()
    col_name = settings.milvus_collection

    if utility.has_collection(col_name):
        if recreate:
            Collection(col_name).drop()
        else:
            _col = Collection(col_name, consistency_level="Strong")
            _col.load()
            return _col

    fields = [
        FieldSchema(name="pk", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(
            name="text",
            dtype=DataType.VARCHAR,
            max_length=2048,
            enable_analyzer=True,  # BM25 需要服务端分词
        ),
        FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
        FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]
    # BM25 Function：服务端自动把 text 转成稀疏向量写入 sparse_vector
    bm25_fn = Function(
        name="text_bm25",
        input_field_names=["text"],
        output_field_names=["sparse_vector"],
        function_type=FunctionType.BM25,
    )
    schema = CollectionSchema(fields, functions=[bm25_fn])
    _col = Collection(col_name, schema, consistency_level="Strong")
    _col.create_index(
        "sparse_vector",
        {
            "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "BM25",
            "params": {"bm25_k1": 1.5, "bm25_b": 0.75},
        },
    )
    _col.create_index("dense_vector", {"index_type": "AUTOINDEX", "metric_type": "IP"})
    _col.load()
    return _col


def get_collection() -> Collection:
    """获取已存在的 collection；不存在时自动创建空 collection。"""
    global _col
    if _col is None:
        _connect()
        if utility.has_collection(settings.milvus_collection):
            _col = Collection(settings.milvus_collection, consistency_level="Strong")
            _col.load()
        else:
            logger.warning(
                "collection %s 不存在，自动创建空集合（请先运行 scripts/ingest_data 入库数据）",
                settings.milvus_collection,
            )
            _col = create_collection(recreate=False)
    return _col


def insert_chunks(chunks: list[str], dense_vectors: list[list[float]], batch_size: int = 50) -> int:
    """分批插入文本与稠密向量（稀疏向量由 BM25 Function 服务端自动生成）。"""
    col = get_collection()
    for i in range(0, len(chunks), batch_size):
        col.insert([
            chunks[i : i + batch_size],
            dense_vectors[i : i + batch_size],
        ])
    col.flush()
    return col.num_entities


def hybrid_search(
    col: Collection,
    query_text: str,
    query_dense: list[float],
    sparse_weight: float = 0.7,
    dense_weight: float = 1.0,
    limit: int = 10,
) -> list[str]:
    """稠密+稀疏混合检索。稀疏腿直接传原始 query 文本，由服务端 BM25 Function 编码。"""
    dense_req = AnnSearchRequest(
        [query_dense], "dense_vector", {"metric_type": "IP", "params": {}}, limit=limit
    )
    sparse_req = AnnSearchRequest(
        [query_text], "sparse_vector", {"metric_type": "BM25", "params": {}}, limit=limit
    )
    rerank = WeightedRanker(sparse_weight, dense_weight)
    res = col.hybrid_search(
        [sparse_req, dense_req], rerank=rerank, limit=limit, output_fields=["text"]
    )[0]
    return [hit.get("text") for hit in res]
