"""测试基座：独立临时 SQLite + 假 LLM 客户端。

- 每个测试会话使用独立临时数据库文件（不用 :memory:，多线程不可见）；
- 每个用例后清空所有表，保证隔离；
- 调度器默认关闭（settings.scheduler_enabled=False）。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.core.config import settings

_TMP_DIR = Path(tempfile.mkdtemp(prefix="agent-test-"))


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    settings.scheduler_enabled = False
    settings.save_chat_log = False
    from app.db.base import configure_engine, init_db, reset_engine

    configure_engine(f"sqlite:///{_TMP_DIR / 'test.db'}")
    init_db()
    yield
    reset_engine()


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    from sqlalchemy import text

    from app.db.base import db_session
    from app.db.models import Base

    with db_session() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(text(f"DELETE FROM {table.name}"))


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
