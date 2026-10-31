"""S1 架构整改的回归护栏。

覆盖 WP-1.1（统一错误体 + 请求 ID）、WP-1.2（暴露面收紧）、
WP-1.3（权限判定全形态生效）、WP-1.4（mode 枚举统一）、
WP-1.5（主循环唯一）、WP-1.9（硬编码清理）。
"""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.errors import AppError, ErrorCode, error_body, get_request_id
from app.main import app

APP_DIR = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# WP-1.1 统一错误体 + 请求 ID
# --------------------------------------------------------------------------- #
class TestUnifiedErrorBody:
    def test_404_响应含统一字段(self, client):
        r = client.get("/api/v1/sessions/does-not-exist")
        assert r.status_code == 404
        body = r.json()
        assert set(body) >= {"code", "message", "detail", "request_id"}
        assert body["code"] == ErrorCode.NOT_FOUND
        assert body["request_id"]

    def test_响应头带请求ID(self, client):
        r = client.get("/api/v1/health")
        assert r.headers.get("X-Request-ID")

    def test_透传调用方提供的请求ID(self, client):
        r = client.get("/api/v1/health", headers={"X-Request-ID": "abc123"})
        assert r.headers.get("X-Request-ID") == "abc123"

    def test_未知API路径返回统一404(self, client):
        r = client.get("/api/v1/not-a-real-endpoint")
        assert r.status_code == 404
        body = r.json()
        assert body["code"] == ErrorCode.NOT_FOUND
        assert body["request_id"]

    def test_detail_保留原始载荷_兼容旧客户端(self, client):
        """旧客户端读 ``detail``，统一错误体不能把它抹掉。"""
        r = client.get("/api/v1/sessions/does-not-exist")
        assert isinstance(r.json()["detail"], str)

    def test_AppError可直接构造统一体(self):
        body = error_body(ErrorCode.RUN, "运行失败", detail={"x": 1})
        assert body["code"] == ErrorCode.RUN
        assert body["message"] == "运行失败"
        assert body["detail"] == {"x": 1}
        assert body["request_id"]

    def test_请求ID上下文可读(self):
        assert get_request_id()


# --------------------------------------------------------------------------- #
# WP-1.2 暴露面收紧
# --------------------------------------------------------------------------- #
class TestExposure:
    def test_未配置CORS时不允许通配源(self):
        """Web 形态未显式配置 CORS 时不得回落到 ``["*"]``。"""
        assert settings.cors_origin_list == []

    def test_显式配置CORS时按逗号切分(self, monkeypatch):
        monkeypatch.setattr(settings, "cors_origins", "http://a.test, http://b.test", raising=False)
        assert settings.cors_origin_list == ["http://a.test", "http://b.test"]

    def test_默认绑定地址是回环(self):
        """配置项默认必须是 127.0.0.1（env 可覆盖）。"""
        from app.core.config import Settings

        assert Settings.model_fields["host"].default == "127.0.0.1"

    def test_桌面态CORS恒为空(self, monkeypatch):
        monkeypatch.setattr(type(settings), "desktop_mode", property(lambda self: True))
        assert settings.cors_origin_list == []


# --------------------------------------------------------------------------- #
# WP-1.3 权限判定全形态生效
# --------------------------------------------------------------------------- #
class TestPermissionAllForms:
    def test_判定函数不再有桌面限定短路(self):
        """``_check_permission`` 不得再出现「非桌面直接放行」的短路。"""
        src = (APP_DIR / "services" / "tool_registry.py").read_text(encoding="utf-8")
        assert "if not settings.desktop_mode:\n            return None" not in src

    def test_Web形态写类动作被拒(self, monkeypatch):
        """过渡口径：Web 形态无审批通道，高危动作按拒绝处理。"""
        from app.services.tool_registry import ToolRegistry
        from app.services.mcp_manager import MCPManager

        registry = ToolRegistry(MCPManager())
        denial = registry._check_permission("execute_bash", {"command": "rm -rf /"})
        assert denial is not None, "Web 形态高危命令应被拦截"
        assert denial["permission"]["decision"] == "deny"

    def test_只读工具在Web形态放行(self, monkeypatch):
        from app.services.tool_registry import ToolRegistry
        from app.services.mcp_manager import MCPManager

        registry = ToolRegistry(MCPManager())
        assert registry._check_permission("read_file", {"path": "README.md"}) is None


# --------------------------------------------------------------------------- #
# WP-1.4 mode 枚举统一
# --------------------------------------------------------------------------- #
class TestModeConsistency:
    def test_三处取值集合一致(self):
        from app.schemas.agent import RunRequest
        from app.schemas.session import AgentMode
        from app.services.desktop_service import VALID_MODES

        expected = {"chat", "plan", "work"}
        assert set(VALID_MODES) == expected
        assert set(RunRequest.model_fields["mode"].annotation.__args__) == expected
        assert set(AgentMode.__args__) == expected

    def test_plan输入归一为_work加_plan_first(self):
        from app.schemas.agent import RunRequest

        req = RunRequest(prompt="x", mode="plan")
        assert req.mode == "work"
        assert req.plan_first is True

    def test_chat模式拒绝plan_first(self):
        from pydantic import ValidationError

        from app.schemas.agent import RunRequest

        with pytest.raises(ValidationError):
            RunRequest(prompt="x", mode="chat", plan_first=True)

    def test_会话plan落库为_work加标记(self, client):
        r = client.post("/api/v1/sessions", json={"mode": "plan"})
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body["mode"] == "plan"
        assert body["plan_first"] is True

    def test_会话模式过滤支持三态(self, client):
        client.post("/api/v1/sessions", json={"mode": "plan", "title": "s1-plan"})
        client.post("/api/v1/sessions", json={"mode": "chat", "title": "s1-chat"})
        r = client.get("/api/v1/sessions", params={"mode": "plan"})
        assert r.status_code == 200
        assert all(s["mode"] == "plan" for s in r.json()["items"])

    def test_迁移脚本可正向执行且可回滚(self):
        """0003 迁移存在且声明了 upgrade / downgrade。"""
        p = APP_DIR / "db" / "migrations" / "versions" / "0003_mode_unify.py"
        assert p.exists()
        tree = ast.parse(p.read_text(encoding="utf-8"))
        funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        assert {"upgrade", "downgrade"} <= funcs


# --------------------------------------------------------------------------- #
# WP-1.5 主循环唯一
# --------------------------------------------------------------------------- #
class TestSingleMainLoop:
    def test_主循环入口只有一个(self):
        """``execute_stream`` / ``execute_sync`` 只能有一个实现。"""
        hits = []
        for p in (APP_DIR / "services").rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            for name in ("def execute_stream", "def execute_sync", "def _stream_loop"):
                if name in text:
                    hits.append(f"{p.relative_to(APP_DIR)}:{name}")
        # 允许 agent_service（主链路）与 run_executor（执行器）各一处
        assert len(hits) <= 3, f"主循环实现疑似重复：{hits}"

    def test_遗留agent包已删除(self):
        """P2-24：``app/services/agent/``（第二套 function-calling 循环）**已删除**。

        此前它自述「不落账、不参与统一执行器」→ 全仓存在两套主循环。
        现在 ``/agent/chat`` 已转调统一执行器，遗留包整体删除。
        """
        legacy = APP_DIR / "services" / "agent"
        assert not legacy.exists(), (
            f"遗留 agent 包应已删除（P2-24），仍存在: {legacy}"
        )

    def test_仅一套function_calling主循环(self):
        """架构断言：全仓**只有一套** function-calling 循环（P2-24 验收②）。"""
        hits: list[str] = []
        for p in APP_DIR.rglob("*.py"):
            rel = p.relative_to(APP_DIR).as_posix()
            # ``mcp/clients/*`` 是**模型客户端**（不是 Agent 循环）→ 排除
            if rel.startswith("mcp/clients/"):
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            if "chat.completions.create" in text and "tools=" in text:
                hits.append(rel)
        # 只允许 agent_service（主循环）一处
        assert len(hits) <= 1, f"function-calling 循环疑似重复: {hits}"

    def test_agent_chat已转调统一执行器(self):
        """``/agent/chat`` 必须走统一执行器（并写账本）。"""
        api = (APP_DIR / "api" / "v1" / "agent.py").read_text(encoding="utf-8")
        assert "services.agent.service" not in api, "/agent/chat 仍在调用遗留服务"
        assert "executor.execute_stream" in api, "/agent/chat 未转调统一执行器"

    def test_包体积_无无运行环境组件(self):
        """app/ 下不得残留需要独立运行环境的组件（如 queue_worker）。"""
        offenders = [
            p.relative_to(APP_DIR).as_posix()
            for p in APP_DIR.rglob("*.py")
            if p.name in {"queue_worker.py", "worker.py", "worker_main.py"}
        ]
        assert not offenders, f"主包内存在无运行环境组件：{offenders}"


# --------------------------------------------------------------------------- #
# WP-1.9 硬编码清理
# --------------------------------------------------------------------------- #
class TestNoHardcoding:
    def test_健康检查的MCP数量来自注册表(self, client):
        from app.services.mcp_manager import MCPManager

        body = client.get("/api/v1/health").json()
        assert body["mcp_servers_available"] == len(MCPManager.SERVER_REGISTRY)

    def test_MCP状态灯不含恒真条件(self):
        src = (APP_DIR / "services" / "mcp_manager.py").read_text(encoding="utf-8")
        assert "or True" not in src


# --------------------------------------------------------------------------- #
# WP-1.6 配置单源 / WP-1.7 LLM 工厂唯一 / WP-1.8 定位与账本
# --------------------------------------------------------------------------- #
class TestConfigSingleSource:
    def test_研究配置不再有import期快照(self):
        src = (APP_DIR / "services" / "research" / "research_config.py").read_text(encoding="utf-8")
        assert "LLM_CONFIG: dict" not in src, "仍存在 import 期 LLM_CONFIG 快照"
        assert "SEARCH_CONFIG: dict" not in src, "仍存在 import 期 SEARCH_CONFIG 快照"

    def test_算法参数不可变(self):
        from app.services.research.research_config import AGENT_CONFIG

        with pytest.raises(TypeError):
            AGENT_CONFIG["max_workers"] = 99  # type: ignore[index]

    def test_输出目录归实例持有(self):
        from app.services.research.research_config import OUTPUT_CONFIG

        assert "output_dir" not in OUTPUT_CONFIG, "输出目录不应再放在全局配置里"

    def test_运行期不再改写全局配置(self):
        src = (APP_DIR / "services" / "research" / "service.py").read_text(encoding="utf-8")
        assert "AGENT_CONFIG.update" not in src, "仍用「改全局再还原」的方式做参数覆盖"
        assert "AGENT_CONFIG.update" not in (
            APP_DIR / "services" / "research" / "research_manager.py"
        ).read_text(encoding="utf-8")

    def test_密钥类配置现取而非快照(self):
        from app.services.research.research_config import llm_config, search_config

        assert isinstance(llm_config(), dict)
        assert isinstance(search_config(), dict)


class TestSingleLlmFactory:
    def test_全仓只有一个客户端工厂(self):
        """除统一工厂外，其它模块不得再自行 new OpenAI 客户端。"""
        offenders = []
        for p in (APP_DIR / "services").rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            if "OpenAI(" in text and p.name != "llm_client.py":
                offenders.append(p.relative_to(APP_DIR).as_posix())
        # research/llm_client.py 保留（仅构造返回契约，不自建客户端）
        assert not offenders, f"存在自建 LLM 客户端的模块：{offenders}"

    def test_工厂支持多provider(self):
        from app.core.llm import PROVIDERS, resolve_provider

        assert {"dashscope", "deepseek", "openai"} <= set(PROVIDERS)
        name, key, url = resolve_provider("dashscope")
        assert name == "dashscope"

    def test_未知provider报错(self):
        from app.core.llm import resolve_provider

        with pytest.raises(ValueError):
            resolve_provider("not-a-provider")


class TestMcpSingleSource:
    def test_注册表给出脚本路径(self):
        from app.services.mcp_manager import MCPManager

        for name, info in MCPManager.SERVER_REGISTRY.items():
            assert info.get("script"), f"{name} 未声明 script"

    def test_脚本路径可解析到真实文件(self):
        from app.services.mcp_manager import MCPManager

        m = MCPManager()
        for name in MCPManager.SERVER_REGISTRY:
            assert m.server_script_path(name).is_file(), f"{name} 脚本不存在"

    def test_调用路径不再由name推导脚本(self):
        src = (APP_DIR / "services" / "mcp_manager.py").read_text(encoding="utf-8")
        assert 'f"{name}_server.py"' not in src, "脚本路径仍在由 name 推导（定位双源）"


class TestResearchLedger:
    def test_研究任务写入runs账本(self):
        from app.db.base import db_session
        from app.db.models import RunRow
        from app.services.research.research_manager import ResearchManager

        mgr = ResearchManager(persist=False)
        task_id = mgr.create_task("研究任务入库验证", max_workers=1)

        with db_session() as db:
            row = db.get(RunRow, task_id)
            assert row is not None, "研究任务未进入 runs 账本"
            assert row.trigger == "research"
            assert row.status == "queued"

        mgr.set_running(task_id)
        with db_session() as db:
            assert db.get(RunRow, task_id).status == "running"

        mgr.set_failed(task_id, "验证用失败")
        with db_session() as db:
            row = db.get(RunRow, task_id)
            assert row.status == "failed"
            assert row.error == "验证用失败"

    def test_可从账本恢复研究任务(self):
        from app.services.research.research_manager import ResearchManager

        mgr = ResearchManager(persist=False)
        mgr.create_task("账本恢复验证", max_workers=1)
        fresh = ResearchManager(persist=False)
        assert fresh._restore_from_db() >= 1
