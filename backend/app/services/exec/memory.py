"""三层记忆与预筛（S5 / WP-5.4）。

三层作用域：
- **user**：跨项目的用户级规则（``{data_dir}/memory/user/``）；
- **workspace**：工作区级长期笔记（``{workspace}/.agent/memory/``）；
- **project**：项目级（工作区根下的 ``memory/``）。

记忆索引表 ``memory_index`` 支持**增量刷新**（不扫描全量），预筛时
从索引取候选 → 打分 → **至多 5 个**注入。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.workspace import get_workspace_dir
from app.db.base import db_session
from app.db.models import MemoryIndexRow, utc_now

logger = logging.getLogger(__name__)

#: 单次注入的记忆条数上限
MAX_INJECTED_MEMORIES = 5

SCOPES = ("user", "workspace", "project")


@dataclass(frozen=True)
class MemoryItem:
    path: str
    scope: str
    summary: str
    tags: list[str]
    size: int
    last_used_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "scope": self.scope,
            "summary": self.summary,
            "tags": self.tags,
            "size": self.size,
            "last_used_at": self.last_used_at,
        }


def memory_root(scope: str) -> Path:
    """某个作用域的记忆目录。"""
    if scope == "user":
        return Path(settings.data_dir) / "memory" / "user"
    if scope == "workspace":
        return Path(get_workspace_dir()) / ".agent" / "memory"
    if scope == "project":
        return Path(get_workspace_dir()) / "memory"
    raise ValueError(f"未知记忆作用域: {scope}")


def _iter_files(scope: str) -> list[Path]:
    root = memory_root(scope)
    if not root.exists():
        return []
    return [p for p in sorted(root.rglob("*.md")) if p.is_file()]


def summarize_file(path: Path) -> str:
    """一行描述：优先取首行标题，否则取首行非空文本。"""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip().lstrip("#").strip()
            if text:
                return text[:120]
    except OSError as exc:
        logger.warning("记忆摘要读取失败: %s", exc)
    return path.stem


def extract_tags(path: Path, text: str) -> list[str]:
    """标签：文件所在目录名 + front-matter 里的 tags。"""
    tags: list[str] = []
    parent = path.parent.name
    if parent and parent not in ("user", "memory"):
        tags.append(parent)
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].splitlines():
                if line.strip().startswith("tags:"):
                    raw = line.split(":", 1)[1].strip()
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, list):
                            tags.extend(str(t) for t in parsed)
                    except json.JSONDecodeError:
                        tags.extend(t.strip() for t in raw.split(",") if t.strip())
    return tags


def refresh_index(scope: str | None = None) -> int:
    """增量刷新索引（只处理新增/变更的文件，不扫描全部内容）。返回索引条数。"""
    scopes = (scope,) if scope else SCOPES
    count = 0
    for sc in scopes:
        files = _iter_files(sc)
        with db_session() as db:
            existing = {
                r.path: r
                for r in db.scalars(select(MemoryIndexRow).where(MemoryIndexRow.scope == sc)).all()
            }
            seen: set[str] = set()
            for f in files:
                key = str(f)
                seen.add(key)
                size = f.stat().st_size
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                summary = summarize_file(f)
                tags = extract_tags(f, text)
                row = existing.get(key)
                if row is None:
                    db.add(MemoryIndexRow(
                        path=key, scope=sc, summary=summary,
                        tags=json.dumps(tags, ensure_ascii=False), size=size,
                    ))
                elif row.size != size or row.summary != summary:
                    row.summary = summary
                    row.tags = json.dumps(tags, ensure_ascii=False)
                    row.size = size
                    row.updated_at = utc_now()
                count += 1
            # 删除已不存在的文件条目
            for key, row in existing.items():
                if key not in seen:
                    db.delete(row)
    return count


def list_memories(scope: str | None = None) -> list[MemoryItem]:
    """列出记忆（来自索引）。"""
    with db_session() as db:
        stmt = select(MemoryIndexRow)
        if scope:
            stmt = stmt.where(MemoryIndexRow.scope == scope)
        rows = db.scalars(stmt).all()
        return [
            MemoryItem(
                path=r.path, scope=r.scope, summary=r.summary,
                tags=json.loads(r.tags or "[]"), size=r.size, last_used_at=r.last_used_at,
            )
            for r in rows
        ]


def write_memory(scope: str, name: str, content: str, *, tags: list[str] | None = None) -> MemoryItem:
    """写入一条记忆并增量刷新索引。"""
    root = memory_root(scope)
    root.mkdir(parents=True, exist_ok=True)
    safe = name if name.endswith(".md") else f"{name}.md"
    path = root / safe
    header = ""
    if tags:
        header = "---\ntags: " + json.dumps(tags, ensure_ascii=False) + "\n---\n\n"
    path.write_text(header + content, encoding="utf-8")
    refresh_index(scope)
    item = next((m for m in list_memories(scope) if m.path == str(path)), None)
    return item or MemoryItem(path=str(path), scope=scope, summary=path.stem, tags=tags or [], size=len(content))


def delete_memory(scope: str, path: str) -> bool:
    """删除一条记忆（文件 + 索引）。"""
    p = Path(path)
    if p.exists():
        try:
            p.unlink()
        except OSError as exc:
            logger.warning("记忆删除失败: %s", exc)
            return False
    refresh_index(scope)
    return True


def clear_memories(scope: str) -> int:
    """清空某作用域的记忆。"""
    root = memory_root(scope)
    removed = 0
    if root.exists():
        for p in list(root.rglob("*.md")):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    refresh_index(scope)
    return removed


def select_memories(
    query: str,
    *,
    limit: int = MAX_INJECTED_MEMORIES,
    used_paths: set[str] | None = None,
) -> list[MemoryItem]:
    """预筛记忆：候选 → 打分 → **至多 limit 条**，并去重（已用过的排除）。"""
    items = list_memories()
    used = used_paths or set()
    q = (query or "").strip().lower()
    tokens = [t for t in q.split() if t]

    scored: list[tuple[int, int, MemoryItem]] = []
    for idx, item in enumerate(items):
        if item.path in used:
            continue  # 去重：已用过的记忆不再被选中
        score = 0
        hay = f"{item.path} {item.summary} {' '.join(item.tags)}".lower()
        if not q:
            score = 1
        else:
            if q in hay:
                score += 10
            for tok in tokens:
                if tok in hay:
                    score += 3
            if any(t in item.tags for t in tokens):
                score += 5
        if score:
            scored.append((-score, idx, item))
    scored.sort()
    return [i for _, _, i in scored[:limit]]


def mark_used(paths: list[str]) -> None:
    """标记记忆已使用（去重依据）。"""
    if not paths:
        return
    with db_session() as db:
        for r in db.scalars(select(MemoryIndexRow).where(MemoryIndexRow.path.in_(paths))).all():
            r.last_used_at = utc_now()
