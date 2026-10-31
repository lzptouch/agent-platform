"""产物登记与查询（S3 / WP-3.5）。

产物 = 显式 ``emit_artifact`` 的交付物；中间文件 = 工作空间内其余文件。
两者在 UI 上分列。
"""
from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path

from sqlalchemy import select

from app.db.base import db_session
from app.db.models import ArtifactRow

_KIND_BY_EXT = {
    ".docx": "doc", ".md": "doc", ".txt": "doc", ".pdf": "pdf",
    ".xlsx": "sheet", ".csv": "sheet",
    ".pptx": "slide",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".py": "code", ".ts": "code", ".js": "code", ".json": "code",
    ".html": "web",
}
_PREVIEWABLE = {"doc", "sheet", "slide", "pdf", "image", "code", "web"}


def register_artifact(
    run_id: str,
    workspace_id: str | None,
    workspace_root: Path,
    path: str | Path,
    *,
    title: str | None = None,
    kind: str | None = None,
    url: str | None = None,
) -> dict:
    """登记一个产物（显式产出）。返回产物记录。

    **F-UX-02**：``kind`` 可显式指定（如 ``browser``——浏览器页面的截图），
    ``url`` 记录该页面的**来源地址** → 前端「浏览器」视图有真实数据源。
    """
    p = Path(path)
    if not p.is_absolute():
        p = workspace_root / p
    ext = p.suffix.lower()
    kind = kind or _KIND_BY_EXT.get(ext, "other")
    size = p.stat().st_size if p.exists() else None
    with db_session() as db:
        row = ArtifactRow(
            run_id=run_id,
            workspace_id=workspace_id,
            path=str(p.relative_to(workspace_root)) if p.is_relative_to(workspace_root) else str(p),
            title=title or p.name,
            mime=mimetypes.guess_type(str(p))[0],
            kind=kind,
            size=size,
            previewable=1 if kind in _PREVIEWABLE else 0,
            url=url,
        )
        db.add(row)
        db.flush()
        return {
            "id": row.id, "run_id": run_id, "path": row.path, "title": row.title,
            "kind": kind, "size": size, "mime": row.mime, "previewable": bool(row.previewable),
            "url": row.url,
        }


def list_artifacts(run_id: str) -> list[dict]:
    """列出一个 run 的**交付物**（不含中间文件）。"""
    with db_session() as db:
        rows = db.scalars(
            select(ArtifactRow).where(ArtifactRow.run_id == run_id).order_by(ArtifactRow.id)
        ).all()
        return [
            {
                "id": r.id, "path": r.path, "title": r.title, "mime": r.mime,
                "kind": r.kind, "size": r.size, "previewable": bool(r.previewable),
                # F-UX-02：浏览器类产物的来源页面地址
                "url": r.url,
                "created_at": r.created_at,
            }
            for r in rows
        ]


def save_as(artifact_id: int, workspace_root: Path, dest: str | Path) -> dict:
    """把产物另存到用户指定位置。"""
    with db_session() as db:
        row = db.get(ArtifactRow, artifact_id)
        if row is None:
            raise ValueError(f"产物不存在: {artifact_id}")
        src = workspace_root / row.path
    if not src.exists():
        raise ValueError(f"产物文件不存在: {src}")
    dest_p = Path(dest).expanduser()
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_p)
    return {"saved_to": str(dest_p), "from": str(src)}
