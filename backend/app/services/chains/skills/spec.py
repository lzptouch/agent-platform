"""SKILL.md 规范与校验（S6 / WP-6.1）。

front matter 字段：
``name / description / version / triggers / tools / requires / risk``

- 校验失败**立即拒绝**（非法即拒）；
- 索引器只读 front matter（体积远小于正文）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

#: 允许的 front matter 字段（**单一真相源**）。
#:
#: **P2-06**：此前存在两套互不相同的白名单——本文件的 ``ALLOWED_FIELDS``
#: （旧规范：version/triggers/tools/requires/risk）与
#: ``skill_manager.ALLOWED_PROPERTIES``（Anthropic 风格：license/allowed-tools/
#: metadata/compatibility）。两套并存时，内置 Skill 里**带 ``license`` 的三个**
#: （frontend-design / pdf / skill-creator）会被本规范**静默跳过**。
#:
#: 现在统一为**两套的并集**，且 ``skill_manager`` 直接引用本常量——
#: 任何新增字段只需改这一处。
ALLOWED_FIELDS = (
    # 现行规范（skill_manager 使用）
    "name", "description", "license", "allowed-tools", "metadata", "compatibility",
    # 旧规范（历史 Skill 兼容）
    "version", "triggers", "tools", "requires", "risk",
)

#: 风险等级
RISK_LEVELS = ("low", "medium", "high", "critical")

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,63}$")
_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


class SkillSpecError(ValueError):
    """技能规范不合法。"""


@dataclass
class SkillSpec:
    """一份技能规范。"""

    name: str
    description: str = ""
    version: str = "0.1.0"
    triggers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    risk: str = "low"
    # P2-06：白名单统一为两套并集后，这些字段必须被**保留**
    # （此前 validate() 会静默丢弃它们——即使白名单允许）。
    license: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    compatibility: dict = field(default_factory=dict)
    body: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "license": self.license,
            "allowed_tools": list(self.allowed_tools),
            "metadata": dict(self.metadata),
            "compatibility": dict(self.compatibility),
            "triggers": list(self.triggers),
            "tools": list(self.tools),
            "requires": list(self.requires),
            "risk": self.risk,
        }

    def index_entry(self) -> dict:
        """轻量索引条目（**不含正文**）。"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "triggers": list(self.triggers),
        }


def _parse_scalar(raw: str):
    raw = raw.strip()
    if raw.startswith("[") or raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return [p.strip() for p in raw.strip("[]").split(",") if p.strip()]
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    return raw.strip('"').strip("'")


def _parse_frontmatter_lines(raw: str) -> dict:
    """逐行解析 front matter（**不支持嵌套**）——YAML 解析失败时的回退路径。"""
    fields: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise SkillSpecError(f"front matter 行格式错误: {line[:40]}")
        key, value = line.split(":", 1)
        key = key.strip()
        if key not in ALLOWED_FIELDS:
            raise SkillSpecError(f"未知 front matter 字段: {key}")
        fields[key] = _parse_scalar(value)
    return fields


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 front matter，返回 ``(字段字典, 正文)``。

    **P2-06 修复**：此前是**逐行**解析——**不支持嵌套结构**，导致
    ``metadata:`` / ``compatibility:`` 下的子键被当成顶层字段，
    报「未知 front matter 字段: team」——即「补齐这两个字段」实际**不可用**。

    现改为 **YAML 解析**（项目已依赖 ``pyyaml``），保留未知字段校验；
    YAML 不可用或解析失败时回退到逐行模式（兼容非标准写法）。
    """
    m = _FM_RE.match(content or "")
    if not m:
        raise SkillSpecError("缺少 front matter（--- 包裹）")
    raw, body = m.group(1), m.group(2)

    fields: dict = {}
    try:
        import yaml

        parsed = yaml.safe_load(raw)
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            raise SkillSpecError("front matter 必须是键值映射")
        fields = {str(k): v for k, v in parsed.items()}
    except SkillSpecError:
        raise
    except Exception:  # noqa: BLE001 - YAML 不可用/语法错误 → 回退逐行
        fields = _parse_frontmatter_lines(raw)

    for key in fields:
        if key not in ALLOWED_FIELDS:
            raise SkillSpecError(f"未知 front matter 字段: {key}")
    return fields, body


def validate(content: str, *, expected_name: str | None = None) -> SkillSpec:
    """校验 SKILL.md 内容，合法返回 ``SkillSpec``，否则抛 ``SkillSpecError``。"""
    fields, body = parse_frontmatter(content)
    name = str(fields.get("name", "")).strip()
    if not name:
        raise SkillSpecError("缺少 name")
    if not _NAME_RE.match(name):
        raise SkillSpecError(f"name 格式非法（只允许小写字母/数字/-/_，≤64）: {name}")
    if expected_name and name != expected_name:
        raise SkillSpecError(f"name 与目录名不一致: {name} != {expected_name}")

    description = str(fields.get("description", "")).strip()
    if not description:
        raise SkillSpecError("缺少 description")

    version = str(fields.get("version", "0.1.0")).strip()
    if not re.match(r"^\d+\.\d+\.\d+", version):
        raise SkillSpecError(f"version 非法: {version}")

    def _as_list(key: str) -> list[str]:
        val = fields.get(key, [])
        if isinstance(val, str):
            val = [val]
        if not isinstance(val, list):
            raise SkillSpecError(f"{key} 必须是数组")
        return [str(v).strip() for v in val if str(v).strip()]

    risk = str(fields.get("risk", "low")).strip().lower()
    if risk not in RISK_LEVELS:
        raise SkillSpecError(f"risk 必须是 {'/'.join(RISK_LEVELS)} 之一: {risk}")

    # P2-06：保留白名单里的其余字段（此前被静默丢弃）
    metadata = fields.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise SkillSpecError("metadata 必须是对象")
    compatibility = fields.get("compatibility") or {}
    if not isinstance(compatibility, dict):
        raise SkillSpecError("compatibility 必须是对象")

    return SkillSpec(
        name=name,
        description=description,
        version=version,
        triggers=_as_list("triggers"),
        tools=_as_list("tools"),
        requires=_as_list("requires"),
        risk=risk,
        license=str(fields.get("license", "")).strip(),
        allowed_tools=_as_list("allowed-tools"),
        metadata=dict(metadata),
        compatibility=dict(compatibility),
        body=body,
    )


def build_skill_md(
    name: str,
    description: str,
    body: str,
    *,
    version: str = "0.1.0",
    triggers: list[str] | None = None,
    tools: list[str] | None = None,
    requires: list[str] | None = None,
    risk: str = "low",
) -> str:
    """生成规范的 SKILL.md 文本。"""
    def _arr(values: list[str] | None) -> str:
        return json.dumps(list(values or []), ensure_ascii=False)

    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"version: {version}\n"
        f"triggers: {_arr(triggers)}\n"
        f"tools: {_arr(tools)}\n"
        f"requires: {_arr(requires)}\n"
        f"risk: {risk}\n"
        "---\n\n"
        f"{body.strip()}\n"
    )
