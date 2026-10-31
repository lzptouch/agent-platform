"""反思分支（``enable_reflection=True``）的**运行期**回归测试。

**背景**：P3-05 给反思路径接上「按剩余 token 预算截断」时，
``_execute_actions()`` 里引用了 ``messages`` 与 ``model``，但**方法签名没有这两个参数**
→ 首个工具动作执行后即 ``NameError`` → ``POST /agent/chat`` 的 reflection 路径
**完全不可用**（被 ``run_executor`` 转成 error 终态）。

这类缺陷不会被「主链路测试」发现（主链路不走反思分支），
因此这里用**真实执行**反思路径来锁住它。
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


class TestReflectionBranchRunnable:
    """反思分支必须能真正跑完，不因 NameError 崩掉。"""

    def test_反思路径不抛NameError(self, client, monkeypatch):
        """跑通一次反思：**Action 阶段**执行工具并产出事件。"""
        from app.core.config import settings
        from app.services.agent_service import AgentService
        from app.services.skill_manager import SkillManager
        from tests.conftest import make_text_response

        # 规划阶段走**模块级** ``app.core.llm.chat``（非 client）→ 必须 patch
        plan_json = '{"actions": [{"tool": "list_directory", "input": {"dir_path": "."}}]}'
        monkeypatch.setattr("app.core.llm.chat", lambda *a, **k: plan_json)
        # 回答阶段用 ``get_llm_client()`` + ``stream=True`` → 需流式 fake
        monkeypatch.setattr("app.core.llm.get_llm_client", lambda: _StreamFakeClient())

        fake = _FakeClient([make_text_response(plan_json)])
        service = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
        service._client = fake

        events = list(service.stream("反思探针", mode="work", enable_reflection=True))
        kinds = [e.get("type") for e in events]

        assert "reflection_start" in kinds, kinds
        # **核心断言**：不得出现 NameError 导致的 error 终态
        errors = [e for e in events if e.get("type") == "error"]
        assert not errors, f"反思路径报错: {errors}"
        # 工具调用应真实发生
        assert "tool_call" in kinds, kinds

    def test_反思路径工具结果带截断标记(self, client, monkeypatch):
        """反思分支的 ``tool_result`` 也带 ``truncated`` / ``budget_ratio``。"""
        from app.core.config import settings
        from app.services.agent_service import AgentService
        from app.services.skill_manager import SkillManager
        from tests.conftest import make_text_response

        plan_json = '{"actions": [{"tool": "list_directory", "input": {"dir_path": "."}}]}'
        monkeypatch.setattr("app.core.llm.chat", lambda *a, **k: plan_json)

        fake = _FakeClient([make_text_response(plan_json)])
        service = AgentService(SkillManager(settings.skills_dir, settings.custom_skills_dir))
        service._client = fake

        events = list(service.stream("反思截断探针", mode="work", enable_reflection=True))
        results = [e for e in events if e.get("type") == "tool_result"]
        assert results, f"未产出 tool_result: {[e.get('type') for e in events]}"
        assert "truncated" in results[0], results[0]
        assert "budget_ratio" in results[0], results[0]

    def test_签名接受messages与model(self, client):
        """``_execute_actions`` 的签名必须真的接受这两个参数（防再犯）。"""
        import inspect

        from app.services.agent_service import AgentService

        params = inspect.signature(AgentService._execute_actions).parameters
        assert "messages" in params, params
        assert "model" in params, params


class _FakeClient:
    """最小 fake client：按脚本顺序返回响应。"""

    def __init__(self, scripts: list) -> None:
        self._scripts = list(scripts)
        self._i = 0
        self.chat = self._chat

    def _chat(self, **kwargs):
        if self._i < len(self._scripts):
            out = self._scripts[self._i]
            self._i += 1
            return out
        from tests.conftest import make_text_response

        return make_text_response("完成")


class _StreamChunk:
    """最小流式 chunk（``choices[0].delta.content``）。"""

    def __init__(self, content: str) -> None:
        delta = type("_Delta", (), {"content": content, "reasoning_content": None})()
        self.choices = [type("_Choice", (), {"delta": delta})()]


class _StreamFakeClient:
    """支持 ``stream=True`` 的 fake client（回答阶段用）。

    注意 ``chat`` 必须是**属性**（对象）——真实 SDK 的形态是
    ``client.chat.completions.create(...)``。
    """

    def __init__(self, text: str = "最终答案") -> None:
        self._text = text
        outer = self

        class _Completions:
            def create(self, **kwargs):
                if kwargs.get("stream"):
                    return iter([_StreamChunk(outer._text)])
                from tests.conftest import make_text_response

                return make_text_response(outer._text)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()
