"""S6 扩展三层与多 Agent 的契约测试。

按 doc/roadmap/07-阶段S6 的 §5.1 组织：技能规范 / 扫描 / 插件安装 / 黑板 /
编排 / 上下文收费站 / 角色档位 / 角色 API / 技能权限。
"""
from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest

from app.services.chains.skills import scanner
from app.services.chains.skills.index import build_index, index_size, load_body, match
from app.services.chains.skills.plugins import PluginManager
from app.services.chains.skills.spec import SkillSpecError, build_skill_md, validate
from app.services.exec.team.blackboard import BlackboardService, readiness, would_create_cycle
from app.services.exec.team.messaging import (
    MessageService,
    build_main_context_block,
    build_summary,
    tollgate,
)
from app.services.exec.team.orchestrator import SubTask, TeamOrchestrator
from app.services.exec.team.roles import RoleError, RoleService, model_for_tier


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# WP-6.1 技能规范与轻量索引
# --------------------------------------------------------------------------- #
class TestSkillSpec:
    def test_frontmatter校验(self):
        content = build_skill_md("demo", "演示技能", "正文内容", triggers=["演示"])
        spec = validate(content)
        assert spec.name == "demo"
        assert spec.description == "演示技能"
        assert spec.triggers == ["演示"]

    def test_非法即拒(self):
        with pytest.raises(SkillSpecError):
            validate("---\nname: Demo_X\ndescription: 非法名\n---\n\n正文")
        with pytest.raises(SkillSpecError):
            validate("---\nname: demo\n---\n\n正文")  # 缺 description
        with pytest.raises(SkillSpecError):
            validate("没有 front matter")
        with pytest.raises(SkillSpecError):
            validate("---\nname: demo\ndescription: d\nunknown_field: 1\n---\n\nx")

    def test_索引只含frontmatter(self, tmp_path):
        skill = tmp_path / "alpha"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            build_skill_md("alpha", "阿尔法技能", "很长的正文" * 500, triggers=["阿尔法"]),
            encoding="utf-8",
        )
        entries = build_index(tmp_path)
        assert len(entries) == 1
        assert entries[0].name == "alpha"
        # 索引体积远小于正文
        body_size = len((skill / "SKILL.md").read_text(encoding="utf-8"))
        assert index_size(entries) < body_size / 10

    def test_命中才读正文(self, tmp_path):
        skill = tmp_path / "alpha"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            build_skill_md("alpha", "阿尔法技能", "正文", triggers=["阿尔法"]),
            encoding="utf-8",
        )
        entries = build_index(tmp_path)
        hits = match(entries, "阿尔法")
        assert hits and hits[0].name == "alpha"
        spec = load_body(hits[0])   # 命中后才读正文
        assert spec.name == "alpha"


# --------------------------------------------------------------------------- #
# WP-6.5 扫描规则集
# --------------------------------------------------------------------------- #
class TestScanner:
    def test_网络调用命中(self):
        result = scanner.scan_text("import requests\nrequests.get('http://x')")
        assert any(f.rule == "network_call" for f in result)

    def test_删除递归命中(self):
        result = scanner.scan_text("shutil.rmtree('/tmp/x')")
        assert any(f.rule == "delete_or_recursive" for f in result)

    def test_敏感路径命中(self):
        result = scanner.scan_text("open('~/.ssh/id_rsa')")
        assert any(f.rule == "sensitive_path" for f in result)

    def test_凭据命中(self):
        result = scanner.scan_text("api_key = 'sk-abcdefghijklmnopqrstuvwxyz012345'")
        assert any(f.rule == "hardcoded_credential" for f in result)

    def test_混淆命中(self):
        result = scanner.scan_text("x = '\\x41\\x42\\x43\\x44\\x45\\x46\\x47\\x48\\x49\\x4a\\x4b\\x4c'")
        assert any(f.rule == "obfuscation" for f in result)

    def test_体积异常(self, tmp_path):
        big = tmp_path / "big.txt"
        big.write_text("x" * 2000, encoding="utf-8")
        result = scanner.scan_directory(tmp_path, max_total_bytes=100)
        assert any(f.rule == "size_anomaly" for f in result.findings)

    def test_分级正确(self):
        low = scanner.scan_text("print('hello')")
        assert low == [] or all(f.level in ("low", "medium") for f in low)
        crit = scanner.scan_text("key='sk-abcdefghijklmnopqrstuvwxyz012345'")
        assert any(f.level == "critical" for f in crit)

    def test_high默认拒绝(self):
        res = scanner.ScanResult(level="high")
        assert scanner.should_reject(res) is True
        assert scanner.needs_confirmation(res) is True
        med = scanner.ScanResult(level="medium")
        assert scanner.should_reject(med) is False
        assert scanner.needs_confirmation(med) is True


# --------------------------------------------------------------------------- #
# WP-6.4 插件安装与回滚
# --------------------------------------------------------------------------- #
def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestPluginInstall:
    def test_原子安装成功(self, tmp_path):
        mgr = PluginManager(tmp_path / "plugins")
        data = _make_zip({
            "plugin.json": json.dumps({"name": "demo-plugin", "version": "1.0.0",
                                       "skills": ["demo"]}),
            "skills/demo/SKILL.md": build_skill_md("demo", "演示", "正文"),
        })
        result = mgr.install_from_zip(data)
        assert result.ok, result.message
        assert result.name == "demo-plugin"
        assert (mgr.plugins_dir / "demo-plugin" / "1.0.0" / "plugin.json").exists()
        # 索引可重建
        entries = build_index(mgr.plugins_dir / "demo-plugin" / "1.0.0" / "skills")
        assert entries and entries[0].name == "demo"

    def test_中途失败回滚(self, tmp_path):
        mgr = PluginManager(tmp_path / "plugins")
        data = _make_zip({"plugin.json": "{ 坏 json"})
        result = mgr.install_from_zip(data)
        assert result.ok is False
        assert not list(mgr.plugins_dir.glob("*/1.0.0")), "失败不应留下半成品"

    def test_版本回滚(self, tmp_path):
        mgr = PluginManager(tmp_path / "plugins")
        v1 = _make_zip({"plugin.json": json.dumps({"name": "p", "version": "1.0.0"}),
                        "skills/a/SKILL.md": build_skill_md("a", "旧", "旧正文")})
        v2 = _make_zip({"plugin.json": json.dumps({"name": "p", "version": "2.0.0"}),
                        "skills/a/SKILL.md": build_skill_md("a", "新", "新正文")})
        assert mgr.install_from_zip(v1).ok
        assert mgr.install_from_zip(v2).ok
        res = mgr.rollback("p", "2.0.0")
        assert res.ok, res.message
        assert res.message == "已回滚到上一版本"

    def test_路径穿越拒绝(self, tmp_path):
        mgr = PluginManager(tmp_path / "plugins")
        data = _make_zip({
            "plugin.json": json.dumps({"name": "evil", "version": "1.0.0"}),
            "../escape.txt": "bad",
        })
        result = mgr.install_from_zip(data)
        assert result.ok is False
        assert "穿越" in result.message or "路径" in result.message
        assert not (tmp_path / "escape.txt").exists()

    def test_high默认拒绝需确认(self, tmp_path):
        mgr = PluginManager(tmp_path / "plugins")
        data = _make_zip({
            "plugin.json": json.dumps({"name": "risky", "version": "1.0.0"}),
            "skills/x/SKILL.md": build_skill_md("x", "危险", "shutil.rmtree('/')"),
        })
        blocked = mgr.install_from_zip(data)
        assert blocked.ok is False
        assert "默认拒绝" in blocked.message
        assert blocked.scan and blocked.scan["rejected_by_default"] is True
        confirmed = mgr.install_from_zip(data, confirm=True)
        assert confirmed.ok, confirmed.message


# --------------------------------------------------------------------------- #
# WP-6.7 黑板
# --------------------------------------------------------------------------- #
class TestBlackboard:
    def test_依赖未完成不ready(self):
        svc = BlackboardService()
        a = svc.create_item("b1", "A")
        b = svc.create_item("b1", "B", deps=[a.id])
        items = svc.list_items("b1")
        states = readiness(items)
        assert states[a.id] == "ready"
        assert states[b.id] == "pending"

    def test_failed导致blocked(self):
        svc = BlackboardService()
        a = svc.create_item("b2", "A")
        b = svc.create_item("b2", "B", deps=[a.id])
        svc.set_status(a.id, "failed")
        states = readiness(svc.list_items("b2"))
        assert states[b.id] == "blocked"

    def test_环检测拒绝(self):
        svc = BlackboardService()
        a = svc.create_item("b3", "A")
        b = svc.create_item("b3", "B", deps=[a.id])
        # 链式依赖不是环：C 依赖 B（B 依赖 A）允许
        c = svc.create_item("b3", "C", deps=[b.id])
        assert c.id
        # 真环：A 依赖 B（B 已依赖 A）必须被拒
        with pytest.raises(ValueError):
            svc.add_dep(a.id, b.id)
        items = svc.list_items("b3")
        assert would_create_cycle(items, a.id, [b.id]) is True

    def test_完成即重算(self):
        svc = BlackboardService()
        a = svc.create_item("b4", "A")
        b = svc.create_item("b4", "B", deps=[a.id])
        items = svc.complete(a.id, {"out": "ok"})
        by_id = {i.id: i for i in items}
        assert by_id[b.id].status == "ready"


# --------------------------------------------------------------------------- #
# WP-6.3 编排
# --------------------------------------------------------------------------- #
class TestOrchestrator:
    def test_parallel汇总(self):
        def executor(task, ctx):
            return f"输出-{task.title}"

        orch = TeamOrchestrator(executor)
        tasks = [SubTask(title="T1", prompt="p1", role="r1"), SubTask(title="T2", prompt="p2", role="r2")]
        result = orch.run(tasks, mode="parallel")
        assert len(result.results) == 2
        assert result.summary
        assert "T1" in result.summary

    def test_sequential串联(self):
        seen: list[str] = []

        def executor(task, ctx):
            seen.append(ctx)
            return f"[{task.title}]"

        orch = TeamOrchestrator(executor)
        tasks = [SubTask(title="T1", prompt="p1"), SubTask(title="T2", prompt="p2")]
        result = orch.run(tasks, mode="sequential")
        assert len(result.results) == 2
        assert seen[1] == "[T1]", "后一个子任务应收到前一个的产出"

    def test_review修订(self):
        def executor(task, ctx):
            return "初稿" if task.title == "T1" else "评审稿"

        orch = TeamOrchestrator(executor)
        tasks = [SubTask(title="T1", prompt="p1", role="执行者")]
        result = orch.run(tasks, mode="review")
        assert result.results[-1].role == "reviewer"
        assert result.results[-1].output == "评审稿"

    def test_汇总结果非空(self):
        orch = TeamOrchestrator(lambda t, c: "out")
        result = orch.run([SubTask(title="T", prompt="p")], mode="parallel")
        assert result.summary.strip()
        assert result.notifications


# --------------------------------------------------------------------------- #
# WP-6.8 上下文收费站
# --------------------------------------------------------------------------- #
class TestContextTollgate:
    def test_主上下文不含子Agent原文(self):
        msgs = MessageService()
        msg = msgs.notify("子任务完成：结论是 X", refs=[{"type": "message", "id": "m1"}])
        block = build_main_context_block([msg])
        assert "[raw-agent-output]" not in block
        assert "结论是 X" in block

    def test_只含压缩通知(self):
        msgs = MessageService()
        msg = msgs.notify("摘要：结论/证据/约束/未决", refs=[{"type": "artifact", "id": "a1"}])
        block = build_main_context_block([msg])
        assert "摘要" in block
        assert "引用" in block

    def test_通知含结构化引用(self):
        msgs = MessageService()
        with pytest.raises(ValueError):
            msgs.notify("没有引用")   # 通知必须带引用
        msg = msgs.notify("带引用", refs=[{"type": "artifact", "id": "a1", "path": "x.md"}])
        assert msg.refs and msg.refs[0]["type"] == "artifact"
        assert msg.is_notification is True

    def test_收费站检测到原文(self):
        assert tollgate("正常上下文")["ok"] is True
        bad = tollgate("[raw-agent-output] 原始推理")
        assert bad["ok"] is False
        assert "[raw-agent-output]" in bad["violations"]

    def test_摘要模板四段(self):
        summary = build_summary("结论A", "证据B", "约束C", "未决D")
        for seg in ("结论：", "证据位置：", "约束：", "未决项："):
            assert seg in summary


# --------------------------------------------------------------------------- #
# WP-6.9 角色模型档
# --------------------------------------------------------------------------- #
class TestRoleTiers:
    def test_轻档角色0工具(self):
        svc = RoleService()
        with pytest.raises(RoleError):
            svc.create("bad-light", model_tier="light", tools=["write_file"])

    def test_档位映射正确(self):
        assert model_for_tier("light") != model_for_tier("strong")
        assert model_for_tier("light") == "qwen-turbo"

    def test_内置角色迁入表且0工具(self):
        svc = RoleService()
        svc.sync_builtin_roles()
        for name in ("compact", "contextSummary", "memorySelector"):
            role = svc.get_by_name(name)
            assert role is not None, name
            assert role.tools == [], f"{name} 应为 0 工具"
            assert role.model_tier == "light"


# --------------------------------------------------------------------------- #
# 角色 API
# --------------------------------------------------------------------------- #
class TestRolesApi:
    def test_角色CRUD(self, client):
        created = client.post("/api/v1/roles", json={
            "name": "数据分析师", "title": "数据分析师",
            "expertise": ["数据分析"], "tools": ["read_file"], "model_tier": "standard",
        })
        assert created.status_code in (200, 201), created.text
        role_id = created.json()["id"]

        listed = client.get("/api/v1/roles").json()
        assert any(r["name"] == "数据分析师" for r in listed["items"])

        updated = client.patch(f"/api/v1/roles/{role_id}", json={"title": "资深数据分析师"})
        assert updated.status_code == 200
        assert updated.json()["title"] == "资深数据分析师"

        deleted = client.delete(f"/api/v1/roles/{role_id}")
        assert deleted.status_code == 200

    def test_创建后不可改名(self, client):
        created = client.post("/api/v1/roles", json={"name": "改名测试"}).json()
        res = client.patch(f"/api/v1/roles/{created['id']}", json={"name": "新名字"})
        assert res.status_code == 422
        assert "不可改名" in res.json().get("detail", "")

    def test_名称唯一(self, client):
        first = client.post("/api/v1/roles", json={"name": "唯一测试"})
        assert first.status_code in (200, 201)
        second = client.post("/api/v1/roles", json={"name": "唯一测试"})
        assert second.status_code == 422


# --------------------------------------------------------------------------- #
# WP-6.6 技能工具不得绕过权限
# --------------------------------------------------------------------------- #
class TestSkillPermission:
    def test_技能工具受统一判定(self):
        """技能提供的工具同样要过权限引擎（不得豁免）。"""
        from app.services.tool_registry import ToolRegistry

        reg = ToolRegistry(mcp_manager=None)
        # 高危动作（批量删除）无论来源，都必须被拒
        denial = reg._check_permission("execute_bash", {"command": "rm -rf /"})
        assert denial is not None
        assert denial["permission"]["decision"] == "deny"


# --------------------------------------------------------------------------- #
# WP-6.4 插件安装目标隔离
# --------------------------------------------------------------------------- #
class TestPluginInstallIsolation:
    def test_不污染源码树(self, client, tmp_path, monkeypatch):
        """插件技能必须装进**用户数据目录**的自定义技能目录，不得写进内置技能目录（源码树）。"""
        import base64
        import io as _io
        import json as _json
        import zipfile

        from app.core.config import settings

        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("plugin.json", _json.dumps({"name": "iso-probe", "version": "1.0.0", "skills": []}))
            zf.writestr("skills/iso-probe/SKILL.md", "---\nname: iso-probe\ndescription: 隔离验证\nversion: 0.1.0\n---\n\n无正文\n")
        data = base64.b64encode(buf.getvalue()).decode()

        builtin = settings.skills_dir
        before = {p.name for p in builtin.iterdir()} if builtin.is_dir() else set()

        r = client.post("/api/v1/plugins/install", json={"content_b64": data})
        assert r.status_code in (200, 201), r.text
        body = r.json()
        # 要么被扫描拦下（不进任何目录），要么装进自定义目录
        if body.get("ok"):
            after = {p.name for p in builtin.iterdir()} if builtin.is_dir() else set()
            assert "iso-probe" not in after, "插件技能不得写进内置技能目录（源码树）"
        else:
            assert (body.get("scan") or {}).get("rejected_by_default") is True or body.get("message")

        # 自定义目录里才可能出现
        custom = settings.custom_skills_dir
        if custom.is_dir():
            for p in custom.iterdir():
                if p.name == "iso-probe":
                    import shutil

                    shutil.rmtree(p, ignore_errors=True)
