"""S3 工作空间、变更与产物的契约测试。

按 doc/roadmap/04-阶段S3 的 §5.1 组织：manifest / 快照与变更 / diff 与回退 /
产物 / 敏感信息 / run 绑定 / 迁移。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.workspace import reset_workspace_dir, set_workspace_dir
from app.db.base import db_session
from app.db.models import ArtifactRow, ChangeRow, WorkspaceRow
from app.services.security import sensitive
from app.services.workspace import artifacts as art
from app.services.workspace import changes as chg
from app.services.workspace import manifest as mf
from app.services.workspace import snapshots as snap
from app.services.workspace.service import WorkspaceService


@pytest.fixture(autouse=True)
def _ws(tmp_path):
    set_workspace_dir(tmp_path)
    snap.reset_snapshots()
    WorkspaceService.reset_for_test()
    yield tmp_path
    reset_workspace_dir()
    WorkspaceService.reset_for_test()


# --------------------------------------------------------------------------- #
# WP-3.1 工作空间实体与 manifest
# --------------------------------------------------------------------------- #
class TestWorkspaceEntity:
    def test_自动生成工作空间ID(self, tmp_path):
        ws = WorkspaceService.instance().create("任务A")
        assert ws.id.startswith("wb-")
        assert Path(ws.root_path).is_dir()
        assert (Path(ws.root_path) / "artifacts").is_dir()

    def test_指定根目录复用用户目录(self, tmp_path):
        user_dir = tmp_path / "mydir"
        user_dir.mkdir()
        ws = WorkspaceService.instance().create("任务B", root_path=str(user_dir))
        assert ws.root_path == str(user_dir)

    def test_manifest读写往返(self, tmp_path):
        ws = WorkspaceService.instance().create("任务C")
        container = Path(ws.root_path).parent
        mf.write_manifest(container, Path(ws.root_path).name, {"default_policy": "deny", "snapshot_budget_mb": 1000})
        back = mf.read_manifest(container, Path(ws.root_path).name)
        assert back["default_policy"] == "deny"
        assert back["snapshot_budget_mb"] == 1000
        assert back["writable_roots"]  # 默认填入工作空间根

    def test_归档不删磁盘文件(self, tmp_path):
        ws = WorkspaceService.instance().create("任务D")
        probe = Path(ws.root_path) / "keep.txt"
        probe.write_text("x", encoding="utf-8")
        WorkspaceService.instance().archive(ws.id)
        assert probe.exists(), "归档不得删除磁盘文件"
        assert WorkspaceService.instance().get(ws.id).status == "archived"

    def test_切换与当前(self, tmp_path):
        ws = WorkspaceService.instance().create("任务E")
        WorkspaceService.instance().switch(ws.id)
        assert WorkspaceService.instance().current().id == ws.id


# --------------------------------------------------------------------------- #
# WP-3.2 run 绑定工作空间（运行期锁定）
# --------------------------------------------------------------------------- #
class TestRunBinding:
    def test_run绑定显式工作空间(self, tmp_path):
        from app.services.run_service import RunService

        ws = WorkspaceService.instance().create("绑定测试")
        run = RunService().create_run(trigger="api", workspace_id=ws.id)
        assert run is not None
        assert run.meta.get("workspace_id") == ws.id
        assert run.meta.get("workspace_root") == ws.root_path

    def test_run未指定时用当前空间(self, tmp_path):
        from app.services.run_service import RunService

        ws = WorkspaceService.instance().create("当前空间")
        WorkspaceService.instance().switch(ws.id)
        run = RunService().create_run(trigger="api")
        assert run.meta.get("workspace_id") == ws.id

    def test_切换工作空间不影响已绑定run(self, tmp_path):
        from app.services.run_service import RunService

        ws_a = WorkspaceService.instance().create("空间A")
        WorkspaceService.instance().switch(ws_a.id)
        run = RunService().create_run(trigger="api")
        ws_b = WorkspaceService.instance().create("空间B")
        WorkspaceService.instance().switch(ws_b.id)
        # 已绑定的 run 仍是空间 A
        assert run.meta.get("workspace_id") == ws_a.id


# --------------------------------------------------------------------------- #
# WP-3.3 快照与变更
# --------------------------------------------------------------------------- #
class TestSnapshotAndChanges:
    def test_写前快照生成(self, tmp_path):
        target = tmp_path / "note.txt"
        target.write_text("v1", encoding="utf-8")
        s = snap.snapshot_before_write("run-1", tmp_path, target, "write_file")
        assert s is not None
        assert Path(s["snapshot_ref"]).exists()
        assert s["before_hash"] == snap.file_hash(target)

    def test_同文件每轮只备份一次(self, tmp_path):
        target = tmp_path / "note.txt"
        target.write_text("v1", encoding="utf-8")
        first = snap.snapshot_before_write("run-1", tmp_path, target, "write_file")
        second = snap.snapshot_before_write("run-1", tmp_path, target, "write_file")
        assert first is not None
        assert second is None, "同文件本轮不应重复备份"

    def test_变更落账含前后哈希(self, tmp_path):
        target = tmp_path / "note.txt"
        target.write_text("v1", encoding="utf-8")
        s = snap.snapshot_before_write("run-1", tmp_path, target, "write_file")
        target.write_text("v2", encoding="utf-8")
        snap.record_change("run-1", "ws-x", tmp_path, target, "modify", "write_file", s)
        rows = chg.list_changes("run-1")
        assert len(rows) == 1
        assert rows[0]["before_hash"] != rows[0]["after_hash"]
        assert rows[0]["op"] == "modify"

    def test_改三个文件三条变更(self, tmp_path):
        for i in range(3):
            target = tmp_path / f"f{i}.txt"
            target.write_text("v1", encoding="utf-8")
            s = snap.snapshot_before_write("run-2", tmp_path, target, "write_file")
            target.write_text("v2", encoding="utf-8")
            snap.record_change("run-2", "ws-x", tmp_path, target, "modify", "write_file", s)
        assert len(chg.list_changes("run-2")) == 3


# --------------------------------------------------------------------------- #
# WP-3.4 diff 与回退
# --------------------------------------------------------------------------- #
class TestDiffAndRevert:
    def test_文本行级diff(self, tmp_path):
        target = tmp_path / "note.txt"
        target.write_text("line1\nline2\n", encoding="utf-8")
        s = snap.snapshot_before_write("run-d", tmp_path, target, "write_file")
        target.write_text("line1\nline2 changed\nline3\n", encoding="utf-8")
        snap.record_change("run-d", None, tmp_path, target, "modify", "write_file", s)
        cid = chg.list_changes("run-d")[0]["id"]
        d = chg.compute_diff(cid, tmp_path)
        assert d["kind"] == "text"
        assert d["added"] >= 2 and d["removed"] >= 1

    def test_回退后内容一致且留痕(self, tmp_path):
        target = tmp_path / "note.txt"
        target.write_text("original", encoding="utf-8")
        s = snap.snapshot_before_write("run-r", tmp_path, target, "write_file")
        target.write_text("modified", encoding="utf-8")
        snap.record_change("run-r", None, tmp_path, target, "modify", "write_file", s)
        cid = chg.list_changes("run-r")[0]["id"]
        chg.revert(cid, tmp_path)
        assert target.read_text(encoding="utf-8") == "original"
        ops = [c["op"] for c in chg.list_changes("run-r")]
        assert "revert" in ops, "回退应留痕"


# --------------------------------------------------------------------------- #
# WP-3.5 产物
# --------------------------------------------------------------------------- #
class TestArtifacts:
    def test_产物登记与查询(self, tmp_path):
        f = tmp_path / "report.md"
        f.write_text("# 报告", encoding="utf-8")
        rec = art.register_artifact("run-a", None, tmp_path, f, title="报告")
        assert rec["kind"] == "doc"
        assert rec["previewable"] is True
        listed = art.list_artifacts("run-a")
        assert len(listed) == 1 and listed[0]["title"] == "报告"

    def test_另存到指定位置(self, tmp_path):
        f = tmp_path / "report.md"
        f.write_text("# 报告", encoding="utf-8")
        rec = art.register_artifact("run-a", None, tmp_path, f)
        dest = tmp_path / "out" / "saved.md"
        res = art.save_as(rec["id"], tmp_path, dest)
        assert dest.exists() and dest.read_text(encoding="utf-8") == "# 报告"


# --------------------------------------------------------------------------- #
# WP-3.6 敏感信息
# --------------------------------------------------------------------------- #
class TestSensitive:
    def test_高置信密钥拒绝(self):
        r = sensitive.process("key = sk-abcdefghijklmnopqrstuvwxyz123456")
        assert r["action"] == "deny"

    def test_私钥拒绝(self):
        r = sensitive.process("-----BEGIN RSA PRIVATE KEY-----\nMII...")
        assert r["action"] == "deny"

    def test_低置信加密且可还原(self):
        text = "token = " + "aB3$xY9_zQ1wE8rT7yU6" + " 其余正常文本"
        r = sensitive.process(text)
        if r["action"] == "allow_and_encrypt":
            assert "ENC[" in r["processed"]
            assert sensitive.restore(r["processed"]) == text

    def test_普通文本放行(self):
        r = sensitive.process("今天天气不错，写个报告")
        assert r["action"] == "allow"
        assert r["processed"] == "今天天气不错，写个报告"

    def test_密文往返(self):
        enc = sensitive.encrypt_fragment("secret-value-123")
        assert sensitive.decrypt_fragment(enc) == "secret-value-123"


# --------------------------------------------------------------------------- #
# WP-3.1 迁移
# --------------------------------------------------------------------------- #
class TestMigration:
    def test_三表存在(self):
        from sqlalchemy import inspect

        from app.db.base import get_engine

        tables = inspect(get_engine()).get_table_names()
        assert {"workspaces", "changes", "artifacts"} <= set(tables)

    def test_工作空间表新列(self):
        from sqlalchemy import inspect

        from app.db.base import get_engine

        cols = {c["name"] for c in inspect(get_engine()).get_columns("workspaces")}
        assert {"id", "name", "root_path", "status", "manifest_json"} <= cols
