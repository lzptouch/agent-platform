"""失败自动归类器（P5-02 · `tests/docs/testing/00` §6.2 / §6.3）。

把失败用例按「现象 → 首查证据 → 责任层」归类，产出 ``classify.json``：

| 归类 | 判据（按优先级） | 处置 |
| --- | --- | --- |
| ``env`` | ``E_ENV_MISSING``、端口耗尽、无显示、浏览器缺失 | 修环境；**同时登记为覆盖率缺口** |
| ``stale_artifact`` | ``E_DIST_STALE`` 或源码 mtime > dist mtime | 先重建再判定，禁止直接开缺陷 |
| ``packaging`` | ``runtime=packaged`` 失败，或 ``E_ARTIFACT_*``/``E_SIGNATURE_*`` | P0，阻塞发布 |
| ``shell`` | ``shell.log``/``sidecar.log`` 异常、状态机非法迁移 | 壳缺陷 |
| ``frontend`` | ``renderer.log`` 有 pageerror、``E_SSE_*`` 且后端正常 | 前端缺陷 |
| ``backend`` | 后端 5xx、``sse.jsonl`` 缺口、裁决链异常 | 后端缺陷 |
| ``test`` | 3 次重跑 ≥2 次通过 | flaky，修测试并登记 |

**未知错误归入 ``E_ASSERT_MISMATCH``**（业务缺陷）而不是丢弃。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 错误码表（§6.3）
ERROR_CODES: tuple[str, ...] = (
    "E_BACKEND_NOT_READY",
    "E_PACKAGED_BOOTSTRAP_FAILED",
    "E_AUTH",
    "E_SSE_NO_FIRST_BYTE",
    "E_SSE_SEQUENCE_GAP",
    "E_RUN_NOT_TERMINAL",
    "E_PERM_BYPASS",
    "E_SCHED_NOT_FIRED",
    "E_ARTIFACT_MISSING",
    "E_SIGNATURE_INVALID",
    "E_DIST_STALE",
    "E_ENV_MISSING",
    "E_ASSERT_MISMATCH",
)

#: 归类优先级（先命中先归）
CLASS_ORDER: tuple[str, ...] = (
    "env", "stale_artifact", "packaging", "shell", "frontend", "backend", "test",
)

#: 归类 → 处置说明
DISPOSITION: dict[str, str] = {
    "env": "修环境；同时登记为覆盖率缺口（不算通过）",
    "stale_artifact": "先重建 dist 再判定，禁止直接开缺陷",
    "packaging": "P0，阻塞发布",
    "shell": "壳缺陷（查 sidecar.log / 状态机）",
    "frontend": "前端缺陷（查 renderer.log / SSE 首字节）",
    "backend": "后端缺陷（查 5xx / sse.jsonl / 裁决链）",
    "test": "flaky：修测试并登记",
}

_ENV_RE = re.compile(r"port ?exhaust|端口耗尽|no ?display|无显示|browser not found|浏览器缺失", re.I)
_DIST_RE = re.compile(r"apps/ui/dist.*(陈旧|过期)|dist stale|E_DIST_STALE", re.I)


def infer_error_code(case: dict[str, Any]) -> str:
    """推断失败用例的错误码。

    优先用用例自带的 ``errorCode``；否则按消息特征匹配；**兜底 ``E_ASSERT_MISMATCH``**
    （业务缺陷）——不丢弃任何失败。
    """
    code = str(case.get("errorCode") or "").strip()
    if code in ERROR_CODES:
        return code
    if code:
        return code
    message = f"{case.get('message') or ''} {case.get('firstFailingStep') or ''}"
    if _ENV_RE.search(message):
        return "E_ENV_MISSING"
    if _DIST_RE.search(message):
        return "E_DIST_STALE"
    for known in ERROR_CODES:
        if known in message:
            return known
    if "401" in message or "403" in message or "E_AUTH" in message:
        return "E_AUTH"
    if "404" in message:
        return "E_ARTIFACT_MISSING"
    if "timeout" in message.lower() or "超时" in message:
        return "E_RUN_NOT_TERMINAL"
    return "E_ASSERT_MISMATCH"


def classify_case(
    case: dict[str, Any],
    *,
    runtime: str = "web",
    source_newer_than_dist: bool = False,
) -> str:
    """把一个失败用例归到 7 类之一。"""
    code = infer_error_code(case)

    if code == "E_ENV_MISSING":
        return "env"
    if code == "E_DIST_STALE" or source_newer_than_dist:
        return "stale_artifact"
    if runtime == "packaged" or code.startswith("E_ARTIFACT_") or code.startswith("E_SIGNATURE_") \
            or code == "E_PACKAGED_BOOTSTRAP_FAILED":
        return "packaging"
    if code in ("E_BACKEND_NOT_READY", "E_PERM_BYPASS"):
        return "shell" if runtime.startswith("desktop") else "backend"
    if code in ("E_SSE_NO_FIRST_BYTE", "E_SSE_SEQUENCE_GAP"):
        return "frontend"
    if code in ("E_RUN_NOT_TERMINAL", "E_SCHED_NOT_FIRED", "E_AUTH"):
        return "backend"
    # 3 次重跑 ≥2 次通过 → flaky
    attempts = int(case.get("attempts") or 1)
    if attempts >= 3 and case.get("flaky"):
        return "test"
    message = f"{case.get('message') or ''}"
    if "pageerror" in message or "白屏" in message:
        return "frontend"
    if "sidecar" in message or "shell" in message.lower():
        return "shell"
    return "backend"


def build_classify(
    cases: list[dict[str, Any]],
    *,
    runtime: str = "web",
    source_newer_than_dist: bool = False,
) -> dict[str, Any]:
    """产出 ``classify.json`` 的内容（按归类聚合）。"""
    buckets: dict[str, list[dict[str, Any]]] = {c: [] for c in CLASS_ORDER}
    for case in cases:
        cls = classify_case(
            case, runtime=runtime, source_newer_than_dist=source_newer_than_dist,
        )
        buckets[cls].append({
            "id": case.get("id"),
            "errorCode": infer_error_code(case),
            "message": (case.get("message") or "")[:300],
            "firstFailingStep": case.get("firstFailingStep"),
            "evidence": case.get("evidence") or [],
            "suspect": case.get("suspect"),
        })
    return {
        "runtime": runtime,
        "total": len(cases),
        "classes": {
            cls: {
                "count": len(items),
                "disposition": DISPOSITION[cls],
                "cases": items,
            }
            for cls, items in buckets.items()
        },
    }


def dist_is_stale(repo_root: Path) -> bool:
    """源码 mtime > dist mtime → 产物过期（``stale_artifact`` 判据）。"""
    dist = repo_root / "frontend" / "dist" / "index.html"
    if not dist.exists():
        return True
    dist_mtime = dist.stat().st_mtime
    newest = 0.0
    for base in (
        repo_root / "frontend" / "web" / "vue-element-plus" / "src",
        repo_root / "backend" / "app",
    ):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in (".ts", ".vue", ".py"):
                newest = max(newest, path.stat().st_mtime)
    return newest > dist_mtime
