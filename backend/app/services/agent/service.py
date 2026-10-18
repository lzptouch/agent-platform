"""Agent 编排：plan -> action -> (reflection -> action) -> answer，源自 notebook 的 agent/agent_reflection。"""
import logging

from app.services.agent.answer import final_answer
from app.services.agent.planner import adjust_format, agent_plan
from app.services.agent.reflection import reflection
from app.services.agent.tools import process_actions

logger = logging.getLogger(__name__)


def _normalize_actions(raw_actions: list[dict] | None) -> list[dict]:
    """反思输出的 prompts 可能是字符串，统一展平为 {action_name, prompt} 列表。"""
    if not raw_actions:
        return []
    normalized = []
    for item in raw_actions:
        prompts = item.get("prompts")
        if isinstance(prompts, list):
            normalized.extend(adjust_format([item]))
        elif prompts:
            normalized.append({"action_name": item["action_name"], "prompt": str(prompts)})
    return normalized


def agent(user_query: str) -> dict:
    """基础流程：plan -> action -> answer。"""
    memory: list[dict] = []

    logger.info("开始任务规划...")
    actions = _normalize_actions(agent_plan(user_query))

    if actions:
        logger.info("开始任务执行...")
        memory.extend(process_actions(actions))

    result = final_answer(memory, user_query)
    return {"query": user_query, "plan": actions, "memory": memory, **result}


def agent_reflection(user_query: str) -> dict:
    """增强流程：plan -> action -> reflection -> action -> answer。"""
    memory: list[dict] = []

    logger.info("开始任务规划...")
    actions = _normalize_actions(agent_plan(user_query))

    if actions:
        logger.info("开始任务执行...")
        memory.extend(process_actions(actions))

    reflect_actions = _normalize_actions(reflection(user_query, memory))
    if reflect_actions:
        logger.info("回顾内容，进行反思补充查询...")
        memory.extend(process_actions(reflect_actions))

    result = final_answer(memory, user_query)
    return {
        "query": user_query,
        "plan": actions,
        "reflection_plan": reflect_actions,
        "memory": memory,
        **result,
    }
