"""深度研究链路（Research）测试。

分两层：
1. **API 层**：健康检查、列表、404、无检索 Key 快速失败、删除保护
2. **链路层**：用 stub LLM + stub 检索驱动完整
   ``decompose → workers → synthesize → quality → (iterate) → completed``
   流程，验证迁移后的编排/配置/状态机连通（不依赖外网与真实 API Key）
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.research.utils import SearchResponse, SearchResult


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------- #
# 1. API 层
# ---------------------------------------------------------------------- #
def test_research_health(client):
    r = client.get("/api/v1/research/health")
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is True
    assert data["search_provider"] in ("bocha", "serper", "none")
    assert data["search_configured"] == (data["search_provider"] != "none")
    assert data["max_concurrent_tasks"] == settings.research_max_concurrent
    assert data["output_dir"].endswith("data/research")


def test_research_list_shape(client):
    r = client.get("/api/v1/research")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["total"], int)
    assert isinstance(body["tasks"], list)


def test_research_status_404(client):
    r = client.get("/api/v1/research/does-not-exist")
    assert r.status_code == 404
    assert "任务不存在" in r.json()["detail"]


def test_research_result_404(client):
    assert client.get("/api/v1/research/nope/result").status_code == 404


def test_research_stream_404(client):
    assert client.get("/api/v1/research/nope/stream").status_code == 404


def test_research_delete_404(client):
    assert client.delete("/api/v1/research/nope").status_code == 404


def test_health_contains_research_fields(client):
    h = client.get("/api/v1/health").json()
    for key in (
        "research_enabled",
        "research_search_provider",
        "research_configured",
        "research_total_tasks",
        "research_running_tasks",
    ):
        assert key in h


def test_submit_without_search_provider_fails_fast(client, monkeypatch):
    """未配置检索 Key 时，提交应**立即**返回 failed 而不是让用户白等。"""
    from app.services.research import search_client as sc_module

    monkeypatch.setattr(sc_module.SearchClient, "provider", property(lambda self: "none"))

    r = client.post("/api/v1/research", json={"task": "任意任务"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert "BOCHA_API_KEY" in body["message"]

    # 任务状态也应可查，且带明确错误原因
    st = client.get(f"/api/v1/research/{body['task_id']}").json()
    assert st["status"] == "failed"
    assert "BOCHA_API_KEY" in (st["error_message"] or "")


# ---------------------------------------------------------------------- #
# 2. 链路层（stub LLM + stub 检索）
# ---------------------------------------------------------------------- #
class _StubLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.model = "stub-model"
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.success = True
        self.error_msg = ""


class _StubLLMClient:
    """按 prompt 特征返回符合解析契约的响应。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def chat(self, prompt: str, system_prompt: str = "", model=None, temperature=0.7, max_tokens=4096):
        self.calls.append(prompt[:120])

        # 任务拆解 → 需要完整 JSON 计划
        if "制定详细的研究计划" in prompt:
            payload = {
                "task_understanding": {"core_question": "测试核心问题", "domain": "测试"},
                "query_type": {
                    "type": "breadth_first",
                    "reasoning": "stub",
                    "recommended_approach": "stub",
                },
                "worker_count": {"recommended": 2, "min": 1, "max": 3},
                "subtasks": [
                    {
                        "id": f"task_{i}",
                        "name": f"子任务{i}",
                        "description": f"描述{i}",
                        "search_queries": [f"查询{i}"],
                        "priority": "high",
                        "expected_output": "要点",
                        "research_objective": "目标",
                        "expected_sources": ["官方"],
                        "scope_boundaries": "范围",
                    }
                    for i in (1, 2)
                ],
                "report_structure": {"sections": ["概述", "结论"]},
                "research_plan": {"steps": ["搜集", "归纳"]},
            }
            return _StubLLMResponse(json.dumps(payload, ensure_ascii=False))

        # 质量检查 → 高分直接通过（避免多轮迭代）
        if "质量检查和批判性评估" in prompt:
            return _StubLLMResponse(json.dumps(
                {"overall_score": 92, "needs_revision": False, "revision_priority": "low",
                 "dimensions": {}, "issues": []},
                ensure_ascii=False,
            ))

        # 收益递减检查 → 未递减
        if "收益递减" in prompt:
            return _StubLLMResponse(json.dumps(
                {"is_diminishing": False, "reason": "stub", "recommendation": "continue"},
                ensure_ascii=False,
            ))

        # 搜索查询扩展 → 返回 JSON 列表
        if "生成多个搜索查询词" in prompt:
            return _StubLLMResponse(json.dumps(["查询A", "查询B"], ensure_ascii=False))

        # 其余（Worker 分析 / 章节撰写 / 综合）→ 普通文本
        return _StubLLMResponse("## 测试报告段落\n\n这是一段由 stub 生成的报告内容。")


class _StubSearchClient:
    """返回固定检索结果的检索客户端。"""

    provider = "stub"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, count=None, freshness=None) -> SearchResponse:
        self.queries.append(query)
        return SearchResponse(
            query=query,
            results=[
                SearchResult(
                    title=f"结果 {query} #{i}",
                    url=f"https://example.com/{i}",
                    snippet=f"关于 {query} 的第 {i} 条事实信息。",
                    site_name="example.com",
                    date="2026-09-15",
                )
                for i in range(1, 4)
            ],
            total_matches=3,
            success=True,
        )

    def multi_search(self, queries, count=None):
        return [self.search(q, count) for q in queries]


@pytest.fixture
def stub_pipeline(monkeypatch):
    """把 orchestrator / workers 的 LLM 与检索客户端替换为 stub。"""
    from app.services.research import orchestrator as orch_module
    from app.services.research import search_client as sc_module
    from app.services.research import workers as workers_module

    llm = _StubLLMClient()
    search = _StubSearchClient()

    monkeypatch.setattr(orch_module, "get_llm_client", lambda: llm)
    monkeypatch.setattr(workers_module, "get_llm_client", lambda: llm)
    monkeypatch.setattr(workers_module, "get_search_client", lambda: search)
    monkeypatch.setattr(sc_module, "get_search_client", lambda: search)
    monkeypatch.setattr(sc_module.SearchClient, "provider", property(lambda self: "stub"))

    return llm, search


def test_full_pipeline_with_stubs(stub_pipeline):
    """完整链路：拆解 → 分发 Worker → 综合 → 质量检查 → 产出报告。"""
    from app.services.research.service import run_research

    llm, search = stub_pipeline
    stages: list[str] = []
    state = run_research("测试：新能源汽车市场分析", max_workers=2, on_progress=lambda s, d: stages.append(s))

    assert state.status == "completed", state.error_msg
    assert state.final_report
    assert state.quality_score >= 80
    assert state.task_plan is not None
    assert len(state.task_plan.subtasks) == 2
    assert state.worker_results, "应至少有一个 Worker 产出"

    # 关键阶段都被触发
    for stage in ("decomposing", "decomposed", "dispatching", "synthesizing", "quality_checking", "completed"):
        assert stage in stages, f"缺少阶段: {stage}（实际: {stages}）"

    # 检索确实被调用，且 LLM 被多次调用（拆解/撰写/质量）
    assert search.queries, "检索客户端未被调用"
    assert len(llm.calls) >= 3


def test_pipeline_through_api_with_stubs(client, stub_pipeline):
    """通过 HTTP API 跑通完整研究任务并取回报告。"""
    import time

    r = client.post("/api/v1/research", json={"task": "测试：API 全链路", "max_workers": 2, "max_iterations": 2})
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    status = None
    for _ in range(120):  # 最多等 60s
        time.sleep(0.5)
        status = client.get(f"/api/v1/research/{task_id}").json()
        if status["status"] in ("completed", "failed"):
            break

    assert status is not None
    assert status["status"] == "completed", status.get("error_message")
    assert status["quality_score"] >= 80
    assert status["progress"], "应记录进度事件"

    # 报告
    result = client.get(f"/api/v1/research/{task_id}/result")
    assert result.status_code == 200
    body = result.json()
    assert body["report"]
    assert body["quality_score"] >= 80

    # 落盘
    task_dir = settings.research_output_abs + "/" + task_id
    import pathlib

    reports = list(pathlib.Path(task_dir).glob("report_*.md"))
    metas = list(pathlib.Path(task_dir).glob("meta_*.json"))
    assert reports, f"报告未落盘: {task_dir}"
    assert metas, f"元数据未落盘: {task_dir}"

    # 完成后可删除
    assert client.delete(f"/api/v1/research/{task_id}").status_code == 200


def test_delete_running_task_rejected(client, stub_pipeline, monkeypatch):
    """运行中的任务不允许删除（400）。"""
    from app.services.research import search_client as sc_module

    # 让后续任务能提交（provider 非 none），但不真正执行
    monkeypatch.setattr(sc_module.SearchClient, "provider", property(lambda self: "stub"))

    from app.api.deps import get_research_manager

    manager = get_research_manager_for_test(client)
    task_id = manager.create_task("运行中的任务")
    manager.set_running(task_id)
    try:
        r = client.delete(f"/api/v1/research/{task_id}")
        assert r.status_code == 400
        assert "运行中" in r.json()["detail"]
    finally:
        manager.tasks.pop(task_id, None)


def get_research_manager_for_test(client):
    """从 TestClient 中取出共享的 ResearchManager。"""
    app.state  # noqa: B018 —— 触发初始化
    from app.core.state import init_app_state

    init_app_state(app)
    return app.state.research_manager
