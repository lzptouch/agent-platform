"""Agent 输出模块：基于记忆生成销售风格最终回答（deepseek-r1，带思考过程），源自 notebook。"""
from app.core.config import settings
from app.core.llm import get_llm_client

FINAL_PROMPT_TEMPLATE = """你是一个星辰电动ES9的智能销售助手，负责根据用户的问题和提供的参考内容生成回答。请严格按照以下要求生成回答：
基于提供的参考内容进行回答，如果原文没有参考内容,根据你自己的知识进行回答
你需要用有打动力的销售的语言进行输出，突出星辰电动的优势

参考内容：
{memory}

用户问题：{user_query}
"""


def final_answer(memory: list[dict], user_query: str) -> dict:
    """
    流式调用回答模型，收集思考过程与最终回复。

    Returns:
        {"reasoning": 思考过程, "answer": 最终回复}
    """
    client = get_llm_client()
    final_prompt = FINAL_PROMPT_TEMPLATE.format(memory=memory, user_query=user_query)

    completion = client.chat.completions.create(
        model=settings.answer_model,
        messages=[{"role": "user", "content": final_prompt}],
        stream=True,
    )

    reasoning_content = ""
    answer_content = ""

    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if getattr(delta, "reasoning_content", None):
            reasoning_content += delta.reasoning_content
        elif delta.content:
            answer_content += delta.content

    return {"reasoning": reasoning_content, "answer": answer_content}
