"""Agent 工具执行模块：按 action_name 分发到本地 RAG 或网络搜索，源自 notebook。"""
import logging

from app.core.config import settings
from app.core.llm import get_llm_client
from app.services.rag.rag_chain import rag

logger = logging.getLogger(__name__)

WEB_SEARCH_PROMPT_TEMPLATE = """
Web 搜索结果：
{web_reference}

指令：你是一个/一名销售助手。使用提供的网络搜索结果，对给定的查询写一个全面而详细的回复。
确保在引用后使用 [number] 标记引用。
在回答的最后，列出带索引的相应参考文献，每个参考文献包含网络搜索结果中的网址和引用句子，按照您在上面标记的顺序排列，这些句子应该与网络搜索结果中的完全相同。
以下是参考文献的示例：
    [1] 网址：https://www.pocketgamer.biz/news/81670/tencent-and-netease-dominated-among-chinas-top-developers-in-q1/
        引用句子：腾讯在本季度占据了国内市场收入的大约50%，相比之下2022年第一季度为40%。

查询：{query}

请你过滤掉检索结果中的不相关性的部分进行回答，如果没有相关的部分，按照你自己的知识进行回答
"""


def web_search_answer(query: str) -> str:
    """网络检索 + LLM 带引用回答。"""
    if not settings.web_search_available:
        raise RuntimeError("未配置 SERPER_API_KEY，网络搜索不可用")

    from app.services.web.retrieval import web_retrieval

    web_reference = web_retrieval(query)
    prompt = WEB_SEARCH_PROMPT_TEMPLATE.format(web_reference=web_reference, query=query)

    client = get_llm_client()
    completion = client.chat.completions.create(
        model=settings.rag_model,
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content


def process_actions(actions: list[dict]) -> list[dict]:
    """
    依次执行 actions 内的动作，根据 action_name 分发到 rag() 或 web_search_answer()。

    Returns:
        memory: 包含每次调用结果的记忆列表
    """
    memory = []

    for action in actions:
        action_name = action["action_name"]
        prompt = action["prompt"]
        logger.info("正在执行%s: %s", action_name, prompt)

        try:
            if action_name == "本地文档搜索":
                _, answer = rag(prompt)
                result = answer
            elif action_name == "网络搜索":
                result = web_search_answer(prompt)
            else:
                result = f"未知的动作类型: {action_name}"

            memory.append({"提问": prompt, "结果": result})
        except Exception:
            logger.exception("执行动作失败: %s / %s", action_name, prompt)
            continue

    return memory
