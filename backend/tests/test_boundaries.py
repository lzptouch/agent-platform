"""执行边界与上传限制测试（批次 01 / WP-1 + WP-2）。

覆盖计划要求的四类场景：

1. 超大文件上传 → 413；
2. 禁止类型上传 → 4xx + 原因；
3. 子进程逃逸工作目录 → **启动前**拒绝；
4. 子进程死循环 → 被时间/资源上限终止（用例自带超时保护）。

另含：输出上限、网络出口开关、审计留痕、白名单语义。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.uploads import (
    ALLOWED_EXTENSIONS,
    DENIED_EXTENSIONS,
    check_extension,
    check_mime,
    check_upload,
    format_bytes,
)
from app.main import app
from app.services.exec.limits import (
    ExecLimits,
    detect_escape,
    detect_network_usage,
    run_with_limits,
)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        c.get("/api/v1/health")  # 触发初始化
        yield c


# --------------------------------------------------------------------------- #
# WP-2：上传限制
# --------------------------------------------------------------------------- #
class TestUploadLimits:
    def test_普通文件可上传(self, client):
        r = client.post(
            "/api/v1/files/upload",
            files={"file": ("probe.txt", b"hello boundary", "text/plain")},
        )
        assert r.status_code in (200, 201), r.text
        assert r.json()["size"] == len(b"hello boundary")
        client.delete("/api/v1/files/probe.txt")

    def test_超大文件返回413(self, client, monkeypatch):
        monkeypatch.setattr(settings, "upload_max_file_bytes", 1024)
        payload = b"x" * (1024 * 64)
        r = client.post(
            "/api/v1/files/upload",
            files={"file": ("big.txt", payload, "text/plain")},
        )
        assert r.status_code == 413, r.text
        body = r.json()
        assert body.get("code"), body  # 统一错误体
        assert body.get("request_id"), body
        assert "上限" in (body.get("message") or body.get("detail") or "")

    def test_超限后不留半成品文件(self, client, monkeypatch):
        monkeypatch.setattr(settings, "upload_max_file_bytes", 1024)
        client.post(
            "/api/v1/files/upload",
            files={"file": ("big2.txt", b"y" * (1024 * 64), "text/plain")},
        )
        listed = client.get("/api/v1/files").json()
        names = [f["name"] for f in listed["files"]]
        assert "big2.txt" not in names, names

    def test_可执行文件被拒(self, client):
        r = client.post(
            "/api/v1/files/upload",
            files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
        )
        assert r.status_code in (400, 413, 415, 422), r.status_code
        body = r.json()
        reason = body.get("message") or body.get("detail") or ""
        assert "禁止上传" in reason or "白名单" in reason, body
        listed = client.get("/api/v1/files").json()
        assert "evil.exe" not in [f["name"] for f in listed["files"]]

    def test_声明为可执行的MIME被拒(self, client):
        r = client.post(
            "/api/v1/files/upload",
            files={"file": ("payload.txt", b"data", "application/x-msdownload")},
        )
        assert r.status_code in (400, 413, 415, 422), r.status_code

    def test_白名单外类型被拒(self, client):
        r = client.post(
            "/api/v1/files/upload",
            files={"file": ("data.bin", b"\x00\x01", "application/octet-stream")},
        )
        assert r.status_code in (400, 413, 415, 422), r.status_code

    def test_白名单语义(self):
        assert check_extension("a.png") is None
        assert check_extension("a.PY") is None
        assert "禁止上传" in (check_extension("a.exe") or "")
        assert check_extension("a.bin") is not None  # .bin 属禁止清单
        assert check_extension("a.zip") is not None  # 不在白名单
        assert check_extension("noext") is not None
        assert check_mime("text/plain") is None
        assert "禁止上传" in (check_mime("application/x-msdownload") or "")
        assert check_mime(None) is None  # 未声明 MIME 时不判定
        assert check_upload("a.txt", "text/plain") is None
        # 禁止清单与白名单不得重叠
        assert not (DENIED_EXTENSIONS & ALLOWED_EXTENSIONS)

    def test_字节格式化可读(self):
        assert format_bytes(512) == "512 B"
        assert format_bytes(2048) == "2 KB"
        assert format_bytes(3 * 1024 * 1024) == "3 MB"


# --------------------------------------------------------------------------- #
# WP-1：执行边界
# --------------------------------------------------------------------------- #
class TestEscapeDetection:
    def test_检出向上逃逸(self, tmp_path):
        assert detect_escape("cat ../../etc/passwd", tmp_path)
        assert detect_escape("python ../outside.py", tmp_path)
        assert detect_escape("type ..\\..\\windows\\system32", tmp_path)

    def test_工作区内路径放行(self, tmp_path):
        assert detect_escape("cat data.txt", tmp_path) is None
        assert detect_escape("cat sub/dir/file.txt", tmp_path) is None
        assert detect_escape("cat ./a/../b.txt", tmp_path) is None

    def test_网络形态检出(self):
        assert detect_network_usage("requests.get('http://x')")
        assert detect_network_usage("curl http://example.com")
        assert detect_network_usage("wget http://example.com")
        assert detect_network_usage("import urllib.request")
        assert detect_network_usage("import requests")
        assert detect_network_usage("echo hello") is None
        assert detect_network_usage("print('requests')") is None


class TestExecutorBoundaries:
    """直接测 ``LocalCodeExecutor`` 的执行边界（不经过 LLM）。"""

    @pytest.fixture()
    def executor(self, tmp_path, monkeypatch):
        from app.services.code_executor import LocalCodeExecutor

        monkeypatch.setattr(type(settings), "output_dir", property(lambda self: tmp_path))
        monkeypatch.setattr(
            "app.core.workspace.get_workspace_dir", lambda: tmp_path
        )
        return LocalCodeExecutor(output_dir=tmp_path, timeout=5)

    def test_逃逸路径在启动前被拒(self, executor):
        result = executor.execute_bash("cat ../../etc/passwd")
        assert result["return_code"] == 1
        assert "逃出工作目录" in result["stderr"], result
        assert result.get("limit_hit") == "preflight"

    def test_联网调用在启动前被拒(self, executor):
        result = executor.execute_bash("curl http://example.com")
        assert result["return_code"] == 1
        assert "联网" in result["stderr"], result
        assert result.get("limit_hit") == "preflight"

    def test_网络开关打开后放行(self, executor, monkeypatch):
        monkeypatch.setattr(settings, "exec_network_enabled", True)
        result = executor.execute_bash("echo no-network-here")
        assert result["return_code"] == 0, result
        assert "联网" not in result["stderr"]

    def test_正常命令可执行(self, executor):
        result = executor.execute_python("print('boundary-ok')")
        assert result["return_code"] == 0, result
        assert "boundary-ok" in result["stdout"]

    def test_死循环被时间上限终止(self, executor, tmp_path):
        """死循环必须被终止（POSIX 走 CPU 上限，Windows 走墙钟超时）。

        用「先落标记文件再死循环」确认子进程**确实启动过**——否则
        「进程没起来」会被误判成「被上限终止」。
        """
        marker = tmp_path / "started.marker"
        code = f"open({str(marker)!r}, 'w').write('x')\nwhile True:\n    pass"
        started = time.monotonic()
        result = executor.execute_python(code)
        elapsed = time.monotonic() - started
        assert marker.exists(), f"子进程未真正启动，判定无效: {result}"
        assert result["return_code"] != 0, result
        assert result.get("limit_hit") in {"cpu", "timeout"}, result
        assert elapsed < 30, f"终止耗时过长: {elapsed:.1f}s"

    def test_输出超量被终止(self, executor):
        result = executor.execute_python("print('x' * 500000)")
        assert result.get("limit_hit") == "output", result
        assert len(result["stdout"]) <= 64 * 1024

    def test_审计留痕(self, executor, monkeypatch, tmp_path):
        """被拒的执行要写审计（可按 run 还原）。"""
        from app.services.security import audit

        monkeypatch.setattr(audit, "audit_path", lambda workspace=None: tmp_path / "audit.jsonl")
        executor.execute_bash("cat ../../etc/passwd")
        text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "execute_bash" in text, text
        assert "逃出工作目录" in text, text


class TestRunWithLimits:
    """``run_with_limits`` 的平台无关语义。"""

    def test_正常执行返回输出(self, tmp_path):
        limits = ExecLimits(timeout=30, max_output_bytes=64 * 1024)
        result = run_with_limits(
            [sys.executable, "-c", "print('hello-limits')"], cwd=tmp_path, limits=limits
        )
        assert result.return_code == 0
        assert "hello-limits" in result.stdout
        assert result.limit_hit == ""

    def test_超时被杀(self, tmp_path):
        limits = ExecLimits(timeout=3, max_output_bytes=64 * 1024)
        started = time.monotonic()
        result = run_with_limits(
            [sys.executable, "-c", "while True: pass"], cwd=tmp_path, limits=limits
        )
        assert time.monotonic() - started < 20
        assert result.return_code != 0
        assert result.limit_hit == "timeout"

    def test_输出上限截断(self, tmp_path):
        limits = ExecLimits(timeout=30, max_output_bytes=1024)
        result = run_with_limits(
            [sys.executable, "-c", "print('a' * 100000)"], cwd=tmp_path, limits=limits
        )
        assert result.limit_hit == "output"
        assert result.truncated
        assert len(result.stdout) <= 1024
