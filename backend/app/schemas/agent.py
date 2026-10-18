"""Agent 相关的请求模型。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.config import settings


class RunRequest(BaseModel):
    """一次 Agent 运行请求。

    mode 语义（对标 WorkBuddy）：
    - ``chat``（Ask）：只读工具，多轮上下文，默认不注入 Skill；
    - ``work``（Craft）：全量工具，可直接产出文件；
    - ``work + plan_first``（Plan）：先产出计划，等待人工确认后执行。
    """

    prompt: str = Field(min_length=1, description="用户请求内容")
    model: str = Field(default=settings.default_model, description="模型 ID")
    mode: Literal["chat", "work"] = Field(default="work", description="对话 / 工作模式")
    session_id: str | None = Field(default=None, description="会话 ID；提供则加载历史并落盘消息")
    team_id: str | None = Field(default=None, description="Skill 团队 ID（与 skills 互斥）")
    plan_first: bool = Field(default=False, description="工作模式：先出计划，待确认后执行")
    skills: list[str] | None = Field(
        default=None,
        description="本次启用的 Skill 名称列表。work 模式 None = 全部；[] = 不启用；chat 模式 None = 不启用",
    )
    enable_mcp: bool = Field(default=False, description="启用 MCP 工具")
    mcp_servers: list[str] = Field(default_factory=list, description="启用的 MCP Server 列表")
    enable_rag: bool = Field(default=False, description="启用本地文档 RAG 工具")
    enable_web_research: bool = Field(default=False, description="启用实时网络检索工具")
    enable_reflection: bool = Field(default=False, description="启用 plan→action→reflection→answer 反思循环")

    @model_validator(mode="after")
    def _cross_check(self):
        if self.mode == "chat" and self.plan_first:
            raise ValueError("对话模式不支持 plan_first")
        if self.team_id and self.skills:
            raise ValueError("team_id 与 skills 互斥，只能二选一")
        return self


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str


class ModelsResponse(BaseModel):
    default_model: str
    models: list[ModelInfo]


class RunResult(BaseModel):
    """非流式运行的汇总结果。"""

    model: str
    prompt: str
    rounds: int
    finished: bool
    files: list[str] = Field(default_factory=list)
    error: str | None = None
    # 会话/运行账本（WorkBuddy 扩展）
    run_id: str | None = None
    session_id: str | None = None
    mode: Literal["chat", "work"] = "work"
    answer: str = ""


class AgentChatRequest(BaseModel):
    """WR 范式销售助手 Agent 请求（plan→action→reflection→answer）。"""

    query: str = Field(..., description="用户问题")
    reflection: bool = Field(False, description="是否启用反思（Reflexion）流程")


class AgentChatResponse(BaseModel):
    query: str
    plan: list = Field(default_factory=list)
    reflection_plan: list | None = None
    memory: list = Field(default_factory=list)
    reasoning: str = ""
    answer: str
