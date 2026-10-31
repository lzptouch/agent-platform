"""P5 批次验收测试（结果可消费 + 门禁体系）。

覆盖 P5-01 ~ P5-06 的验收断言。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
PYTHON = BACKEND_ROOT / ".venv" / "bin" / "python"


def _run(cmd: list[str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=900)


# --------------------------------------------------------------------------- #
# P5-01 · report.json 产出器
# --------------------------------------------------------------------------- #
class TestReportProducer:
    """``report.json`` + ``index.md`` + ``junit.xml`` + ``classify.json`` 四件套。"""

    def test_报告库存在(self, client):
        assert (REPO_ROOT / "tests" / "common" / "report.py").exists()

    def test_产出器可运行(self, client, tmp_path):
        """跑一轮后：report.json 存在且 summary **自洽**。"""
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from common.report import LayerResult, build_report, write_report

        layer = LayerResult(
            id="demo", title="演示层", command=["true"], exit_code=0,
            total=3, passed=2, failed=1, duration_ms=12,
            failed_cases=[{
                "id": "DEMO-01", "title": "演示失败", "errorCode": "E_AUTH",
                "message": "401 未授权", "firstFailingStep": "auth",
                "evidence": ["logs/demo.log"], "suspect": "backend",
            }],
        )
        report = build_report([layer])
        assert report["summary"]["total"] == sum(l["total"] for l in report["layers"])
        assert report["summary"]["failed"] == sum(l["failed"] for l in report["layers"])
        assert report["env"]["frontendDistHash"], "frontendDistHash 必须存在（防旧 dist 幻觉）"

        out = write_report(report, tmp_path / "run")
        assert (out / "report.json").is_file()
        assert (out / "index.md").is_file()
        assert (out / "junit.xml").is_file()
        data = json.loads((out / "report.json").read_text(encoding="utf-8"))
        assert data["cases"][0]["errorCode"] == "E_AUTH"
        assert data["cases"][0]["evidence"], "失败用例必须有非空 evidence"
        assert data["cases"][0]["suspect"], "失败用例必须有 suspect"

    def test_失败用例在index里可查(self, client, tmp_path):
        """``index.md`` 能列出失败用例的 firstFailingStep 与 evidence。"""
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from common.report import LayerResult, build_report, write_report

        layer = LayerResult(
            id="demo2", title="演示层2", command=["true"], exit_code=1,
            total=1, passed=0, failed=1, duration_ms=5,
            failed_cases=[{
                "id": "DEMO-02", "errorCode": "E_SSE_NO_FIRST_BYTE",
                "message": "SSE 无首字节", "firstFailingStep": "sse",
                "evidence": ["logs/sse.log"], "suspect": "frontend",
            }],
        )
        out = write_report(build_report([layer]), tmp_path / "run2")
        index = (out / "index.md").read_text(encoding="utf-8")
        assert "DEMO-02" in index
        assert "sse" in index
        assert "logs/sse.log" in index


# --------------------------------------------------------------------------- #
# P5-02 · 失败自动归类器
# --------------------------------------------------------------------------- #
class TestClassifier:
    """按错误码表把失败用例归到 7 类之一。"""

    def test_分类器存在(self, client):
        assert (REPO_ROOT / "tests" / "common" / "classify.py").exists()

    def test_三类失败正确归类(self, client):
        """验收断言①：故意制造 3 类失败 → 归类正确。"""
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from common.classify import classify_case

        assert classify_case({"errorCode": "E_ENV_MISSING"}) == "env"
        assert classify_case({"errorCode": "E_DIST_STALE"}) == "stale_artifact"
        assert classify_case({"errorCode": "E_ARTIFACT_MISSING"}, runtime="packaged") == "packaging"
        assert classify_case({"errorCode": "E_SSE_NO_FIRST_BYTE"}) == "frontend"
        assert classify_case({"errorCode": "E_PERM_BYPASS"}) == "backend"

    def test_未知错误归入断言不符(self, client):
        """验收断言②：未知错误归 ``E_ASSERT_MISMATCH`` 而非丢弃。"""
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from common.classify import build_classify, classify_case, infer_error_code

        case = {"id": "X-01", "message": "某种从未见过的奇怪失败"}
        assert infer_error_code(case) == "E_ASSERT_MISMATCH"
        assert classify_case(case) in {"backend", "test", "frontend", "shell"}
        out = build_classify([case])
        assert out["total"] == 1
        assert sum(v["count"] for v in out["classes"].values()) == 1, "失败用例被丢弃了"

    def test_归类输出结构(self, client):
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from common.classify import CLASS_ORDER, build_classify

        out = build_classify([{"id": "A", "errorCode": "E_AUTH"}])
        assert set(out["classes"]) == set(CLASS_ORDER)
        for name, bucket in out["classes"].items():
            assert "count" in bucket and "disposition" in bucket


# --------------------------------------------------------------------------- #
# P5-03 · 分层 marker 体系
# --------------------------------------------------------------------------- #
class TestMarkers:
    """5 个 marker；``-m unit`` 只跑单元；无未打标用例。"""

    def test_五层marker已声明(self, client):
        import tomllib

        cfg = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        markers = cfg["tool"]["pytest"]["ini_options"]["markers"]
        for m in ("unit", "integration", "e2e", "slow", "real_llm"):
            assert any(m in x for x in markers), f"缺 marker: {m}"

    def test_tests侧marker同源(self, client):
        text = (REPO_ROOT / "tests" / "pytest.ini").read_text(encoding="utf-8")
        for m in ("unit", "integration", "e2e", "slow", "real_llm"):
            assert f"{m}:" in text, f"tests/pytest.ini 缺 marker: {m}"

    def test_unit子集不含e2e(self, client):
        """验收断言①：``-m unit`` 只跑单元测试。"""
        proc = _run([str(PYTHON), "-m", "pytest", "tests", "-q", "-m", "unit"], cwd=BACKEND_ROOT)
        assert proc.returncode == 0, proc.stdout[-800:]
        assert "passed" in proc.stdout

    def test_real_llm子集可单独选(self, client):
        """验收断言②：``-m real_llm`` 只选真 LLM 用例。"""
        proc = _run([str(PYTHON), "-m", "pytest", "tests", "-q", "-m", "real_llm"], cwd=BACKEND_ROOT)
        assert proc.returncode == 0, proc.stdout[-800:]

    def test_无未打标用例(self, client):
        """验收断言③：无未打标用例。"""
        proc = _run([
            str(PYTHON), "-m", "pytest", "tests", "--collect-only", "-q",
            "-m", "not unit and not integration and not e2e and not slow and not real_llm",
        ], cwd=BACKEND_ROOT)
        assert "no tests collected" in proc.stdout, proc.stdout[-500:]


# --------------------------------------------------------------------------- #
# P5-04 · CI 流水线
# --------------------------------------------------------------------------- #
class TestCiWorkflow:
    """7 个 job；L0~L3 阻断合并。"""

    def test_workflow存在(self, client):
        assert (REPO_ROOT / ".github" / "workflows" / "ci.yml").exists()

    def test_七层job齐备(self, client):
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for job in ("contract", "backend", "web-e2e", "desktop-e2e", "package", "release", "nightly"):
            assert f"  {job}:" in text, f"缺 job: {job}"

    def test_分层阻断策略(self, client):
        """L0~L3 阻断合并；L4 阻塞阶段出口；L5 阻塞发布。"""
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "needs: [contract, backend, web-e2e, desktop-e2e]" in text, "L4 未依赖 L0~L3"
        assert "needs: [package]" in text, "L5 未依赖 L4"
        assert "if: startsWith(github.ref, 'refs/tags/v')" in text, "L5 未限定发布标签"

    def test_ci跑门禁脚本(self, client):
        text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        for script in ("check_doc_consistency.py", "check_doc_numbers.py", "check_traceability.py"):
            assert script in text, f"CI 未跑 {script}"


# --------------------------------------------------------------------------- #
# P5-05 / P5-06 · 门禁脚本
# --------------------------------------------------------------------------- #
class TestGateScripts:
    """文档数字门禁 + 需求追溯门禁。"""

    def test_脚本存在(self, client):
        assert (REPO_ROOT / "scripts" / "check_doc_numbers.py").exists()
        assert (REPO_ROOT / "scripts" / "check_traceability.py").exists()

    def test_数字门禁当前通过(self, client):
        """验收断言②：当前仓库状态下脚本**通过**。"""
        proc = _run([str(PYTHON), str(REPO_ROOT / "scripts" / "check_doc_numbers.py")])
        assert proc.returncode == 0, proc.stdout[-1200:]

    def test_追溯门禁当前通过(self, client):
        """验收断言②：追溯覆盖率 100%。"""
        proc = _run([str(PYTHON), str(REPO_ROOT / "scripts" / "check_traceability.py")])
        assert proc.returncode == 0, proc.stdout[-1200:]

    def test_追溯表已生成(self, client):
        path = REPO_ROOT / "doc" / "traceability.md"
        assert path.exists(), "追溯表未生成"
        text = path.read_text(encoding="utf-8")
        assert "F-SEC-01" in text and "F-ENG-13" in text
        assert "自动生成" in text
