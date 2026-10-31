"""P1 批次（正确性与安全边界）回归测试。

对应 [`doc/plan/01-正确性与安全边界.md`](../../doc/plan/01-正确性与安全边界.md) 的
P1-04 ~ P1-07；测试用例编号与 [`doc/testing/00`](../../doc/testing/00-全面测试计划.md) §4.9 一致。

覆盖的 4 个缺陷（均为「看起来实现了、实际不生效」类）：

- **P1-05 / EXT-WR-01 / EXT-WR-02**：Web Research 的 LLM 请求落到 DeepSeek 端点 → 回答生成必然失败
- **P1-06 / EXT-WR-03**：Serper 硬编码 ``page=2`` → 静默丢弃搜索结果第 1 页
- **P1-04 / SEC-DANGER-01**：``allow_dangerous_tools`` 恒失效（ContextVar 唯一写入点恒为 False）
- **P1-07 / RUN-CANCEL-01**：取消后 run 终态被 ``error`` 覆盖为 ``failed``
"""
from __future__ import annotations

import json
import time

import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# P1-05 · Web Research 的 LLM 端点（EXT-WR-01 / EXT-WR-02）
# --------------------------------------------------------------------------- #
class TestWebResearchLlmEndpoint:
    """Web Research 的回答生成必须打到 **OpenAI 兼容端点**。

    缺陷背景：``llm_answer.py`` 调 ``get_langchain_chat_model`` 时未传 provider，
    ``resolve_provider(None)`` 落到默认 provider（deepseek）→ **用 OpenAI 的 key
    + ``gpt-4o`` 打 DeepSeek 端点** → 整条 Web Research 链路不可用。
    """

    def test_openai_provider_解析出openai端点(self):
        """`resolve_provider("openai")` 必须返回 openai 的 base_url。"""
        from app.core.llm import resolve_provider

        name, _key, url = resolve_provider("openai")
        assert name == "openai"
        assert url == settings.openai_base_url
        assert url, "openai_base_url 不应为空"
        assert "deepseek" not in url, "openai provider 不得解析到 DeepSeek 端点"

    def test_默认provider仍是deepseek(self):
        """防回归：默认 provider 若被改成 openai，串线会以另一种形式复发。"""
        from app.core.llm import DEFAULT_PROVIDER

        assert DEFAULT_PROVIDER == "deepseek"

    def test_openai_base_url_有独立配置项(self):
        """openai 必须有独立 base_url 配置项（此前被映射为空串 → 落到 provider 默认）。"""
        assert settings.openai_base_url.startswith("http")
        assert "deepseek" not in settings.openai_base_url

    def test_llm_answer_显式传openai(self, monkeypatch):
        """`GPTAnswer.get_answer` 必须显式传 ``provider="openai"`` 与 openai 端点。"""
        from app.services.web.llm_answer import GPTAnswer

        monkeypatch.setattr(settings, "openai_base_url", "https://openai.example/v1")
        monkeypatch.setattr(settings, "llm_base_url", "https://deepseek.example/v1")

        captured: dict = {}

        class FakeLLM:
            def invoke(self, _messages):
                return "回答"

        def fake_model(**kwargs):
            captured.update(kwargs)
            return FakeLLM()

        monkeypatch.setattr("app.core.llm.get_langchain_chat_model", fake_model)
        GPTAnswer().get_answer("问题", ["资料"], "zh", "text", None)

        assert captured.get("provider") == "openai", "必须显式指定 provider=openai"
        assert captured.get("base_url") == "https://openai.example/v1"
        assert captured.get("base_url") != "https://deepseek.example/v1", "不得落到 DeepSeek 端点"
        assert captured.get("model") == settings.openai_model

    def test_各provider端点互不串线(self, monkeypatch):
        """三个 provider 必须各取各的 base_url。

        用固定值断言（不依赖 ``.env`` 的具体配置——本机 ``LLM_BASE_URL`` 实际指向
        dashscope，那是合法的用户配置，不是缺陷）。
        """
        from app.core.llm import resolve_provider

        monkeypatch.setattr(settings, "dashscope_base_url", "https://dashscope.example/v1")
        monkeypatch.setattr(settings, "llm_base_url", "https://deepseek.example/v1")
        monkeypatch.setattr(settings, "openai_base_url", "https://openai.example/v1")

        urls = {p: resolve_provider(p)[2] for p in ("dashscope", "deepseek", "openai")}
        assert urls["dashscope"] == "https://dashscope.example/v1"
        assert urls["deepseek"] == "https://deepseek.example/v1"
        assert urls["openai"] == "https://openai.example/v1"
        assert len(set(urls.values())) == 3, "三个 provider 的端点必须互不相同"


# --------------------------------------------------------------------------- #
# P1-06 · Serper 页码（EXT-WR-03）
# --------------------------------------------------------------------------- #
class TestSerperPage:
    """Serper 检索默认必须请求**第 1 页**。

    缺陷背景：``serper_service.py`` 硬编码 ``{"q": query, "page": 2}`` →
    用户无感知地拿到**不完整**的搜索结果（第 1 页被静默丢弃）。
    """

    @staticmethod
    def _patch_requests(monkeypatch, captured: dict):
        from app.services.web import serper_service

        class FakeResp:
            def json(self):
                return {"organic": []}

        def fake_request(method, url, headers=None, data=None):
            captured["method"] = method
            captured["url"] = url
            captured["payload"] = json.loads(data)
            return FakeResp()

        monkeypatch.setattr(serper_service.requests, "request", fake_request)
        return serper_service

    def test_默认请求第1页(self, monkeypatch):
        captured: dict = {}
        mod = self._patch_requests(monkeypatch, captured)

        mod.SerperClient().serper("测试查询")

        assert captured["payload"]["page"] == 1, "默认必须是第 1 页"
        assert captured["payload"]["q"] == "测试查询"

    def test_可显式指定页码(self, monkeypatch):
        """翻页能力保留，但默认仍为第 1 页。"""
        captured: dict = {}
        mod = self._patch_requests(monkeypatch, captured)

        mod.SerperClient().serper("测试查询", page=3)

        assert captured["payload"]["page"] == 3

    def test_默认页码常量(self):
        from app.services.web.serper_service import SerperClient

        assert SerperClient.DEFAULT_PAGE == 1


# --------------------------------------------------------------------------- #
# P1-04 · allow_dangerous_tools 二次开关（SEC-DANGER-01）
# --------------------------------------------------------------------------- #
class TestDangerousToolsSwitch:
    """``allow_dangerous_tools`` 必须真正生效。

    缺陷背景：``dangerous_tools_context`` 全仓**唯一**写入点在 ``finally`` 里恒为
    ``False``，从未 ``set(True)`` → 无论入库成什么样，危险工具分支恒走「拒绝」。
    这是一个「可写可查可输出、但永远不生效」的**误导性配置**。
    """

    def test_默认上下文为拒绝(self):
        """默认（交互路径）必须是拒绝。"""
        from app.services.scheduler_service import dangerous_tools_context
        from app.services.security.permissions import PermissionService

        assert dangerous_tools_context.get() is False
        assert PermissionService.instance()._dangerous_tools_allowed() is False

    def test_显式置位后放行(self):
        """显式置位后权限引擎应读到 True。"""
        from app.services.scheduler_service import dangerous_tools_context
        from app.services.security.permissions import PermissionService

        token = dangerous_tools_context.set(True)
        try:
            assert PermissionService.instance()._dangerous_tools_allowed() is True
        finally:
            dangerous_tools_context.reset(token)

    def test_置位随上下文隔离(self):
        """ContextVar 语义：reset 后回到 False，不泄漏到后续调用。"""
        from app.services.scheduler_service import dangerous_tools_context

        token = dangerous_tools_context.set(True)
        dangerous_tools_context.reset(token)
        assert dangerous_tools_context.get() is False

    def _make_task(self, client, allow: bool) -> dict:
        created = client.post("/api/v1/schedules", json={
            "name": "危险工具任务",
            "prompt": "跑一下",
            "schedule_kind": "cron",
            "cron_expr": "0 9 * * *",
            "allow_unattended_tools": True,
            "allow_dangerous_tools": allow,
        })
        assert created.status_code in (200, 201), created.text
        return created.json()

    def test_调度路径按任务行置位(self, client, monkeypatch):
        """集成：``allow_dangerous_tools=true`` 的任务，执行期间 ContextVar 必须为 True。"""
        from app.services.scheduler_service import dangerous_tools_context

        task = self._make_task(client, allow=True)
        captured: dict = {}

        def fake_execute_sync(prompt, **kwargs):
            captured["dangerous"] = dangerous_tools_context.get()
            return {
                "run_id": None, "session_id": None, "finished": True,
                "files": [], "error": None, "answer": "ok",
            }

        monkeypatch.setattr(app.state.run_executor, "execute_sync", fake_execute_sync)
        app.state.scheduler_service._fire(task["id"])

        assert captured.get("dangerous") is True, "调度路径必须按任务行置位开关"

    def test_未开启时保持拒绝(self, client, monkeypatch):
        """``allow_dangerous_tools=false`` → 执行期间 ContextVar 必须为 False。"""
        from app.services.scheduler_service import dangerous_tools_context

        task = self._make_task(client, allow=False)
        captured: dict = {}

        def fake_execute_sync(prompt, **kwargs):
            captured["dangerous"] = dangerous_tools_context.get()
            return {
                "run_id": None, "session_id": None, "finished": True,
                "files": [], "error": None, "answer": "ok",
            }

        monkeypatch.setattr(app.state.run_executor, "execute_sync", fake_execute_sync)
        app.state.scheduler_service._fire(task["id"])

        assert captured.get("dangerous") is False

    def test_执行结束后复位(self, client, monkeypatch):
        """执行结束后开关必须复位为 False（不泄漏到交互路径）。"""
        from app.services.scheduler_service import dangerous_tools_context

        task = self._make_task(client, allow=True)

        def fake_execute_sync(prompt, **kwargs):
            return {
                "run_id": None, "session_id": None, "finished": True,
                "files": [], "error": None, "answer": "ok",
            }

        monkeypatch.setattr(app.state.run_executor, "execute_sync", fake_execute_sync)
        app.state.scheduler_service._fire(task["id"])

        assert dangerous_tools_context.get() is False, "执行结束后必须复位"


# --------------------------------------------------------------------------- #
# P1-03 · 内置权限规则去重与写入收敛（SEC-RULE-01 / DB-MIGRATE-02）
# --------------------------------------------------------------------------- #
class TestBuiltinRuleConvergence:
    """内置权限规则必须**唯一且完整**。

    缺陷背景：内置规则被 ``0002_desktop``（普通 INSERT，8 条）与
    ``0004_security``（INSERT OR IGNORE，20 条）**各写一遍**，而 SQLite 的
    唯一约束 ``(scope, pattern, workspace_id)`` 对 ``workspace_id IS NULL``
    **不去重**（NULL ≠ NULL）→ **8 条规则出现两次**。
    """

    @staticmethod
    def _builtin_rows() -> list:
        from sqlalchemy import select

        from app.db.base import db_session
        from app.db.models import PermissionRuleRow

        with db_session() as db:
            return list(db.scalars(
                select(PermissionRuleRow).where(PermissionRuleRow.origin == "builtin")
            ).all())

    @staticmethod
    def _duplicates() -> list:
        rows = TestBuiltinRuleConvergence._builtin_rows()
        counter: dict[tuple[str, str], int] = {}
        for r in rows:
            counter[(r.scope, r.pattern)] = counter.get((r.scope, r.pattern), 0) + 1
        return [k for k, v in counter.items() if v > 1]

    def test_收敛后无重复(self):
        """收敛后 ``(scope, pattern)`` 分组无 COUNT>1。"""
        from app.services.security.permissions import PermissionService

        PermissionService.instance().ensure_builtin_rules()
        assert self._duplicates() == [], f"仍有重复规则: {self._duplicates()}"

    def test_收敛后条数等于清单条数(self):
        """``origin="builtin"`` 条数必须等于规则清单条数（无缺失、无多余）。"""
        from app.services.security.permissions import BUILTIN_RULES, PermissionService

        PermissionService.instance().ensure_builtin_rules()
        rows = self._builtin_rows()
        assert len(rows) == len(BUILTIN_RULES), (
            f"builtin 条数 {len(rows)} != 清单 {len(BUILTIN_RULES)}"
        )

    def test_收敛是幂等的(self):
        """重复调用不产生新增、不再删除。"""
        from app.services.security.permissions import PermissionService

        engine = PermissionService.instance()
        engine.ensure_builtin_rules()
        first = len(self._builtin_rows())
        second_stats = engine.ensure_builtin_rules()
        assert second_stats["added"] == 0
        assert second_stats["removed"] == 0
        assert len(self._builtin_rows()) == first

    def test_重复行被清理(self):
        """人为插入一条重复 builtin → 收敛时必须被删除。"""
        from app.db.base import db_session
        from app.db.models import PermissionRuleRow, utc_now
        from app.services.security.permissions import PermissionService

        engine = PermissionService.instance()
        engine.ensure_builtin_rules()

        with db_session() as db:
            db.add(PermissionRuleRow(
                scope="tool", pattern="write_file", decision="ask", risk="normal",
                workspace_id=None, priority=100, origin="builtin",
                expires_at=None, hit_count=0, last_hit_at=None, updated_at=utc_now(),
            ))
        assert ("tool", "write_file") in self._duplicates(), "前置条件：制造出重复"

        engine.ensure_builtin_rules()
        assert self._duplicates() == []

    def test_缺失规则被补齐(self):
        """人为删掉一条 → 收敛时必须补回。"""
        from app.db.base import db_session
        from app.db.models import PermissionRuleRow
        from app.services.security.permissions import BUILTIN_RULES, PermissionService

        engine = PermissionService.instance()
        engine.ensure_builtin_rules()

        scope, pattern = BUILTIN_RULES[0][0], BUILTIN_RULES[0][1]
        with db_session() as db:
            for r in db.query(PermissionRuleRow).filter(
                PermissionRuleRow.scope == scope,
                PermissionRuleRow.pattern == pattern,
                PermissionRuleRow.origin == "builtin",
            ).all():
                db.delete(r)

        stats = engine.ensure_builtin_rules()
        assert stats["added"] == 1
        assert self._duplicates() == []

    def test_规则列表端点无重复(self, client):
        """``GET /permissions/rules`` 返回的列表必须无重复项。"""
        from app.services.security.permissions import PermissionService

        PermissionService.instance().ensure_builtin_rules()

        r = client.get("/api/v1/permissions/rules")
        assert r.status_code == 200, r.text
        rules = r.json().get("rules", r.json() if isinstance(r.json(), list) else [])
        # 只断言**内置规则**无重复——自定义规则与内置同键是合法的
        # （判定链按 priority 取先匹配的那条），全表去重会破坏用户规则。
        builtin_keys = [
            (x.get("scope"), x.get("pattern"))
            for x in rules
            if x.get("origin") == "builtin" or x.get("origin") is None
        ]
        assert len(builtin_keys) == len(set(builtin_keys)), "内置规则列表存在重复项"


# --------------------------------------------------------------------------- #
# P1-09 · allowed_roots 全形态生效（SEC-WS-05）
# --------------------------------------------------------------------------- #
class TestAllowedRoots:
    """**写**操作的工作区边界必须**全形态**生效。

    缺陷背景：``LocalCodeExecutor.allowed_roots`` 仅桌面模式有值，
    Web 形态返回 ``[]`` → ``_check_allowed`` 直接放行 →
    模型给出的**任意绝对路径**都能写（绕过工作区约束）。
    """

    def test_web形态写工作区外被拒(self, client, tmp_path):
        """Web 形态：写工作区外的绝对路径必须被拒。"""
        target = tmp_path / "escaped.txt"

        out = app.state.executor.write_file(str(target), "越界写入")

        assert out.get("success") is False, "工作区外写入必须被拒绝"
        assert "范围" in (out.get("error") or ""), out
        assert not target.exists(), "被拒绝时不得创建目标文件"

    def test_web形态写工作区内允许(self, client):
        """Web 形态：写工作区内路径正常放行。"""
        from app.core.workspace import get_workspace_dir

        root = get_workspace_dir()
        root.mkdir(parents=True, exist_ok=True)
        target = root / "p1_inside.txt"

        out = app.state.executor.write_file(str(target), "工作区内内容")

        assert out.get("success") is True, out
        assert target.exists()

    def test_web形态写产出目录允许(self, client):
        """产出目录（``data/outputs``）是合法写入目标，不应被拦。"""
        target = app.state.executor.output_dir / "p1_output.txt"
        target.parent.mkdir(parents=True, exist_ok=True)

        out = app.state.executor.write_file(str(target), "产物内容")

        assert out.get("success") is True, out
        assert target.exists()

    def test_web形态读工作区外仍允许(self, client, tmp_path):
        """读不设硬边界——读工作区外的源码/配置是合法且常见的。"""
        src = tmp_path / "readme.txt"
        src.write_text("外部文件", encoding="utf-8")

        out = app.state.executor.read_file(str(src))

        assert out.get("error") == "", out
        assert out.get("content") == "外部文件"

    def test_allowed_roots含工作区与产出目录(self, client):
        """allowed_roots 必须同时包含工作区根与产出目录。"""
        roots = app.state.executor.allowed_roots
        assert app.state.executor.cwd_dir in roots
        assert app.state.executor.output_dir in roots
        assert len(roots) >= 2


# --------------------------------------------------------------------------- #
# P1-08 · 审批恢复接入 steer / cancel（RUN-STEER-02 / RUN-STEER-03）
# --------------------------------------------------------------------------- #
class TestResumeAfterApprovalControl:
    """审批通过后的恢复执行必须**可干预**。

    缺陷背景：``resume_after_approval`` 调 ``agent_service.stream`` 时
    **未传** ``steer_hook`` / ``cancel_hook``（主路径传了）→ 恢复段既不能
    取消也不能转向；且恢复段把取消当成 error → 终态错标为 failed。
    """

    @staticmethod
    def _make_queued_run(prompt: str = "继续执行") -> str:
        run = app.state.run_service.create_run(
            trigger="api",
            status="queued",
            meta={"prompt": prompt, "mode": "chat"},
        )
        assert run is not None
        return run.id

    @staticmethod
    def _wait_terminal(run_id: str, timeout: float = 5.0) -> str:
        deadline = time.monotonic() + timeout
        status = ""
        while time.monotonic() < deadline:
            run = app.state.run_service.get_run(run_id)
            if run is not None:
                status = run.status
                if status in ("success", "failed", "interrupted", "rejected", "skipped"):
                    return status
            time.sleep(0.05)
        return status

    def test_恢复段传入steer与cancel_hook(self, client, monkeypatch):
        """恢复执行必须拿到与主路径同一份 hook。"""
        captured: dict = {}

        def fake_stream(*args, **kwargs):
            captured.update(kwargs)
            yield {"type": "model_text", "content": "完成"}

        monkeypatch.setattr(app.state.agent_service, "stream", fake_stream)

        run_id = self._make_queued_run()
        assert app.state.run_executor.resume_after_approval(run_id) is True
        assert self._wait_terminal(run_id) == "success"

        assert "steer_hook" in captured, "恢复段必须传入 steer_hook"
        assert "cancel_hook" in captured, "恢复段必须传入 cancel_hook"
        assert callable(captured["steer_hook"])
        assert callable(captured["cancel_hook"])

    def test_恢复段可取消(self, client, monkeypatch):
        """恢复段收到 interrupted → 终态 interrupted（不是 failed）。"""
        def fake_stream(*args, **kwargs):
            yield {"type": "interrupted", "content": "用户取消"}

        monkeypatch.setattr(app.state.agent_service, "stream", fake_stream)

        run_id = self._make_queued_run()
        assert app.state.run_executor.resume_after_approval(run_id) is True
        assert self._wait_terminal(run_id) == "interrupted"

    def test_恢复段steer_hook可取到指令(self, client, monkeypatch):
        """steer_hook 必须能从执行器的 steer 队列取到待注入指令。"""
        captured: dict = {}

        def fake_stream(*args, **kwargs):
            captured.update(kwargs)
            yield {"type": "model_text", "content": "完成"}

        monkeypatch.setattr(app.state.agent_service, "stream", fake_stream)

        run_id = self._make_queued_run()
        app.state.run_executor.request_steer(run_id, "改一下方向")
        assert app.state.run_executor.resume_after_approval(run_id) is True
        assert self._wait_terminal(run_id) == "success"

        pending = captured["steer_hook"]()
        assert pending, "steer_hook 应能取到待注入的指令"
        assert pending[0].get("text") == "改一下方向"
        assert pending[0].get("seq") == 1, "steer 指令应带保序序号"


# --------------------------------------------------------------------------- #
# P1-10 · 绑定地址统一（SEC-HOST-01）
# --------------------------------------------------------------------------- #
class TestHostBinding:
    """绑定地址与端口**只由配置决定**（``HOST`` 是唯一真相）。

    缺陷背景：``settings.host`` 全仓**零使用点**——各文档与脚本都用
    ``uvicorn app.main:app --host 0.0.0.0 --port 8000`` 启动，**绕过了配置**：

    - 「默认绑定 127.0.0.1」这条安全约束**形同虚设**；
    - 命令行里的 ``--port 8000`` 与前端 dev proxy 的 ``18040`` **不一致**
      → 按文档走一遍，前端根本连不上后端。
    """

    def test_配置默认host是回环(self):
        """配置项的**默认值**必须是回环（``.env`` 可显式覆盖）。"""
        from app.core.config import Settings

        assert Settings.model_fields["host"].default == "127.0.0.1"

    def test_桌面launcher无硬编码host字面量(self):
        """桌面端实际绑定由 ``bind_loopback()`` 决定，不应再写看似可配的字面量。"""
        from pathlib import Path

        import app.desktop.launcher as launcher

        src = Path(launcher.__file__).read_text(encoding="utf-8")
        assert 'host="127.0.0.1"' not in src, "桌面端不得留硬编码 host 字面量"
        assert 'host="0.0.0.0"' not in src, "桌面端不得留硬编码 host 字面量"

    def test_统一启动入口读settings(self, monkeypatch):
        """``run()`` 必须用 ``settings.host`` / ``settings.port`` 启动。"""
        import sys

        import app.main as main_mod

        captured: dict = {}

        class FakeUvicorn:
            @staticmethod
            def run(_app, **kwargs):
                captured.update(kwargs)

        monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)
        monkeypatch.setattr(settings, "host", "127.0.0.1")
        monkeypatch.setattr(settings, "port", 18040)

        main_mod.run()

        assert captured["host"] == "127.0.0.1"
        assert captured["port"] == 18040

    def test_模块可作为入口执行(self):
        """``python -m app.main`` 必须可用（``__main__`` 块存在）。"""
        from pathlib import Path

        import app.main as main_mod

        src = Path(main_mod.__file__).read_text(encoding="utf-8")
        assert '__name__ == "__main__"' in src, "缺少 python -m app.main 入口"

    def test_env_example默认回环(self):
        """样例配置也必须是安全默认——否则新用户一上来就暴露端口。"""
        from pathlib import Path

        import app.core.config as cfg_mod

        example = Path(cfg_mod.__file__).resolve().parents[2] / ".env.example"
        text = example.read_text(encoding="utf-8")
        assert "HOST=127.0.0.1" in text, ".env.example 必须默认只监听回环"


# --------------------------------------------------------------------------- #
# P1-02 · save-as 路径约束（SEC-WS-04 / WEB-36）
# --------------------------------------------------------------------------- #
class TestSaveAsPermission:
    """产物「另存到指定位置」的 ``dest`` 必须走权限判定。

    缺陷背景：``dest`` 直接进 ``shutil.copy2``、**无任何路径限制** →
    可写任意绝对路径；而同一文件里的 ``revert`` 端点**有**权限判定——
    同一份代码里存在**两套安全标准**。
    """

    @staticmethod
    def _seed_artifact(client, tmp_path):
        """登记一个产物并返回 (run_id, artifact_id, 产物文件路径)。"""
        from app.core.workspace import get_workspace_dir
        from app.services.workspace import artifacts as art

        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        run = client.post("/api/v1/agent/run/sync", json={
            "prompt": "产出", "mode": "chat", "session_id": sess["id"],
        }).json()
        run_id = run["run_id"]

        root = get_workspace_dir()
        root.mkdir(parents=True, exist_ok=True)
        src = root / "p1_artifact.txt"
        src.write_text("产物内容", encoding="utf-8")

        rec = art.register_artifact(run_id, None, root, src)
        return run_id, rec["id"], src

    def test_工作区外dest被拒绝(self, client, tmp_path):
        """工作区外绝对路径 → 403 + ``E_PERMISSION``。"""
        run_id, artifact_id, _src = self._seed_artifact(client, tmp_path)
        outside = tmp_path / "escaped.txt"

        r = client.post(
            f"/api/v1/runs/{run_id}/artifacts/{artifact_id}/save-as",
            json={"dest": str(outside)},
        )
        assert r.status_code == 403, r.text
        assert r.json()["code"] == "E_PERMISSION"
        assert not outside.exists(), "被拒绝时不得创建目标文件"

    def test_工作区内dest允许(self, client, tmp_path):
        """工作区内路径 → 200 且真实落盘。"""
        from app.core.workspace import get_workspace_dir

        run_id, artifact_id, _src = self._seed_artifact(client, tmp_path)
        inside = get_workspace_dir() / "saved_inside.txt"

        r = client.post(
            f"/api/v1/runs/{run_id}/artifacts/{artifact_id}/save-as",
            json={"dest": str(inside)},
        )
        assert r.status_code == 200, r.text
        assert inside.exists(), "允许时必须真实落盘"
        assert inside.read_text(encoding="utf-8") == "产物内容"

    def test_拒绝时有可读原因(self, client, tmp_path):
        """403 的 message 必须带可读原因（便于前端展示）。"""
        run_id, artifact_id, _src = self._seed_artifact(client, tmp_path)

        r = client.post(
            f"/api/v1/runs/{run_id}/artifacts/{artifact_id}/save-as",
            json={"dest": str(tmp_path / "x.txt")},
        )
        assert r.status_code == 403
        assert "拒绝" in r.json()["message"]

    def test_缺少dest返回422(self, client, tmp_path):
        run_id, artifact_id, _src = self._seed_artifact(client, tmp_path)

        r = client.post(
            f"/api/v1/runs/{run_id}/artifacts/{artifact_id}/save-as",
            json={},
        )
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# P1-01 · Web 形态最小鉴权（SEC-01 / WEB-35）
# --------------------------------------------------------------------------- #
class TestWebApiKeyGuard:
    """Web 形态下 ``/api/v1/**`` 的最小鉴权。

    缺陷背景：桌面形态有会话守卫 + Host 白名单，**Web 形态此前完全无鉴权**
    （API 层 0 个鉴权型依赖，81 处 ``Depends`` 全是服务获取器）。

    设计取舍：**不默认开启**——单机自用是默认形态，开启会打断既有用户；
    配置 ``AGENT_API_KEY`` 后才生效，并在启动日志显式告警未配置的情况。
    """

    def test_未配置时放行(self, client):
        """默认不启用鉴权——不打断单机用户。"""
        r = client.get("/api/v1/health")
        assert r.status_code == 200, r.text

    def test_配置后无Key返回401(self, client, monkeypatch):
        """配置后，无 Key 请求受保护端点 → 401 + 统一错误体。"""
        monkeypatch.setattr(settings, "agent_api_key", "secret-key")

        r = client.get("/api/v1/health")
        assert r.status_code == 401
        body = r.json()
        assert body["code"] == "E_AUTH"
        assert body["request_id"], "401 响应必须带 request_id"

    def test_配置后带正确Key返回200(self, client, monkeypatch):
        monkeypatch.setattr(settings, "agent_api_key", "secret-key")

        r = client.get("/api/v1/health", headers={"X-API-Key": "secret-key"})
        assert r.status_code == 200, r.text

    def test_错误Key返回401(self, client, monkeypatch):
        monkeypatch.setattr(settings, "agent_api_key", "secret-key")

        r = client.get("/api/v1/health", headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401

    def test_支持bearer_token(self, client, monkeypatch):
        monkeypatch.setattr(settings, "agent_api_key", "secret-key")

        r = client.get("/api/v1/health", headers={"Authorization": "Bearer secret-key"})
        assert r.status_code == 200, r.text

    def test_支持query参数(self, client, monkeypatch):
        """SSE 场景：浏览器 ``EventSource`` 无法自定义请求头 → 支持 ``?api_key=``。"""
        monkeypatch.setattr(settings, "agent_api_key", "secret-key")

        r = client.get("/api/v1/health?api_key=secret-key")
        assert r.status_code == 200, r.text

    def test_非api路径不受影响(self, client, monkeypatch):
        """``/docs-info`` 等非 ``/api/v1/`` 路径不受此守卫影响。"""
        monkeypatch.setattr(settings, "agent_api_key", "secret-key")

        r = client.get("/docs-info")
        assert r.status_code == 200

    def test_401响应带request_id头(self, client, monkeypatch):
        monkeypatch.setattr(settings, "agent_api_key", "secret-key")

        r = client.get("/api/v1/health")
        assert r.headers.get("X-Request-ID"), "401 响应必须带 X-Request-ID 头"

    def test_桌面形态不受此守卫影响(self, client, monkeypatch):
        """桌面形态由会话守卫负责，本守卫必须让路。

        ``desktop_mode`` 是只读 property（由环境变量 ``AGENT_DESKTOP`` 派生），
        因此这里改环境变量而不是改属性。
        """
        monkeypatch.setattr(settings, "agent_api_key", "secret-key")
        monkeypatch.setenv("AGENT_DESKTOP", "1")

        r = client.get("/api/v1/health")
        assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# P1-07 · 取消后 run 终态（RUN-CANCEL-01）
# --------------------------------------------------------------------------- #
class TestCancelTerminalStatus:
    """用户点「停止」后，run 终态必须是 ``interrupted``（不是 ``failed``）。

    缺陷背景：``interrupted`` 事件同时设了 ``error``，随后收尾处的
    ``if error: final_status="failed"`` **无条件覆盖**了 ``interrupted``。
    """

    def test_取消后终态为interrupted(self, client, monkeypatch):
        """取消事件 → run 终态 interrupted。"""
        def fake_stream(*args, **kwargs):
            yield {"type": "interrupted", "content": "用户取消"}

        monkeypatch.setattr(app.state.agent_service, "stream", fake_stream)

        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        run = client.post("/api/v1/agent/run/sync", json={
            "prompt": "你好", "mode": "chat", "session_id": sess["id"],
        }).json()
        run_id = run["run_id"]

        r = client.get(f"/api/v1/runs/{run_id}")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "interrupted", (
            f"取消后终态应为 interrupted，实际 {r.json()['status']}"
        )

    def test_真失败仍为failed(self, client, monkeypatch):
        """失败场景**不得回归**——仍然是 failed。"""
        def fake_stream(*args, **kwargs):
            yield {"type": "error", "content": "模型炸了"}

        monkeypatch.setattr(app.state.agent_service, "stream", fake_stream)

        sess = client.post("/api/v1/sessions", json={"mode": "chat"}).json()
        run = client.post("/api/v1/agent/run/sync", json={
            "prompt": "你好", "mode": "chat", "session_id": sess["id"],
        }).json()
        run_id = run["run_id"]

        r = client.get(f"/api/v1/runs/{run_id}")
        assert r.json()["status"] == "failed", "真失败必须是 failed"

    def test_显式终止原因集合(self):
        """终态优先级常量必须包含三种显式终止原因。"""
        from app.services.run_executor import EXPLICIT_TERMINAL_STATUSES

        assert EXPLICIT_TERMINAL_STATUSES == {"interrupted", "rejected", "skipped"}
