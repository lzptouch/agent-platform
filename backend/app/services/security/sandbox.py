"""沙箱能力探测（S2 / WP-2.6）。

本仓库**不提供原生沙箱**（无 macOS sandbox-exec / Windows Hook / 容器）。
因此这里**诚实标注**：能力是"仅策略层拦截"，并说明拦截范围与替代机制。
不再返回硬编码 ``sandbox_available: false``。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SandboxCapability:
    """沙箱能力的诚实描述。"""

    level: str            # none | policy_only | os_native
    available: bool       # 是否有任何隔离
    platform: str
    enforced_paths: bool  # 路径策略是否生效
    enforced_commands: bool
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def probe() -> SandboxCapability:
    """探测当前平台的沙箱能力。

    当前实现：全部平台均为 ``policy_only``（规则集 + 写前校验），无原生隔离。
    后续增强：macOS 可升级为 ``sandbox-exec``（os_native）。

    **W1-07 / AUD2-H43（沙箱能力诚实化）**：
    此前 ``available=True`` **恒定** —— 而同一对象的 ``message`` 明说
    「无操作系统级沙箱隔离」→ ``api/v1/desktop.py`` 直接把它暴露成
    ``sandbox_available`` → 前端 / 桌面壳显示「沙箱可用」，
    用户据此以为存在 OS 级隔离（**与 F-SEC-12「沙箱能力诚实化」直接冲突**）。

    现在：``available`` 的语义收紧为「**存在任何隔离机制**」——
    仅策略层拦截时为 ``False``（保留 ``level`` / ``message`` 供 UI 展示）。
    """
    platform = sys.platform
    if platform == "darwin" and _has_sandbox_exec():
        # 尚未接入原生实现，保持诚实：有能力但未启用
        return SandboxCapability(
            level="policy_only",
            available=False,
            platform=platform,
            enforced_paths=True,
            enforced_commands=True,
            message="当前为策略层拦截（路径/命令规则集）；macOS 原生 sandbox-exec 可用但未启用。",
        )
    return SandboxCapability(
        level="policy_only",
        available=False,
        platform=platform,
        enforced_paths=True,
        enforced_commands=True,
        message=(
            "当前为**仅策略层拦截**（路径 / 命令规则集 + 写前校验），"
            "无操作系统级沙箱隔离。原生沙箱（macOS sandbox-exec / Windows Hook）为后续增强项。"
        ),
    )


def _has_sandbox_exec() -> bool:
    return os.path.exists("/usr/bin/sandbox-exec")
