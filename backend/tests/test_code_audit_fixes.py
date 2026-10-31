"""本轮**代码审计**发现的缺陷修复的验收测试。

覆盖：
1. **P2-10 核心承诺失效** —— ``role_tools`` 参数「声明并注释承诺」作为工具上界，
   但函数体从未使用 → 角色声明的工具集**根本没有裁剪效果**。
2. **反思分支必崩** —— ``_execute_actions()`` 引用未定义的 ``messages`` / ``model``
   → ``POST /agent/chat`` 的 reflection 路径完全不可用。
3. **一次性补丁脚本残留在 app 包内** —— import 即执行改写源文件
   （``_p214b.py`` 甚至会 ``git checkout --`` 覆盖源文件）。
4. **orchestrator 用了未定义的 logger** —— checkpoint 写/读失败路径抛 NameError。
"""
from __future__ import annotations

from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_ROOT / "app"


def _registry():
    """构造带 MCP 管理器的 ``ToolRegistry``（生产同款依赖）。"""
    from app.services.mcp_manager import get_mcp_manager
    from app.services.tool_registry import ToolRegistry

    return ToolRegistry(get_mcp_manager())


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


class TestRoleToolsUpperBound:
    """P2-10：角色的工具集必须是**真实的上界**。"""

    def test_非空role_tools裁剪工具集(self, client):
        from app.services.tool_registry import ToolRegistry

        reg = _registry()
        all_tools = reg.get_combined_tools(enable_rag=True)
        assert len(all_tools) > 2, all_tools

        limited = reg.get_combined_tools(
            enable_rag=True, role_tools=["read_file", "list_directory"],
        )
        names = {t["name"] for t in limited}
        assert names == {"read_file", "list_directory"}, names
        assert "write_file" not in names, "角色上界未生效"

    def test_空role_tools不限制(self, client):
        """内置角色的 ``tools`` 为空 → **不限制**（保持全量工具）。"""
        from app.services.tool_registry import ToolRegistry

        reg = _registry()
        full = reg.get_combined_tools(enable_rag=True)
        same = reg.get_combined_tools(enable_rag=True, role_tools=[])
        assert len(same) == len(full), (len(same), len(full))

    def test_mcp族匹配(self, client):
        """``mcp_<server>`` 形式的允许项应匹配该 Server 的全部工具。"""
        from app.services.tool_registry import ToolRegistry

        reg = _registry()
        tools = reg.get_combined_tools(
            enable_mcp=True, mcp_servers=["weather"], role_tools=["mcp_weather"],
        )
        names = {t["name"] for t in tools}
        assert all(n.startswith("mcp_weather__") for n in names), names
        assert names, "MCP 族匹配未命中"

    def test_agent_service确实传入role_tools(self, client):
        """``agent_service`` 必须把角色的工具集传下去（否则上界形同虚设）。"""
        src = (APP_DIR / "services" / "agent_service.py").read_text(encoding="utf-8")
        assert "role_tools=" in src, "未传 role_tools"
        assert "list(role.tools)" in src, "未从角色读取 tools"


class TestReflectionBranchFixed:
    """反思分支必须能真跑通（不再 NameError）。"""

    def test_签名接受messages与model(self, client):
        import inspect

        from app.services.agent_service import AgentService

        params = inspect.signature(AgentService._execute_actions).parameters
        assert "messages" in params, params
        assert "model" in params, params


class TestNoPatchScriptResidue:
    """app 包内**不得**残留一次性补丁脚本（import 即改写源文件）。"""

    def test_无补丁脚本(self, client):
        offenders = [
            p.relative_to(APP_DIR).as_posix()
            for p in APP_DIR.rglob("*.py")
            if p.name.startswith(("_p", "_batch")) or p.name.endswith("_patch.py")
        ]
        assert not offenders, f"app 包内残留一次性补丁脚本: {offenders}"

    def test_补丁脚本不会改写源文件(self, client):
        """app 内不得**真实调用** ``git checkout`` / ``git reset``（改写源文件）。

        注意：``services/security/policy.py`` 的 docstring 里**举例**提到
        ``git reset``（危险命令前缀检测），那不是调用 → 判据必须看
        ``subprocess`` / ``os.system`` 的**实参**，而非全文包含。
        """
        import re

        pattern = re.compile(
            r"(subprocess\.[a-z_]+|os\.system|os\.popen)\s*\([^)]*"
            r"['\"][^'\"]*git\s+(checkout|reset)",
            re.S,
        )
        offenders = []
        for p in APP_DIR.rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                offenders.append(p.relative_to(APP_DIR).as_posix())
        assert not offenders, f"真实调用破坏性 git 操作的文件: {offenders}"


class TestOrchestratorLogger:
    """orchestrator 用了 ``logger`` → 必须真的定义。"""

    def test_logger已定义(self, client):
        from app.services.research import orchestrator

        assert hasattr(orchestrator, "logger"), "orchestrator 未定义 logger"

    def test_模块可导入(self, client):
        import importlib

        mod = importlib.import_module("app.services.research.orchestrator")
        assert mod is not None
