# Milvus Lite 本地化与 BM25 混合检索（扩充版）

> - **整理日期**：2026-09-15（首发 2026-09-15 扩充）
> - **依据项目**：`apps/agent/backend/app/services/rag/` + `config.py`
> - **资料来源**：Milvus 官方文档 + Milvus Lite + BM25 论文 + RRF 论文 + Qdrant + Weaviate + LanceDB

---

# 第一章 原理

## 1.1 Milvus Lite 是什么

[Milvus Lite](https://milvus.io/docs/milvus_lite.md) = Milvus 的 Python 嵌入式版本，单文件存储，无需服务器。

| 维度 | Milvus Server | Milvus Lite（本项目） |
|------|--------------|---------------------|
| **部署** | Docker / K8s 集群 | `pip install pymilvus` |
| **存储** | etcd + MinIO + Pulsar | **单文件** `data/milvus.db` |
| **扩展** | 千万级向量 | 百万级 |
| **适用** | 生产 | POC / 单机 / 桌面 |
| **多副本** | ✅ | ❌ 仅单进程 |

## 1.2 BM25 混合检索

BM25 + Dense 双路融合：

```
用户 Query
   │
   ├──→ BM25（精确术语匹配，关键词权重）
   │      ↑
   │      服务端分词（Milvus 2.5+ BM25 Function）
   │
   ├──→ Dense 向量（语义匹配，余弦相似度）
   │      ↑
   │      DashScope text-embedding-v3 API
   │
   ↓
WeightedRanker (1.0, 0.7)  # ★ 融合两路结果
   ↓
Top-K 文档
```

### 1.2.1 为什么需要混合检索？

| 模式 | 优势 | 劣势 |
|------|------|------|
| **纯 BM25** | 精确关键词匹配 | 无语义；漏召回 |
| **纯 Dense** | 语义理解 | 漏精确词；同义词召回多 |
| **混合** | 兼顾两者 | 计算复杂度 +30% |

## 1.3 关键 Milvus 2.5 特性

- ✅ **BM25 Function**：服务端分词，无需本地分词器
- ✅ **Hybrid Search**：单次检索融合 BM25 + Dense
- ✅ **Milvus Lite**：单文件 Python 库
- ✅ **WeightedRanker**：动态权重融合

---

# 第二章 工程实现

## 2.1 关键配置（实测）

```python
# config.py:57-60
# ---------- RAG 链路（Embedding 走 DashScope API，无需本地模型）----------
# ⚠ 重要：不能用 MILVUS_URI 作环境变量名（pymilvus/settings.py import 时会 load_dotenv 抢占它）
milvus_db_path: str = "data/milvus.db"
milvus_collection: str = "hybrid_demo"
```

**重要细节**：注释说明不能用 `MILVUS_URI` 作环境变量名——`pymilvus/settings.py` 导入时会抢占。

## 2.2 Milvus Lite + BM25 Function 实现

```python
# services/rag/milvus_store.py
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

def create_collection(recreate: bool = False) -> Collection:
    """创建（或按需重建）混合检索 collection"""
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
    
    # 字段定义
    fields = [
        FieldSchema("pk", INT64, is_primary=True, auto_id=True),
        FieldSchema(
            "text", VARCHAR, max_length=2048,
            enable_analyzer=True,     # ★ BM25 需要服务端分词
        ),
        FieldSchema("sparse_vector", SPARSE_FLOAT_VECTOR),
        FieldSchema("dense_vector", FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]
    
    # ★ BM25 Function（核心创新）
    bm25_fn = Function(
        name="text_bm25",
        input_field_names=["text"],
        output_field_names=["sparse_vector"],
        function_type=FunctionType.BM25,
    )
    schema = CollectionSchema(fields, functions=[bm25_fn])
    
    # 建 Collection
    _col = Collection(col_name, schema, consistency_level="Strong")
    
    # 索引
    _col.create_index(
        "sparse_vector",
        {
            "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "BM25",
            "params": {"bm25_k1": 1.5, "bm25_b": 0.75},  # ★ BM25 参数
        }
    )
    _col.create_index("dense_vector", {"index_type": "AUTOINDEX", "metric_type": "IP"})
    
    _col.load()
    return _col
```

## 2.3 混合检索

```python
# services/rag/milvus_store.py
def hybrid_search(col, query_text, query_dense, sparse_weight=0.7, dense_weight=1.0, limit=10):
    """★ 双路融合检索"""
    # 1. BM25 路（服务端自动分词）
    sparse_req = AnnSearchRequest(
        data=[query_text],                  # ★ 直接传文本
        anns_field="sparse_vector",
        param={"metric_type": "BM25"},
        limit=limit,
    )
    
    # 2. Dense 路
    dense_req = AnnSearchRequest(
        data=[query_dense],                  # ★ 传 embedding
        anns_field="dense_vector",
        param={"metric_type": "IP"},
        limit=limit,
    )
    
    # 3. WeightedRanker 融合
    ranker = WeightedRanker(dense_weight, sparse_weight)
    
    # 4. 一次检索返回双路融合结果
    results = col.hybrid_search(
        reqs=[sparse_req, dense_req],
        ranker=ranker,
        limit=limit,
        output_fields=["text"],
    )
    
    return [hit.get("text") for hit in results[0]]
```

## 2.4 RAG 链（含引用）

```python
# services/rag/rag_chain.py
def retrieval(query: str, limit: int = 10) -> list[str]:
    """API 编码 query 后进行稠密+稀疏混合检索"""
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


RAG_PROMPT_TEMPLATE = """你是一个智能助手，负责根据用户的问题和提供的参考内容生成回答。请严格按照以下要求生成回答：
1. 回答必须基于提供的参考内容。
2. 在回答中，每一块内容都必须标注引用的来源，格式为：[引用编号]。例如：[1] 表示引用自第1条参考内容。
3. 如果没有参考内容，请明确说明。如果没有参考知识，根据你自己的知识进行回答

参考内容：
{formatted_references}

用户问题：{query}
"""


def rag(query: str) -> tuple[str, str]:
    """本地文档 RAG：检索 + LLM 生成带引用回答"""
    formatted_references = format_list_with_markers(retrieval(query))
    prompt = RAG_PROMPT_TEMPLATE.format(formatted_references=formatted_references, query=query)
    
    client = get_llm_client()
    completion = client.chat.completions.create(
        model=settings.rag_model,         # deepseek-v3.2
        messages=[{"role": "user", "content": prompt}],
    )
    return formatted_references, completion.choices[0].message.content
```

## 2.5 Embedding 调用

```python
# services/rag/embedding.py
import httpx

def embed_texts(texts: list[str]) -> list[list[float]]:
    """DashScope API Embedding（text-embedding-v3，1024 维）"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.dashscope_base_url}/embeddings",
            headers={"Authorization": f"Bearer {settings.dashscope_api_key}"},
            json={"model": settings.embedding_model, "input": texts},
            timeout=30,
        )
    data = response.json()
    return [item["embedding"] for item in data["data"]]
```

---

# 第三章 业界做法调研

## 3.1 向量数据库横向对比

| 方案 | 部署 | 性能 | 持久化 | 适用 |
|------|------|------|--------|------|
| **Milvus Lite**（本项目） | 嵌入式 | 百万级 | ✅ 文件 | POC/桌面 |
| **Milvus Standalone** | Docker | 千万级 | ✅ 服务 | 中小生产 |
| **Milvus Cluster** | K8s | 亿级 | ✅ 分布式 | 大规模 |
| **Qdrant** | Rust 单文件/集群 | 千万级 | ✅ | 性能优先 |
| **Weaviate** | Go 集群 | 千万级 | ✅ | GraphQL 集成 |
| **Chroma** | Python 嵌入式 | 万级 | ✅ | 原型 |
| **pgvector** | PG 扩展 | 百万级 | ✅ | 已用 PG |
| **LanceDB** | Rust 列式 | 百万级 | ✅ | Serverless |
| **Weaviate** | Go | 千万级 | ✅ | 模块化 |

## 3.2 BM25 实现对比

| 方案 | 分词器 | 集成方式 |
|------|--------|---------|
| **Milvus BM25 Function** | 服务端自动 | Function 配置 |
| **Elasticsearch BM25** | 内置 | analyzer + query |
| **Whoosh** | jieba / 自定义 | Python 库 |
| **rank_bm25** | jieba / 自定义 | Python 库 |
| **Milvus Sparse Vector** | 服务端 | BM25 Function |

## 3.3 Milvus Lite 限制（官方）

- ⚠️ 仅支持单进程访问
- ⚠️ 不支持分布式
- ⚠️ 不支持 Query Node 高可用
- ❌ **不推荐生产用** —— 仅适合单机 POC

## 3.4 Hybrid Search 业界做法

| 方案 | 融合算法 | 优势 |
|------|---------|------|
| **Milvus WeightedRanker** | 加权求和 | 简单；可调 |
| **RRF** (Cormack 2009) | 倒数排名融合 | 不需调权 |
| **Cross-Encoder Rerank** | 双向编码重排 | 精度高 |
| **ColBERT** | Token 级匹配 | 细粒度 |

---

# 第四章 操作步骤

## 4.1 P1-1：Milvus Lite 升级到 Milvus Standalone（生产）

```yaml
# docker-compose.yml
services:
  milvus:
    image: milvusdb/milvus:v2.5-latest
    command: ["milvus", "run", "standalone"]
    ports:
      - "19530:19530"
      - "9091:9091"
    volumes:
      - milvus_data:/var/lib/milvus
    depends_on:
      - etcd
      - minio
```

```python
# config.py
MILVUS_URI = "http://milvus:19530"   # ★ 从文件路径改为 HTTP
```

## 4.2 P1-2：BM25 参数调优

```python
# BM25 参数
params = {
    "bm25_k1": 1.2,    # 词频饱和度（1.2-2.0，常用 1.5）
    "bm25_b": 0.75,    # 文档长度归一化（0-1，常用 0.75）
}
```

**调优建议**：
- 技术文档：`k1=1.5, b=0.75`（默认）
- 长文档：`k1=1.2, b=0.5`（减少长度归一化）
- 短查询：`k1=2.0, b=0.75`（增强词频）

## 4.3 P1-3：切块策略

```python
# services/rag/chunking.py
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """简单切块"""
    chunks = []
    for i in range(0, len(text), chunk_size - overlap):
        chunks.append(text[i:i + chunk_size])
    return chunks


# 更优：按语义切块
def semantic_chunk(text: str, embeddings_model) -> list[str]:
    """按段落 + 语义相似度切块"""
    paragraphs = text.split("\n\n")
    # 用 embedding 计算段落相似度
    # 相似度高的合并，低的拆分
    ...
```

## 4.4 P2-1：备份策略

```bash
# Lite 模式：直接复制 db 文件
cp data/milvus.db backup/milvus-$(date +%Y%m%d).db

# Standalone：用 milvus-cli backup 命令
milvus_cli backup create --collection hybrid_demo
```

## 4.5 P2-2：Cross-Encoder Rerank

```python
# 加 Cross-Encoder 提高精度
from sentence_transformers import CrossEncoder

class Reranker:
    def __init__(self):
        self.model = CrossEncoder("BAAI/bge-reranker-base")
    
    def rerank(self, query: str, documents: list[str], top_k: int = 5):
        pairs = [[query, doc] for doc in documents]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)
        return [doc for doc, score in ranked[:top_k]]
```

---

## 附录 A：参考文献

| # | 类型 | 标题 | 来源 | 访问日期 |
|---|------|------|------|----------|
| [1] | 官方文档 | Milvus Lite | https://milvus.io/docs/milvus_lite.md | 2026-09-15 |
| [2] | 官方文档 | Milvus Hybrid Search | https://milvus.io/docs/multi-vector-search.md | 2026-09-15 |
| [3] | 官方文档 | Milvus BM25 Function | https://milvus.io/docs/full-text-search.md | 2026-09-15 |
| [4] | 官方文档 | pymilvus | https://milvus.io/api-reference/pymilvus/v2.5.x/About.md | 2026-09-15 |
| [5] | 官方文档 | Milvus Standalone | https://milvus.io/docs/install_standalone-docker.md | 2026-09-15 |
| [6] | 论文 | BM25 (Robertson 1994) | https://www.staff.city.ac.uk/~sb317/papers/foundations_bm25_review.pdf | 2026-09-15 |
| [7] | 论文 | RRF (Cormack 2009) | https://dl.acm.org/doi/10.1145/1571941.1572114 | 2026-09-15 |
| [8] | OSS 项目 | Qdrant | https://github.com/qdrant/qdrant | 2026-09-15 |
| [9] | OSS 项目 | Weaviate | https://github.com/weaviate/weaviate | 2026-09-15 |
| [10] | 官方文档 | LanceDB | https://lancedb.github.io/lancedb/ | 2026-09-15 |
| [11] | OSS 库 | sentence-transformers (CrossEncoder) | https://github.com/UKPLab/sentence-transformers | 2026-09-15 |
| [12] | 官方文档 | DashScope Embedding | https://help.aliyun.com/zh/model-studio/developer-reference/use-embedding-by-calling-api | 2026-09-15 |
| [13] | 同源文档 | `apps/finance-report/backend/app/tools/rag_search.py` | 内存 RAG 对比 | 2026-09-15 |
| [14] | 同源文档 | `apps/industry-research/doc/analysis/04_五端一致性.md` | PG + Milvus Server | 2026-09-15 |

---

> **本文档结构遵循「五段式」**：当前实现 → 原理剖析 → 业界做法调研 → 操作步骤 → 参考文献附录。
