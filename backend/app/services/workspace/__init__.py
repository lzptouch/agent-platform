"""工作空间子系统（S3）：实体 / manifest / 快照 / 变更 / 产物。

公共入口：
- ``WorkspaceService`` —— 工作空间 CRUD 与当前选择；
- ``snapshot_before_write`` / ``record_change`` —— 写前快照与变更落账（工具层钩子）；
- ``register_artifact`` —— 产物登记；
- ``current_run_context`` —— 当前 run 的工作空间上下文（contextvar）。
"""
from app.services.workspace.service import WorkspaceService  # noqa: F401
