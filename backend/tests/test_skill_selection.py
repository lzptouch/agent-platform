"""Skill 可选模式测试。

覆盖三层：
1. ``SkillManager.resolve_selection`` 的语义（None / [] / 子集 / 非法名）
2. ``build_system_prompt`` 只注入选中的 Skill
3. ``AgentService.stream`` 首个 ``skills_selected`` 事件 + API 请求模型
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.schemas.agent import RunRequest
from app.services.skill_manager import SkillManager

HEADING_RE = re.compile(r"^### ", re.MULTILINE)


@pytest.fixture(scope="module")
def manager() -> SkillManager:
    return SkillManager(settings.skills_dir)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------- #
# 1. resolve_selection
# ---------------------------------------------------------------------- #
def test_resolve_none_returns_all(manager):
    assert len(manager.resolve_selection(None)) == len(manager.list_skills())


def test_resolve_empty_returns_none(manager):
    assert manager.resolve_selection([]) == []


def test_resolve_subset(manager):
    names = [s["name"] for s in manager.list_skills()][:2]
    selected = manager.resolve_selection(names)
    assert [s["name"] for s in selected] == names


def test_resolve_ignores_unknown(manager):
    assert manager.resolve_selection(["不存在的-skill", "pdf"]) != []
    assert [s["name"] for s in manager.resolve_selection(["nope"])] == []


# ---------------------------------------------------------------------- #
# 2. build_system_prompt
# ---------------------------------------------------------------------- #
def test_prompt_default_injects_all(manager):
    prompt = manager.build_system_prompt(None)
    assert len(HEADING_RE.findall(prompt)) == len(manager.list_skills())


def test_prompt_empty_injects_none(manager):
    prompt = manager.build_system_prompt([])
    assert HEADING_RE.findall(prompt) == []
    assert "未启用任何 Skill" in prompt


def test_prompt_subset_injects_only_selected(manager):
    prompt = manager.build_system_prompt(["pdf", "data-analysis"])
    headings = HEADING_RE.findall(prompt)
    assert len(headings) == 2
    assert "### pdf" in prompt
    assert "### data-analysis" in prompt
    # 其它 Skill 不应出现
    for other in ("frontend-design", "marketing-materials", "ralph-loop", "skill-creator"):
        assert f"### {other}" not in prompt


def test_prompt_still_has_base_tools(manager):
    """即使不启用 Skill，基础工具说明仍必须在。"""
    prompt = manager.build_system_prompt([])
    for tool in ("read_file", "write_file", "execute_python", "execute_bash", "list_directory"):
        assert tool in prompt


# ---------------------------------------------------------------------- #
# 3. AgentService 事件 + API 模型
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "skills,expected",
    [
        ([], []),
        (["pdf"], ["pdf"]),
        (None, None),  # None → 全部
    ],
)
def test_stream_emits_skills_selected(client, skills, expected):
    """首个事件应为 skills_selected，且与入参一致（不消耗 LLM 调用）。"""
    from app.core.state import init_app_state

    init_app_state(app)
    service = app.state.agent_service

    gen = service.stream("你好", skills=skills)
    first = next(gen)
    assert first["type"] == "skills_selected"

    if expected is None:
        assert len(first["skills"]) == len(first["all_skills"])
    else:
        assert first["skills"] == expected

    # 只取前两个事件（skills_selected / system_prompt），不触发真实 LLM 调用
    second = next(gen)
    assert second["type"] == "system_prompt"
    gen.close()


def test_runrequest_accepts_skills():
    assert RunRequest(prompt="hi").skills is None
    assert RunRequest(prompt="hi", skills=[]).skills == []
    assert RunRequest(prompt="hi", skills=["pdf"]).skills == ["pdf"]


def test_run_sync_rejects_empty_prompt():
    with pytest.raises(Exception):
        RunRequest(prompt="")
