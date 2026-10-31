"""MCP 管理相关的请求/响应模型。"""
from pydantic import BaseModel, Field


class McpToolInfo(BaseModel):
    name: str
    description: str = ""


class McpServerInfo(BaseModel):
    name: str
    stage: str = ""
    description: str = ""
    status: str = Field(
        default="ready",
        description="真实连接状态：connected / disconnected / error / disabled（兼容旧的 ready）",
    )
    # P4-11：可读的失败/状态原因（列表页即可见，不必进详情页）
    reason: str = ""
    read_only: bool = False
    last_ok_at: str | None = None


class McpServerDetail(McpServerInfo):
    tools: list[McpToolInfo] = Field(default_factory=list)
    error: str | None = None


class McpServerListResponse(BaseModel):
    total: int
    servers: list[McpServerInfo]


class McpCallRequest(BaseModel):
    tool: str = Field(..., description="MCP 工具名")
    arguments: dict = Field(default_factory=dict)


class McpCallResponse(BaseModel):
    server: str
    tool: str
    result: str
    error: str | None = None
