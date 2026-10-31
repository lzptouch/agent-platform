"""投递抽象与通道实现（S7 / WP-7.3）。

通道：``local``（桌面通知）、``webhook``（企微/飞书/钉钉通用）、``mobile``（占位）。

约定：
- 载荷统一：任务名、状态、耗时、摘要、产物链接；
- **失败重试 3 次**（指数退避）；失败写事件，**不改任务状态**；
- 凭证存本机配置，**不入库明文**（``webhook`` 的 URL 完整保存，但不写日志正文）。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)

CHANNELS = ("local", "webhook", "mobile")

#: 载荷里必须带的字段（任务名、状态、耗时、摘要、产物链接）
#: 载荷中**必须存在**的字段（值可以是 0 / "" / []）
REQUIRED_PAYLOAD_FIELDS = ("task_name", "status", "duration_ms", "summary", "artifacts")
#: 载荷中**必须非空**的字段（空串视为缺失）
NON_EMPTY_PAYLOAD_FIELDS = ("task_name", "status")


@dataclass(frozen=True)
class DeliveryConfig:
    """一个投递通道的配置。"""

    type: str                    # local | webhook | mobile
    target: str = ""             # webhook URL / 本地描述
    template: str = ""           # 自定义模板（可空，用默认）
    enabled: bool = True


@dataclass
class DeliveryPayload:
    """统一的推送载荷。"""

    task_name: str
    status: str
    duration_ms: int
    summary: str
    artifacts: list[str] = field(default_factory=list)
    run_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "task_name": self.task_name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "summary": self.summary,
            "artifacts": list(self.artifacts),
            "run_id": self.run_id,
        }

    def as_markdown(self, template: str = "") -> str:
        if template:
            try:
                return template.format(**self.as_dict())
            except (KeyError, IndexError):
                pass
        lines = [
            f"## {self.task_name}",
            f"状态：{self.status}　耗时：{self.duration_ms} ms",
            "",
            self.summary or "（无摘要）",
        ]
        if self.artifacts:
            lines.append("")
            lines.append("产物：")
            lines.extend(f"- {a}" for a in self.artifacts)
        return "\n".join(lines)


@dataclass
class DeliveryResult:
    """一次投递的结果。"""

    ok: bool
    channel: str
    target: str
    attempts: int = 0
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "channel": self.channel,
            "target": self.target,
            "attempts": self.attempts,
            "error": self.error,
        }


def validate_payload(payload: DeliveryPayload) -> list[str]:
    """校验载荷字段齐全（缺一即列出）。

    **W9-01 / AUD2-H07 修复（此前所有通知 100% 被拒）**

    旧实现是 ``not getattr(payload, f, None)`` —— 把「**值为空**」当成「**字段缺失**」：

    - ``duration_ms``：``execute_sync()`` 的返回字典里**根本没有** ``duration_ms``
      （只有 run_id/session_id/finished/files/error/answer/model/prompt/mode）
      → 恒为 ``0`` → ``not 0`` 为真 → 判为缺字段 → **每次投递都直接返回 ok=False**；
    - ``summary``：无回答时为 ``""`` → 同样判为缺字段；
    - ``artifacts``：无产物时为 ``[]`` → 同样判为缺字段。

    结果：**webhook / 桌面通知一次都发不出去**，而 `F-SCH-02/03/04` 标 ✅。

    现在区分两类约束：
    - **必须存在**：5 个字段都要有（``hasattr``）；
    - **必须非空**：只有 ``task_name`` / ``status``（其余允许 0 / "" / []）。
    """
    missing: list[str] = []
    for field in REQUIRED_PAYLOAD_FIELDS:
        if not hasattr(payload, field):
            missing.append(field)
    for field in NON_EMPTY_PAYLOAD_FIELDS:
        if hasattr(payload, field) and not getattr(payload, field, None):
            missing.append(field)
    return missing


def deliver(
    config: DeliveryConfig,
    payload: DeliveryPayload,
    *,
    retries: int = 3,
    on_failure=None,
) -> DeliveryResult:
    """投递一次（带重试；失败写事件，**不改任务状态**）。"""
    if not config.enabled:
        result = DeliveryResult(ok=False, channel=config.type, target=config.target,
                                 error="通道已禁用")
        # **W9-01 / AUD2-M08**：早退路径也要触发 on_failure
        # （此前「通道禁用」「载荷缺字段」直接 return，调用方拿不到失败通知，
        #   而真正发送失败时是会调的 —— 语义不一致）。
        if on_failure:
            on_failure(result)
        return result
    missing = validate_payload(payload)
    if missing:
        result = DeliveryResult(ok=False, channel=config.type, target=config.target,
                                 error=f"载荷缺字段: {', '.join(missing)}")
        if on_failure:
            on_failure(result)
        return result

    attempt = 0
    last_error: str | None = None
    while attempt < retries:
        attempt += 1
        try:
            ok = _send_once(config, payload)
            if ok:
                return DeliveryResult(ok=True, channel=config.type, target=config.target,
                                      attempts=attempt)
            last_error = "投递失败"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        if attempt < retries:
            time.sleep(min(0.05 * (2 ** (attempt - 1)), 1.0))  # 指数退避（测试不阻塞）

    result = DeliveryResult(ok=False, channel=config.type, target=config.target,
                            attempts=attempt, error=last_error)
    if on_failure:
        on_failure(result)
    # **W9-01 / AUD2-M07**：webhook URL 本身即凭据（企微/飞书/钉钉的 `?key=SECRET`），
    # 原样落盘与模块头部「凭证不写日志正文」的约定自相矛盾 → 只记 host+path。
    logger.warning("投递失败（%s → %s）：%s（已重试 %d 次）",
                   config.type, _safe_target(config.target), last_error, attempt)
    return result


def _safe_target(target: str) -> str:
    """把投递目标脱敏（webhook URL 的 query 即凭据）。"""
    if not target:
        return target
    if "://" not in target:
        return target
    try:
        from urllib.parse import urlsplit

        parts = urlsplit(target)
        if not parts.query:
            return target
        return f"{parts.scheme}://{parts.netloc}{parts.path}?***"
    except Exception:  # noqa: BLE001
        return "<invalid target>"


def _send_once(config: DeliveryConfig, payload: DeliveryPayload) -> bool:
    """真正发送一次。成功返回 True。"""
    body = payload.as_markdown(config.template)
    if config.type == "local":
        # 桌面通知：主进程监听，这里只记录
        logger.info("[local] %s: %s", payload.task_name, payload.status)
        return True
    if config.type == "webhook":
        return _send_webhook(config.target, payload, body)
    if config.type == "mobile":
        # 占位：保留接口，暂不实现
        logger.info("[mobile] %s: %s", payload.task_name, payload.status)
        return True
    raise ValueError(f"未知通道: {config.type}")


def _send_webhook(url: str, payload: DeliveryPayload, body_markdown: str) -> bool:
    """企微/飞书/钉钉通用 webhook（JSON POST）。"""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"webhook URL 非法: {url[:60]}")
    data = json.dumps({
        "task_name": payload.task_name,
        "status": payload.status,
        "duration_ms": payload.duration_ms,
        "summary": payload.summary,
        "artifacts": payload.artifacts,
        "markdown": body_markdown,
    }).encode("utf-8")
    req = urllib_request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "agent-platform/1.0"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except HTTPError as exc:
        raise RuntimeError(f"webhook HTTP {exc.status}") from exc
    except URLError as exc:
        raise RuntimeError(f"webhook 连接失败: {exc.reason}") from exc
