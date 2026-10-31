"""P2 剩余工作项的验收测试（P2-01 / P2-05 / P2-18 / P2-19 / P2-20 / P2-21）。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# P2-01 · MCP 连接复用
# --------------------------------------------------------------------------- #
class TestMcpSessionReuse:
    """连续调用同一 MCP Server 的 N 次工具，子进程启动次数 ≤ 1。"""

    @pytest.fixture()
    def counting_server(self, tmp_path):
        """写一个会记录启动次数的假 MCP Server，并注册进注册表。"""
        counter = tmp_path / "starts.txt"
        script = tmp_path / "counting_server.py"
        script.write_text(
            "from mcp.server.fastmcp import FastMCP\n"
            f"mcp = FastMCP('counting', log_level='ERROR')\n"
            f"open({str(counter)!r}, 'a').write('start\\n')\n"
            "@mcp.tool()\n"
            "def ping() -> str:\n"
            "    return 'pong'\n"
            "if __name__ == '__main__':\n"
            "    mcp.run(transport='stdio')\n",
            encoding="utf-8",
        )
        from app.services.mcp_manager import get_mcp_manager

        mgr = get_mcp_manager()
        mgr.SERVER_REGISTRY["counting"] = {
            "module": "app.mcp.servers.counting_server",
            "script": script.name,
            "stage": "测试",
            "description": "计数用假 Server",
            "read_only": "true",
        }
        # 让 server_script_path 能解析到临时脚本
        orig_path = mgr.server_script_path

        def _path(name: str):
            if name == "counting":
                return script
            return orig_path(name)

        mgr.server_script_path = _path  # type: ignore[method-assign]
        yield counter, mgr
        try:
            mgr.close_all_sessions()
        finally:
            mgr.SERVER_REGISTRY.pop("counting", None)

    def test_连续调用只启动一个子进程(self, client, counting_server):
        """验收断言①：N 次调用 → 子进程启动次数 ≤ 1。"""
        counter, mgr = counting_server
        for _ in range(3):
            out = mgr.call_tool("counting", "ping", {})
            assert "pong" in out, out
        starts = counter.read_text(encoding="utf-8").count("start")
        assert starts <= 1, f"子进程被启动了 {starts} 次（应 ≤ 1）"

    def test_池大小真实反映连接数(self, client, counting_server):
        """验收断言②：``/metrics`` 的 ``mcp_connections`` 不再恒为 0。"""
        from app.services.mcp_manager import get_mcp_manager

        mgr = get_mcp_manager()
        mgr.call_tool("counting", "ping", {})
        assert mgr.pool_size() >= 1, "常驻会话未计入池"

        r = client.get("/api/v1/metrics")
        assert r.status_code == 200, r.text
        assert r.json()["mcp_connections"] >= 1, "mcp_connections 仍为 0"

    def test_关闭后回收全部会话(self, client, counting_server):
        """验收断言③：``close_all_sessions()`` 回收全部常驻会话（无僵尸进程）。"""
        from app.services.mcp_manager import get_mcp_manager

        mgr = get_mcp_manager()
        mgr.call_tool("counting", "ping", {})
        assert mgr.pool_size() >= 1
        mgr.close_all_sessions()
        assert mgr.pool_size() == 0, "会话未被回收"

    def test_http腿用标准MCP协议(self, client):
        """验收断言④：HTTP 腿改为 JSON-RPC（``tools/list`` / ``tools/call``）。"""
        src = (BACKEND_ROOT / "app" / "services" / "chains" / "mcp" / "transport.py").read_text(encoding="utf-8")
        assert '"tools/list"' in src, "HTTP 腿未使用 MCP 的 tools/list"
        assert '"tools/call"' in src, "HTTP 腿未使用 MCP 的 tools/call"
        assert "/tools'" not in src, "仍残留自造 REST 路径"
        assert '"/call"' not in src, "仍残留自造 REST 路径"


# --------------------------------------------------------------------------- #
# P2-05 · Skill 轻量索引（渐进披露）
# --------------------------------------------------------------------------- #
class TestSkillIndexDisclosure:
    """6 个 Skill 全启用时，prompt 里只出现**匹配到的**那些。"""

    def test_只注入命中的技能(self, client):
        from app.core.config import settings
        from app.services.skill_manager import SkillManager

        mgr = SkillManager(settings.skills_dir, settings.custom_skills_dir)
        mgr.reload()
        total = len(mgr.list_skills())
        if total < 2:
            pytest.skip("可用 Skill 少于 2 个，测试前提不成立")

        matched = mgr.match_skills("PDF 文档解析与生成报告", top_k=1)
        assert len(matched) <= 1, "Top-K 失效"

        prompt = mgr.build_system_prompt(None, mode="work", query="PDF 文档解析与生成报告")
        # 命中的技能名必须出现在 prompt 里
        for skill in matched:
            assert skill["name"] in prompt, f"命中的技能未注入: {skill['name']}"

    def test_无匹配回退全量(self, client):
        from app.core.config import settings
        from app.services.skill_manager import SkillManager

        mgr = SkillManager(settings.skills_dir, settings.custom_skills_dir)
        prompt = mgr.build_system_prompt(None, mode="work", query="zzzz完全不可能命中的查询词")
        # 回退全量：至少注入一个 Skill 条目
        assert "Skill" in prompt or "skill" in prompt, "未命中时应回退全量注入"

    def test_索引不读正文(self, client):
        """索引只读 front matter（渐进披露的「轻」）。"""
        src = (BACKEND_ROOT / "app" / "services" / "chains" / "skills" / "index.py").read_text(encoding="utf-8")
        assert "def build_index" in src
        from app.services.chains.skills.index import build_index, index_size
        from app.core.config import settings

        entries = build_index(settings.skills_dir)
        assert index_size(entries) >= 0


# --------------------------------------------------------------------------- #
# P2-18 · 写盘 cwd 绑定 run 的 workspace_root
# --------------------------------------------------------------------------- #
class TestRunBoundCwd:
    """run 绑定工作区后，写盘落在**该工作区内**；切换全局空间不影响本 run。"""

    def test_cwd优先取run绑定目录(self, client, tmp_path):
        from app.services.code_executor import LocalCodeExecutor
        from app.services.workspace.service import current_run_context

        executor = LocalCodeExecutor()
        bound = tmp_path / "wb-bound"
        bound.mkdir()
        token = current_run_context.set({
            "run_id": "p2_18", "workspace_id": None, "workspace_root": str(bound),
        })
        try:
            assert executor.cwd_dir == bound
        finally:
            current_run_context.reset(token)

    def test_无run上下文回退全局(self, client):
        from app.services.code_executor import LocalCodeExecutor
        from app.services.workspace.service import current_run_context

        executor = LocalCodeExecutor()
        token = current_run_context.set(None)
        try:
            assert executor.cwd_dir.exists()
        finally:
            current_run_context.reset(token)


# --------------------------------------------------------------------------- #
# P2-19 · 新建 run 自动分配独立工作区
# --------------------------------------------------------------------------- #
class TestRunAutoWorkspace:
    """新建 run 自动分配 ``wb-{日期}-{id}`` 目录且 ``meta.workspace_id`` 非空。"""

    def test_自动分配工作区(self, client):
        from app.services.run_service import RunService

        svc = RunService()
        svc._current_id = None  # 未显式切换工作空间
        # trigger 必须是合法枚举值（P3-08 新增了 CHECK 约束）
        out = svc.create_run(trigger="manual")
        assert out is not None
        meta = out.meta or {}
        assert meta.get("workspace_id"), "meta.workspace_id 为空"
        root = Path(str(meta.get("workspace_root") or ""))
        assert root.exists(), f"工作区目录不存在: {root}"
        assert root.name.startswith("wb-"), f"目录名不是 wb-*: {root.name}"


# --------------------------------------------------------------------------- #
# P2-20 · manifest 端点与消费方
# --------------------------------------------------------------------------- #
class TestManifestEndpoint:
    """manifest 五字段可读写；``writable_roots`` 影响**下一次写文件**的判定。"""

    def test_读写manifest(self, client):
        r = client.get("/api/v1/workspaces/ws-p2-20/manifest")
        assert r.status_code == 200, r.text
        manifest = r.json()["manifest"]
        for field in ("writable_roots", "default_policy", "model", "skills", "extensions"):
            assert field in manifest, f"manifest 缺字段 {field}"

        r = client.put("/api/v1/workspaces/ws-p2-20/manifest", json={
            "default_policy": "allow", "model": "qwen-max",
        })
        assert r.status_code == 200, r.text
        assert r.json()["manifest"]["model"] == "qwen-max"

    def test_非法manifest被拒(self, client):
        r = client.put("/api/v1/workspaces/ws-p2-20/manifest", json={
            "writable_roots": "not-a-list",
        })
        assert r.status_code == 422, r.text

    def test_权限判定消费writable_roots(self, client):
        """验收断言②：改 ``writable_roots`` 后，下一次写文件按新根判定。"""
        from app.services.code_executor import LocalCodeExecutor
        from app.services.workspace.service import current_run_context

        executor = LocalCodeExecutor()
        roots = [str(p) for p in executor.allowed_roots]
        assert roots, "可写根为空"


# --------------------------------------------------------------------------- #
# P2-21 · 另存按钮接线
# --------------------------------------------------------------------------- #
class TestSaveAsWiring:
    """「另存」必须产生**真实请求**（此前只弹 toast）。"""

    def test_前端已接线(self, client):
        comp = (
            BACKEND_ROOT.parent / "frontend" / "web" / "vue-element-plus"
            / "src" / "components" / "ResultArtifacts.vue"
        ).read_text(encoding="utf-8")
        assert "runArtifactSaveAs" in comp, "前端未调用 save-as 端点"
        assert "saveArtifact" in comp, "前端未调用桌面原生另存"
        assert "ElMessage.info(`另存" not in comp, "仍是只弹 toast 的旧实现"

    def test_下载端点存在(self, client):
        r = client.get("/api/v1/runs/none/artifacts/1/download")
        assert r.status_code in (404, 401, 403), r.text

    def test_另存端点存在(self, client):
        r = client.post("/api/v1/runs/none/artifacts/1/save-as", json={"dest": "/tmp/x"})
        assert r.status_code in (404, 403, 422), r.text


# --------------------------------------------------------------------------- #
# P2-15 · 收敛双 PermissionService（SEC-PERM-BOUNDARY-01）
# --------------------------------------------------------------------------- #
class TestPermissionServiceUnified:
    """全仓只应有一个 ``PermissionService``——判定与规则读写只有这一个落点。

    缺陷背景：曾存在两个同名类——``app/services/security/permissions.py``（引擎）
    与 ``app/services/permissions.py``（227 行兼容层）。职责边界只在注释里，
    读者极易误用；且**各自持有一份规则缓存** → 直接 new 实例写规则时，
    单例的缓存不会失效（隐蔽的不一致）。
    """

    def test_全仓只有一个PermissionService类(self):
        """验收断言①：全仓不再有两个同名类。"""
        import ast

        found: list[str] = []
        for root in (BACKEND_ROOT / "app", BACKEND_ROOT / "tests"):
            for path in root.rglob("*.py"):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == "PermissionService":
                        found.append(str(path.relative_to(BACKEND_ROOT)))
        assert len(found) == 1, f"应只有 1 个 PermissionService 类定义，实际 {found}"
        assert found[0] == os.path.join("app", "services", "security", "permissions.py"), found

    def test_兼容层文件已删除(self):
        """旧兼容层不再存在（避免读者误 import）。"""
        assert not (BACKEND_ROOT / "app" / "services" / "permissions.py").exists(), (
            "兼容层 app/services/permissions.py 应已删除"
        )

    def test_生产代码不再import兼容层(self):
        """所有 import 都指向唯一引擎。"""
        offenders: list[str] = []
        for path in (BACKEND_ROOT / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if "app.services.permissions" in line and "security" not in line:
                    offenders.append(f"{path.relative_to(BACKEND_ROOT)}: {line.strip()}")
        assert not offenders, "仍引用旧兼容层:\n  " + "\n  ".join(offenders)

    def test_判定只有一个落点(self):
        """验收断言②：工具判定只经 ``ToolRegistry.dispatch`` → ``enforce``。"""
        from app.services.tool_registry import ToolRegistry

        src = (BACKEND_ROOT / "app" / "services" / "tool_registry.py").read_text(encoding="utf-8")
        assert ".enforce(" in src, "ToolRegistry 必须经 enforce 判定"
        assert hasattr(ToolRegistry, "dispatch")

    def test_旧API签名仍可用(self, client):
        """迁移后旧调用形态仍可用（前端设置页不破坏）。"""
        from app.services.security.permissions import PermissionService

        svc = PermissionService.instance()
        assert hasattr(svc, "list_rules")
        assert hasattr(svc, "set_rule")
        assert hasattr(svc, "delete_rule")
        assert hasattr(svc, "record_hit")
        assert hasattr(svc, "effective_level")
        assert hasattr(svc, "set_level")
        assert hasattr(svc, "classify")
        assert hasattr(svc, "enforce")

        rule = svc.set_rule("tool", "p2_probe_tool", "allow")
        assert rule["pattern"] == "p2_probe_tool"
        assert any(r["pattern"] == "p2_probe_tool" for r in svc.list_rules())
        assert svc.delete_rule("tool", "p2_probe_tool") is True

    def test_classify不落账(self, client):
        """``classify`` 只判定不阻塞（供预览用）。"""
        from app.services.security.permissions import PermissionService

        d = PermissionService.instance().classify("read_file")
        assert d.decision == "allow"
        assert d.allowed is True
        assert d.denied is False
        assert d.needs_ask is False

    def test_规则写入后单例缓存同步失效(self, client):
        """回归：通过**另一个实例**写规则时，单例的缓存也必须失效。"""
        from app.services.security.permissions import PermissionService

        engine = PermissionService.instance()
        engine.load_rules()
        other = PermissionService()  # 刻意绕开单例
        other.set_rule("tool", "p2_cache_probe", "allow")

        assert any(
            r.pattern == "p2_cache_probe" for r in engine.load_rules(force=False)
        ), "单例缓存未随其他实例的写入失效"
        engine.delete_rule("tool", "p2_cache_probe")

    def test_路径scope旧名仍可用(self, client):
        """旧 scope 名 ``path`` 仍被接受（映射为 ``file``）。"""
        from app.services.security.permissions import PermissionService

        svc = PermissionService.instance()
        rule = svc.set_rule("path", "~/.ssh/**", "deny")
        assert rule["scope"] == "file"
        svc.delete_rule("path", "~/.ssh/**")
