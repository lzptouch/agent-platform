"""S5 上下文经济性与成本的契约测试。

按 doc/roadmap/06-阶段S5 的 §5.1 组织：工具目录 / 预算裁剪 / 压缩 / 记忆预筛 /
单价 / 角色 / 记忆索引 / 计量 / 长会话。
"""
from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.core.pricing import DEFAULT_PRICES, calculate_cost, get_price
from app.db.base import db_session
from app.db.models import LlmCallRow, MemoryIndexRow, RunRow, utc_now
from app.services.exec import memory as mem
from app.services.exec.memory import memory_root as real_memory_root
from app.services.exec.accounting import CallUsage, aggregate_run, cost_percentiles, record_call
from app.services.exec.catalog import (
    CatalogEntry,
    ToolLoader,
    build_catalog,
    catalog_text,
    search_catalog,
    split_core_and_catalog,
)
from app.services.exec.context import (
    NINE_SECTIONS,
    ContextBudget,
    build_nine_section_summary,
    compress,
    estimate_tokens,
    extract_sections,
    trim_messages,
)
from app.services.exec.team.roles import BUILTIN_ROLE_META, BUILTIN_ROLE_PROMPTS


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_memories(tmp_path, monkeypatch):
    """把三层记忆目录重定向到临时目录（不改 settings.data_dir —— 它是派生属性）。"""
    from app.core import workspace as ws_mod

    root = tmp_path / "mem"
    monkeypatch.setattr(
        mem, "memory_root",
        lambda scope: root / scope,
    )
    ws_mod.set_workspace_dir(tmp_path / "ws")
    yield
    ws_mod.reset_workspace_dir()


# --------------------------------------------------------------------------- #
# WP-5.1 工具目录与延迟装载
# --------------------------------------------------------------------------- #
class TestToolCatalog:
    def test_目录不含Schema(self):
        tools = [
            {"name": "read_file", "description": "读取文件。\n第二行", "input_schema": {"type": "object"}},
            {"name": "write_file", "description": "写文件。", "input_schema": {"type": "object"}},
        ]
        catalog = build_catalog(tools)
        assert all(isinstance(e, CatalogEntry) for e in catalog)
        assert catalog[0].description == "读取文件。"  # 只取首行
        text = catalog_text(catalog)
        assert "input_schema" not in text, "目录里不应出现 Schema"
        assert len(text) < sum(len(str(t)) for t in tools), "目录体积应远小于 Schema 体积"

    def test_tool_search返回TopK(self):
        tools = [
            {"name": "read_file", "description": "读取本地文件内容", "input_schema": {}},
            {"name": "write_file", "description": "写入文件", "input_schema": {}},
            {"name": "execute_bash", "description": "执行 shell 命令", "input_schema": {}},
        ]
        catalog = build_catalog(tools)
        hits = search_catalog(catalog, "文件", top_k=2)
        assert len(hits) <= 2
        assert any(h.name in ("read_file", "write_file") for h in hits)

    def test_tool_load后可调用(self):
        from app.services.tool_registry import ToolRegistry

        reg = ToolRegistry(mcp_manager=None)
        out = reg._dispatch_builtin("tool_load", {"names": ["write_file"]}, None)
        assert out["loaded"][0]["name"] == "write_file"
        assert "input_schema" in out["loaded"][0]

    def test_重复装载幂等(self):
        loader = ToolLoader([{"name": "a", "input_schema": {}}, {"name": "b", "input_schema": {}}])
        first = loader.load(["a"])
        second = loader.load(["a"])
        assert len(first) == 1
        assert second == [], "重复装载应幂等"

    def test_延迟装载只注入核心Schema(self):
        tools = [
            {"name": "read_file", "input_schema": {}},
            {"name": "write_file", "input_schema": {}},
            {"name": "list_directory", "input_schema": {}},
            {"name": "execute_bash", "input_schema": {}},
        ]
        injected, catalog = split_core_and_catalog(tools, lazy=True)
        names = {t["name"] for t in injected}
        assert "execute_bash" not in names, "非核心工具的 Schema 不应首轮注入"
        assert "read_file" in names
        assert len(catalog) == 4

    def test_降级开关关闭时全量注入(self):
        tools = [{"name": "read_file", "input_schema": {}}, {"name": "execute_bash", "input_schema": {}}]
        injected, _ = split_core_and_catalog(tools, lazy=False)
        assert len(injected) == 2


# --------------------------------------------------------------------------- #
# WP-5.2 上下文预算与裁剪
# --------------------------------------------------------------------------- #
class TestContextBudget:
    def test_预算计算(self):
        budget = ContextBudget.for_model("qwen-plus", 0.85)
        assert budget.window == 128_000
        assert budget.token_limit == int(128_000 * 0.85)
        usage = budget.usage([{"role": "user", "content": "你好世界"}])
        assert usage["tokens"] > 0
        assert 0 < usage["ratio"] < 1

    def test_裁剪保留最近N轮(self):
        budget = ContextBudget.for_model("qwen-plus", 0.85)
        messages = [{"role": "system", "content": "系统提示"}]
        for i in range(20):
            messages.append({"role": "user", "content": f"第{i}轮 " + "内容" * 4000})
            messages.append({"role": "assistant", "content": f"答{i} " + "回复" * 4000})
        trimmed = trim_messages(messages, budget, keep_recent_turns=2)
        assert trimmed.dropped > 0
        assert trimmed.messages[0]["content"] == "系统提示", "系统提示不被裁"
        kept = " ".join(str(m.get("content")) for m in trimmed.messages)
        assert "第19轮" in kept, "最近一轮应保留"
        assert "第0轮" not in kept, "最旧一轮应被裁掉"

    def test_预算内不裁剪(self):
        budget = ContextBudget.for_model("qwen-plus", 0.85)
        messages = [{"role": "user", "content": "短"}]
        trimmed = trim_messages(messages, budget)
        assert trimmed.dropped == 0


# --------------------------------------------------------------------------- #
# WP-5.3 压缩（九段结构 + 阈值）
# --------------------------------------------------------------------------- #
class TestCompression:
    def test_九段模板齐全(self):
        summary = build_nine_section_summary(intent="做报告")
        assert len(NINE_SECTIONS) == 9
        assert extract_sections(summary) == list(NINE_SECTIONS)

    def test_阈值定义(self):
        """真实阈值走 ``settings``（P2-13 删除了 context.py 里的重复常量）。"""
        from app.core.config import settings

        assert settings.context_compact_threshold == 0.70
        assert settings.context_summary_threshold == 0.85

    def test_压缩保留最近N轮原文(self):
        budget = ContextBudget.for_model("qwen-plus", 0.85)
        messages = [{"role": "system", "content": "系统"}]
        for i in range(10):
            messages.append({"role": "user", "content": f"问题{i} " + "细节" * 500})
            messages.append({"role": "assistant", "content": f"回答{i} " + "内容" * 500})
        result = compress(messages, budget, build_nine_section_summary(), keep_recent_turns=2)
        assert result.before_tokens > result.after_tokens
        assert any(m.get("_compressed") for m in result.messages)
        assert "问题9" in " ".join(str(m.get("content")) for m in result.messages)
        assert "问题0" not in " ".join(str(m.get("content")) for m in result.messages), "旧历史应被摘要替换"

    def test_压缩事件含前后token(self):
        budget = ContextBudget.for_model("qwen-plus", 0.85)
        messages = [{"role": "user", "content": "x" * 5000}]
        result = compress(messages, budget, build_nine_section_summary())
        payload = result.event_payload()
        assert payload["before_tokens"] > 0
        assert payload["after_tokens"] > 0
        assert payload["saved_tokens"] >= 0
        assert len(payload["sections"]) == 9


# --------------------------------------------------------------------------- #
# WP-5.4 记忆预筛与索引
# --------------------------------------------------------------------------- #
class TestMemory:
    def test_注入不超过5条(self):
        for i in range(8):
            mem.write_memory("project", f"m{i}.md", f"关于主题{i}的笔记")
        picked = mem.select_memories("主题", limit=5)
        assert len(picked) <= 5

    def test_去重(self):
        mem.write_memory("project", "dup.md", "重复内容")
        first = mem.select_memories("重复")
        assert first
        second = mem.select_memories("重复", used_paths={first[0].path})
        assert all(m.path != first[0].path for m in second)

    def test_索引与文件数一致(self):
        mem.write_memory("project", "a.md", "内容A")
        mem.write_memory("user", "b.md", "内容B")
        project_items = mem.list_memories("project")
        assert len(project_items) == 1
        assert project_items[0].scope == "project"

    def test_作用域目录不同(self):
        """用**真实实现**断言（夹具会把 memory_root 重定向到临时目录）。"""
        from app.core.workspace import get_workspace_dir

        assert real_memory_root("user") != real_memory_root("workspace")
        assert real_memory_root("project") != real_memory_root("workspace")
        assert str(get_workspace_dir()) in str(real_memory_root("workspace"))


# --------------------------------------------------------------------------- #
# WP-5.5 单价与计量
# --------------------------------------------------------------------------- #
class TestPricing:
    def test_成本计算(self):
        cost, snapshot = calculate_cost("qwen-plus", 1000, 1000)
        expected = (DEFAULT_PRICES["qwen-plus"].input_per_1k
                    + DEFAULT_PRICES["qwen-plus"].output_per_1k)
        assert abs(cost - expected) < 1e-6
        assert snapshot["provider"] == "dashscope"

    def test_单价快照后历史金额不变(self):
        cost1, snap1 = calculate_cost("qwen-plus", 1000, 1000)
        # 改价（模拟配置覆盖）
        original = DEFAULT_PRICES["qwen-plus"]
        try:
            DEFAULT_PRICES["qwen-plus"] = type(original)("dashscope", 99.0, 99.0)
            cost2, snap2 = calculate_cost("qwen-plus", 1000, 1000)
        finally:
            DEFAULT_PRICES["qwen-plus"] = original
        assert cost1 != cost2, "改价应影响新计算"
        assert snap1 != snap2
        # 快照本身保存了旧价 → 历史金额可复原
        restored = (snap1["input_per_1k"] + snap1["output_per_1k"])
        assert abs(restored - (original.input_per_1k + original.output_per_1k)) < 1e-9

    def test_每次调用有计量记录(self):
        rec = record_call(CallUsage(model="qwen-plus", prompt_tokens=100, completion_tokens=50), run_id="r1")
        assert rec["cost"] > 0
        with db_session() as db:
            row = db.scalars(
                __import__("sqlalchemy").select(LlmCallRow).where(LlmCallRow.run_id == "r1")
            ).first()
            assert row is not None
            assert row.price_snapshot  # 单价快照落库

    def test_run级token可加总(self):
        for _ in range(3):
            record_call(CallUsage(model="qwen-plus", prompt_tokens=100, completion_tokens=20), run_id="r2")
        agg = aggregate_run("r2")
        assert agg["llm_calls"] == 3
        assert agg["prompt_tokens"] == 300
        assert agg["completion_tokens"] == 60

    def test_区间统计可算(self):
        for _ in range(5):
            record_call(CallUsage(model="qwen-plus", prompt_tokens=1000, completion_tokens=100), run_id="r3")
        pct = cost_percentiles("qwen-plus")
        assert pct["samples"] >= 1
        assert pct["p50"] is not None


# --------------------------------------------------------------------------- #
# WP-5.3/5.4 角色（0 工具）
# --------------------------------------------------------------------------- #
class TestContextRoles:
    def test_压缩角色工具集为空(self):
        assert BUILTIN_ROLE_META["compact"]["tools"] == ()
        assert BUILTIN_ROLE_META["contextSummary"]["tools"] == ()

    def test_记忆筛选角色0工具(self):
        assert BUILTIN_ROLE_META["memorySelector"]["tools"] == ()

    def test_三个内置角色齐备(self):
        assert set(BUILTIN_ROLE_PROMPTS) == {"compact", "contextSummary", "memorySelector"}
        assert set(BUILTIN_ROLE_META) == {"compact", "contextSummary", "memorySelector"}


# --------------------------------------------------------------------------- #
# 端到端：长会话占用不线性增长
# --------------------------------------------------------------------------- #
class TestLongSession:
    def test_占用不线性增长(self):
        """50 轮后经裁剪，占用不应线性膨胀。"""
        budget = ContextBudget.for_model("qwen-plus", 0.85)
        messages: list[dict] = [{"role": "system", "content": "系统"}]
        for i in range(50):
            messages.append({"role": "user", "content": f"第{i}轮 " + "内容" * 2000})
            messages.append({"role": "assistant", "content": f"答{i} " + "回复" * 2000})
        raw = budget.usage(messages)
        trimmed = trim_messages(messages, budget, keep_recent_turns=3)
        after = budget.usage(trimmed.messages)
        assert after["ratio"] <= budget.ratio
        assert after["tokens"] < raw["tokens"], "裁剪后应显著小于原始体积"


# --------------------------------------------------------------------------- #
# 端点契约
# --------------------------------------------------------------------------- #
class TestContextEndpoints:
    def test_成本端点(self, client):
        r = client.get("/api/v1/runs/none/cost")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "totals" in body and "pricing" in body

    def test_记忆端点增删(self, client):
        created = client.post("/api/v1/memories", json={
            "scope": "project", "name": "e2e-memory", "content": "内容", "tags": ["x"],
        })
        assert created.status_code in (200, 201), created.text
        listed = client.get("/api/v1/memories").json()
        assert any(i["path"].endswith("e2e-memory.md") for i in listed["items"])
        deleted = client.request("DELETE", "/api/v1/memories", json={
            "scope": "project", "path": created.json()["path"],
        })
        assert deleted.status_code == 200

    def test_记忆端点校验(self, client):
        assert client.post("/api/v1/memories", json={"scope": "不存在", "name": "x", "content": "y"}).status_code == 422
        assert client.post("/api/v1/memories", json={"scope": "project"}).status_code == 422

    def test_会话上下文端点(self, client):
        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        r = client.get(f"/api/v1/sessions/{sess['id']}/context")
        assert r.status_code == 200
        body = r.json()
        assert "usage" in body and "thresholds" in body
