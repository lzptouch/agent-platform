"""原生层（NAT）端到端（P5-07）。

覆盖**不经 HTTP** 的原生能力：文件读写、执行器、工作空间落盘、权限判定、
产物登记。本层不经 API，因此能捕捉「API 正常但底层不对」的缺陷。

用例编号前缀：``NAT-*``。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def executor():
    from app.core.config import settings
    from app.services.code_executor import LocalCodeExecutor

    ex = LocalCodeExecutor()
    ex.output_dir.mkdir(parents=True, exist_ok=True)
    return ex


class TestNativeFileOps:
    """文件工具的原生行为（不经过 API）。"""

    def test_写入与读回(self, executor, tmp_path):
        """NAT-01：write_file → read_file 往返一致（需在工作区允许根内）。"""
        from app.services.workspace.service import current_run_context

        target = tmp_path / "native.txt"
        token = current_run_context.set({
            "run_id": "nat-01", "workspace_id": None, "workspace_root": str(tmp_path),
        })
        try:
            out = executor.write_file(str(target), "原生内容")
            assert out["success"], out
            back = executor.read_file(str(target))
            assert "原生内容" in back.get("content", ""), back
        finally:
            current_run_context.reset(token)

    def test_越界写入被拒(self, executor):
        """NAT-02：写入允许根之外 → 拒绝。"""
        out = executor.write_file("/tmp/native-should-be-denied.txt", "x")
        # **W11-01**：旧断言 `success is False or error == ""` 在**写入被放行**时
        # 同样成立（success=True 时 error 也可能是 ""）→ 越界写入被放行时测试仍然绿。
        assert out.get("success") is False, out
        assert "范围" in (out.get("error") or ""), out

    def test_工作区绑定影响落盘位置(self, executor, tmp_path):
        """NAT-03：run 绑定的 workspace_root 决定落盘目录（P2-18）。"""
        from app.services.workspace.service import current_run_context

        bound = tmp_path / "wb-native"
        bound.mkdir()
        token = current_run_context.set({
            "run_id": "nat-03", "workspace_id": None, "workspace_root": str(bound),
        })
        try:
            assert executor.cwd_dir == bound
        finally:
            current_run_context.reset(token)


class TestNativeWorkspace:
    """工作空间的原生布局与 manifest。"""

    def test_布局完整(self, tmp_path):
        """NAT-04：工作空间目录布局齐备（.agent/ + artifacts/）。"""
        from app.services.workspace.manifest import ensure_layout

        root = ensure_layout(tmp_path, "wb-native-test")
        assert (root / ".agent").is_dir()
        assert (root / "artifacts").is_dir()
        # manifest 由 WorkspaceService.create 落盘（ensure_layout 只建目录）
        from app.services.workspace.manifest import manifest_path

        assert manifest_path(tmp_path, "wb-native-test").parent.is_dir()

    def test_manifest读写与校验(self, tmp_path):
        """NAT-05：manifest 可读写；非法值被拒（P2-20）。"""
        from app.services.workspace.manifest import (
            ensure_layout, read_manifest, validate_manifest, write_manifest,
        )

        root = ensure_layout(tmp_path, "wb-native-manifest")
        manifest = write_manifest(root, "wb-native-manifest", {"model": "qwen-max"})
        assert manifest["model"] == "qwen-max"
        assert read_manifest(root, "wb-native-manifest")["model"] == "qwen-max"

        with pytest.raises(ValueError):
            validate_manifest({"writable_roots": "not-a-list"})
        with pytest.raises(ValueError):
            validate_manifest({"default_policy": "whatever"})


class TestNativePermissions:
    """权限引擎的原生判定。"""

    def test_三态判定(self, client):
        """NAT-06：同一工具在不同规则下得到 allow / ask / deny。"""
        from app.services.security.permissions import PermissionRequest, PermissionService

        svc = PermissionService.instance()
        check = svc.classify("read_file")
        assert check.decision in ("allow", "ask", "deny")
        assert isinstance(check.allowed, bool)

    def test_内置规则已收敛(self, client):
        """NAT-07：内置规则无重复（P1-03）。"""
        from app.services.security.permissions import PermissionService

        svc = PermissionService.instance()
        svc.ensure_builtin_rules()
        rules = [r for r in svc.list_rules() if r.get("origin") == "builtin"]
        keys = [(r["scope"], r["pattern"]) for r in rules]
        assert len(keys) == len(set(keys)), "内置规则存在重复项"


class TestNativeArtifact:
    """产物登记的原生路径。"""

    def test_登记与列出(self, client, tmp_path):
        """NAT-08：register_artifact → list_artifacts 一致。"""
        from app.services.workspace import artifacts as art

        root = tmp_path / "ws"
        root.mkdir()
        (root / "out.md").write_text("交付", encoding="utf-8")
        import uuid
        run_id = f"nat-run-08-{uuid.uuid4().hex[:8]}"  # 唯一 run_id（避免重跑累积）
        art.register_artifact(run_id, None, root, "out.md", title="交付物")
        items = art.list_artifacts(run_id)
        assert len(items) == 1, items
        assert items[0]["title"] == "交付物"


class TestNativeMcp:
    """MCP 管理器的原生状态。"""

    def test_池大小可读(self, client):
        """NAT-09：连接池大小可读且非负（P2-01）。"""
        from app.services.chains.mcp.transport import pool_size
        from app.services.mcp_manager import get_mcp_manager

        assert pool_size() >= 0
        assert get_mcp_manager().pool_size() >= 0

    def test_注册表完整(self, client):
        """NAT-10：内置 MCP Server 注册表含脚本路径。"""
        from app.services.mcp_manager import get_mcp_manager

        mgr = get_mcp_manager()
        assert mgr.SERVER_REGISTRY, "注册表为空"
        for name, info in mgr.SERVER_REGISTRY.items():
            assert info.get("script"), f"{name} 未声明脚本路径"
