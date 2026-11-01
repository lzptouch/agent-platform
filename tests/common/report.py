"""测试结果汇总与产出（P5-01 · `tests/docs/testing/00` §5.2）。

产出三件套：

- ``report.json`` —— 机器可读总纲（schema 见 §5.2；``env.frontendDistHash`` **必填**）
- ``index.md`` —— 人读摘要（失败用例列出 ``firstFailingStep`` 与 ``evidence[]``）
- ``junit.xml`` —— 供 CI 消费

**自洽性硬要求**（P5-01 验收断言①②）：

- ``summary.total == sum(layers[*].total)``
- ``summary.failed == sum(layers[*].failed)``
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from .classify import build_classify, dist_is_stale, infer_error_code

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


@dataclass
class LayerResult:
    """一层的执行结果。"""

    id: str
    title: str
    command: list[str]
    exit_code: int
    total: int
    passed: int
    failed: int
    skipped: int = 0
    duration_ms: int = 0
    runtime: str = "web"
    failed_cases: list[dict[str, Any]] = field(default_factory=list)
    stdout_tail: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "command": " ".join(self.command),
            "exitCode": self.exit_code,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "durationMs": self.duration_ms,
            "runtime": self.runtime,
            "failedCaseIds": [c.get("id") for c in self.failed_cases],
            "stdout_tail": list(self.stdout_tail),
        }


def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=20,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def build_env(*, runtime: str = "web") -> dict[str, Any]:
    """环境信息（``frontendDistHash`` **必填**——防旧 dist 幻觉）。"""
    dirty = bool(_git("status", "--porcelain"))
    return {
        "platform": platform.platform(),
        "arch": platform.machine(),
        "osVersion": platform.release(),
        "python": sys.version.split()[0],
        "node": _node_version(),
        "electron": _electron_version(),
        "gitCommit": _git("rev-parse", "--short", "HEAD"),
        "dirty": dirty,
        "frontendDistHash": sha256_file(FRONTEND_DIST / "index.html"),
        "artifact": None,
        "artifactSha256": None,
        "artifactSizeMb": None,
        "ports": {"backend": None, "cdn": None},
        "runtime": runtime,
    }


def _node_version() -> str:
    try:
        return subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _electron_version() -> str:
    pkg = REPO_ROOT / "frontend" / "desktop" / "package.json"
    try:
        meta = json.loads(pkg.read_text(encoding="utf-8"))
        return str(meta.get("devDependencies", {}).get("electron", ""))
    except Exception:  # noqa: BLE001
        return ""


def summarize(layers: Iterable[LayerResult]) -> dict[str, Any]:
    """汇总各层（**total / failed 必须等于各层之和**——P5-01 验收断言①②）。"""
    layers = list(layers)
    total = sum(l.total for l in layers)
    passed = sum(l.passed for l in layers)
    failed = sum(l.failed for l in layers)
    skipped = sum(l.skipped for l in layers)
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "flaky": 0,
        "durationMs": sum(l.duration_ms for l in layers),
        "skippedDetail": {"unknown": skipped} if skipped else {},
    }


def build_report(
    layers: list[LayerResult],
    *,
    run_id: str | None = None,
    runtime: str = "web",
    started_at: str | None = None,
) -> dict[str, Any]:
    """组装 ``report.json``。"""
    summary = summarize(layers)
    cases: list[dict[str, Any]] = []
    for layer in layers:
        for case in layer.failed_cases:
            case = dict(case)
            case.setdefault("errorCode", infer_error_code(case))
            case.setdefault("evidence", [])
            case.setdefault("firstFailingStep", "assert")
            case.setdefault("suspect", "unknown")
            case["domain"] = layer.id
            case["host"] = layer.runtime
            case["priority"] = case.get("priority", "P0")
            cases.append(case)

    now = datetime.now(timezone.utc)
    return {
        "runId": run_id or now.strftime("%Y%m%dT%H%M%SZ"),
        "host": "desktop-sidecar" if runtime.startswith("desktop") else "web",
        "runtime": runtime,
        "startedAt": started_at or now.isoformat(),
        "durationMs": summary["durationMs"],
        "env": build_env(runtime=runtime),
        "summary": summary,
        "layers": [l.as_dict() for l in layers],
        "cases": cases,
    }


def write_index_md(report: dict[str, Any]) -> str:
    """人读摘要（失败用例列出 ``firstFailingStep`` 与 ``evidence[]``）。"""
    lines = [
        f"# 测试报告 {report['runId']}",
        "",
        f"- 运行时：`{report['runtime']}`",
        f"- 提交：`{report['env']['gitCommit']}`（dirty={report['env']['dirty']}）",
        f"- 前端产物指纹：`{report['env']['frontendDistHash'][:23]}`",
        f"- 合计：**{report['summary']['total']}**"
        f"（passed {report['summary']['passed']} / failed {report['summary']['failed']}"
        f" / skipped {report['summary']['skipped']}）",
        "",
        "| 层 | 通过 | 失败 | 跳过 | 耗时 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for layer in report["layers"]:
        lines.append(
            f"| {layer['title']} | {layer['passed']} | {layer['failed']} | "
            f"{layer['skipped']} | {layer['durationMs']}ms |"
        )
    if report["cases"]:
        lines += [
            "",
            "## 失败用例",
            "",
            "| 用例 | 错误码 | 首查步骤 | 责任层 | 证据 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for case in report["cases"]:
            evidence = "<br>".join(str(e) for e in case.get("evidence") or []) or "—"
            lines.append(
                f"| {case.get('id')} | `{case.get('errorCode')}` | {case.get('firstFailingStep')} "
                f"| {case.get('suspect')} | {evidence} |"
            )
    return "\n".join(lines) + "\n"


def write_junit_xml(report: dict[str, Any]) -> str:
    """JUnit XML（供 CI 消费）。"""
    suite = ET.Element("testsuite", {
        "name": f"agent-{report['runId']}",
        "tests": str(report["summary"]["total"]),
        "failures": str(report["summary"]["failed"]),
        "skipped": str(report["summary"]["skipped"]),
        "time": str(round(report["summary"]["durationMs"] / 1000, 3)),
    })
    for layer in report["layers"]:
        case = ET.SubElement(suite, "testcase", {
            "classname": layer["id"], "name": layer["title"],
            "time": str(round(layer["durationMs"] / 1000, 3)),
        })
        if layer["failed"]:
            failure = ET.SubElement(case, "failure", {
                "message": f"{len(layer['failedCaseIds'])} 个用例失败",
                "type": "E_TEST_FAILED",
            })
            failure.text = "\n".join((layer.get("stdout_tail") or [])[-20:])
    return ET.tostring(suite, encoding="unicode", xml_declaration=True)


def write_report(
    report: dict[str, Any],
    out_dir: Path,
    *,
    classify: dict[str, Any] | None = None,
) -> Path:
    """把三件套写进 ``out_dir``（自包含目录）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (out_dir / "index.md").write_text(write_index_md(report), encoding="utf-8")
    (out_dir / "junit.xml").write_text(write_junit_xml(report), encoding="utf-8")
    if classify is not None:
        (out_dir / "classify.json").write_text(
            json.dumps(classify, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    return out_dir


def build_classify_for(report: dict[str, Any]) -> dict[str, Any]:
    """按报告内容归类失败用例（``stale_artifact`` 判据用真实 mtime 比较）。"""
    return build_classify(
        report.get("cases") or [],
        runtime=str(report.get("runtime") or "web"),
        source_newer_than_dist=dist_is_stale(REPO_ROOT),
    )


def archive_legacy_reports(repo_root: Path = REPO_ROOT) -> int:
    """把旧的裸 ``report-*.md`` 归档到 ``tests/report/archive/``（P5-01 ③）。"""
    report_dir = repo_root / "tests" / "report"
    if not report_dir.exists():
        return 0
    archive = report_dir / "archive"
    count = 0
    for path in report_dir.glob("report-*.md"):
        archive.mkdir(parents=True, exist_ok=True)
        path.rename(archive / path.name)
        count += 1
    return count


__all__ = [
    "LayerResult", "build_report", "write_report", "write_index_md",
    "write_junit_xml", "summarize", "build_env", "build_classify_for",
    "archive_legacy_reports", "sha256_file",
]
