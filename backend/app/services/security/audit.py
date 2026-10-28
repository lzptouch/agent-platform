"""JSONL 审计（S2 / WP-2.7）。

每次受控动作追加一行到工作区内的审计日志，便于按 run 还原动作序列。
写失败**不阻断**主流程（仅记告警）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.workspace import get_workspace_dir

logger = logging.getLogger(__name__)


def audit_path(workspace: Path | None = None) -> Path:
    """审计日志路径：``{workspace}/.workbuddy/audit/``（本仓库落地到 ``{workspace}/.agent/audit/``）。"""
    root = workspace or get_workspace_dir()
    d = root / ".agent" / "audit"
    d.mkdir(parents=True, exist_ok=True)
    return d / "audit.jsonl"


def record(
    *,
    run_id: str | None,
    tool: str,
    decision: str,
    reason: str,
    target: str,
    request: dict[str, Any] | None = None,
    matched_rule_id: int | None = None,
    latency_ms: int = 0,
) -> None:
    """追加一条审计记录。"""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "tool": tool,
        "decision": decision,
        "reason": reason,
        "target": target,
        "matched_rule_id": matched_rule_id,
        "latency_ms": latency_ms,
        "request": request or {},
    }
    try:
        with audit_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("审计写入失败（不影响主流程）: %s", exc)


def read_for_run(run_id: str) -> list[dict]:
    """读取某次 run 的全部审计记录（按时间序）。"""
    path = audit_path()
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("run_id") == run_id:
                out.append(entry)
    except OSError as exc:
        logger.warning("审计读取失败: %s", exc)
    return out
