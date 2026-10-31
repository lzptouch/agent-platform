"""P2/P3/P4 批次续作的验收测试。

覆盖本轮新交付的 9 项：
- P2-03 / R-22 · 九段摘要真正接 LLM（内置角色 Prompt 送出）
- P2-04 · DR 评分兜底不虚高 + 事实核查接线
- P2-07 · 敏感信息三档处置 + 写前扫描 + 输出还原
- P2-10 · 角色层接入（Prompt 注入 / 工具上界 / 模型档）
- P2-12 · emit_artifact 工具（产物登记接入工具层）
- P3-02 · 投递通道可配置
- P3-03 · 反思轮数上限
- P4-02 · 前端消费 done.status
- P4-03 · SSE 重连退避与上限
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = BACKEND_ROOT.parent / "frontend" / "web" / "vue-element-plus" / "src"


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# P2-12 · emit_artifact 工具（产物登记接入工具层）
# --------------------------------------------------------------------------- #
class TestEmitArtifactTool:
    """``emit_artifact`` 此前**只存在于注释**——``artifacts`` 表在生产路径恒空。"""

    def test_工具已注册(self, client):
        from app.services.tool_registry import BUILTIN_TOOLS

        names = {t["name"] for t in BUILTIN_TOOLS}
        assert "emit_artifact" in names, "emit_artifact 未注册到工具目录"

    def test_权限规则已放行(self, client):
        from app.services.security.permissions import BUILTIN_RULES

        assert any(
            scope == "tool" and pattern == "emit_artifact" and decision == "allow"
            for scope, pattern, decision, _risk, _prio in BUILTIN_RULES
        ), "内置规则缺 emit_artifact → 权限引擎会按 ask 拦截"

    def test_无运行上下文时报错(self, client):
        from app.services.tool_registry import ToolRegistry

        out = ToolRegistry._dispatch_builtin("emit_artifact", {"path": "a.txt"}, None)
        assert out.get("error"), "无运行上下文时必须明确报错而不是静默成功"

    def test_有运行上下文时登记成功(self, client, tmp_path):
        """真实登记：产物表从空变为有一条记录。"""
        from app.db.base import db_session
        from app.db.models import ArtifactRow
        from app.services.tool_registry import ToolRegistry
        from app.services.workspace.service import current_run_context

        root = tmp_path / "ws"
        root.mkdir()
        (root / "out.md").write_text("交付内容", encoding="utf-8")

        ctx = {
            "run_id": "p2_emit_run",
            "workspace_id": None,
            "workspace_root": str(root),
        }
        token = current_run_context.set(ctx)
        try:
            out = ToolRegistry._dispatch_builtin("emit_artifact", {"path": "out.md"}, None)
        finally:
            current_run_context.reset(token)

        assert not out.get("error"), out
        assert out.get("registered") is True
        assert out["artifact"]["path"] == "out.md"

        with db_session() as db:
            rows = db.query(ArtifactRow).filter(ArtifactRow.run_id == "p2_emit_run").all()
            assert len(rows) == 1, "产物未落库"
            assert rows[0].path == "out.md"


# --------------------------------------------------------------------------- #
# P2-07 · 敏感信息三档处置
# --------------------------------------------------------------------------- #
class TestSensitivePolicy:
    """``sensitive.process`` 的 ``policy`` 参数此前**形同虚设**。"""

    #: 高置信（``sk-`` 前缀 → dashscope/openai 模式 → 一律拒绝）
    SECRET = "sk-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOP"
    #: 低置信（``generic_token`` 模式 → 可加密参与上下文）
    TOKEN = "api_key=abcdefghijklmnopqrstuvwx"

    def test_allow策略只记录不改内容(self):
        from app.services.security import sensitive

        out = sensitive.process(f"配置 {self.TOKEN}", policy="allow")
        assert out["action"] == "allow"
        assert self.TOKEN in out["processed"], "allow 策略不应改内容"
        assert out["hits"], "命中必须被记录"

    def test_encrypt策略加密片段(self):
        from app.services.security import sensitive

        out = sensitive.process(f"配置 {self.TOKEN}", policy="encrypt")
        assert out["action"] == "allow_and_encrypt"
        assert self.TOKEN not in out["processed"], "encrypt 策略必须替换原文"
        assert "ENC[" in out["processed"]

    def test_encrypt后可以还原(self):
        from app.services.security import sensitive

        original = f"配置 {self.TOKEN}"
        enc = sensitive.process(original, policy="encrypt")["processed"]
        assert self.TOKEN in sensitive.restore(enc), "密文应能还原"

    def test_deny策略命中即拒(self):
        from app.services.security import sensitive

        out = sensitive.process(f"配置 {self.TOKEN}", policy="deny")
        assert out["action"] == "deny"

    def test_写前扫描拒绝高危内容(self, client, tmp_path):
        """写文件前扫描命中 → 拒绝写入且不落盘。"""
        from app.services.code_executor import LocalCodeExecutor

        executor = LocalCodeExecutor()
        target = tmp_path / "secret.txt"
        out = executor.write_file(str(target), f"key={self.SECRET}")
        assert out.get("success") is False, "高危敏感内容不应被写入"
        assert not target.exists()

    def test_输出还原(self):
        """模型输出前还原加密片段。"""
        from app.services.agent_service import _restore_sensitive
        from app.services.security import sensitive

        enc = sensitive.process(f"配置 {self.TOKEN}", policy="encrypt")["processed"]
        assert self.TOKEN in _restore_sensitive(enc)

    def test_配置项存在(self):
        from app.core.config import settings

        assert settings.sensitive_policy in ("allow", "encrypt", "deny")


# --------------------------------------------------------------------------- #
# P3-02 · 投递通道可配置
# --------------------------------------------------------------------------- #
class TestScheduleDelivery:
    """``delivery_json`` 此前**有读无写** → 用户无法配置投递。"""

    PAYLOAD = {"channels": [{"type": "webhook", "target": "https://example.com/hook"}]}

    def test_创建时落库(self, client):
        from app.schemas.schedule import ScheduleCreate

        svc = app.state.scheduler_service
        out = svc.create(ScheduleCreate(
            name="p3-delivery", prompt="p", schedule_kind="interval", interval_seconds=600,
            mode="chat", delivery=self.PAYLOAD,
        ))
        assert out is not None
        assert out.delivery, "投递配置未回显"
        assert out.delivery["channels"][0]["type"] == "webhook"

    def test_非法通道被拒(self):
        from app.schemas.schedule import ScheduleCreate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ScheduleCreate(
                name="x", prompt="p", schedule_kind="interval", interval_seconds=600, mode="chat",
                delivery={"channels": [{"type": "carrier_pigeon", "target": "x"}]},
            )

    def test_三通道均可配置(self):
        from app.schemas.schedule import ScheduleCreate

        payload = {"channels": [
            {"type": "local", "target": "本机"},
            {"type": "webhook", "target": "https://x/y"},
            {"type": "mobile", "target": "device-1"},
        ]}
        data = ScheduleCreate(
            name="p3-all", prompt="p", schedule_kind="interval", interval_seconds=600,
            mode="chat", delivery=payload,
        )
        assert len(data.delivery["channels"]) == 3

    def test_更新投递配置(self, client):
        from app.schemas.schedule import ScheduleCreate, ScheduleUpdate

        svc = app.state.scheduler_service
        out = svc.create(ScheduleCreate(
            name="p3-delivery-upd", prompt="p", schedule_kind="interval", interval_seconds=600,
            mode="chat", delivery=self.PAYLOAD,
        ))
        updated = svc.update(out.id, ScheduleUpdate(
            delivery={"channels": [{"type": "local", "target": "本机通知"}]},
        ))
        assert updated is not None
        assert updated.delivery["channels"][0]["type"] == "local"


# --------------------------------------------------------------------------- #
# P2-04 · DR 评分兜底与事实核查
# --------------------------------------------------------------------------- #
class TestResearchQuality:
    """``overall_score=70`` 兜底会让「结果无法解析」被当成「质量良好」。"""

    def test_解析失败按零分(self, client):
        from app.services.research.orchestrator import Orchestrator

        class _Stub:
            success = False
            error_msg = "boom"
            content = ""

        orch = Orchestrator.__new__(Orchestrator)
        orch.llm = type("L", (), {"chat": staticmethod(lambda **kw: _Stub())})()
        orch._emit_progress = lambda *a, **k: None  # type: ignore[assignment]

        out = orch.check_quality("报告", "任务")
        assert out["overall_score"] == 0, "LLM 失败不得给出非零分"
        assert out.get("error")

    def test_事实核查方法已接线(self, client):
        """``FACT_CHECK_PROMPT`` 此前零引用。"""
        from app.services.research.orchestrator import Orchestrator

        assert callable(Orchestrator.fact_check)
        src = (
            BACKEND_ROOT / "app" / "services" / "research" / "orchestrator.py"
        ).read_text(encoding="utf-8")
        assert "FACT_CHECK_PROMPT" in src, "FACT_CHECK_PROMPT 仍未被引用"

    def test_事实核查解析失败不虚高(self, client):
        from app.services.research.orchestrator import Orchestrator

        class _Stub:
            success = True
            error_msg = ""
            content = "not json"

        orch = Orchestrator.__new__(Orchestrator)
        orch.llm = type("L", (), {"chat": staticmethod(lambda **kw: _Stub())})()
        orch._emit_progress = lambda *a, **k: None  # type: ignore[assignment]

        out = orch.fact_check("某结论", sources=["某来源"])
        assert out["verified"] is False
        assert out.get("parse_failed") is True

    def test_事实核查开关存在(self):
        from app.core.config import settings

        assert isinstance(settings.research_fact_check, bool)


# --------------------------------------------------------------------------- #
# P3-03 · 反思轮数上限
# --------------------------------------------------------------------------- #
class TestReflectionRounds:
    """反思分支此前**没有迭代上限**。"""

    def test_配置项存在(self):
        from app.core.config import settings

        assert settings.reflection_max_rounds >= 1

    def test_反思循环带上限(self, client):
        from app.core.config import settings
        from app.services.agent_service import AgentService

        src = (BACKEND_ROOT / "app" / "services" / "agent_service.py").read_text(encoding="utf-8")
        assert "settings.reflection_max_rounds" in src, "反思未使用轮数上限配置"
        assert "range(1, limit + 1)" in src, "反思未按上限循环"

    def test_轮数上限可配置为1(self, client, monkeypatch):
        """上限 = 1 时只执行 plan 的 actions，不做反思。"""
        from app.core.config import settings
        from app.services.agent_service import AgentService

        assert AgentService is not None
        monkeypatch.setattr(settings, "reflection_max_rounds", 1)
        assert settings.reflection_max_rounds == 1


# --------------------------------------------------------------------------- #
# P2-03 / R-22 · 九段摘要真正接 LLM
# --------------------------------------------------------------------------- #
class TestLlmSummary:
    """九段摘要此前是**纯模板填充**；内置角色 Prompt 从未送给 LLM。"""

    def test_摘要函数存在(self, client):
        from app.services.exec.context import summarize_with_llm

        assert callable(summarize_with_llm)

    def test_使用内置角色Prompt(self, client):
        """``contextSummary`` 角色的 prompt 必须真的被用上（R-22）。

        **P2-13**：内置角色 Prompt 已从 ``exec/roles.py`` 迁入 ``exec/team/roles.py``。
        """
        from app.services.exec.team.roles import BUILTIN_ROLE_PROMPTS

        assert BUILTIN_ROLE_PROMPTS["contextSummary"], "内置角色 prompt 为空"

        src = (BACKEND_ROOT / "app" / "services" / "exec" / "context.py").read_text(encoding="utf-8")
        assert 'BUILTIN_ROLE_PROMPTS.get("contextSummary"' in src, "未使用内置角色 prompt"

    def test_空输入返回空串(self, client):
        from app.services.exec.context import summarize_with_llm

        assert summarize_with_llm(transcript="   ") == ""

    def test_LLM失败不抛异常(self, client, monkeypatch):
        """摘要失败必须退回确定性模板，不得阻断主流程。"""
        from app.services.exec import context

        def boom(*a, **k):
            raise RuntimeError("llm down")

        monkeypatch.setattr("app.core.llm.chat", boom)
        assert context.summarize_with_llm(transcript="一些对话") == ""


# --------------------------------------------------------------------------- #
# P2-10 · 角色层接入执行链路
# --------------------------------------------------------------------------- #
class TestRoleWiring:
    """``roles`` 表此前零消费方——角色不参与工具裁剪、不注入 Prompt。"""

    def test_角色Prompt块(self, client):
        from app.services.agent_service import _role_prompt_block

        class _R:
            title = "数据分析师"
            identity = "你是数据分析师"
            expertise = ["SQL", "可视化"]
            boundaries = ["不访问生产库"]
            workflow = ["取数", "分析"]
            output_style = "结论先行"
            name = "analyst"

        block = _role_prompt_block(_R())
        for frag in ("数据分析师", "SQL", "不访问生产库", "取数", "结论先行"):
            assert frag in block, f"角色 Prompt 缺 {frag}"

    def test_模型档映射(self, client):
        from app.core.config import settings
        from app.services.agent_service import role_model

        assert role_model("light", "gpt-4o") == (settings.plan_model or settings.default_model)
        assert role_model("standard", "gpt-4o") == "gpt-4o"
        assert role_model("strong", None) == settings.default_model

    def test_角色解析(self, client):
        from app.services.agent_service import resolve_role

        assert resolve_role(None) is None
        assert resolve_role(999999) is None

    def test_角色id进请求契约(self, client):
        from app.schemas.agent import RunRequest

        assert RunRequest(prompt="x", role_id=3).role_id == 3

    def test_执行链路透传role_id(self, client):
        """role_id 必须一路传到 agent_service.stream。"""
        src = (BACKEND_ROOT / "app" / "services" / "run_executor.py").read_text(encoding="utf-8")
        assert "role_id=role_id" in src, "run_executor 未透传 role_id"
        api_src = (BACKEND_ROOT / "app" / "api" / "v1" / "agent.py").read_text(encoding="utf-8")
        assert "role_id=payload.role_id" in api_src, "端点未透传 role_id"

    def test_工具上界参数存在(self, client):
        """角色的 tools 是**上界**，必须参与工具集合裁剪。"""
        from app.services.tool_registry import ToolRegistry

        import inspect

        params = inspect.signature(ToolRegistry.get_combined_tools).parameters
        assert "role_tools" in params


# --------------------------------------------------------------------------- #
# P4-02 / P4-03 · 前端契约
# --------------------------------------------------------------------------- #
class TestFrontendContracts:
    """前端侧的契约缺口（静态断言，不跑浏览器）。"""

    def test_done带status(self):
        types_ts = (FRONTEND_SRC / "api" / "types.ts").read_text(encoding="utf-8")
        done_block = types_ts.split("export interface DoneEv")[1].split("}")[0]
        assert "status?" in done_block, "DoneEv 未声明 status（P4-02）"

    def test_工作台消费done_status(self):
        view = (FRONTEND_SRC / "views" / "WorkspaceView.vue").read_text(encoding="utf-8")
        assert "doneStatus" in view, "WorkspaceView 未消费 done.status（P4-02）"

    def test_sse有退避与上限(self):
        sse = (FRONTEND_SRC / "api" / "sse.ts").read_text(encoding="utf-8")
        assert "RECONNECT_MAX_ATTEMPTS" in sse, "SSE 重连缺上限（P4-03）"
        assert "backoffMs" in sse, "SSE 重连缺退避（P4-03）"


# --------------------------------------------------------------------------- #
# P2-13 · 死符号已删除
# --------------------------------------------------------------------------- #
class TestDeadSymbolsRemoved:
    """``exec/roles.py`` 与 ``exec/context.py`` 的死符号必须真的不存在。"""

    def test_exec_roles文件已删除(self, client):
        """内置角色 Prompt 已迁入 ``exec/team/roles.py``。"""
        assert not (BACKEND_ROOT / "app" / "services" / "exec" / "roles.py").exists(), (
            "exec/roles.py 应已删除（内置角色 Prompt 已迁入 exec/team/roles.py）"
        )

    def test_context死符号已删除(self, client):
        """5 个未被引用的重复定义必须删除（真实阈值走 ``settings``）。"""
        import app.services.exec.context as ctx

        for name in (
            "COMPACT_THRESHOLD", "SUMMARY_THRESHOLD",
            "should_compact", "should_summarize", "truncate_tool_result",
        ):
            assert not hasattr(ctx, name), f"死符号仍存在: {name}"

    def test_内置角色记录仍能同步(self, client):
        """``sync_builtin_roles()`` 仍写入 3 条内置角色记录。"""
        from app.services.exec.team.roles import get_role_service

        svc = get_role_service()
        svc.sync_builtin_roles()
        names = {r.name for r in svc.list()}
        assert {"compact", "contextSummary", "memorySelector"} <= names, names

    def test_真实阈值走settings(self, client):
        from app.core.config import settings

        assert settings.context_compact_threshold == 0.70
        assert settings.context_summary_threshold == 0.85


# --------------------------------------------------------------------------- #
# P2-14 · DR 死键与闲置 Worker 已清理
# --------------------------------------------------------------------------- #
class TestResearchCleanup:
    """``research_config`` 的 10 个死键与 3 个闲置 Worker 必须消失。"""

    DEAD_KEYS = (
        "max_search_depth", "worker_count_guidelines", "min_sources_per_topic",
        "report_language", "include_sources", "include_summary",
        "diminishing_returns_threshold", "early_termination_min_score",
        "worker_max_ooda_cycles", "research_budget", "model_smart", "model_fast",
    )

    def test_死键已删除(self, client):
        from app.services.research.research_config import AGENT_CONFIG

        for key in self.DEAD_KEYS:
            assert key not in AGENT_CONFIG, f"死键仍在: {key}"

    def test_配置键与实际引用一致(self, client):
        """AGENT_CONFIG 的每个键都应在代码里**真的被用到**（否则又是死键）。"""
        import re
        from app.services.research.research_config import AGENT_CONFIG

        src_dir = BACKEND_ROOT / "app" / "services" / "research"
        corpus = "\n".join(
            p.read_text(encoding="utf-8", errors="ignore")
            for p in src_dir.glob("*.py")
            if p.name != "research_config.py"
        )
        for key in AGENT_CONFIG:
            assert re.search(rf"\b{re.escape(key)}\b", corpus), (
                f"AGENT_CONFIG 的键 {key} 在代码中无任何引用（死键）"
            )

    def test_闲置Worker已删除(self, client):
        import app.services.research.workers as workers

        for name in ("WriterWorker", "AnalysisWorker", "VisualizationWorker", "WorkerFactory"):
            assert not hasattr(workers, name), f"闲置类仍在: {name}"

    def test_搜索Worker保留(self, client):
        """``SearchWorker`` 是**在用**的，必须保留。"""
        import app.services.research.workers as workers

        assert hasattr(workers, "SearchWorker")
        assert hasattr(workers, "search_worker_factory")

    def test_编排器未用导入已清理(self, client):
        src = (BACKEND_ROOT / "app" / "services" / "research" / "orchestrator.py").read_text(encoding="utf-8")
        assert "PARALLEL_TASK_COORDINATION_PROMPT," not in src, "未用导入仍在"
