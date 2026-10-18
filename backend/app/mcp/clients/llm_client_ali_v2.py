#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM + MCP 原生 Function-Calling Demo（重构版）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. 自动发现并注册 MCP 工具（高德地图）
2. 支持最多 N 次工具调用（默认 10）
3. 更清晰的结构、更稳健的异常处理
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# ──────────────────────────────── 环境变量 ────────────────────────────────
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(ENV_PATH, override=False)

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
GAODE_API_KEY = os.getenv("GAODE_API_KEY")

if not DASHSCOPE_API_KEY or not GAODE_API_KEY:
    raise EnvironmentError("请在 .env 或系统环境变量中提供 DASHSCOPE_API_KEY 与 GAODE_API_KEY")


# ──────────────────────────────── 日志配置 ────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
# 把 httpx / httpcore 调到 DEBUG 才显示，或直接 WARNING 以上才显示
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)  # 或 logging.DEBUG
log = logging.getLogger("llm-mcp")


# ──────────────────────────────── MCP 客户端 ────────────────────────────────
class MCPClient:
    """一次性上下文管理：调用即连接、退出即关闭"""

    def __init__(self, api_key: str):
        self._url = f"https://mcp.amap.com/mcp?key={api_key}"

    async def list_tools(self) -> List[dict]:
        async with streamablehttp_client(self._url) as (read, write, _):
            async with ClientSession(read, write) as s:
                await s.initialize()
                result = await s.list_tools()
                return [t.model_dump() for t in result.tools]  # type: ignore

    async def call_tool(self, name: str, params: Dict[str, Any]) -> str:
        async with streamablehttp_client(self._url) as (read, write, _):
            async with ClientSession(read, write) as s:
                await s.initialize()
                resp = await s.call_tool(name, params)
                if resp.content and resp.content[0].type == "text":
                    return resp.content[0].text
                return resp.model_dump_json()


# ──────────────────────────────── LLM + 工具交互 ────────────────────────────────
class LLMToolAgent:
    """封装与 LLM 的多轮对话，并在需要时动态调用 MCP 工具"""

    MODEL_NAME = "qwen-plus"
    MAX_TOOL_CALLS = 10

    def __init__(self, llm_api_key: str, mcp_client: MCPClient) -> None:
        self._llm = OpenAI(
            api_key=llm_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self._mcp = mcp_client
        self._tools_openai: List[dict] = []
        self._tool_schemas: Dict[str, Optional[dict]] = {}

    # ───────── 初始化：获取 MCP 工具，并转为 OpenAI schema ─────────
    async def bootstrap_tools(self) -> None:
        raw_tools = await self._mcp.list_tools()
        if not raw_tools:
            log.warning("MCP 未发现任何工具，后续将只使用语言模型")
            return

        for t in raw_tools:
            name = t["name"]
            desc = t.get("description", "")
            schema = t.get("inputSchema") or {
                # MCP 若未提供 schema，则给个兜底
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查询关键词"},
                    "num_results": {
                        "type": "integer",
                        "description": "需要返回的结果数量",
                        "default": 5,
                    },
                },
                "required": ["query"],
            }
            self._tools_openai.append(
                {
                    "type": "function",
                    "function": {"name": name, "description": desc, "parameters": schema},
                }
            )
            self._tool_schemas[name] = schema

        log.info("已加载 %d 个 MCP 工具：%s", len(self._tools_openai), ", ".join(self._tool_schemas))

    # ───────── 构造系统提示 ─────────
    def _system_prompt(self) -> str:
        if not self._tools_openai:
            return "你是一个智能助手，但当前无法使用任何外部工具。请基于已知知识回答问题。"

        tools_brief = "\n".join(
            f"- {t['function']['name']}: {t['function']['description']}" for t in self._tools_openai
        )
        return (
            f"你是一个智能助手，具备调用以下工具的能力：\n{tools_brief}\n\n"
            "在需要具体地理坐标的时候需要调用工具；"
            "另外，在需要最新、实时或地理信息时也需要调用工具；"
            "如果问题和工具没有直接联系，则直接回答。调用完成后，如果仍需更多数据可再次调用，"
            "最多允许调用 10 次；若信息已足够则给出最终答案。"
        )

    # ───────── 对话主循环 ─────────
    async def chat(self, user_query: str) -> str:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": user_query},
        ]

        for attempt in range(self.MAX_TOOL_CALLS + 1):  # +1 表示最后一次不给工具机会
            log.debug("LLM 请求轮次 %d", attempt + 1)
            response = self._llm.chat.completions.create(
                model=self.MODEL_NAME,
                messages=messages,
                tools=self._tools_openai if attempt < self.MAX_TOOL_CALLS else None,
                temperature=0.35,
            )

            assistant_msg = response.choices[0].message
            tool_calls = assistant_msg.tool_calls or []

            # ── 无需调用工具：直接给最终答案 ──
            if not tool_calls:
                return assistant_msg.content or "（空响应）"

            # ── 有工具调用请求 ──
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            # 逐个调用工具并追加结果
            for tc in tool_calls:
                name = tc.function.name
                try:
                    args_dict = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args_dict = {}
                log.info("→ 调用工具 %s, 参数: %s", name, args_dict)

                try:
                    tool_resp = await self._mcp.call_tool(name, args_dict)
                except Exception as e:  # noqa: BLE001
                    tool_resp = f"工具调用失败：{type(e).__name__} - {e}"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_resp,
                    }
                )

        # 超出最大调用次数，返回最新的工具结果或提示
        log.warning("达到最大工具调用次数，强制结束对话")
        return "已达到允许的最大工具调用次数，请结合以上信息自行判断。"


# ──────────────────────────────── DEMO ────────────────────────────────
async def demo() -> None:
    mcp = MCPClient(GAODE_API_KEY)
    agent = LLMToolAgent(DASHSCOPE_API_KEY, mcp)
    await agent.bootstrap_tools()

    queries = [
        "你好，请介绍一下自己",
        "南京今天的天气如何？",
        "南京安德门附近的加油站在哪儿？",
        "Python是什么编程语言？",
        "从深圳罗湖万象城开车到深圳南山海岸城需要多久？",
    ]

    for i, q in enumerate(queries, 1):
        print(f"\n====== 测试 {i}: {q} ======")
        answer = await agent.chat(q)
        print("🔹 Assistant:", answer)


if __name__ == "__main__":
    asyncio.run(demo())