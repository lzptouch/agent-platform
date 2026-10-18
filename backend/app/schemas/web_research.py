"""Web Research 链路相关的请求/响应模型。"""
from pydantic import BaseModel, Field


class WebResearchRequest(BaseModel):
    query: str = Field(..., description="研究问题")
    profile: str = Field("", description="LLM 角色，如 'conscientious researcher'")
    output_format: str = Field("", description="输出格式要求，可为空")


class WebResearchResponse(BaseModel):
    query: str
    answer: str
    reference_cards: list = Field(default_factory=list, description="引用卡片列表")


class WebResearchStatusResponse(BaseModel):
    serper_available: bool
    openai_available: bool
    openai_model: str
