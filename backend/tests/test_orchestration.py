"""多 Agent 编排接线的验收测试（P2-09 路 B · P2-11 黑板 · P2-08 收费站）。

缺陷背景：``exec/team/orchestrator.py``（~350 行，parallel / sequential / review
三模式）**只被测试引用**——运行时零调用，文档却称「多 Agent 编排（3 模式）
已落地」；黑板与收费站同样只走 API 层。
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _stub_executor(outputs: dict[str, str] | None = None):
    """返回一个记录调用的假执行器。"""
    calls: list[tuple[str, str]] = []

    def _exec(task, context: str) -> str:
        calls.append((task.title, context))
        return (outputs or {}).get(task.title, f"[{task.title}] 完成")

    _exec.calls = calls  # type: ignore[attr-defined]
    return _exec


# --------------------------------------------------------------------------- #
# P2-09 路 B · 端点与三模式
# --------------------------------------------------------------------------- #
class TestOrchestrateEndpoint:
    """``POST /api/v1/orchestrate`` 是编排器的**真实入口**。"""

    def test_端点已注册(self, client):
        """FastAPI 新版用 ``_IncludedRouter`` 包装，路由不在 ``app.routes`` 里展平——
        因此以**实际调用**为准（非法入参 → 422 说明端点存在且已挂载）。"""
        r = client.post("/api/v1/orchestrate", json={"task": "t", "mode": "bad"})
        assert r.status_code == 422, r.text
        spec = app.openapi()
        assert "/api/v1/orchestrate" in spec.get("paths", {}), "编排端点未出现在 OpenAPI"

    def test_编排器不再只被测试引用(self, client):
        """生产代码必须真的引用编排器（此前零调用）。"""
        from pathlib import Path

        src = Path("app/services/exec/team/service.py").read_text(encoding="utf-8")
        assert "TeamOrchestrator" in src, "编排服务未使用 TeamOrchestrator"

    def test_非法模式被拒(self, client):
        r = client.post("/api/v1/orchestrate", json={
            "task": "t", "mode": "diagonal",
            "subtasks": [{"title": "a", "prompt": "p"}],
        })
        assert r.status_code == 422, r.text

    def test_无子任务被拒(self, client):
        r = client.post("/api/v1/orchestrate", json={"task": "t", "subtasks": []})
        assert r.status_code == 422, r.text

    def test_子任务缺title被拒(self, client):
        r = client.post("/api/v1/orchestrate", json={
            "task": "t", "subtasks": [{"prompt": "p"}],
        })
        assert r.status_code == 422, r.text

    @pytest.mark.parametrize("mode", ["parallel", "sequential", "review"])
    def test_三种模式都返回聚合结果(self, client, mode):
        """验收断言②：三种模式各自返回聚合结果。"""
        from app.services.exec.team.service import OrchestrationService

        svc = OrchestrationService()
        out = svc.orchestrate(
            task="总体任务",
            subtasks=[
                {"title": "取数", "prompt": "取数", "role": "analyst"},
                {"title": "作图", "prompt": "作图", "role": "artist"},
            ],
            mode=mode,
            executor=_stub_executor(),
        )
        assert out["mode"] == mode
        # review 模式会追加一个「评审修订」子任务
        assert len(out["results"]) >= 2, out
        assert out["summary"], "应有聚合摘要"
        assert all(r["output"] for r in out["results"])


# --------------------------------------------------------------------------- #
# 主 Agent 作为 worker
# --------------------------------------------------------------------------- #
class TestAgentAsWorker:
    """子任务应由**主 Agent** 执行（不是外部注入的假执行器）。"""

    def test_默认执行器调用主Agent(self, client):
        from app.services.exec.team.service import OrchestrationService

        seen: list[dict] = []

        class _StubAgent:
            def stream(self, prompt, model=None, **kw):
                seen.append({"prompt": prompt, "model": model, **kw})
                yield {"type": "model_text", "content": "主 Agent 的答案"}

        svc = OrchestrationService(_StubAgent())
        out = svc.orchestrate(
            task="总体任务",
            subtasks=[{"title": "子任务A", "prompt": "做点事"}],
            model="qwen-plus",
        )
        assert seen, "主 Agent 未被调用"
        assert "做点事" in seen[0]["prompt"]
        assert seen[0]["model"] == "qwen-plus"
        assert out["results"][0]["output"] == "主 Agent 的答案"

    def test_未绑定Agent时子任务失败但整体不崩(self, client):
        """编排器的约定：单个子任务失败**不拖垮整体**（错误进 ``result.error``）。"""
        from app.services.exec.team.service import OrchestrationService

        svc = OrchestrationService()
        out = svc.orchestrate(task="t", subtasks=[{"title": "a", "prompt": "p"}])
        assert out["results"][0]["error"], "未绑定 Agent 时子任务应报错"
        assert out["summary"], "整体仍应给出摘要"

    def test_共享上下文注入(self, client):
        """sequential 模式下，后一个子任务应拿到前一个的产出作为上下文。"""
        from app.services.exec.team.service import OrchestrationService

        exec_ = _stub_executor({"第一步": "第一步产出"})
        svc = OrchestrationService()
        svc.orchestrate(
            task="总体任务",
            subtasks=[
                {"title": "第一步", "prompt": "p1"},
                {"title": "第二步", "prompt": "p2"},
            ],
            mode="sequential",
            executor=exec_,
        )
        second_ctx = dict(exec_.calls).get("第二步", "")
        assert "第一步产出" in second_ctx, f"上下文未透传：{second_ctx!r}"


# --------------------------------------------------------------------------- #
# P2-11 · 黑板接入
# --------------------------------------------------------------------------- #
class TestBlackboardWiring:
    """子任务应登记为黑板任务项，状态随执行流转。"""

    def test_子任务登记为黑板项(self, client):
        from app.services.exec.team.service import OrchestrationService

        svc = OrchestrationService()
        out = svc.orchestrate(
            task="总体任务",
            subtasks=[{"title": "取数", "prompt": "p"}],
            board_id="p2-board-1",
            executor=_stub_executor(),
        )
        assert out["board_id"] == "p2-board-1"
        assert out["board_items"], "黑板项未生成"
        item = out["board_items"][0]
        assert item["title"] == "取数"
        assert item["status"] == "done", f"黑板项状态未流转：{item}"

    def test_执行失败时黑板项标失败(self, client):
        from app.services.exec.team.service import OrchestrationService

        def _boom(task, context):
            raise RuntimeError("子任务炸了")

        svc = OrchestrationService()
        out = svc.orchestrate(
            task="总体任务",
            subtasks=[{"title": "会炸的", "prompt": "p"}],
            board_id="p2-board-2",
            executor=_boom,
        )
        item = out["board_items"][0]
        assert item["status"] == "failed", item

    def test_依赖项在依赖完成后才就绪(self, client):
        """「依赖未完成的项不启动」——黑板依赖图真正生效。"""
        from app.services.exec.team.service import OrchestrationService

        svc = OrchestrationService()
        out = svc.orchestrate(
            task="总体任务",
            subtasks=[
                {"title": "前置", "prompt": "p1"},
                {"title": "后置", "prompt": "p2", "deps": [0]},
            ],
            board_id="p2-board-3",
            executor=_stub_executor(),
        )
        by_title = {i["title"]: i for i in out["board_items"]}
        assert by_title["前置"]["status"] == "done"
        assert by_title["后置"]["status"] == "done"
        # 依赖关系已翻译成黑板项 id
        assert by_title["后置"]["deps"], "依赖未翻译成黑板项 id"

    def test_黑板消息可查(self, client):
        """子任务产出应写一条**压缩通知**进消息表。"""
        from app.services.exec.team.service import OrchestrationService

        svc = OrchestrationService()
        svc.orchestrate(
            task="总体任务",
            subtasks=[{"title": "取数", "prompt": "p"}],
            board_id="p2-board-4",
            executor=_stub_executor(),
        )
        msgs = svc.messages.list(board_id="p2-board-4")
        assert msgs, "黑板消息未写入"
        assert any("取数" in (m.content or "") for m in msgs)


# --------------------------------------------------------------------------- #
# P2-08 · 收费站
# --------------------------------------------------------------------------- #
class TestTollgate:
    """主上下文**只含压缩通知**——子任务原始推理不进主上下文。"""

    def test_主上下文不含子任务原文(self, client):
        from app.services.exec.team.service import OrchestrationService

        long_output = "SECRET_RAW_OUTPUT_" + "x" * 500
        svc = OrchestrationService()
        out = svc.orchestrate(
            task="总体任务",
            subtasks=[{"title": "取数", "prompt": "p"}],
            executor=_stub_executor({"取数": long_output}),
        )
        ctx = out["main_context"]
        assert "SECRET_RAW_OUTPUT_" + "x" * 500 not in ctx, "主上下文混入了子任务原文"
        assert "取数" in ctx, "主上下文应含压缩通知"

    def test_收费站校验通过(self, client):
        from app.services.exec.team.service import OrchestrationService

        svc = OrchestrationService()
        out = svc.orchestrate(
            task="总体任务",
            subtasks=[{"title": "a", "prompt": "p"}],
            executor=_stub_executor(),
        )
        assert out["tollgate"]["ok"] is True, out["tollgate"]
        assert out["tollgate"]["violations"] == []

    def test_响应含完整结果与压缩上下文(self, client):
        """API 响应给用户看**完整**结果；主上下文只有**压缩通知**（摘要 ≤200 字）。"""
        from app.services.exec.team.service import OrchestrationService

        long_output = "完整产出内容" + "尾巴" * 300
        svc = OrchestrationService()
        out = svc.orchestrate(
            task="总体任务",
            subtasks=[{"title": "a", "prompt": "p"}],
            executor=_stub_executor({"a": long_output}),
        )
        assert out["results"][0]["output"] == long_output, "响应应含完整结果"
        assert "尾巴" * 300 not in out["main_context"], "主上下文混入了子任务原文"
        assert "完整产出内容" in out["main_context"], "主上下文应含压缩通知摘要"
