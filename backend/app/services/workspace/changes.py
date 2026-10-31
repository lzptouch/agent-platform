"""变更的 diff 计算与回退（S3 / WP-3.4）。

- 文本文件 → 行级 unified diff；
- 二进制 → 哈希 + 大小 + 类型摘要；
- 回退：从 ``snapshot_ref`` 恢复，写一条 ``op=revert`` 记录，且**走权限判定**。
"""
from __future__ import annotations

import difflib
import logging
import shutil
from pathlib import Path

from sqlalchemy import select

from app.db.base import db_session
from app.db.models import ChangeRow, utc_now
from app.services.workspace.snapshots import file_hash, record_change

logger = logging.getLogger(__name__)

_TEXT_EXTS = {".txt", ".md", ".py", ".ts", ".js", ".json", ".html", ".css", ".yml", ".yaml", ".csv"}
_BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".exe", ".dll", ".so", ".pyd"}


def list_changes(run_id: str) -> list[dict]:
    with db_session() as db:
        rows = db.scalars(
            select(ChangeRow).where(ChangeRow.run_id == run_id).order_by(ChangeRow.id)
        ).all()
        return [
            {
                "id": r.id,
                "path": r.path,
                "op": r.op,
                "before_hash": r.before_hash,
                "after_hash": r.after_hash,
                "snapshot_ref": r.snapshot_ref,
                "tool": r.tool,
                "size_before": r.size_before,
                "size_after": r.size_after,
                "created_at": r.created_at,
            }
            for r in rows
        ]


def compute_diff(change_id: int, workspace_root: Path) -> dict:
    """计算一次变更的 diff（文本行级 / 二进制摘要）。"""
    with db_session() as db:
        row = db.get(ChangeRow, change_id)
        if row is None:
            raise ValueError(f"变更不存在: {change_id}")
        rel = row.path
        snapshot_ref = row.snapshot_ref

    target = workspace_root / rel
    is_binary = Path(rel).suffix.lower() in _BINARY_EXTS

    if is_binary:
        return {
            "kind": "binary",
            "path": rel,
            "before_hash": row.before_hash,
            "after_hash": row.after_hash,
            "size_before": row.size_before,
            "size_after": row.size_after,
            "summary": f"二进制文件 {rel}：{row.size_before}B → {row.size_after}B",
        }

    before_text = ""
    if snapshot_ref and Path(snapshot_ref).exists():
        before_text = Path(snapshot_ref).read_text(encoding="utf-8", errors="replace")
    after_text = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""

    diff_lines = list(difflib.unified_diff(
        before_text.splitlines(),
        after_text.splitlines(),
        fromfile=f"before/{rel}",
        tofile=f"after/{rel}",
        lineterm="",
    ))
    return {
        "kind": "text",
        "path": rel,
        "diff": "\n".join(diff_lines),
        "added": sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++")),
        "removed": sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---")),
    }


def revert(change_id: int, workspace_root: Path, *, tool: str = "revert") -> dict:
    """从快照恢复一个文件。

    回退本身也写一条 ``op=revert`` 的变更记录（可追溯）。
    **权限判定由调用方（API 层）负责**，这里只做恢复。
    """
    with db_session() as db:
        row = db.get(ChangeRow, change_id)
        if row is None:
            raise ValueError(f"变更不存在: {change_id}")
        rel = row.path
        snapshot_ref = row.snapshot_ref
        run_id = row.run_id
        workspace_id = row.workspace_id

    if not snapshot_ref or not Path(snapshot_ref).exists():
        raise ValueError(f"快照不存在，无法回退: {snapshot_ref}")

    target = workspace_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)

    # **F-WS-07 / AUD-M24（回退留痕的 before_hash 取错时机）**
    # 此前在 ``shutil.copy2`` **之后**才取 ``before_hash`` / ``size_before``
    # → 记录的是**回退后**的内容哈希 → 回退记录的「变更前」字段等于「变更后」，
    # 审计链断裂（无法据此再回退一次）。
    # 现在：在**覆盖之前**取变更前的哈希与大小。
    before_hash = (file_hash(target) or "") if target.exists() else ""
    size_before = target.stat().st_size if target.exists() else 0

    shutil.copy2(snapshot_ref, target)
    record_change(run_id, workspace_id, workspace_root, target, "revert", tool, {
        "before_hash": before_hash,
        "size_before": size_before,
        "snapshot_ref": snapshot_ref,
    })
    logger.info("已回退: %s ← %s", target, snapshot_ref)
    return {"reverted": rel, "from_snapshot": snapshot_ref}
