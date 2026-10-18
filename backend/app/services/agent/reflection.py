"""Agent 反思模块：回顾已有信息，判断是否需要补充查询，源自 notebook。"""
import logging

from app.services.agent.planner import (
    TOOL_DOC_SECTIONS,
    TOOL_RULES,
    _parse_actions,
    middle_json_model,
)

logger = logging.getLogger(__name__)

REFLECTION_PROMPT_TEMPLATE = '''
你是一个专业的汽车销售助手的规划模块。你的任务是：
1. 分析用户的查询:{0}
2. 基于已有的信息，是否还需要延伸再进行查询

##目前已有的信息:
{1}


## 可用工具
1. **本地文档搜索**：搜索本地星辰电动ES9的文档，包含以下章节：
   - {2}

2. **网络搜索**：在互联网上搜索相关信息

{3}

###重要！
至多再扩展不超过3个查询，如果需要扩展则按照下面的输出格式输出，如果不需要则返回None




## 输出格式
你的输出应该是一个JSON格式的列表，每个项目包含：
1. `action_name`：工具名称（"本地文档搜索"或"网络搜索"）
2. `prompts`：一个扩展的问题，如果是网络检索，prompt不包含电动ES9，如果是本地检索，prompt只包含询问电动ES9，检索内容一定是一个简单问题，不包含对比
[
  {{
    "action_name": "工具名称",
    "prompts":'查询内容'
  }}
  ...
]

'''


def reflection(user_query: str, memory: list[dict]) -> list[dict] | None:
    """根据已有信息反思，返回需要补充执行的动作清单（或 None）。"""
    prompt = REFLECTION_PROMPT_TEMPLATE.format(user_query, memory, TOOL_DOC_SECTIONS, TOOL_RULES)
    result = middle_json_model(prompt)
    logger.info("reflection 原始输出: %s", result)
    return _parse_actions(result)
