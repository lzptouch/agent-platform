"""写前快照与变更落账（S3 / WP-3.3 / WP-3.4）。

工具层唯一钩子：写工具执行前调用 ``snapshot_before_write``，
执行后调用 ``record_change``。快照失败**不阻断写入**（记录告警）。

约定：
- 快照放 ``{workspace}/.agent/snapshots/{seq}/{相对路径}``；
- 同一文件**每轮只备份一次**（``_snapshotted`` 集合）；
- 快照预算 3000MB，超限按 LRU 清理（写审计）。
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import threading
from pathlib import Path

from app.db.base import db_session
from app.db.models import ChangeRow, utc_now

logger = logging.getLogger(__name__)

SNAPSHOT_BUDGET_MB = 3000

#: 已备份的 (run_id, path) —— 同文件每轮只备份一次
_snapshotted: set[tuple[str, str]] = set()
_lock = threading.Lock()


def file_hash(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def snapshot_before_write(
    run_id: str, workspace_root: Path, target: Path, tool: str
) -> dict | None:
    """写前快照。返回 ``{snapshot_ref, before_hash, size_before}``，文件不存在返回 ``None``。"""
    key = (run_id, str(target))
    with _lock:
        if key in _snapshotted:
            return None  # 本轮已备份过
    if not target.exists() or not target.is_file():
        return None

    before_hash = file_hash(target)
    size_before = target.stat().st_size
    seq = f"{len(_snapshotted) + 1:04d}"
    try:
        rel = target.relative_to(workspace_root)
    except ValueError:
        rel = Path(target.name)
    snap_dir = workspace_root / ".agent" / "snapshots" / seq
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_ref = snap_dir / rel.name
    try:
        shutil.copy2(target, snap_ref)
    except OSError as exc:
        logger.warning("快照失败（不阻断写入）: %s -> %s: %s", target, snap_ref, exc)
        return None
    with _lock:
        _snapshotted.add(key)
    _enforce_budget(workspace_root)
    return {"snapshot_ref": str(snap_ref), "before_hash": before_hash, "size_before": size_before}


def record_change(
    run_id: str,
    workspace_id: str | None,
    workspace_root: Path,
    target: Path,
    op: str,
    tool: str,
    snapshot: dict | None,
) -> None:
    """写后落账一条变更。"""
    after_hash = file_hash(target)
    size_after = target.stat().st_size if target.exists() else None
    try:
        rel = str(target.relative_to(workspace_root))
    except ValueError:
        rel = str(target)
    with db_session() as db:
        db.add(ChangeRow(
            run_id=run_id,
            workspace_id=workspace_id,
            path=rel,
            op=op,
            before_hash=(snapshot or {}).get("before_hash"),
            after_hash=after_hash,
            snapshot_ref=(snapshot or {}).get("snapshot_ref"),
            tool=tool,
            size_before=(snapshot or {}).get("size_before"),
            size_after=size_after,
        ))


def _enforce_budget(workspace_root: Path) -> None:
    """快照预算：超限按 LRU（最旧 seq）清理，并写审计。"""
    snap_root = workspace_root / ".agent" / "snapshots"
    if not snap_root.exists():
        return
    total = sum(f.stat().st_size for f in snap_root.rglob("*") if f.is_file())
    budget = SNAPSHOT_BUDGET_MB * 1024 * 1024
    if total <= budget:
        return
    seqs = sorted([d for d in snap_root.iterdir() if d.is_dir()])
    while total > budget and seqs:
        oldest = seqs.pop(0)
        freed = sum(f.stat().st_size for f in oldest.rglob("*") if f.is_file())
        shutil.rmtree(oldest, ignore_errors=True)
        total -= freed
        try:
            from app.services.security import audit

            audit.record(
                run_id=None, tool="snapshot_gc", decision="allow",
                reason=f"快照预算超限，LRU 清理 {oldest.name}", target=str(oldest),
            )
        except Exception:  # noqa: BLE001
            pass
        logger.info("快照预算清理: %s（释放 %d 字节）", oldest, freed)


def reset_snapshots() -> None:
    """测试用：清空已备份集合。"""
    with _lock:
        _snapshotted.clear()
