"""ToolRegistry —— 统一工具抽象层。

把 4 类工具合并为 Anthropic 兼容的 tools schema：
1. 内置工具（read_file / write_file / execute_python / execute_bash / list_directory）
2. MCP 工具（命名空间 ``mcp_<server>__<tool>``，动态反射发现）
3. RAG 工具（rag_query / rag_ingest，静态定义）
4. Web Research 工具（web_research，静态定义）
"""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

from app.core.config import settings
from app.services.code_executor import LocalCodeExecutor
from app.services.mcp_manager import MCPManager

logger = logging.getLogger(__name__)


class ToolProfile(str, Enum):
    """工具档案：对话模式只读，工作模式全量。"""

    CHAT = "chat"
    WORK = "work"


# 对话模式允许的内置工具（只读）
CHAT_BUILTIN_NAMES = {"read_file", "list_directory"}
# 写类工具（任何模式下都需显式能力开关之外的档案控制点）
WRITE_TOOL_NAMES = {"write_file", "execute_python", "execute_bash", "rag_ingest"}


def assert_profile_consistency(tools: list[dict], profile: ToolProfile) -> None:
    """断言 chat 档案中不含写类工具（供测试与防御性检查使用）。"""
    names = {t["name"] for t in tools}
    if profile == ToolProfile.CHAT:
        illegal = names & WRITE_TOOL_NAMES
        assert not illegal, f"chat 档案不应包含写类工具: {illegal}"

# ----------------------------------------------------------------------
# 内置工具定义（Anthropic tool schema）
# ----------------------------------------------------------------------
BUILTIN_TOOLS: list[dict[str, Any]] = [
    {
        "name": "tool_search",
        "description": "按关键词检索可用工具目录，返回候选工具名与一句话描述（不返回完整参数）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索关键词"},
                "top_k": {"type": "integer", "description": "候选数量（默认 5）"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "tool_load",
        "description": "装载指定工具的完整调用 Schema（返回参数说明，之后即可直接调用该工具）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要装载的工具名列表",
                },
            },
            "required": ["names"],
        },
    },
    {
        "name": "read_file",
        "description": "读取本地文件的内容。用于读取 Skill 指令文件（SKILL.md）或其他参考文件。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "要读取的文件的绝对路径或相对路径"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": "创建或覆盖写入一个文件。用于保存生成的代码、数据或报告。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "要写入的文件路径"},
                "content": {"type": "string", "description": "要写入的文件内容"},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "execute_python",
        "description": "执行一段 Python 代码。代码在本地运行，工作目录为 output/。可以使用 pandas、matplotlib、numpy 等已安装的库。",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "要执行的 Python 代码"}},
            "required": ["code"],
        },
    },
    {
        "name": "execute_bash",
        "description": "执行一条 Bash 命令。工作目录为 output/。",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "要执行的 Bash 命令"}},
            "required": ["command"],
        },
    },
    {
        "name": "list_directory",
        "description": "列出指定目录下的文件和子目录。",
        "input_schema": {
            "type": "object",
            "properties": {"dir_path": {"type": "string", "description": "要列出内容的目录路径"}},
            "required": ["dir_path"],
        },
    },
]

# ----------------------------------------------------------------------
# RAG / Web 工具定义（静态）
# ----------------------------------------------------------------------
RAG_TOOLS: list[dict[str, Any]] = [
    {
        "name": "rag_query",
        "description": "[本地文档库] 从产品手册/内部文档中检索并带 [n] 引用回答。适用于产品参数、技术规格、内部知识问答。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "用户问题"},
                "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    },
    {
        "name": "rag_ingest",
        "description": "[本地文档库] 重新解析 data/pdf/ 下的 PDF 并入库 Milvus（慢操作）。",
        "input_schema": {
            "type": "object",
            "properties": {"recreate": {"type": "boolean", "default": True}},
        },
    },
]

WEB_TOOLS: list[dict[str, Any]] = [
    {
        "name": "web_research",
        "description": "[实时网络] Serper Google 搜索 + 爬虫 + 向量召回 + 带引用回答。适用于实时新闻、竞品对比、最新评测。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "研究问题"},
                "profile": {"type": "string", "default": "", "description": "LLM 角色"},
                "output_format": {"type": "string", "default": "", "description": "输出格式要求"},
            },
            "required": ["query"],
        },
    },
]


class ToolRegistry:
    """合并 4 类工具并统一分发。"""

    def __init__(self, mcp_manager: MCPManager) -> None:
        self.mcp_manager = mcp_manager

    # ------------------------------------------------------------------ #
    # 工具合并
    # ------------------------------------------------------------------ #
    def get_combined_tools(
        self,
        enable_mcp: bool = False,
        mcp_servers: list[str] | None = None,
        enable_rag: bool = False,
        enable_web_research: bool = False,
        profile: ToolProfile = ToolProfile.WORK,
    ) -> list[dict]:
        """合并工具。

        profile=CHAT：仅只读内置工具（read_file/list_directory）+ rag_query（不含 rag_ingest）
        + web_research + 标记 read_only 的 MCP Server 工具。
        """
        if profile == ToolProfile.CHAT:
            tools = [t for t in BUILTIN_TOOLS if t["name"] in CHAT_BUILTIN_NAMES]
        else:
            tools = list(BUILTIN_TOOLS)

        if enable_rag:
            if profile == ToolProfile.CHAT:
                tools.extend(t for t in RAG_TOOLS if t["name"] == "rag_query")
            else:
                tools.extend(RAG_TOOLS)

        if enable_web_research:
            tools.extend(WEB_TOOLS)

        if enable_mcp and mcp_servers:
            for name in mcp_servers:
                if profile == ToolProfile.CHAT and not self.mcp_manager.is_read_only(name):
                    logger.info("chat 模式跳过非只读 MCP Server: %s", name)
                    continue
                try:
                    for t in self.mcp_manager.list_tools_with_schema(name):
                        tools.append({
                            "name": f"mcp_{name}__{t['name']}",
                            "description": f"[MCP:{name}] {t.get('description', '').split(chr(10))[0]}",
                            "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
                        })
                except Exception as exc:  # noqa: BLE001 - 单个 Server 失败不阻塞其他
                    logger.warning("加载 MCP Server %s 工具失败: %s", name, exc)

        return tools

    # ------------------------------------------------------------------ #
    # 工具分发
    # ------------------------------------------------------------------ #
    def dispatch(
        self,
        tool_name: str,
        tool_input: dict,
        executor: LocalCodeExecutor,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> tuple[str, str, dict]:
        """执行工具，返回 (result_json_str, tool_source, extra)。"""
        # 权限判定（唯一落点）：内置 / MCP / Web 三类工具共用同一条判定链
        denial = self._check_permission(tool_name, tool_input, run_id=run_id, session_id=session_id)
        if denial is not None:
            return json.dumps(denial, ensure_ascii=False), "denied", {}

        # MCP 工具
        if tool_name.startswith("mcp_"):
            _, server, actual = tool_name.split("__", 1)
            result = self.mcp_manager.call_tool(server, actual, tool_input)
            return json.dumps({"result": result}, ensure_ascii=False), "mcp", {"mcp_server": server}

        # RAG 工具
        if tool_name == "rag_query":
            from app.services.rag import rag_chain

            try:
                refs, answer = rag_chain.rag(tool_input["query"])
                return (
                    json.dumps({"answer": answer, "references": refs}, ensure_ascii=False),
                    "rag",
                    {"references": refs},
                )
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"error": f"RAG 查询失败: {exc}"}, ensure_ascii=False), "rag", {}

        if tool_name == "rag_ingest":
            from app.services.rag.ingest import ingest

            try:
                stats = ingest(recreate=bool(tool_input.get("recreate", False)))
                return json.dumps(stats, ensure_ascii=False), "rag", {}
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"error": f"RAG 入库失败: {exc}"}, ensure_ascii=False), "rag", {}

        # Web Research 工具
        if tool_name == "web_research":
            from app.services.web import research_service

            try:
                result = research_service.web_research(
                    tool_input["query"],
                    tool_input.get("profile", ""),
                    tool_input.get("output_format", ""),
                )
                return (
                    json.dumps(result, ensure_ascii=False),
                    "web",
                    {"reference_cards": result.get("reference_cards", [])},
                )
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"error": f"Web Research 失败: {exc}"}, ensure_ascii=False), "web", {}

        # 内置工具
        return json.dumps(self._dispatch_builtin(tool_name, tool_input, executor), ensure_ascii=False), "builtin", {}

    # ------------------------------------------------------------------ #
    # 权限判定
    # ------------------------------------------------------------------ #
    def _check_permission(
        self,
        tool_name: str,
        tool_input: dict,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
    ) -> dict | None:
        """按权限规则判定一次工具调用（**S2 起为阻塞式审批**）。

        返回 ``None`` 表示放行；返回字典表示被拒绝，调用方据此回给模型。

        语义（doc/design/04 §3）：
        - 判定走 ``app/services/security`` 引擎（归一化 → 规则匹配 → 信任分层回落）；
        - 命中 ``ask`` 时**阻塞等待**用户决策（事件 + 审批端点），超时按 ``deny``；
        - 每次受控动作写 JSONL 审计与决策日志（含命中规则与原因）。
        """
        import time

        from app.core.config import settings
        from app.core.workspace import get_workspace_dir
        from app.services.security import audit
        from app.services.security.permissions import PermissionRequest, PermissionService

        service = PermissionService.instance()
        service.approval_timeout = float(settings.permission_approval_timeout)
        action = self._detect_action(tool_name, tool_input)
        path = self._detect_path(tool_name, tool_input)
        command = None
        code = None
        if tool_name == "execute_bash":
            command = str(tool_input.get("command", "")) or None
        if tool_name == "execute_python":
            code = str(tool_input.get("code", "")) or None

        request = PermissionRequest(
            tool=tool_name, action=action, path=path, command=command,
        )
        # Python 代码危险调用扫描（补 engine 动作检测）
        if code and action is None:
            from app.services.security import policy

            if policy.python_has_dangerous_calls(code):
                request = PermissionRequest(
                    tool=tool_name, action="external_script_exec", path=path, command=None,
                )

        started = time.monotonic()
        decision = service.enforce(request, run_id=run_id, session_id=session_id)
        latency_ms = int((time.monotonic() - started) * 1000)

        if settings.permission_audit_enabled:
            audit.record(
                run_id=run_id, tool=tool_name, decision=decision.decision,
                reason=decision.reason, target=decision.target,
                matched_rule_id=decision.matched_rule.id if decision.matched_rule else None,
                latency_ms=latency_ms,
                request={"tool": tool_name, "path": path, "command": command, "action": action},
            )

        if decision.allowed:
            return None

        return {
            "error": f"操作被权限策略拒绝（{decision.reason}）",
            "permission": {
                "decision": decision.decision,
                "reason": decision.reason,
                "scope": decision.scope,
                "target": decision.target,
                "risk": decision.risk,
                "workspace_dir": str(get_workspace_dir()),
            },
        }

    @staticmethod
    def _detect_action(tool_name: str, tool_input: dict) -> str | None:
        """识别高危动作（批量删除 / 改系统配置 / 工作区外脚本）。"""
        from app.core.config import settings

        if tool_name == "execute_bash":
            command = str(tool_input.get("command", ""))
            lowered = command.lower()
            if any(token in lowered for token in ("rm -rf", "del /", "rmdir /s", "format ")):
                return "batch_delete"
            if any(token in lowered for token in ("reg add", "reg delete", "chmod 777", "setx ")):
                return "system_config_write"
        if tool_name == "write_file":
            target = str(tool_input.get("file_path", ""))
            if target:
                from app.core.workspace import is_in_workspace

                if not is_in_workspace(target):
                    try:
                        import os

                        from pathlib import Path

                        resolved = Path(target).expanduser().resolve()
                        if resolved == Path(settings.user_data_dir).resolve() or str(
                            resolved
                        ).startswith(str(settings.user_data_dir)):
                            return "system_config_write"
                    except (OSError, RuntimeError):
                        pass
        return None

    @staticmethod
    def _detect_path(tool_name: str, tool_input: dict) -> str | None:
        """提取工具涉及的目标路径（用于路径维度判定）。"""
        if tool_name in ("read_file", "write_file"):
            return str(tool_input.get("file_path", "")) or None
        if tool_name == "list_directory":
            return str(tool_input.get("dir_path", "")) or None
        return None

    @classmethod
    def _dispatch_builtin(cls, tool_name: str, tool_input: dict, executor: LocalCodeExecutor) -> dict:
        if tool_name == "tool_search":
            return cls._tool_search(tool_input)
        if tool_name == "tool_load":
            return cls._tool_load(tool_input)
        if tool_name == "read_file":
            return executor.read_file(tool_input["file_path"])
        if tool_name == "write_file":
            return executor.write_file(tool_input["file_path"], tool_input["content"])
        if tool_name == "execute_python":
            return executor.execute_python(tool_input["code"])
        if tool_name == "execute_bash":
            return executor.execute_bash(tool_input["command"])
        if tool_name == "list_directory":
            return executor.list_directory(tool_input["dir_path"])
        return {"error": f"未知工具: {tool_name}"}

    # ------------------------------------------------------------------ #
    # S5 / WP-5.1 工具检索与装载
    # ------------------------------------------------------------------ #
    @classmethod
    def _tool_search(cls, tool_input: dict) -> dict:
        """按关键词检索工具目录，返回 Top-K 候选（name + 描述 + 命名空间）。"""
        from app.services.exec.catalog import build_catalog, search_catalog

        query = str(tool_input.get("query", "") or "")
        top_k = int(tool_input.get("top_k", 5) or 5)
        catalog = build_catalog(BUILTIN_TOOLS)
        hits = search_catalog(catalog, query, top_k=top_k)
        return {
            "query": query,
            "candidates": [e.as_dict() for e in hits],
            "hint": "如需完整参数，调用 tool_load 传入 names。",
        }

    @classmethod
    def _tool_load(cls, tool_input: dict) -> dict:
        """装载工具的完整 Schema（返回参数说明，之后可直接调用）。"""
        import json

        names = tool_input.get("names") or []
        if isinstance(names, str):
            names = [names]
        by_name = {str(t.get("name")): t for t in BUILTIN_TOOLS}
        loaded = []
        missing = []
        for n in names:
            tool = by_name.get(str(n))
            if tool is None:
                missing.append(str(n))
                continue
            loaded.append({
                "name": tool["name"],
                "description": str(tool.get("description", ""))[:300],
                "input_schema": tool.get("input_schema", {}),
            })
        return {
            "loaded": loaded,
            "missing": missing,
            "schemas_json": json.dumps(loaded, ensure_ascii=False),
        }

    # ------------------------------------------------------------------ #
    # System Prompt 附加段
    # ------------------------------------------------------------------ #
    def build_tools_prompt_section(
        self,
        enable_mcp: bool = False,
        mcp_servers: list[str] | None = None,
        enable_rag: bool = False,
        enable_web_research: bool = False,
        profile: ToolProfile = ToolProfile.WORK,
    ) -> str:
        parts: list[str] = []
        if enable_rag:
            lines = ["- `rag_query`: 检索本地产品文档并带 [n] 引用回答"]
            if profile != ToolProfile.CHAT:
                lines.append("- `rag_ingest`: 重新入库 data/pdf/ 下的 PDF")
            parts.append("## 可用的本地文档库（RAG）工具\n" + "\n".join(lines))
        if enable_web_research:
            parts.append(
                "## 可用的实时网络检索工具\n"
                "- `web_research`: Serper 搜索 + 爬虫 + GPT 带引用回答，返回引用卡片\n"
            )
        if enable_mcp and mcp_servers:
            lines = []
            for name in mcp_servers:
                if profile == ToolProfile.CHAT and not self.mcp_manager.is_read_only(name):
                    continue
                try:
                    for t in self.mcp_manager.list_tools(name):
                        lines.append(f"- `mcp_{name}__{t['name']}`: {t['description']}")
                except Exception:  # noqa: BLE001
                    continue
            if lines:
                parts.append("## 可用的 MCP 工具\n" + "\n".join(lines))
        return "\n".join(parts)
