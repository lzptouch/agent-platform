"""测试基座：独立临时 SQLite + 假 LLM 客户端。

- 每个测试会话使用独立临时数据库文件（不用 :memory:，多线程不可见）；
- 每个用例后清空所有表，保证隔离；
- 调度器默认关闭（settings.scheduler_enabled=False）。
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from app.core.config import settings

_TMP_DIR = Path(tempfile.mkdtemp(prefix="agent-test-"))


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    settings.scheduler_enabled = False
    from app.db.base import configure_engine, init_db, reset_engine

    configure_engine(f"sqlite:///{_TMP_DIR / 'test.db'}")
    init_db()
    yield
    reset_engine()
    # 清理本会话自建的临时目录（否则每次跑测试都会在系统临时目录留下残留）
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_tables():
    """每个用例后清空所有表**并复位进程级单例**。

    **W11-02 / AUD2-L22**：此前只清表，**不复位任何进程级单例** ——
    ``PermissionService.instance()``（规则缓存 + ``hit_count``）、
    ``MCPManager``（``_config_servers`` / ``_enabled`` / ``_conn_status`` / ``_tools_cache``）、
    ``WorkspaceService.instance()``、``current_run_context``、
    ``app.state.agent_service._client`` 全部**跨用例残留** →
    **测试结果依赖文件执行顺序**。

    典型症状：``test_mcp_sse_config.py`` 自己写了一个局部 ``_isolate_manager_config``
    来补这个洞（说明问题被感知但没在 conftest 根治）；``test_new_chains.py`` 断言
    内置 MCP server 数量为 3，而 ``MCPManager.__init__`` 启动即读**真实**
    ``~/.agent/mcp.json`` → 在配置过 MCP 的机器上直接失败。
    """
    yield
    from sqlalchemy import text

    from app.db.base import db_session
    from app.db.models import Base

    with db_session() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(text(f"DELETE FROM {table.name}"))

    # ---- 复位进程级单例 ----
    # PermissionService：规则缓存 + hit_count 跨用例累积
    try:
        from app.services.security.permissions import PermissionService

        PermissionService.reset_for_test()
    except Exception:  # noqa: BLE001
        pass

    # WorkspaceService：当前工作空间跨用例残留
    try:
        from app.services.workspace.service import WorkspaceService

        WorkspaceService.reset_for_test()
    except Exception:  # noqa: BLE001
        pass

    # MCPManager：配置 / 启用集合 / 连接状态 / 工具缓存
    try:
        import app.services.mcp_manager as mcp_mod

        mgr = mcp_mod._manager
        if mgr is not None:
            mgr._config_servers = {}
            mgr._config_errors = []
            mgr._enabled = set()
            mgr._conn_status = {}
            mgr._tools_cache = {}
    except Exception:  # noqa: BLE001
        pass

    # run 上下文（contextvar）
    try:
        from app.services.workspace.service import current_run_context

        current_run_context.set(None)
    except Exception:  # noqa: BLE001
        pass

    # AgentService 的假客户端（部分用例直接赋值 `svc._client = fake`）
    try:
        from app.main import app as fastapi_app

        svc = getattr(fastapi_app.state, "agent_service", None)
        if svc is not None:
            svc._client = None
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------- #
# 假 OpenAI 兼容客户端
# ---------------------------------------------------------------------- #
class FakeToolCallFunction:
    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = json.dumps(arguments, ensure_ascii=False)


class FakeToolCall:
    def __init__(self, name: str, arguments: dict, call_id: str = "call_1"):
        self.id = call_id
        self.type = "function"
        self.function = FakeToolCallFunction(name, arguments)


class FakeMessage:
    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class FakeChoice:
    def __init__(self, message: FakeMessage):
        self.message = message


class FakeResponse:
    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.choices = [FakeChoice(FakeMessage(content, tool_calls))]


class FakeCompletions:
    """按脚本依次返回响应；记录每次调用的入参。"""

    def __init__(self, scripts: list[FakeResponse]):
        self.scripts = list(scripts)
        self.calls: list[dict] = []

    def create(self, model=None, max_tokens=None, messages=None, tools=None, **_kw):
        self.calls.append({
            "model": model,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
        })
        if self.scripts:
            return self.scripts.pop(0)
        return FakeResponse(content="（默认回答）")


class FakeChat:
    def __init__(self, completions: FakeCompletions):
        self.completions = completions


class FakeClient:
    def __init__(self, scripts: list[FakeResponse]):
        self.chat = FakeChat(FakeCompletions(scripts))


def make_tool_call_response(tool: str, arguments: dict) -> FakeResponse:
    return FakeResponse(content="", tool_calls=[FakeToolCall(tool, arguments)])


def make_text_response(text: str) -> FakeResponse:
    return FakeResponse(content=text)


@pytest.fixture()
def fake_client_factory():
    """返回一个工厂：fake, calls = fake_client_factory(scripts)。"""

    def _factory(scripts: list[FakeResponse]):
        client = FakeClient(scripts)
        return client, client.chat.completions.calls

    return _factory


# --------------------------------------------------------------------------- #
# P5-03 · 分层 marker 自动打标（与 tests/conftest.py 同源）
# --------------------------------------------------------------------------- #
#: 文件名特征 → 标记
_NAME_MARKERS: list[tuple[str, str]] = [
    ("live_", "real_llm"),
    ("real_llm", "real_llm"),
    ("research", "slow"),
    ("p2_batch", "slow"),
    ("p3_batch", "slow"),
    ("smoke_", "integration"),
]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """按文件名给用例打标（兜底：保证**无未打标用例**）。"""
    for item in items:
        name = Path(str(item.fspath)).stem.lower()
        markers = {"integration"}
        for token, marker in _NAME_MARKERS:
            if token in name:
                markers.add(marker)
        if "test_p1_batch" in name or "test_p2_batch" in name:
            markers.discard("integration")
            markers.add("unit")
        for marker in sorted(markers):
            item.add_marker(getattr(pytest.mark, marker))
