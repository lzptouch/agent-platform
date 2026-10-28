"""工作空间目录布局与 manifest 读写（S3 / WP-3.1）。

布局：
    {root}/{workspace_id}/
    ├── .agent/               # 本仓库实现用 .agent（设计文档写 .workbuddy，语义相同）
    │   ├── manifest.json     # 工作空间元信息
    │   ├── memory/           # 长期记忆（S5 用）
    │   ├── snapshots/{seq}/  # 写前快照
    │   ├── audit/            # JSONL 审计
    │   ├── runtime/          # 临时产物
    │   └── locks/            # 任务锁
    └── artifacts/            # 交付物（用户可见）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

INTERNAL_DIR = ".agent"
MANIFEST_NAME = "manifest.json"

DEFAULT_MANIFEST: dict = {
    "writable_roots": [],          # 可写根（默认 = 工作空间根）
    "default_policy": "ask",
    "model": None,
    "skills": [],
    "extensions": [],
    "snapshot_budget_mb": 3000,
}


def workspace_dir(root: Path, workspace_id: str) -> Path:
    return Path(root) / workspace_id


def ensure_layout(root: Path, workspace_id: str) -> Path:
    """按约定创建工作空间目录布局，返回工作空间根。"""
    base = workspace_dir(root, workspace_id)
    for sub in ("snapshots", "audit", "runtime", "locks", "memory"):
        (base / INTERNAL_DIR / sub).mkdir(parents=True, exist_ok=True)
    (base / "artifacts").mkdir(parents=True, exist_ok=True)
    return base


def manifest_path(root: Path, workspace_id: str) -> Path:
    return workspace_dir(root, workspace_id) / INTERNAL_DIR / MANIFEST_NAME


def read_manifest(root: Path, workspace_id: str) -> dict:
    """读 manifest；不存在则返回默认。"""
    p = manifest_path(root, workspace_id)
    if not p.exists():
        return dict(DEFAULT_MANIFEST)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("manifest 损坏，使用默认: %s", exc)
        return dict(DEFAULT_MANIFEST)
    merged = dict(DEFAULT_MANIFEST)
    merged.update(data)
    return merged


def write_manifest(root: Path, workspace_id: str, updates: dict) -> dict:
    """更新 manifest（合并写）。返回更新后的完整 manifest。"""
    manifest = read_manifest(root, workspace_id)
    manifest.update(updates)
    manifest.setdefault("writable_roots", [])
    if not manifest["writable_roots"]:
        manifest["writable_roots"] = [str(workspace_dir(root, workspace_id))]
    p = manifest_path(root, workspace_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def snapshots_dir(root: Path, workspace_id: str) -> Path:
    return workspace_dir(root, workspace_id) / INTERNAL_DIR / "snapshots"


def artifacts_dir(root: Path, workspace_id: str) -> Path:
    return workspace_dir(root, workspace_id) / "artifacts"
