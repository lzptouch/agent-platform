"""安全子系统（S2）：权限判定、策略集、审计、沙箱能力探测。

公共入口：
- ``PermissionService.instance()`` —— 权限判定与审批（单例）；
- ``policy`` —— 归一化与策略集（纯函数）；
- ``audit`` —— JSONL 审计；
- ``sandbox`` —— 能力探测（诚实标注）。
"""
from app.services.security.permissions import (  # noqa: F401
    ALLOW,
    ASK,
    DENY,
    Decision,
    PermissionRequest,
    PermissionService,
    Rule,
    decide,
)
