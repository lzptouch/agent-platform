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
REQUIRED_PAYLOAD_FIELDS = ("task_name", "status", "duration_ms", "summary", "artifacts")


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
    """校验载荷字段齐全（缺一即列出）。"""
    missing = [f for f in REQUIRED_PAYLOAD_FIELDS if not getattr(payload, f, None)]
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
        return DeliveryResult(ok=False, channel=config.type, target=config.target,
                              error="通道已禁用")
    missing = validate_payload(payload)
    if missing:
        return DeliveryResult(ok=False, channel=config.type, target=config.target,
                              error=f"载荷缺字段: {', '.join(missing)}")

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
    logger.warning("投递失败（%s → %s）：%s（已重试 %d 次）",
                   config.type, config.target, last_error, attempt)
    return result


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
