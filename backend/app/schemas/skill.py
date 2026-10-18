"""Skill 相关的响应模型。"""

from pydantic import BaseModel, Field


class SkillMeta(BaseModel):
    """Skill 元数据（第一级披露：name + description）。"""

    name: str
    description: str = ""
    path: str = Field(description="Skill 目录相对项目根目录的路径")
    skill_md_path: str = Field(description="SKILL.md 绝对路径（供工具读取）")
    skill_md_rel: str = Field(description="SKILL.md 相对路径（供展示）")
    resources: list[str] = Field(default_factory=list, description="打包资源文件相对路径列表")
    source: str = Field(default="builtin", description="builtin=内置（只读） / custom=用户自定义")
    enabled: bool = True


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    description: str = Field(min_length=1, max_length=1024)
    content: str = Field(default="", description="SKILL.md 正文（frontmatter 自动生成）")


class SkillUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=1024)
    content: str | None = None


class SkillToggle(BaseModel):
    enabled: bool


class SkillDetail(SkillMeta):
    """Skill 详情（第二级披露：完整 SKILL.md 内容）。"""

    content: str


class SkillListResponse(BaseModel):
    total: int
    skills: list[SkillMeta]


class ValidationResult(BaseModel):
    valid: bool
    message: str
    name: str | None = None
