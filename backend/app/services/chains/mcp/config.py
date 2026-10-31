"""F-SCH-06 · MCP 配置**两级合并**（用户级 + 项目级）。

此前 MCP Server 只有**硬编码注册表**（``MCPManager.SERVER_REGISTRY``），
既不能按用户配置，也不能按项目覆盖 → 「配置两级合并」这条需求**不成立**。

本模块提供两级来源：

- **用户级**：``~/.agent/mcp.json``（全局默认，对所有项目生效）；
- **项目级**：``<workspace_root>/.agent/mcp.json``（**覆盖**同名的用户级项）。

合并规则：**同名以项目级为准**（项目级字段级覆盖用户级；未给出的字段沿用用户级）。
配置里的 server **不覆盖**内置注册表，而是**追加**（内置始终可用）。

配置文件格式::

    {
      "servers": {
        "my-server": {
          "transport": "stdio",       # stdio | sse | http
          "command": "python",
          "args": ["-m", "my_server"],
          "env": {"KEY": "VALUE"},
          "url": "http://127.0.0.1:8931/sse",   # sse / http 时使用
          "headers": {"Authorization": "Bearer ..."},
          "description": "自定义 MCP Server",
          "read_only": true
        }
      }
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

#: 配置文件名（放在 ``.agent/`` 目录下）
CONFIG_FILENAME = "mcp.json"

#: 允许的传输类型
VALID_TRANSPORTS = ("stdio", "sse", "http")


class McpConfigError(ValueError):
    """配置文件非法。"""


def user_config_path() -> Path:
    """用户级配置路径（``~/.agent/mcp.json``）。"""
    return Path.home() / ".agent" / CONFIG_FILENAME


def project_config_path(workspace_root: str | Path | None) -> Path | None:
    """项目级配置路径（``<workspace_root>/.agent/mcp.json``）。"""
    if not workspace_root:
        return None
    return Path(workspace_root) / ".agent" / CONFIG_FILENAME


def _read_config(path: Path | None) -> tuple[dict[str, dict], list[str]]:
    """读一个配置文件，返回 ``(servers, 错误信息列表)``。"""
    if path is None or not path.exists():
        return {}, []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"{path}: 读取失败（{exc}）"]
    if not isinstance(raw, dict):
        return {}, [f"{path}: 顶层必须是对象"]
    servers = raw.get("servers")
    if servers is None:
        return {}, []
    if not isinstance(servers, dict):
        return {}, [f"{path}: servers 必须是对象"]
    out: dict[str, dict] = {}
    for name, spec in servers.items():
        if not isinstance(spec, dict):
            continue
        out[str(name)] = dict(spec)
    return out, []


def validate_server(name: str, spec: dict) -> dict:
    """校验并归一化一个 server 配置。"""
    transport = str(spec.get("transport") or "stdio").strip().lower()
    if transport not in VALID_TRANSPORTS:
        raise McpConfigError(
            f"MCP Server {name}: transport 必须是 {VALID_TRANSPORTS} 之一（实际 {transport}）",
        )
    # **只写 spec 里显式存在的字段**——否则项目级配置会把用户级的
    # description / read_only 覆盖成默认值，破坏「字段级合并」。
    out: dict[str, Any] = {"transport": transport}
    if "description" in spec:
        out["description"] = str(spec.get("description") or "")
    if "read_only" in spec:
        out["read_only"] = bool(spec.get("read_only"))
    if transport == "stdio":
        cmd = str(spec.get("command") or "").strip()
        if not cmd:
            raise McpConfigError(f"MCP Server {name}: stdio 传输必须声明 command")
        out["command"] = cmd
        out["args"] = [str(a) for a in (spec.get("args") or [])]
        out["env"] = {str(k): str(v) for k, v in (spec.get("env") or {}).items()}
    else:
        url = str(spec.get("url") or "").strip()
        if not url:
            raise McpConfigError(f"MCP Server {name}: {transport} 传输必须声明 url")
        out["url"] = url
        out["headers"] = {str(k): str(v) for k, v in (spec.get("headers") or {}).items()}
    if spec.get("module"):
        out["module"] = str(spec["module"])
    if spec.get("script"):
        out["script"] = str(spec["script"])
    return out


def load_user_servers() -> tuple[dict[str, dict], list[str]]:
    """用户级配置。"""
    return _read_config(user_config_path())


def load_project_servers(
    workspace_root: str | Path | None,
) -> tuple[dict[str, dict], list[str]]:
    """项目级配置。"""
    return _read_config(project_config_path(workspace_root))


def merge_servers(
    user: dict[str, dict],
    project: dict[str, dict],
) -> tuple[dict[str, dict], list[str]]:
    """合并两级配置：**同名以项目级为准**（字段级覆盖）。"""
    merged: dict[str, dict] = {}
    errors: list[str] = []
    for source, servers in (("user", user), ("project", project)):
        for name, spec in servers.items():
            try:
                normalized = validate_server(name, spec)
            except McpConfigError as exc:
                errors.append(str(exc))
                continue
            base = merged.get(name, {})
            base.update(normalized)
            merged[name] = base
    return merged, errors


def load_merged_servers(
    workspace_root: str | Path | None = None,
) -> tuple[dict[str, dict], list[str]]:
    """一次性读取并合并两级配置。"""
    user, user_errors = load_user_servers()
    project, project_errors = load_project_servers(workspace_root)
    merged, merge_errors = merge_servers(user, project)
    return merged, [*user_errors, *project_errors, *merge_errors]


def config_sources(workspace_root: str | Path | None = None) -> list[dict]:
    """各来源的**存在性与内容摘要**（供端点展示与排障）。"""
    out = []
    for level, path in (
        ("user", user_config_path()),
        ("project", project_config_path(workspace_root)),
    ):
        servers, errors = _read_config(path)
        out.append({
            "level": level,
            "path": str(path) if path else None,
            "exists": bool(path and path.exists()),
            "servers": sorted(servers),
            "errors": errors,
        })
    return out


__all__ = [
    "CONFIG_FILENAME", "VALID_TRANSPORTS", "McpConfigError",
    "user_config_path", "project_config_path",
    "load_user_servers", "load_project_servers", "merge_servers",
    "load_merged_servers", "config_sources", "validate_server",
]
