"""RAG 链路相关的请求/响应模型。"""
from pydantic import BaseModel, Field


class RagQueryRequest(BaseModel):
    query: str = Field(..., description="用户问题")
    limit: int = Field(10, ge=1, le=50, description="检索返回条数")


class RagQueryResponse(BaseModel):
    query: str
    references: str = Field(..., description="带 [n] 编号的参考内容")
    answer: str


class IngestResponse(BaseModel):
    chunks: int
    entities: int
    collection: str


class RagStatsResponse(BaseModel):
    collection: str
    entities: int
    dense_dim: int
    embedding_model: str
    llm_available: bool
