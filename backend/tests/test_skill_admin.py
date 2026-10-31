"""Skill 管理闭环测试：CRUD / 启停用 / 导入导出 / 安全（服务级，临时目录隔离）。"""
import io
import zipfile
from pathlib import Path

import pytest

from app.services.skill_manager import (
    SkillConflictError,
    SkillForbiddenError,
    SkillManager,
    SkillValidationError,
)


@pytest.fixture()
def manager(tmp_path):
    builtin = tmp_path / "skills"
    builtin.mkdir()
    (builtin / "demo").mkdir()
    (builtin / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 内置演示\n---\n\n内置内容\n", encoding="utf-8"
    )
    custom = tmp_path / "custom"
    custom.mkdir()
    return SkillManager(builtin, custom)


def test_builtin_readonly(manager):
    with pytest.raises(SkillForbiddenError):
        manager.update("demo", description="x")
    with pytest.raises(SkillForbiddenError):
        manager.delete("demo")


def test_create_update_delete(manager):
    skill = manager.create("my-skill", "我的技能", "# 说明\n做点事")
    assert skill["source"] == "custom"
    assert (Path(manager.custom_dir) / "my-skill" / "SKILL.md").exists()

    with pytest.raises(SkillConflictError):
        manager.create("my-skill", "重复", "x")

    updated = manager.update("my-skill", description="新描述")
    assert updated["description"] == "新描述"

    trash = manager.delete("my-skill")
    assert ".trash" in trash
    assert manager.get("my-skill") is None


def test_create_invalid_name(manager):
    with pytest.raises(SkillValidationError):
        manager.create("Bad_Name", "desc", "content")


def test_toggle(manager):
    manager.set_enabled("demo", False)
    assert manager.get("demo")["enabled"] is False
    # 禁用时 resolve_selection 默认不含
    assert manager.resolve_selection(None) == []
    assert manager.resolve_selection(["demo"]) == []
    manager.set_enabled("demo", True)
    assert manager.get("demo")["enabled"] is True


def test_export_import_roundtrip(manager):
    manager.create("pack-skill", "打包", "内容正文")
    (Path(manager.custom_dir) / "pack-skill" / "note.txt").write_text("资源", encoding="utf-8")
    manager.reload()

    data, filename = manager.export_zip("pack-skill")
    assert filename == "pack-skill.zip"
    # **W11-01**：`or True` 使内容校验恒真 → 导出内容从未被验证
    assert b"SKILL.md" in data
    assert b"note.txt" in data

    manager.delete("pack-skill")
    assert manager.get("pack-skill") is None

    skill = manager.import_zip(data)
    assert skill["name"] == "pack-skill"
    assert skill["description"] == "打包"
    assert "note.txt" in skill["resources"]


def test_import_conflicts(manager):
    manager.create("dup-skill", "已存在", "x")
    data, _ = manager.export_zip("dup-skill")
    with pytest.raises(SkillConflictError):
        manager.import_zip(data)
    # overwrite=true 可覆盖
    skill = manager.import_zip(data, overwrite=True)
    assert skill["name"] == "dup-skill"
    # 与内置同名 → 409
    data2, _ = manager.export_zip("demo")
    with pytest.raises(SkillConflictError):
        manager.import_zip(data2)


def test_import_security(manager):
    # 路径穿越
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.md", "x")
        zf.writestr("SKILL.md", "---\nname: evil\ndescription: x\n---\n")
    with pytest.raises(SkillValidationError):
        manager.import_zip(buf.getvalue())

    # 缺少 SKILL.md
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as zf:
        zf.writestr("readme.txt", "x")
    with pytest.raises(SkillValidationError, match="SKILL.md"):
        manager.import_zip(buf2.getvalue())

    # 非法 zip
    with pytest.raises(SkillValidationError):
        manager.import_zip(b"not a zip")

    # 带一层顶层目录的打包格式可导入
    buf3 = io.BytesIO()
    with zipfile.ZipFile(buf3, "w") as zf:
        zf.writestr("top/SKILL.md", "---\nname: top-skill\ndescription: 顶层目录\n---\n\nok\n")
    skill = manager.import_zip(buf3.getvalue())
    assert skill["name"] == "top-skill"


def test_create_conflict_with_builtin(manager):
    """create 与内置同名 → 冲突（覆盖仅允许通过文件系统 + reload 发生）。"""
    with pytest.raises(SkillConflictError):
        manager.create("demo", "自定义覆盖", "x")


def test_custom_overrides_builtin_via_scan(manager):
    """扫描层面：同名时自定义目录覆盖内置。"""
    (manager.custom_dir / "demo").mkdir()
    (manager.custom_dir / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 自定义覆盖\n---\n\n自定义内容\n", encoding="utf-8"
    )
    manager.reload()
    assert manager.get("demo")["source"] == "custom"
    assert manager.get("demo")["description"] == "自定义覆盖"


def test_chat_mode_prompt(manager):
    prompt = manager.build_system_prompt([], mode="chat")
    assert "对话模式" in prompt
    assert "write_file" not in prompt
    work_prompt = manager.build_system_prompt(None, mode="work")
    assert "write_file" in work_prompt
    assert "demo" in work_prompt
