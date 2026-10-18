"""SkillManager —— Skill 的扫描 / 加载 / 管理。

存储模型（v2）：
- **内容真相在文件系统**：Agent 通过 ``read_file`` 读取 ``SKILL.md``，社区生态以目录分发；
- **元数据与启停用状态在 DB**：``skills`` 表由 ``sync_to_db()`` 在启动 / 变更后同步；
- 双目录：``skills/``（内置，只读）+ ``data/skills_custom/``（用户，可写），同名时自定义覆盖内置。
"""
from __future__ import annotations

import io
import json
import logging
import re
import shutil
import time
import zipfile
from pathlib import Path

import yaml

from app.core.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

# SKILL.md frontmatter 允许的字段
ALLOWED_PROPERTIES = {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}

# 打包 Skill 时需要排除的内容
EXCLUDE_DIRS = {"__pycache__", "node_modules", "evals"}
EXCLUDE_FILES = {".DS_Store"}
EXCLUDE_GLOBS = {"*.pyc"}

IMPORT_MAX_BYTES = 20 * 1024 * 1024
IMPORT_MAX_FILES = 500


class SkillConflictError(ValueError):
    """同名 Skill 冲突。"""


class SkillForbiddenError(PermissionError):
    """内置 Skill 禁止修改 / 删除。"""


class SkillValidationError(ValueError):
    """Skill 内容校验失败。"""


def rel_to_root(path: Path) -> str:
    """把绝对路径转成相对项目根目录的路径，便于展示。"""
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


class SkillManager:
    """管理内置 + 自定义 Skill。"""

    def __init__(self, skills_dir: Path, custom_dir: Path | None = None) -> None:
        self.skills_dir = Path(skills_dir)
        self.custom_dir = Path(custom_dir) if custom_dir else None
        self.skills: dict[str, dict] = {}
        self.reload()

    # ------------------------------------------------------------------ #
    # 扫描 / 加载（custom 先扫，builtin 后扫但低优先级）
    # ------------------------------------------------------------------ #
    def reload(self) -> int:
        """重新扫描两个目录，返回加载到的 Skill 数量。"""
        self.skills = {}
        for base, source in ((self.custom_dir, "custom"), (self.skills_dir, "builtin")):
            if base is None or not base.exists():
                continue
            for skill_dir in sorted(base.iterdir()):
                if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                    continue
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                try:
                    content = skill_md.read_text(encoding="utf-8")
                    meta = self._parse_frontmatter(content)
                except (OSError, UnicodeDecodeError) as exc:
                    logger.warning("跳过损坏的 Skill 目录 %s: %s", skill_dir, exc)
                    continue
                if not meta or not meta.get("name"):
                    continue
                name = str(meta["name"]).strip()
                if source == "builtin" and name in self.skills:
                    continue  # 自定义覆盖内置（同名不重复加载）
                self.skills[name] = {
                    "name": name,
                    "description": str(meta.get("description", "")).strip(),
                    "path": rel_to_root(skill_dir),
                    "skill_md_path": str(skill_md.resolve()),
                    "skill_md_rel": rel_to_root(skill_md),
                    "content": content,
                    "resources": self._list_resources(skill_dir),
                    "source": source,
                    "mtime": skill_md.stat().st_mtime,
                    "enabled": True,
                }
        return len(self.skills)

    @staticmethod
    def _parse_frontmatter(content: str) -> dict | None:
        """解析 SKILL.md 开头的 YAML frontmatter。"""
        if not content.startswith("---"):
            return None
        parts = content.split("---", 2)
        if len(parts) < 3:
            return None
        try:
            data = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _list_resources(skill_dir: Path) -> list[str]:
        """列出 Skill 目录下的附属资源（scripts / references / assets ...）。"""
        resources: list[str] = []
        for file_path in sorted(skill_dir.rglob("*")):
            if not file_path.is_file() or file_path.name == "SKILL.md":
                continue
            if any(part in EXCLUDE_DIRS for part in file_path.parts):
                continue
            if file_path.name in EXCLUDE_FILES or file_path.suffix == ".pyc":
                continue
            resources.append(str(file_path.relative_to(skill_dir)))
        return resources

    # ------------------------------------------------------------------ #
    # DB 同步（元数据索引与启停用状态）
    # ------------------------------------------------------------------ #
    def sync_to_db(self) -> dict:
        """把磁盘扫描结果同步到 skills 表；应用 DB 中的 enabled 状态。

        返回告警信息（如团队引用了已删除的 Skill）。失败不阻塞启动。
        """
        warnings: list[str] = []
        try:
            from app.db.base import db_session
            from app.db.models import SkillRecordRow, utc_now
            from sqlalchemy import select

            with db_session() as db:
                records = {r.name: r for r in db.scalars(select(SkillRecordRow)).all()}
                for name, skill in self.skills.items():
                    rec = records.get(name)
                    if rec is None:
                        # 新建时显式 enabled=1（ORM 列默认值在 flush 前为 None）
                        rec = SkillRecordRow(name=name, enabled=1)
                        db.add(rec)
                    rec.description = skill["description"]
                    rec.source = skill["source"]
                    rec.path = skill["path"]
                    rec.stale = 0
                    rec.updated_at = utc_now()
                    skill["enabled"] = bool(rec.enabled)
                # 磁盘已删除的标记 stale 并禁用
                for name, rec in records.items():
                    if name not in self.skills:
                        rec.stale = 1
                        rec.enabled = 0
                        warnings.append(f"Skill 已从磁盘删除: {name}")
        except Exception as exc:  # noqa: BLE001 - DB 未就绪（如迁移前）不影响扫描
            logger.warning("Skill DB 同步失败（忽略）: %s", exc)
        return {"warnings": warnings}

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def list_skills(self) -> list[dict]:
        return list(self.skills.values())

    def get(self, name: str) -> dict | None:
        return self.skills.get(name)

    def get_skill_content(self, name: str) -> str | None:
        skill = self.skills.get(name)
        return skill["content"] if skill else None

    def get_resource_path(self, name: str, resource: str) -> Path | None:
        """安全地解析 Skill 内某个资源文件的绝对路径（防止路径穿越 / 符号链接逃逸）。"""
        skill = self.skills.get(name)
        if not skill:
            return None
        base = (PROJECT_ROOT / skill["path"]).resolve()
        target = (base / resource).resolve()
        if not str(target).startswith(str(base)) or not target.is_file():
            return None
        return target

    # ------------------------------------------------------------------ #
    # 管理（CRUD / 启停用 / 导入导出）—— 只作用于自定义目录
    # ------------------------------------------------------------------ #
    def _require_custom_dir(self) -> Path:
        if self.custom_dir is None:
            raise SkillForbiddenError("未配置自定义 Skill 目录")
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        return self.custom_dir

    @staticmethod
    def _build_skill_md(name: str, description: str, content: str) -> str:
        body = content.strip()
        return (
            "---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "---\n\n"
            f"{body}\n"
        )

    def create(self, name: str, description: str, content: str) -> dict:
        base = self._require_custom_dir()
        if name in self.skills:
            raise SkillConflictError(f"Skill 已存在: {name}")
        target = base / name
        target.mkdir(parents=True, exist_ok=False)
        (target / "SKILL.md").write_text(
            self._build_skill_md(name, description, content), encoding="utf-8"
        )
        ok, msg, _ = self.validate_skill(target)
        if not ok:
            shutil.rmtree(target, ignore_errors=True)
            raise SkillValidationError(msg)
        self.reload()
        self.sync_to_db()
        return self.skills[name]

    def update(self, name: str, description: str | None = None, content: str | None = None) -> dict:
        skill = self.skills.get(name)
        if not skill:
            raise KeyError(f"Skill 不存在: {name}")
        if skill["source"] != "custom":
            raise SkillForbiddenError(f"内置 Skill 不可修改: {name}")
        new_desc = description if description is not None else skill["description"]
        body = content if content is not None else self._extract_body(skill["content"])
        target = PROJECT_ROOT / skill["path"]
        (target / "SKILL.md").write_text(
            self._build_skill_md(name, new_desc, body), encoding="utf-8"
        )
        ok, msg, _ = self.validate_skill(target)
        if not ok:
            (target / "SKILL.md").write_text(skill["content"], encoding="utf-8")
            raise SkillValidationError(msg)
        self.reload()
        self.sync_to_db()
        return self.skills[name]

    @staticmethod
    def _extract_body(full_content: str) -> str:
        parts = full_content.split("---", 2)
        return parts[2].strip() if len(parts) >= 3 else full_content

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name not in self.skills:
            raise KeyError(f"Skill 不存在: {name}")
        from app.db.base import db_session
        from app.db.models import SkillRecordRow, utc_now

        with db_session() as db:
            rec = db.get(SkillRecordRow, name)
            if rec is None:
                rec = SkillRecordRow(
                    name=name,
                    description=self.skills[name]["description"],
                    source=self.skills[name]["source"],
                    path=self.skills[name]["path"],
                )
                db.add(rec)
            rec.enabled = 1 if enabled else 0
            rec.updated_at = utc_now()
        self.reload()
        self.sync_to_db()

    def delete(self, name: str) -> str:
        """软删除：移动到 .trash，可手工恢复。返回 trash 相对路径。"""
        skill = self.skills.get(name)
        if not skill:
            raise KeyError(f"Skill 不存在: {name}")
        if skill["source"] != "custom":
            raise SkillForbiddenError(f"内置 Skill 不可删除: {name}")
        base = self._require_custom_dir()
        trash = base / ".trash"
        trash.mkdir(exist_ok=True)
        dest = trash / f"{name}-{int(time.time())}"
        shutil.move(str(PROJECT_ROOT / skill["path"]), str(dest))
        self.reload()
        self.sync_to_db()
        return rel_to_root(dest)

    def export_zip(self, name: str) -> tuple[bytes, str]:
        skill = self.skills.get(name)
        if not skill:
            raise KeyError(f"Skill 不存在: {name}")
        base = PROJECT_ROOT / skill["path"]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(base.rglob("*")):
                if not file_path.is_file():
                    continue
                if any(part in EXCLUDE_DIRS for part in file_path.parts):
                    continue
                if file_path.name in EXCLUDE_FILES or file_path.suffix == ".pyc":
                    continue
                zf.write(file_path, arcname=str(file_path.relative_to(base)))
        return buf.getvalue(), f"{name}.zip"

    def import_zip(self, data: bytes, overwrite: bool = False) -> dict:
        """导入 zip。逐条校验路径安全；支持带一层顶层目录的打包格式。"""
        if len(data) > IMPORT_MAX_BYTES:
            raise SkillValidationError(f"zip 超过大小上限 {IMPORT_MAX_BYTES // (1024 * 1024)}MB")
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise SkillValidationError("非法 zip 文件") from None

        members = [m for m in zf.infolist() if not m.is_dir()]
        if len(members) > IMPORT_MAX_FILES:
            raise SkillValidationError(f"zip 文件数超过上限 {IMPORT_MAX_FILES}")

        # 统一剥离一层顶层目录（如 my-skill/SKILL.md）
        names = [m.filename for m in members]
        top = names[0].split("/")[0] if names and "/" in names[0] else ""
        strip_prefix = ""
        if top and all(n.startswith(top + "/") for n in names):
            strip_prefix = top + "/"

        staged: dict[str, bytes] = {}
        for m in members:
            rel = m.filename[len(strip_prefix):] if strip_prefix else m.filename
            if not rel:
                continue
            parts = Path(rel).parts
            if rel.startswith("/") or ".." in parts:
                raise SkillValidationError(f"非法路径条目: {m.filename}")
            staged[rel] = zf.read(m)

        if "SKILL.md" not in staged:
            raise SkillValidationError("zip 中缺少 SKILL.md")

        content = staged["SKILL.md"].decode("utf-8", errors="replace")
        meta = self._parse_frontmatter(content)
        if not meta or not meta.get("name"):
            raise SkillValidationError("SKILL.md 缺少有效 frontmatter (name)")
        name = str(meta["name"]).strip()

        existing = self.skills.get(name)
        if existing and existing["source"] == "builtin":
            raise SkillConflictError(f"与内置 Skill 同名: {name}")
        if existing and not overwrite:
            raise SkillConflictError(f"Skill 已存在: {name}（overwrite=true 可覆盖）")

        base = self._require_custom_dir()
        staging = base / ".staging" / f"{name}-{int(time.time() * 1000)}"
        staging.mkdir(parents=True, exist_ok=False)
        try:
            for rel, blob in staged.items():
                target = staging / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
            ok, msg, _ = self.validate_skill(staging)
            if not ok:
                raise SkillValidationError(msg)
            dest = base / name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(staging), str(dest))
        finally:
            shutil.rmtree(staging.parent / staging.name, ignore_errors=True)
            if staging.parent.exists() and not any(staging.parent.iterdir()):
                staging.parent.rmdir()

        self.reload()
        self.sync_to_db()
        return self.skills[name]

    # ------------------------------------------------------------------ #
    # System Prompt（第一级披露 + 模式/团队感知）
    # ------------------------------------------------------------------ #
    def resolve_selection(self, skill_names: list[str] | None) -> list[dict]:
        """把前端传入的 Skill 名称列表解析为 Skill 元数据列表。

        语义：
        - ``None``  → **全部启用中的 Skill**（默认，保持向后兼容）
        - ``[]``    → **不使用任何 Skill**
        - ``[...]`` → 仅使用列出的 Skill（不存在或未启用的名称被忽略）
        """
        enabled = {n: s for n, s in self.skills.items() if s.get("enabled", True)}
        if skill_names is None:
            return list(enabled.values())
        return [enabled[name] for name in skill_names if name in enabled]

    def resolve_for_mode(self, skill_names: list[str] | None, mode: str) -> list[dict]:
        """模式感知的 Skill 解析：chat 模式下 None 解释为 []（默认不加载 Skill）。"""
        if mode == "chat" and skill_names is None:
            return []
        return self.resolve_selection(skill_names)

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        *,
        mode: str = "work",
        team: dict | None = None,
    ) -> str:
        """构建 system prompt。

        参数:
            skill_names: 要启用的 Skill 名称列表（None 语义由 ``resolve_for_mode`` 处理后的调用方决定）。
            mode: ``chat``（只读）或 ``work``（全量工具）。
            team: Skill 团队元数据（name / prompt_prefix / strategy / step_skills）。
        """
        output_dir = settings.output_dir
        selected = self.resolve_selection(skill_names if skill_names is not None else ([] if mode == "chat" else None))

        if mode == "chat":
            parts: list[str] = [
                "你是一个乐于助人的 AI 助手，当前处于**对话模式（Ask）**。",
                "",
                "规则：",
                "1. 直接回答用户问题；不要创建或修改文件，不要执行代码或命令",
                "2. 你可以使用 read_file / list_directory 查看本地文件来辅助回答",
                "3. 如需写文件或执行代码，请提示用户切换到工作模式",
                "",
            ]
        else:
            parts = [
                "你是一个强大的 AI 助手，具备代码执行和文件操作能力（工作模式 / Craft）。",
                "",
                "你可以使用以下工具来完成任务：",
                "- read_file: 读取本地文件内容",
                "- write_file: 创建或写入文件",
                "- execute_python: 执行 Python 代码",
                "- execute_bash: 执行 Bash 命令",
                "- list_directory: 列出目录内容",
                "",
                "## 重要：execute_python 使用规则",
                "**每次 execute_python 调用都是独立进程，变量不会在多次调用之间共享。**",
                "因此你必须：",
                "1. 在每次 execute_python 调用中包含完整的 import 和数据定义",
                "2. 如果需要多步操作（如先生成图表再生成 PDF），把所有代码写在同一次调用中",
                "3. 或者通过文件（CSV/JSON/PNG）在多次调用之间传递数据",
                "4. 不要假设上一次调用的变量仍然存在",
                "",
                f"生成的文件请保存到: {output_dir}（绝对路径，执行代码时使用此路径）",
                "",
                "## 重要：中文支持",
                "- matplotlib 图表中文字体已自动配置，无需手动设置",
                "- 生成 PDF 时优先使用已注册的中文字体",
                "",
            ]

        if team:
            parts.append(f"## 团队：{team.get('name', '')}")
            prefix = (team.get("prompt_prefix") or "").strip()
            if prefix:
                parts.append(prefix)
            if team.get("strategy") == "sequential" and selected:
                parts.append("")
                parts.append("请按以下标注顺序执行 Skill，前一步的产出作为后一步的输入。")
            parts.append("")

        if selected:
            parts.append("## 可用的 Agent Skills")
            parts.append("")
            parts.append(
                f"本次会话已启用 {len(selected)} 个 Skill。当用户请求匹配某个 Skill 的描述时，"
                "请先使用 read_file 工具读取对应的 SKILL.md 获取详细指令，然后按照指令执行。"
            )
            parts.append("")
            total = len(selected)
            for i, skill in enumerate(selected, start=1):
                step = f"[步骤 {i}/{total}] " if team and team.get("strategy") == "sequential" else ""
                parts.append(f"### {step}{skill['name']}")
                parts.append(f"- 描述: {skill['description']}")
                parts.append(f"- 指令文件: {skill['skill_md_path']}")
                parts.append("")
        else:
            parts.append("## Agent Skills")
            parts.append("")
            parts.append("本次会话未启用任何 Skill，请仅使用上述基础工具完成任务。")
            parts.append("")

        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # 校验（等价于 skill-creator 的 quick_validate.py）
    # ------------------------------------------------------------------ #
    @staticmethod
    def validate_skill(skill_path: Path) -> tuple[bool, str, str | None]:
        """校验一个 Skill 目录，返回 (是否有效, 消息, name)。"""
        skill_path = Path(skill_path)
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            return False, "SKILL.md not found", None

        content = skill_md.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return False, "No YAML frontmatter found", None

        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return False, "Invalid frontmatter format", None

        try:
            frontmatter = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:  # pragma: no cover - 依赖具体输入
            return False, f"Invalid YAML in frontmatter: {exc}", None
        if not isinstance(frontmatter, dict):
            return False, "Frontmatter must be a YAML dictionary", None

        unexpected = set(frontmatter) - ALLOWED_PROPERTIES
        if unexpected:
            allowed = ", ".join(sorted(ALLOWED_PROPERTIES))
            return False, f"Unexpected key(s): {', '.join(sorted(unexpected))}. Allowed: {allowed}", None

        if "name" not in frontmatter:
            return False, "Missing 'name' in frontmatter", None
        if "description" not in frontmatter:
            return False, "Missing 'description' in frontmatter", None

        name = frontmatter.get("name", "")
        if not isinstance(name, str):
            return False, f"Name must be a string, got {type(name).__name__}", None
        name = name.strip()
        if name:
            if not re.match(r"^[a-z0-9-]+$", name):
                return False, f"Name '{name}' should be kebab-case", None
            if name.startswith("-") or name.endswith("-") or "--" in name:
                return False, f"Name '{name}' cannot start/end with hyphen or contain '--'", None
            if len(name) > 64:
                return False, f"Name is too long ({len(name)} > 64)", None

        description = frontmatter.get("description", "")
        if not isinstance(description, str):
            return False, f"Description must be a string, got {type(description).__name__}", None
        description = description.strip()
        if description:
            if "<" in description or ">" in description:
                return False, "Description cannot contain angle brackets (< or >)", None
            if len(description) > 1024:
                return False, f"Description is too long ({len(description)} > 1024)", None

        return True, "Skill is valid!", name
