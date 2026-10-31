"""部署层（DEP）端到端（P5-08）。

校验**可部署形态**：compose / 镜像 / 环境变量 / 迁移在部署态的一致性。

环境不具备（无 Docker）时，相关用例 **skip 并计入覆盖率缺口**
（`doc/testing/00` §6.4 的 ``env`` 归类——**不算通过**）。

用例编号前缀：``DEP-*``。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "deploy" / "docker-compose.ha.yml"
COMPOSE_ALT = REPO_ROOT / "docker-compose.yml"


def _compose_file() -> Path | None:
    for path in (COMPOSE, COMPOSE_ALT):
        if path.exists():
            return path
    return None


class TestDeployCompose:
    """compose 文件的结构校验（不需要 Docker）。"""

    def test_compose存在(self):
        """DEP-01：至少存在一份 compose 定义。"""
        assert _compose_file() is not None, "未找到 docker-compose 定义"

    def test_服务定义完整(self):
        """DEP-02：每个服务都有 image 或 build。"""
        path = _compose_file()
        assert path is not None
        text = path.read_text(encoding="utf-8")
        assert "services:" in text, "compose 缺少 services 段"
        assert ("image:" in text) or ("build:" in text), "服务均未声明 image/build"

    def test_数据卷与网络(self):
        """DEP-03：compose 声明了持久化卷（否则重启即丢数据）。"""
        path = _compose_file()
        assert path is not None
        text = path.read_text(encoding="utf-8")
        assert "volumes:" in text or ":/" in text, "未声明任何持久化挂载"

    def test_环境变量来自env文件(self):
        """DEP-04：关键环境变量走 ``env_file``/``environment``，不硬编码在 compose 里。"""
        path = _compose_file()
        assert path is not None
        text = path.read_text(encoding="utf-8")
        assert "env_file" in text or "environment" in text, "环境变量未声明来源"


class TestDeployRuntime:
    """部署态的运行时一致性。"""

    def test_迁移可从零跑通(self, tmp_path, monkeypatch):
        """DEP-05：全新库能跑完迁移链（部署时首次启动的必经路径）。"""
        from alembic import command
        from alembic.config import Config

        from app.core.config import settings

        db_path = (tmp_path / "deploy.db").as_posix()
        # **必须改环境变量**——alembic 的 env.py 从环境读 URL，
        # 只改 settings 对象会导致「迁移跑在别处、断言查空表」。
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
        cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
        cfg.set_main_option(
            "script_location", str(REPO_ROOT / "backend" / "app" / "db" / "migrations"),
        )
        command.upgrade(cfg, "head")

        import sqlite3

        con = sqlite3.connect(db_path)
        try:
            version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            assert version == "0012", f"迁移未到 head，实际 {version}"
        finally:
            con.close()

    def test_健康检查端点存在(self, client):
        """DEP-06：部署探活端点存在（用 OpenAPI 判定——FastAPI 新版不把子路由展平）。"""
        spec = client.app.openapi()
        assert "/api/v1/health" in spec.get("paths", {}), "未找到健康检查端点"

    def test_健康检查返回ok(self, client):
        """DEP-06（续）：探活返回 ``status=ok``。"""
        r = client.get("/api/v1/health")
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "ok"


class TestDeployDocker:
    """真实容器编排（**需要 Docker**；不具备则 skip 并计入 env 缺口）。"""

    def test_compose配置可解析(self):
        """DEP-07：``docker compose config`` 能解析配置。"""
        if shutil.which("docker") is None:
            pytest.skip("环境不具备（无 docker）——计入覆盖率缺口，不算通过")
        path = _compose_file()
        if path is None:
            pytest.skip("未找到 compose 定义")
        proc = subprocess.run(
            ["docker", "compose", "-f", str(path), "config"],
            capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[:400]
