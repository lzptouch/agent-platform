"""技能轻量索引（S6 / WP-6.1.2/6.1.3）。

索引**只读 front matter**（name / description / version / triggers），
正文与 ``scripts/``、``references/``、``assets/`` **命中时才读**。

用途：
- 首轮上下文只放索引条目（体积远小于正文）；
- 命中触发词时才加载全文。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.chains.skills.spec import SkillSpec, SkillSpecError, validate


@dataclass(frozen=True)
class IndexEntry:
    """索引条目（不含正文）。"""

    name: str
    description: str
    version: str
    triggers: tuple[str, ...]
    path: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "triggers": list(self.triggers),
            "path": self.path,
        }

    @property
    def size(self) -> int:
        """索引条目自身的体积（近似 JSON 长度）。"""
        return len(str(self.as_dict()))


def _skill_md(skill_dir: Path) -> Path:
    return skill_dir / "SKILL.md"


def build_index(skills_dir: Path) -> list[IndexEntry]:
    """扫描技能目录，构建轻量索引（**不读正文**）。"""
    entries: list[IndexEntry] = []
    if not skills_dir.exists():
        return entries
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        md = _skill_md(skill_dir)
        if not md.exists():
            continue
        try:
            # 只读 front matter：validate 会顺带解析正文，但我们只用 front matter 字段
            spec = validate(md.read_text(encoding="utf-8", errors="replace"), expected_name=skill_dir.name)
        except (SkillSpecError, OSError):
            continue  # 非法技能不进索引
        entries.append(IndexEntry(
            name=spec.name,
            description=spec.description,
            version=spec.version,
            triggers=tuple(spec.triggers),
            path=str(skill_dir),
        ))
    return entries


def index_size(entries: list[IndexEntry]) -> int:
    """索引总体积（近似）。"""
    return sum(e.size for e in entries)


def match(entries: list[IndexEntry], query: str, *, top_k: int = 3) -> list[IndexEntry]:
    """按触发词/名称/描述匹配（命中才建议加载全文）。"""
    q = (query or "").strip().lower()
    if not q:
        return []
    scored: list[tuple[int, int, IndexEntry]] = []
    for idx, e in enumerate(entries):
        score = 0
        if q in e.name.lower():
            score += 60
        if q in e.description.lower():
            score += 30
        for trig in e.triggers:
            if q in trig.lower() or trig.lower() in q:
                score += 50
                break
        cjk = [c for c in q if "\u4e00" <= c <= "\u9fff"]
        if cjk:
            hits = sum(1 for c in cjk if c in f"{e.name} {e.description} {' '.join(e.triggers)}")
            if hits:
                score = max(score, int(20 * hits / len(cjk)))
        if score:
            scored.append((-score, idx, e))
    scored.sort()
    return [e for _, _, e in scored[:top_k]]


def load_body(entry: IndexEntry) -> SkillSpec:
    """**命中后**才读全文并校验。"""
    md = Path(entry.path) / "SKILL.md"
    return validate(md.read_text(encoding="utf-8", errors="replace"), expected_name=entry.name)


def resource_path(entry: IndexEntry, resource: str) -> Path | None:
    """取关联资源（``scripts/`` ``references/`` ``assets/``）路径。"""
    base = Path(entry.path) / resource
    if base.exists() and base.is_file():
        return base
    return None
