"""双模式行为测试：工具档案 / 迭代上限 / 反思忽略 / Skill 默认策略。"""
from app.services.mcp_manager import MCPManager
from app.services.tool_registry import (
    ToolProfile,
    ToolRegistry,
    assert_profile_consistency,
)


def _registry() -> ToolRegistry:
    return ToolRegistry(MCPManager())


def test_chat_profile_readonly_tools():
    tools = _registry().get_combined_tools(
        enable_mcp=True, mcp_servers=["weather", "xiaohongshu"],
        enable_rag=True, enable_web_research=True,
        profile=ToolProfile.CHAT,
    )
    names = {t["name"] for t in tools}
    # 只读内置 + rag_query + web_research + 只读 MCP（weather）；xiaohongshu 被排除
    assert {"read_file", "list_directory", "rag_query", "web_research"} <= names
    assert not (names & {"write_file", "execute_python", "execute_bash", "rag_ingest"})
    assert not any(n.startswith("mcp_xiaohongshu__") for n in names)
    assert_profile_consistency(tools, ToolProfile.CHAT)


def test_work_profile_full_tools():
    tools = _registry().get_combined_tools(enable_rag=True, profile=ToolProfile.WORK)
    names = {t["name"] for t in tools}
    assert {"read_file", "write_file", "execute_python", "execute_bash", "list_directory",
            "rag_query", "rag_ingest"} <= names


def test_prompt_section_consistent_with_profile():
    reg = _registry()
    chat_section = reg.build_tools_prompt_section(enable_rag=True, profile=ToolProfile.CHAT)
    assert "rag_ingest" not in chat_section
    work_section = reg.build_tools_prompt_section(enable_rag=True, profile=ToolProfile.WORK)
    assert "rag_ingest" in work_section


def test_agent_stream_chat_mode_filters_tools(fake_client_factory):
    """chat 模式实际传给 LLM 的工具不含写类工具（抓 fake client 入参断言）。"""
    from app.core.config import settings
    from app.services.agent_service import AgentService
    from app.services.skill_manager import SkillManager

    fake, calls = fake_client_factory([
        # 模型即便要求调用写工具，我们也验证工具列表里根本没有它
        __import__("tests.conftest", fromlist=["make_text_response"]).make_text_response("你好"),
    ])
    manager = SkillManager(settings.skills_dir, settings.custom_skills_dir)
    service = AgentService(manager)
    service._client = fake

    events = list(service.stream("你好", mode="chat"))
    assert any(e["type"] == "done" for e in events)
    assert calls, "LLM 应被调用"
    tool_names = {t["function"]["name"] for t in calls[0]["tools"]}
    assert not (tool_names & {"write_file", "execute_python", "execute_bash"})
    assert {"read_file", "list_directory"} <= tool_names
    # system prompt 中不应包含 execute_python
    system_msg = calls[0]["messages"][0]["content"]
    assert "对话模式" in system_msg
    assert "execute_python" not in system_msg.split("## Agent Skills")[0]


def test_agent_stream_chat_reflection_ignored(fake_client_factory):
    from tests.conftest import make_text_response

    from app.core.config import settings
    from app.services.agent_service import AgentService
    from app.services.skill_manager import SkillManager

    fake, _ = fake_client_factory([make_text_response("ok")])
    service = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
    service._client = fake
    events = list(service.stream("hi", mode="chat", enable_reflection=True))
    assert any(e["type"] == "notice" and "反思" in e["content"] for e in events)
    assert not any(e["type"] == "reflection_start" for e in events)


def test_chat_mode_default_no_skills(fake_client_factory):
    from tests.conftest import make_text_response

    from app.core.config import settings
    from app.services.agent_service import AgentService
    from app.services.skill_manager import SkillManager

    fake, _ = fake_client_factory([make_text_response("ok")])
    service = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
    service._client = fake
    events = list(service.stream("hi", mode="chat", skills=None))
    selected = next(e for e in events if e["type"] == "skills_selected")
    assert selected["skills"] == []


def test_work_mode_default_all_skills(fake_client_factory):
    from tests.conftest import make_text_response

    from app.core.config import settings
    from app.services.agent_service import AgentService
    from app.services.skill_manager import SkillManager

    fake, _ = fake_client_factory([make_text_response("ok")])
    manager = SkillManager(settings.skills_dir, settings.custom_skills_dir)
    service = AgentService(manager)
    service._client = fake
    events = list(service.stream("hi", mode="work"))
    selected = next(e for e in events if e["type"] == "skills_selected")
    assert len(selected["skills"]) == len(manager.list_skills()) > 0


def test_chat_max_iterations(fake_client_factory):
    """chat 模式迭代上限收紧：模型持续要求调用工具时最多 5 轮。"""
    from tests.conftest import make_tool_call_response

    from app.core.config import settings
    from app.services.agent_service import AgentService
    from app.services.skill_manager import SkillManager

    scripts = [make_tool_call_response("read_file", {"file_path": "/tmp/x"})] * 10
    fake, calls = fake_client_factory(scripts)
    service = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
    service._client = fake
    events = list(service.stream("loop", mode="chat"))
    assert len(calls) == settings.chat_max_iterations == 5
    assert any("最大迭代" in e.get("content", "") for e in events if e["type"] == "error")


def test_history_replay(fake_client_factory):
    from tests.conftest import make_text_response

    from app.core.config import settings
    from app.services.agent_service import AgentService
    from app.services.skill_manager import SkillManager

    fake, calls = fake_client_factory([make_text_response("ok")])
    service = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
    service._client = fake
    history = [
        {"role": "user", "content": "第一轮问题"},
        {"role": "assistant", "content": "第一轮回答"},
        {"role": "tool", "content": "不应回放"},          # 必须被过滤
        {"role": "assistant", "content": "", "tool_calls": []},  # 空内容过滤
    ]
    list(service.stream("第二轮", mode="chat", history=history))
    roles = [m["role"] for m in calls[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
