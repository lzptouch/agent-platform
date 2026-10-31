"""延迟装载（``context_lazy_tool_loading``）的**可达性**测试。

**缺陷（已修）**：`exec/catalog.py` 的 ``CORE_TOOLS`` 不含 ``tool_search`` /
``tool_load`` → 引导工具**自身不可见** → 模型无法装载其他工具 →
``execute_python`` / ``execute_bash`` / ``rag_*`` / ``web_research`` / 所有
``mcp_*`` 在默认配置下**全部不可达**，而 prompt 却要求「先 tool_search 再
tool_load」→ 提示与工具集自相矛盾。
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


class TestLazyToolLoadingReachable:
    """引导工具必须始终可见；装载机制必须真的能装进工具。"""

    def test_核心工具含引导工具(self, client):
        from app.services.exec.catalog import CORE_TOOLS

        assert "tool_search" in CORE_TOOLS, CORE_TOOLS
        assert "tool_load" in CORE_TOOLS, CORE_TOOLS

    def test_注入的schema含引导工具(self, client):
        """默认（lazy 开启）注入的工具集必须**含**两个引导工具。"""
        from app.core.config import settings
        from app.services.exec.catalog import ToolLoader
        from app.services.mcp_manager import get_mcp_manager
        from app.services.tool_registry import ToolRegistry

        reg = ToolRegistry(get_mcp_manager())
        tools = reg.get_combined_tools(enable_rag=True)
        loader = ToolLoader(tools)
        names = {t["name"] for t in loader.schema_list()}
        assert "tool_search" in names, names
        assert "tool_load" in names, names

    def test_装载机制能把工具装进来(self, client):
        """调用 ``tool_load`` 后，非核心工具应进入下一轮的 schema 列表。"""
        from app.services.exec.catalog import ToolLoader
        from app.services.mcp_manager import get_mcp_manager
        from app.services.tool_registry import ToolRegistry

        reg = ToolRegistry(get_mcp_manager())
        tools = reg.get_combined_tools(enable_rag=True)
        loader = ToolLoader(tools)

        before = {t["name"] for t in loader.schema_list()}
        assert "execute_python" not in before, "execute_python 本应是需要装载的非核心工具"

        loader.load(["execute_python"])
        after = {t["name"] for t in loader.schema_list()}
        assert "execute_python" in after, after

    def test_检索面覆盖rag与web工具(self, client):
        """``tool_search`` 必须能搜到 RAG / Web 工具（此前只搜内置 8 个）。"""
        from app.services.mcp_manager import get_mcp_manager
        from app.services.tool_registry import ToolRegistry

        reg = ToolRegistry(get_mcp_manager())
        out = reg._tool_search({"query": "rag"})
        assert out, out
        text = str(out)
        assert "rag" in text.lower(), text

    def test_引导工具定义在注册表里(self, client):
        """注册表必须**自带**两个引导工具的定义（否则注入的是空气）。"""
        from app.services.mcp_manager import get_mcp_manager
        from app.services.tool_registry import ToolRegistry

        reg = ToolRegistry(get_mcp_manager())
        names = {t["name"] for t in reg.get_combined_tools()}
        assert "tool_search" in names, names
        assert "tool_load" in names, names
