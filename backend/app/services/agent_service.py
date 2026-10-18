"""AgentService —— 显式 Agent 循环（含流式事件 + 4 类工具 + 可选反思）。

- **默认模式**：Skill 原版显式循环（messages.create + tool_use 回填），
  工具由 ToolRegistry 动态合并（内置 + MCP + RAG + Web）。
- **反思模式**（``enable_reflection=True``）：借鉴 webResearch 的
  plan → action → reflection → action → answer 五步循环，
  使用 DeepSeek（JSON-mode 规划 + reasoning_content 流式回答）。
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from app.core.config import PROJECT_ROOT, settings
from app.services.code_executor import LocalCodeExecutor
from app.services.mcp_manager import MCPManager
from app.services.skill_manager import SkillManager
from app.services.tool_registry import BUILTIN_TOOLS, ToolProfile, ToolRegistry

logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_ABS_PREFIX = str(PROJECT_ROOT) + "/"

# 向后兼容：原 Skill 的静态 TOOLS
TOOLS: list[dict[str, Any]] = BUILTIN_TOOLS

# 反思模式规划模板（通用版，不限定业务领域）
PLAN_PROMPT_TEMPLATE = """你是一个智能助手的规划模块。你的任务是：
1. 分析用户的查询: {query}
2. 基于可用工具，决定需要调用哪些工具来获取信息
3. 将用户的原始查询拆解为 1-3 个工具调用

## 可用工具
{tools_desc}

## 输出格式
输出 JSON 列表，每项包含：
- `tool`: 工具名（必须是上面列出的工具之一）
- `input`: 工具入参（符合该工具的 input_schema）

如果不需要调用任何工具，输出空列表 []。
只输出 JSON，前后不要输出任何信息。
"""

REFLECTION_PROMPT_TEMPLATE = """你是一个智能助手的反思模块。你的任务是：
1. 用户原始查询: {query}
2. 目前已有的信息:
{memory}

判断是否需要再补充 1-2 个工具调用来获取更完整的信息。
可用工具同上。如果信息已足够，输出空列表 []。

## 可用工具
{tools_desc}

## 输出格式
输出 JSON 列表，每项包含 `tool` 和 `input`。只输出 JSON。
"""

FINAL_ANSWER_TEMPLATE = """你是一个智能助手，负责根据用户的问题和已收集的信息生成完整、准确的回答。

已收集的信息：
{memory}

用户问题：{query}
"""

# Plan-first（工作模式-先规划）：把用户目标拆解为可审批的执行计划
PLAN_STEPS_TEMPLATE = """你是一个任务规划器。把用户的任务目标拆解为 2-6 个可执行步骤。

## 用户目标
{query}

## 输出格式
输出 JSON 列表，每项包含：
- `id`: 步骤编号（从 1 开始）
- `title`: 步骤标题（≤ 20 字）
- `detail`: 该步骤要做什么（≤ 60 字）

只输出 JSON 列表，不要输出其他内容。
"""


def display_path(text: str) -> str:
    """把绝对路径替换为相对路径，仅用于前端展示。"""
    return text.replace(_ABS_PREFIX, "./")


def _serialize(obj: Any) -> Any:
    """把 SDK 对象递归转成可 JSON 序列化的结构。"""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


class MissingApiKeyError(RuntimeError):
    """未配置 DASHSCOPE_API_KEY。"""


class AgentService:
    """封装模型客户端、Agent 循环与产出文件收集。"""

    def __init__(
        self,
        skill_manager: SkillManager,
        executor: LocalCodeExecutor | None = None,
        mcp_manager: MCPManager | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.skill_manager = skill_manager
        self.executor = executor or LocalCodeExecutor()
        self.mcp_manager = mcp_manager or MCPManager()
        self.tool_registry = tool_registry or ToolRegistry(self.mcp_manager)
        self._client = None

    # ------------------------------------------------------------------ #
    # 客户端（OpenAI 兼容协议：DashScope /chat/completions + function calling）
    # ------------------------------------------------------------------ #
    def _get_client(self):
        if not settings.has_api_key:
            raise MissingApiKeyError(
                "未配置 DASHSCOPE_API_KEY。请在项目根目录 .env 中设置后重启服务。"
            )
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.dashscope_api_key,
                base_url=settings.dashscope_base_url,
            )
        return self._client

    def is_ready(self) -> bool:
        return settings.has_api_key

    @staticmethod
    def _to_openai_tools(tools: list[dict]) -> list[dict]:
        """Anthropic 风格 schema（input_schema / inputSchema）→ OpenAI function schema（parameters）。"""
        openai_tools = []
        for t in tools:
            params = t.get("input_schema") or t.get("inputSchema") or {"type": "object", "properties": {}}
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": params,
                },
            })
        return openai_tools

    # ------------------------------------------------------------------ #
    # 产出文件
    # ------------------------------------------------------------------ #
    def _snapshot_files(self) -> set[str]:
        return {f.name for f in self.executor.output_dir.iterdir() if f.is_file()}

    def _collect_new_files(self, existing: set[str]) -> list[dict]:
        files: list[dict] = []
        for path in sorted(self.executor.output_dir.iterdir()):
            if not path.is_file() or path.name in existing:
                continue
            files.append(
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "is_image": path.suffix.lower() in IMAGE_SUFFIXES,
                }
            )
        return files

    # ------------------------------------------------------------------ #
    # 主入口：事件流
    # ------------------------------------------------------------------ #
    def stream(
        self,
        user_prompt: str,
        model: str | None = None,
        *,
        skills: list[str] | None = None,
        enable_mcp: bool = False,
        mcp_servers: list[str] | None = None,
        enable_rag: bool = False,
        enable_web_research: bool = False,
        enable_reflection: bool = False,
        mode: str = "work",
        history: list[dict] | None = None,
        team: dict | None = None,
        plan: list[dict] | None = None,
        plan_first: bool = False,
        deadline: float | None = None,
    ) -> Iterator[dict]:
        """运行 Agent 并逐步产出事件字典。

        参数:
            skills: 本次启用的 Skill 名称列表。work 模式 ``None`` = 全部；chat 模式 ``None`` = 不启用。
            mode: ``chat``（只读工具 / Ask）或 ``work``（全量工具 / Craft）。
            history: 会话历史（仅 user/assistant 纯文本）。
            team: Skill 团队元数据。
            plan: 已批准的计划（恢复执行时注入 system prompt）。
            plan_first: 先生成计划并等待人工确认（仅 work 模式）。
            deadline: 协作式超时（``time.monotonic()`` 秒），每轮迭代前检查。
        """
        model = model or settings.default_model
        profile = ToolProfile.CHAT if mode == "chat" else ToolProfile.WORK
        selected_skills = self.skill_manager.resolve_for_mode(skills, mode)
        tools = self.tool_registry.get_combined_tools(
            enable_mcp=enable_mcp,
            mcp_servers=mcp_servers,
            enable_rag=enable_rag,
            enable_web_research=enable_web_research,
            profile=profile,
        )
        system_prompt = self.skill_manager.build_system_prompt(
            skills if mode != "chat" or skills is not None else [],
            mode=mode,
            team=team,
        )
        extra_section = self.tool_registry.build_tools_prompt_section(
            enable_mcp=enable_mcp,
            mcp_servers=mcp_servers,
            enable_rag=enable_rag,
            enable_web_research=enable_web_research,
            profile=profile,
        )
        if extra_section:
            system_prompt = system_prompt + "\n\n" + extra_section

        if plan:
            plan_lines = "\n".join(
                f"{p.get('id', i)}. {p.get('title', '')}：{p.get('detail', '')}"
                for i, p in enumerate(plan, start=1)
            )
            system_prompt += f"\n\n## 已批准的执行计划\n请严格按照以下计划执行：\n{plan_lines}"

        yield {
            "type": "skills_selected",
            "skills": [s["name"] for s in selected_skills],
            "all_skills": [s["name"] for s in self.skill_manager.list_skills()],
            "total": len(self.skill_manager.list_skills()),
        }
        yield {"type": "system_prompt", "content": display_path(system_prompt)}
        yield {"type": "user_input", "content": user_prompt}

        if enable_reflection and mode == "chat":
            yield {"type": "notice", "content": "对话模式不支持反思循环，已忽略 enable_reflection"}
            enable_reflection = False

        # Plan-first：只产计划，等待审批
        if plan_first and mode == "work" and plan is None:
            plan_steps = self._generate_plan(user_prompt)
            yield {"type": "approval_required", "plan": plan_steps}
            yield {"type": "done", "status": "awaiting_approval"}
            return

        if enable_reflection:
            yield from self._stream_reflection(user_prompt, model, tools, deadline=deadline)
            return

        max_iterations = settings.chat_max_iterations if mode == "chat" else settings.max_iterations
        yield from self._stream_loop(
            user_prompt, model, tools, system_prompt,
            history=history, deadline=deadline, max_iterations=max_iterations,
        )

    def _generate_plan(self, user_prompt: str) -> list[dict]:
        """生成可审批的执行计划（失败降级为单步计划）。"""
        try:
            from app.core.llm import chat

            text = chat(
                PLAN_STEPS_TEMPLATE.format(query=user_prompt),
                model=settings.plan_model,
                json_mode=True,
            )
            import re

            match = re.search(r"(\[[\s\S]*\])", text or "")
            if match:
                data = json.loads(match.group(1))
                steps = [
                    {"id": i + 1, "title": str(s.get("title", ""))[:40], "detail": str(s.get("detail", ""))[:120]}
                    for i, s in enumerate(data)
                    if isinstance(s, dict) and s.get("title")
                ]
                if steps:
                    return steps
        except Exception as exc:  # noqa: BLE001 - 降级不阻塞
            logger.warning("计划生成失败，降级为单步计划: %s", exc)
        return [{"id": 1, "title": "执行任务", "detail": user_prompt[:120]}]

    # ------------------------------------------------------------------ #
    # 模式 1：默认显式循环（OpenAI 兼容 function calling）
    # ------------------------------------------------------------------ #
    def _stream_loop(
        self,
        user_prompt: str,
        model: str,
        tools: list[dict],
        system_prompt: str,
        history: list[dict] | None = None,
        deadline: float | None = None,
        max_iterations: int | None = None,
    ) -> Iterator[dict]:
        limit = max_iterations or settings.max_iterations
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for item in history or []:
            # 只回放最终问答，绝不回放 tool / tool_calls 消息（会破坏协议配对）
            if item.get("role") in ("user", "assistant") and item.get("content"):
                messages.append({"role": item["role"], "content": item["content"]})
        messages.append({"role": "user", "content": user_prompt})
        existing_files = self._snapshot_files()

        try:
            client = self._get_client()
        except MissingApiKeyError as exc:
            yield {"type": "error", "content": str(exc)}
            yield {"type": "done"}
            return

        openai_tools = self._to_openai_tools(tools)
        finished = False

        for iteration in range(limit):
            if deadline is not None and time.monotonic() > deadline:
                yield {"type": "error", "content": "timeout: 超过执行时限"}
                break
            yield {"type": "round_start", "round": iteration + 1}
            yield {"type": "round_input", "messages": self._summarize_messages(messages)}

            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=settings.max_tokens,
                    messages=messages,
                    tools=openai_tools,
                )
            except Exception as exc:  # 网络 / 鉴权 / 限流等
                yield {"type": "error", "content": f"{type(exc).__name__}: {exc}"}
                break

            assistant_msg = response.choices[0].message
            tool_calls = assistant_msg.tool_calls or []

            if assistant_msg.content:
                yield {
                    "type": "model_text",
                    "content": display_path(assistant_msg.content),
                    "round": iteration + 1,
                }

            if not tool_calls:
                finished = True
                break

            # 回填 assistant 消息（含 tool_calls）
            messages.append({
                "role": "assistant",
                "content": assistant_msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            })

            # 逐个执行工具
            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    tool_input = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    tool_input = {}

                yield {
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "tool_input": display_path(json.dumps(tool_input, ensure_ascii=False)),
                    "round": iteration + 1,
                    "tool_source": self._tool_source(tool_name),
                    "mcp_server": self._mcp_server_of(tool_name),
                }

                result_str, source, extra = self.tool_registry.dispatch(
                    tool_name, tool_input, self.executor
                )
                event = {
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "result": display_path(result_str[:2000]),
                    "round": iteration + 1,
                    "tool_source": source,
                    "mcp_server": extra.get("mcp_server"),
                }
                if extra.get("references"):
                    event["references"] = extra["references"]
                if extra.get("reference_cards"):
                    event["reference_cards"] = extra["reference_cards"]
                yield event

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str[:8000],
                })
        else:
            yield {"type": "error", "content": f"达到最大迭代次数 {limit}"}

        files = self._collect_new_files(existing_files)
        yield {"type": "files", "files": files}
        yield {"type": "done"}

        if settings.save_chat_log:
            self._save_log(model, user_prompt, messages, finished)

    # ------------------------------------------------------------------ #
    # 模式 2：反思循环（DeepSeek JSON-mode + reasoning_content 流式）
    # ------------------------------------------------------------------ #
    def _stream_reflection(
        self,
        user_prompt: str,
        model: str,
        tools: list[dict],
        deadline: float | None = None,
    ) -> Iterator[dict]:
        from app.core.llm import chat, get_llm_client

        existing_files = self._snapshot_files()
        tools_desc = "\n".join(
            f"- `{t['name']}`: {t.get('description', '')}" for t in tools
        )

        yield {"type": "reflection_start", "mode": "plan_action_reflection_answer"}

        # Step 1: Plan
        try:
            plan_text = chat(
                PLAN_PROMPT_TEMPLATE.format(query=user_prompt, tools_desc=tools_desc),
                model=settings.plan_model,
                json_mode=True,
            )
            actions = self._parse_actions(plan_text)
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "content": f"规划失败: {type(exc).__name__}: {exc}"}
            yield {"type": "done"}
            return
        yield {"type": "plan", "actions": actions}

        # Step 2: Action
        memory: list[dict] = []
        for event in self._execute_actions(actions):
            if event["type"] == "memory_item":
                memory.append({"tool": event["tool"], "input": event["input"], "result": event["result"]})
            else:
                yield event

        # Step 3: Reflection
        try:
            reflect_text = chat(
                REFLECTION_PROMPT_TEMPLATE.format(
                    query=user_prompt,
                    memory=json.dumps(memory, ensure_ascii=False)[:3000],
                    tools_desc=tools_desc,
                ),
                model=settings.plan_model,
                json_mode=True,
            )
            reflect_actions = self._parse_actions(reflect_text)
        except Exception:  # noqa: BLE001
            reflect_actions = []
        yield {"type": "reflection_plan", "actions": reflect_actions}
        if reflect_actions:
            for event in self._execute_actions(reflect_actions):
                if event["type"] == "memory_item":
                    memory.append({"tool": event["tool"], "input": event["input"], "result": event["result"]})
                else:
                    yield event

        # Step 4: Answer（DeepSeek-r1 流式，分离 reasoning_content）
        try:
            client = get_llm_client()
            final_prompt = FINAL_ANSWER_TEMPLATE.format(
                memory=json.dumps(memory, ensure_ascii=False)[:4000],
                query=user_prompt,
            )
            completion = client.chat.completions.create(
                model=settings.answer_model,
                messages=[{"role": "user", "content": final_prompt}],
                stream=True,
            )
            for chunk in completion:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "reasoning_content", None):
                    yield {"type": "reasoning_delta", "content": delta.reasoning_content}
                elif delta.content:
                    yield {"type": "model_text", "content": delta.content}
        except Exception as exc:  # noqa: BLE001
            yield {"type": "error", "content": f"回答生成失败: {type(exc).__name__}: {exc}"}

        files = self._collect_new_files(existing_files)
        yield {"type": "files", "files": files}
        yield {"type": "done"}

    def _execute_actions(self, actions: list[dict]) -> list[dict]:
        """执行反思模式下的工具调用，返回事件列表（tool_call/tool_result/memory_item）。"""
        events: list[dict] = []
        for action in actions:
            tool_name = action.get("tool", "")
            tool_input = action.get("input", {}) or {}
            events.append({
                "type": "tool_call",
                "tool_name": tool_name,
                "tool_input": display_path(json.dumps(tool_input, ensure_ascii=False)),
                "tool_source": self._tool_source(tool_name),
                "mcp_server": self._mcp_server_of(tool_name),
            })
            result_str, source, extra = self.tool_registry.dispatch(
                tool_name, tool_input, self.executor
            )
            event = {
                "type": "tool_result",
                "tool_name": tool_name,
                "result": display_path(result_str[:2000]),
                "tool_source": source,
                "mcp_server": extra.get("mcp_server"),
            }
            if extra.get("references"):
                event["references"] = extra["references"]
            if extra.get("reference_cards"):
                event["reference_cards"] = extra["reference_cards"]
            events.append(event)
            events.append({"type": "memory_item", "tool": tool_name, "input": tool_input, "result": result_str[:3000]})
        return events

    @staticmethod
    def _parse_actions(text: str) -> list[dict]:
        """从 JSON-mode 输出中提取 [{tool, input}, ...]。"""
        import re

        match = re.search(r"(\[[\s\S]*\])", text or "")
        if not match:
            return []
        try:
            data = json.loads(match.group(1))
        except (TypeError, json.JSONDecodeError):
            return []
        return [item for item in data if isinstance(item, dict) and item.get("tool")]

    @staticmethod
    def _tool_source(tool_name: str) -> str:
        if tool_name.startswith("mcp_"):
            return "mcp"
        if tool_name in ("rag_query", "rag_ingest"):
            return "rag"
        if tool_name == "web_research":
            return "web"
        return "builtin"

    @staticmethod
    def _mcp_server_of(tool_name: str) -> str | None:
        if tool_name.startswith("mcp_"):
            return tool_name.split("__", 1)[0][4:]
        return None

    @staticmethod
    def _summarize_messages(messages: list[dict]) -> list[dict]:
        summary = []
        for index, msg in enumerate(messages):
            content = msg.get("content", "")
            if isinstance(content, str):
                preview = display_path(content[:200])
            elif isinstance(content, list):
                types = [
                    item.get("type", "?") if isinstance(item, dict) else getattr(item, "type", "?")
                    for item in content
                ]
                preview = f"[{', '.join(types)}]"
            else:
                preview = "(content blocks)"
            summary.append({"index": index, "role": msg["role"], "preview": preview})
        return summary

    def _save_log(self, model: str, user_prompt: str, messages: list[dict], finished: bool) -> None:
        from datetime import timezone

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.executor.output_dir / f"chat_log_{ts}.json"
        payload = {
            "model": model,
            "user_prompt": user_prompt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "finished": finished,
            "messages": _serialize(messages),
        }
        try:
            log_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # 非流式运行（便于脚本 / 测试）
    # ------------------------------------------------------------------ #
    def run(self, user_prompt: str, model: str | None = None, **kwargs) -> dict:
        rounds = 0
        files: list[str] = []
        error: str | None = None
        finished = False
        answer_parts: list[str] = []
        for event in self.stream(user_prompt, model, **kwargs):
            if event["type"] == "round_start":
                rounds = max(rounds, event["round"])
            elif event["type"] == "model_text":
                answer_parts.append(event.get("content", ""))
            elif event["type"] == "files":
                files = [f["name"] for f in event["files"]]
            elif event["type"] == "error":
                error = event["content"]
            elif event["type"] == "done":
                finished = True
        return {
            "model": model or settings.default_model,
            "prompt": user_prompt,
            "rounds": rounds,
            "finished": finished,
            "files": files,
            "error": error,
            "answer": "".join(answer_parts)[-4000:],
        }
