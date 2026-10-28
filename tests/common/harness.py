"""端到端测试公共骨架。

按 `c:\\workspace\\practice\\测试计划.md`【全局头部固定规则】实现：
- 统一输出顺序由报告生成器保证（概要 → 用例表 → 脚本 → 报告模板）；
- 显式等待 / 页面就绪判断，禁止大量强制 sleep；
- 关键步骤与断言失败必截图，失败自动保存 trace；
- 缺陷分类：业务 Bug / 元素识别不稳定（脚本问题）/ 环境问题，按 P0~P3 分级；
- 用例数据隔离在独立临时目录，不触碰生产数据。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
REPORT_DIR = REPO_ROOT / "tests" / "report"
WORK_DIR = REPO_ROOT / "tests" / ".work"


# --------------------------------------------------------------------------- #
# 用例结果与缺陷分类
# --------------------------------------------------------------------------- #
CATEGORY_BUSINESS = "业务Bug"
CATEGORY_SCRIPT = "元素/控件识别不稳定"
CATEGORY_ENV = "环境问题"

LEVELS = ("P0", "P1", "P2", "P3")


@dataclass
class CaseResult:
    case_id: str
    title: str
    layer: str
    status: str = "PASS"  # PASS / FAIL / SKIP
    category: str = ""
    level: str = "P2"
    detail: str = ""
    evidence: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def as_row(self) -> str:
        evidence = "<br>".join(self.evidence) if self.evidence else "-"
        return (
            f"| {self.case_id} | {self.title} | {self.layer} | {self.status} | "
            f"{self.category or '-'} | {self.level} | {self.detail or '-'} | {evidence} |"
        )


class Suite:
    """用例收集器。"""

    def __init__(self, name: str, target: str) -> None:
        self.name = name
        self.target = target
        self.results: list[CaseResult] = []
        self.started = datetime.now(timezone.utc)

    def record(self, result: CaseResult) -> CaseResult:
        self.results.append(result)
        status = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}[result.status]
        print(
            f"[{status}] {result.case_id} {result.title}"
            + (f" — {result.detail}" if result.detail else ""),
            flush=True,
        )
        return result

    def ok(self, case_id: str, title: str, layer: str, detail: str = "") -> CaseResult:
        return self.record(CaseResult(case_id, title, layer, "PASS", "", "P3", detail))

    def fail(
        self,
        case_id: str,
        title: str,
        layer: str,
        detail: str,
        category: str = CATEGORY_BUSINESS,
        level: str = "P1",
        evidence: list[str] | None = None,
    ) -> CaseResult:
        return self.record(
            CaseResult(case_id, title, layer, "FAIL", category, level, detail, evidence or [])
        )

    def skip(
        self,
        case_id: str,
        title: str,
        layer: str,
        detail: str,
        level: str = "P3",
    ) -> CaseResult:
        return self.record(CaseResult(case_id, title, layer, "SKIP", CATEGORY_ENV, level, detail))

    # ------------------------------------------------------------------ #
    # 报告
    # ------------------------------------------------------------------ #
    def summary(self) -> dict[str, int]:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == "PASS")
        failed = sum(1 for r in self.results if r.status == "FAIL")
        skipped = sum(1 for r in self.results if r.status == "SKIP")
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "business": sum(1 for r in self.results if r.category == CATEGORY_BUSINESS),
            "script": sum(1 for r in self.results if r.category == CATEGORY_SCRIPT),
            "env": sum(1 for r in self.results if r.category == CATEGORY_ENV),
        }

    def write_report(self, extra_notes: list[str] | None = None) -> Path:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = REPORT_DIR / f"report-{self.name}-{stamp}.md"
        s = self.summary()
        lines = [
            f"# 测试报告 · {self.name}",
            "",
            f"> 被测对象：{self.target}",
            f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
            f"> 报告格式：全局头部固定规则（概要 → 用例表 → 脚本 → 报告模板）",
            "",
            "## 一、测试概要",
            "",
            "| 指标 | 值 |",
            "| --- | --- |",
            f"| 用例总数 | {s['total']} |",
            f"| 成功 | {s['passed']} |",
            f"| 失败 | {s['failed']} |",
            f"| 跳过（环境不具备） | {s['skipped']} |",
            f"| 业务 Bug | {s['business']} |",
            f"| 元素/控件识别不稳定 | {s['script']} |",
            f"| 环境问题 | {s['env']} |",
            "",
            "## 二、测试用例表",
            "",
            "| 编号 | 用例 | 层次 | 结果 | 分类 | 级别 | 说明 | 证据 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines += [r.as_row() for r in self.results]
        lines += ["", "## 三、脚本与运行方式", "", "```bash", "# 本套件（Web / 桌面端）", "", "# 后端 pytest（单元 + 集成）", "cd backend && .venv/Scripts/python.exe -m pytest tests/ -q", "",
                  "# 桌面壳单测", "cd frontend/desktop && npm test", "", "# 前端单测", "cd frontend/web/vue-element-plus && npm test", "",
                  "# 本套件（需要 Playwright chromium）", "backend/.venv/Scripts/python.exe -m pytest tests/ -q", "```", ""]
        lines += ["## 四、缺陷清单", ""]
        defects = [r for r in self.results if r.status == "FAIL"]
        if defects:
            for d in defects:
                lines.append(f"- **{d.case_id} {d.title}**（{d.category} / {d.level}）：{d.detail}")
                for e in d.evidence:
                    lines.append(f"  - 证据：{e}")
        else:
            lines.append("本轮无失败用例。")
        if extra_notes:
            lines += ["", "## 五、备注", ""] + [f"- {n}" for n in extra_notes]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


# --------------------------------------------------------------------------- #
# 后端进程编排
# --------------------------------------------------------------------------- #
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def python_exe() -> str:
    for rel in ("Scripts/python.exe", "bin/python"):
        p = BACKEND_DIR / ".venv" / rel
        if p.exists():
            return str(p)
    return sys.executable


class BackendProcess:
    """启动后端并等待就绪（显式等待，不用 sleep 轮询式盲等）。"""

    def __init__(self, port: int | None = None) -> None:
        self.port = port or free_port()
        self.proc: subprocess.Popen | None = None
        # 后端 stdout 必须**持续抽干**：管道缓冲写满后后端会阻塞在 write 上，
        # 表现为「跑到一半所有接口超时」（批次 03 落盘日志上线后暴露）。
        self._output_tail: deque[str] = deque(maxlen=300)
        self._reader: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _drain_stdout(self) -> None:
        """持续读取后端输出（只保留尾部若干行，供失败时展示）。"""
        stream = self.proc.stdout if self.proc else None
        if stream is None:
            return
        try:
            for raw in iter(stream.readline, b""):
                self._output_tail.append(raw.decode("utf-8", "replace"))
        except (ValueError, OSError):
            pass

    def output_tail(self, lines: int = 30) -> str:
        return "".join(list(self._output_tail)[-lines:])

    def start(self, timeout: float = 90.0) -> tuple[bool, str]:
        env = dict(os.environ)
        env["AGENT_DESKTOP"] = "0"
        # e2e 环境把单文件上传上限调到 1MB（默认值 50MB 由后端单测冻结），
        # 避免为了验证 413 而真的传输 50MB。
        env.setdefault("UPLOAD_MAX_FILE_BYTES", str(1024 * 1024))
        env.setdefault("UPLOAD_MAX_REQUEST_BYTES", str(2 * 1024 * 1024))
        self.proc = subprocess.Popen(
            [
                python_exe(),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        # 后台抽干 stdout（否则管道写满 → 后端阻塞 → 接口大面积超时）
        self._reader = threading.Thread(target=self._drain_stdout, daemon=True)
        self._reader.start()
        deadline = time.monotonic() + timeout
        import urllib.error
        import urllib.request

        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                time.sleep(0.2)  # 等抽干线程把尾部读完
                return False, f"后端进程提前退出：\n{self.output_tail()}"
            try:
                with urllib.request.urlopen(f"{self.base_url}/api/v1/health", timeout=2) as resp:
                    if resp.status == 200:
                        return True, "后端就绪"
            except (urllib.error.URLError, OSError):
                time.sleep(0.4)
        return False, f"后端 {timeout}s 内未就绪"

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc and self.proc.stdout:
            self.proc.stdout.close()


# --------------------------------------------------------------------------- #
# 截图 / 录屏 / 临时目录
# --------------------------------------------------------------------------- #
def work_dir(name: str) -> Path:
    p = WORK_DIR / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def shot(page: Any, name: str) -> str:
    """关键步骤与断言失败截图。"""
    out = REPORT_DIR / "shots"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        return str(path.relative_to(REPO_ROOT))
    except Exception as exc:  # 截图失败不掩盖主断言
        return f"截图失败: {exc}"


def dump_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)[:2000]
