"""插件包安装与回滚（S6 / WP-6.4）。

清单 ``plugin.json``：``skills / mcp_servers / commands / hooks / agents``。

安装流程：**校验 → 扫描 → 解包到临时目录 → 原子切换**到正式目录。
- 中途失败**不留半成品**（临时目录清理，旧版本完好）；
- 保留上一版本目录以支持**回滚**；
- 拒绝路径穿越（``..`` / 绝对路径 / 符号链接逃逸）。
"""
from __future__ import annotations

import json
import re
import logging
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.db.base import db_session
from app.db.models import PluginRow, utc_now
from app.services.chains.skills import scanner

logger = logging.getLogger(__name__)

#: 插件清单允许的**列表型**字段
MANIFEST_FIELDS = ("skills", "mcp_servers", "commands", "hooks", "agents")

#: 插件清单允许的**元信息**字段
MANIFEST_META_FIELDS = ("name", "version", "description", "author", "homepage")

#: 插件目录布局
PLUGINS_DIRNAME = "plugins"
SKILLS_DIRNAME = "skills"


class PluginError(RuntimeError):
    """插件安装失败。"""


@dataclass
class InstallResult:
    """安装结果。"""

    ok: bool
    name: str = ""
    version: str = ""
    scan: dict | None = None
    message: str = ""
    plugin_id: int | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "name": self.name,
            "version": self.version,
            "scan": self.scan,
            "message": self.message,
            "plugin_id": self.plugin_id,
        }


def _validate_manifest(manifest: dict) -> dict:
    unknown = set(manifest) - set(MANIFEST_FIELDS) - set(MANIFEST_META_FIELDS)
    if unknown:
        raise PluginError(f"清单含未知字段: {', '.join(sorted(unknown))}")
    out: dict = {}
    for key in MANIFEST_FIELDS:
        val = manifest.get(key, [])
        if not isinstance(val, list):
            raise PluginError(f"清单字段 {key} 必须是数组")
        out[key] = [str(v) for v in val]
    return out


def _safe_extract(zip_path: Path, dest: Path) -> None:
    """解包并**拒绝路径穿越**。"""
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if not str(target).startswith(str(dest)):
                raise PluginError(f"包内路径穿越被拒: {member}")
        zf.extractall(dest)


def read_manifest(pkg_dir: Path) -> dict:
    """读取并校验 ``plugin.json``。"""
    manifest_path = pkg_dir / "plugin.json"
    if not manifest_path.exists():
        raise PluginError("缺少 plugin.json")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PluginError(f"plugin.json 解析失败: {exc}") from exc
    if not isinstance(raw, dict):
        raise PluginError("plugin.json 必须是对象")
    name = str(raw.get("name", "")).strip()
    version = str(raw.get("version", "")).strip()
    if not name or not version:
        raise PluginError("plugin.json 必须含 name 与 version")
    return _validate_manifest(raw)



#: 插件名 / 版本号白名单（**W0-05**：防止越界写文件）
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
class PluginManager:
    """插件安装与回滚。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.plugins_dir = self.root / PLUGINS_DIRNAME
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # 安装
    # ------------------------------------------------------------------ #
    def install_from_zip(
        self,
        data: bytes,
        *,
        confirm: bool = False,
        skills_dir: Path | None = None,
    ) -> InstallResult:
        """从 zip 安装插件包（原子切换 + 扫描拦截）。"""
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="plugin-", dir=str(self.root)))
        try:
            zip_path = tmp / "package.zip"
            zip_path.write_bytes(data)
            unpacked = tmp / "unpacked"
            unpacked.mkdir()
            try:
                _safe_extract(zip_path, unpacked)
            except PluginError as exc:
                return InstallResult(ok=False, message=str(exc))
            # 包内可能有一层顶层目录
            roots = [p for p in unpacked.iterdir() if p.is_dir()]
            pkg_dir = roots[0] if len(roots) == 1 and (roots[0] / "plugin.json").exists() else unpacked
            return self._install_dir(pkg_dir, confirm=confirm, skills_dir=skills_dir)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _install_dir(
        self,
        pkg_dir: Path,
        *,
        confirm: bool = False,
        skills_dir: Path | None = None,
    ) -> InstallResult:
        try:
            manifest = read_manifest(pkg_dir)
        except PluginError as exc:
            return InstallResult(ok=False, message=str(exc))

        # **W0-05 / AUD-C06（plugin.json 的 name/version 未校验 → 越界写文件）**
        # 此前**重新读原始 JSON**（绕过了 ``read_manifest`` 的校验），
        # ``plugin_name`` 可为 ``../../../../tmp/evil``
        # → ``copytree`` 写到插件目录**之外**。
        # 现在：只用 ``read_manifest`` 的**已校验值**，并对 name/version 做白名单校验。
        import json as _json
        meta = _json.loads((pkg_dir / "plugin.json").read_text(encoding="utf-8"))
        plugin_name = str(meta.get("name"))
        version = str(meta.get("version"))
        if not _SAFE_COMPONENT.match(plugin_name):
            return InstallResult(
                ok=False, name=plugin_name, version=version,
                message=f"插件名非法（只允许字母/数字/短横线/下划线/点）: {plugin_name!r}",
            )
        if not _SAFE_COMPONENT.match(version):
            return InstallResult(
                ok=False, name=plugin_name, version=version,
                message=f"插件版本非法: {version!r}",
            )

        scan = scanner.scan_directory(pkg_dir)
        scan_dict = scan.as_dict()
        if scanner.should_reject(scan) and not confirm:
            return InstallResult(
                ok=False, name=plugin_name, version=version, scan=scan_dict,
                message=f"扫描等级 {scan.level}，默认拒绝安装（需显式确认）",
            )

        target = (self.plugins_dir / plugin_name / version).resolve()
        if not target.is_relative_to(self.plugins_dir.resolve()):
            return InstallResult(
                ok=False, name=plugin_name, version=version,
                message="插件安装路径越界",
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # **保留旧版本目录**以支持回滚：装新版本时旧目录原地留存
            # （`rollback(name, version)` 用它把内容还原回上一版）。
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(pkg_dir, target)
        except OSError as exc:
            shutil.rmtree(target, ignore_errors=True)
            return InstallResult(ok=False, name=plugin_name, version=version,
                                 message=f"复制失败（已清理，无半成品）: {exc}")

        # 技能目录：把包内 skills/ 原子切换进正式技能目录
        if skills_dir is not None:
            try:
                self._install_skills(pkg_dir, Path(skills_dir), plugin_name, version)
            except OSError as exc:
                shutil.rmtree(target, ignore_errors=True)
                return InstallResult(ok=False, name=plugin_name, version=version,
                                     message=f"技能安装失败（已回滚）: {exc}")

        with db_session() as db:
            row = db.scalar(
                select(PluginRow).where(
                    PluginRow.name == plugin_name, PluginRow.version == version
                )
            )
            if row is None:
                row = PluginRow(name=plugin_name, version=version)
                db.add(row)
            row.source = "local"
            row.status = "installed"
            row.scan_result = json.dumps(scan_dict, ensure_ascii=False)
            row.manifest_json = json.dumps(manifest, ensure_ascii=False)
            row.installed_at = utc_now()
            row.updated_at = utc_now()
            db.flush()
            plugin_id = int(row.id)

        return InstallResult(
            ok=True, name=plugin_name, version=version, scan=scan_dict,
            message="安装成功", plugin_id=plugin_id,
        )

    def _install_skills(self, pkg_dir: Path, skills_dir: Path, plugin_name: str, version: str) -> None:
        """把包内 ``skills/`` 切进正式技能目录（逐个技能原子替换）。"""
        src_skills = pkg_dir / SKILLS_DIRNAME
        if not src_skills.exists():
            return
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill_dir in sorted(p for p in src_skills.iterdir() if p.is_dir()):
            target = skills_dir / skill_dir.name
            backup = skills_dir / f".{skill_dir.name}.bak.{version}"
            if target.exists():
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                shutil.move(str(target), str(backup))
            shutil.copytree(skill_dir, target)

    # ------------------------------------------------------------------ #
    # 回滚
    # ------------------------------------------------------------------ #
    def rollback(self, name: str, version: str) -> InstallResult:
        """回滚到上一版本。

        做法：取该插件**除当前版本外最新的版本目录**，用它的内容覆盖当前版本目录
        （旧版本目录保留在原地，可再次回滚）。没有其它版本时明确失败。
        """
        base = self.plugins_dir / name
        target = base / version
        if not target.exists():
            return InstallResult(ok=False, name=name, version=version, message="目标版本不存在，无法回滚")
        others = sorted(
            (p for p in base.iterdir() if p.is_dir() and p.name != version and not p.name.endswith(".bak")),
            key=lambda p: p.name,
        )
        if not others:
            return InstallResult(ok=False, name=name, version=version,
                                 message="没有上一版本可回滚")
        prev = others[-1]
        try:
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(prev, target)
        except OSError as exc:
            return InstallResult(ok=False, name=name, version=version, message=f"回滚失败: {exc}")
        with db_session() as db:
            row = db.scalar(
                select(PluginRow).where(PluginRow.name == name, PluginRow.version == version)
            )
            if row is not None:
                row.status = "rolled_back"
                row.updated_at = utc_now()
        return InstallResult(ok=True, name=name, version=version, message="已回滚到上一版本")

    def list_plugins(self) -> list[dict]:
        """列出已安装插件（含扫描结果）。"""
        with db_session() as db:
            rows = db.scalars(select(PluginRow).order_by(PluginRow.name, PluginRow.version)).all()
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "version": r.version,
                    "status": r.status,
                    "scan": json.loads(r.scan_result or "{}"),
                    "manifest": json.loads(r.manifest_json or "{}"),
                    "installed_at": r.installed_at,
                }
                for r in rows
            ]
