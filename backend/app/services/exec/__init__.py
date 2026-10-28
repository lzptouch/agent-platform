"""执行层扩展（S5）：上下文经济性与成本。

- ``context``：预算、裁剪、九段压缩；
- ``catalog``：工具目录与延迟装载；
- ``memory``：三层记忆、索引与预筛；
- ``roles``：内置轻量角色（0 工具）。
"""
from app.services.exec.catalog import (  # noqa: F401
    CatalogEntry,
    ToolLoader,
    build_catalog,
    catalog_text,
    search_catalog,
    split_core_and_catalog,
)
from app.services.exec.context import (  # noqa: F401
    ContextBudget,
    CompressionResult,
    build_nine_section_summary,
    compress,
    estimate_tokens,
    trim_messages,
)
from app.services.exec.roles import BUILTIN_ROLES, Role, get_role  # noqa: F401
