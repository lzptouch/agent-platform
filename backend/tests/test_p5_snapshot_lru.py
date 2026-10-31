"""P5-13 · 快照 LRU 清理分支测试。

快照预算 3000MB + 超限 LRU 清理 + 清理写审计**都已实现**，但
**LRU 清理分支无任何测试** —— 意味着「超预算时最旧的被删、审计留痕」
这条路径**从未被验证过**（也从未被回归保护）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def client():
    from starlette.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def _make_snapshots(root: Path, count: int, size_bytes: int) -> Path:
    """造 ``count`` 个快照目录（每个含一个 ``size_bytes`` 的文件）。"""
    snap_root = root / ".agent" / "snapshots"
    snap_root.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        d = snap_root / f"seq{i:03d}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "payload.bin").write_bytes(b"x" * size_bytes)
    return snap_root


class TestSnapshotLruCleanup:
    """预算超限 → 按 LRU（最旧 seq）清理 + 写审计。"""

    def test_超预算清理最旧快照(self, client, tmp_path, monkeypatch):
        from app.services.workspace import snapshots

        monkeypatch.setattr(snapshots, "SNAPSHOT_BUDGET_MB", 1)  # 1 MB
        root = tmp_path / "ws"
        snap_root = _make_snapshots(root, count=3, size_bytes=600_000)  # 共 1.8MB

        snapshots._enforce_budget(root)

        left = sorted(p.name for p in snap_root.iterdir() if p.is_dir())
        assert "seq000" not in left, f"最旧快照未被清理: {left}"
        assert "seq002" in left, f"最新快照被误删: {left}"
        assert len(left) < 3, f"清理未发生: {left}"

    def test_清理后不超预算(self, client, tmp_path, monkeypatch):
        from app.services.workspace import snapshots

        monkeypatch.setattr(snapshots, "SNAPSHOT_BUDGET_MB", 1)
        root = tmp_path / "ws"
        snap_root = _make_snapshots(root, count=3, size_bytes=600_000)

        snapshots._enforce_budget(root)

        total = sum(f.stat().st_size for f in snap_root.rglob("*") if f.is_file())
        assert total <= 1 * 1024 * 1024, f"清理后仍超预算: {total}"

    def test_清理写审计留痕(self, client, tmp_path, monkeypatch):
        from app.services.security import audit
        from app.services.workspace import snapshots

        monkeypatch.setattr(snapshots, "SNAPSHOT_BUDGET_MB", 1)
        root = tmp_path / "ws"
        _make_snapshots(root, count=3, size_bytes=600_000)

        # 审计写到临时工作区（避免污染开发环境）
        monkeypatch.setattr(audit, "audit_path", lambda workspace=None: tmp_path / "audit.log")

        snapshots._enforce_budget(root)

        log = tmp_path / "audit.log"
        assert log.exists(), "清理未写审计"
        text = log.read_text(encoding="utf-8")
        entries = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        assert entries, "审计内容不可解析"
        hits = [e for e in entries if e.get("tool") == "snapshot_gc"]
        assert hits, f"审计未记录 snapshot_gc: {entries}"
        assert "seq000" in str(hits[0]), f"审计未指明清理对象: {hits[0]}"

    def test_不超预算不清理(self, client, tmp_path, monkeypatch):
        from app.services.workspace import snapshots

        monkeypatch.setattr(snapshots, "SNAPSHOT_BUDGET_MB", 10)  # 10MB
        root = tmp_path / "ws"
        snap_root = _make_snapshots(root, count=3, size_bytes=100_000)  # 共 0.3MB

        snapshots._enforce_budget(root)

        left = sorted(p.name for p in snap_root.iterdir() if p.is_dir())
        assert left == ["seq000", "seq001", "seq002"], f"未超预算却被清理: {left}"

    def test_无快照目录时不报错(self, client, tmp_path, monkeypatch):
        from app.services.workspace import snapshots

        monkeypatch.setattr(snapshots, "SNAPSHOT_BUDGET_MB", 1)
        snapshots._enforce_budget(tmp_path / "empty-ws")
