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



def resolve_manifest_location(workspace_id: str) -> tuple[Path, str] | None:
    """定位某工作空间的 manifest（返回 ``(容器目录, 工作空间目录名)``）。

    **P2-20 修复**：``read_manifest(root, ws_id)`` 的 ``root`` 语义是
    **工作空间根的父目录**（``manifest_path`` = ``root/<ws_id>/.agent/manifest.json``）。
    写入方（``WorkspaceService.create``）传的是正确的容器目录，而读取方此前传了
    ``get_workspace_dir()``（当前工作区目录）→ **读不到写入的文件**。

    这里按 ``workspaces.root_path`` 反推容器目录，与写入方**同语义**。

    :return: ``(container, dir_name)``；工作空间不存在时返回 ``None``。
    """
    try:
        from app.db.base import db_session
        from app.db.models import WorkspaceRow

        with db_session() as db:
            row = db.get(WorkspaceRow, workspace_id)
            if row is None or not row.root_path:
                return None
            root = Path(row.root_path)
            return root.parent, root.name
    except Exception:  # noqa: BLE001 - 解析失败不应阻断调用方
        return None


def read_manifest_for(workspace_id: str) -> dict:
    """按工作空间**真实根目录**读 manifest。

    工作空间不在表里时回退到「当前工作区目录」旧语义（与
    ``write_manifest_for`` 对称），保证读写落在同一处。
    """
    loc = resolve_manifest_location(workspace_id)
    if loc is None:
        from app.core.workspace import get_workspace_dir

        return read_manifest(get_workspace_dir(), workspace_id)
    container, name = loc
    return read_manifest(container, name)


def write_manifest_for(workspace_id: str, updates: dict) -> dict:
    """按工作空间**真实根目录**写 manifest（合并写）。

    工作空间**不在 ``workspaces`` 表**里时（如测试直接用虚拟 id）→ 回退到
    「当前工作区目录」这一旧语义，保证既有调用方不被破坏。
    """
    loc = resolve_manifest_location(workspace_id)
    if loc is None:
        from app.core.workspace import get_workspace_dir

        return write_manifest(get_workspace_dir(), workspace_id, updates)
    container, name = loc
    return write_manifest(container, name, updates)

def validate_manifest(updates: dict) -> dict:
    """校验 manifest 更新（**P2-20**：非法值 → 422，而不是静默写入坏数据）。

    ``writable_roots`` 会被**权限判定**直接消费——写成字符串会让判定逻辑
    行为异常（迭代字符串得到字符），因此必须在入口拦住。
    """
    if not isinstance(updates, dict):
        raise ValueError("manifest 必须是对象")
    out = dict(updates)
    roots = out.get("writable_roots")
    if roots is not None:
        if not isinstance(roots, list) or any(not isinstance(r, str) for r in roots):
            raise ValueError("writable_roots 必须是字符串数组")
    policy = out.get("default_policy")
    if policy is not None and policy not in ("allow", "ask", "deny"):
        raise ValueError(f"default_policy 必须是 allow / ask / deny 之一: {policy}")
    model = out.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError("model 必须是字符串或 null")
    for key in ("skills", "extensions"):
        val = out.get(key)
        if val is not None and (
            not isinstance(val, list) or any(not isinstance(v, str) for v in val)
        ):
            raise ValueError(f"{key} 必须是字符串数组")
    return out


def write_manifest(root: Path, workspace_id: str, updates: dict) -> dict:
    """更新 manifest（合并写）。返回更新后的完整 manifest。"""
    updates = validate_manifest(updates)
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
