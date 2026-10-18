"""Agent 规划模块：任务拆解（plan）与格式调整（state），源自 notebook。"""
import json
import logging
import re

from app.core.config import settings
from app.core.llm import chat

logger = logging.getLogger(__name__)

TOOL_DOC_SECTIONS = """产品概述、设计理念、技术规格、驱动系统、电池与充电、智能座舱、智能驾驶、
安全系统、车身结构、舒适性与便利性、版本与配置、价格与购买信息、售后服务、
环保贡献、用户评价、竞品对比、常见问题、联系方式"""

TOOL_RULES = """## 工具选择规则
- 当查询明确涉及星辰电动ES9的具体信息、参数、功能或服务时，优先使用**本地文档搜索**
- 当查询涉及以下情况时，使用**网络搜索**：
  - 与其他品牌车型的详细对比
  - 最新市场动态或新闻
  - 非官方的用户体验或评测
  - 星辰电动ES9文档中可能没有的信息
  - 需要实时数据（如当前市场价格波动等）

## prompt延伸的规则
- 本地检索的查询扩展侧重于产品信息的深度查询
- 网络检索的查询扩展侧重于本地无法检索到的信息"""

PLAN_PROMPT_TEMPLATE = '''
你是一个专业的汽车销售助手的规划模块。你的任务是：
1. 分析用户的查询:{0}
2. 基于已有的信息，决定使用哪个工具来查询以获得更多需要的信息（本地文档搜索或网络搜索）
3. 将用户的原始查询拆解或延伸为1-2个相关问题，以获取更全面的信息


## 可用工具
1. **本地文档搜索**：搜索本地星辰电动ES9的文档，包含以下章节：
   - {1}

2. **网络搜索**：在互联网上搜索相关信息

{2}

## 输出格式
你的输出应该是一个JSON格式的列表，每个项目包含：
1. `action_name`：工具名称（"本地文档搜索"或"网络搜索"）
2. `prompts`：问题列表，第一个是原始查询，后面是拆解或延伸的问题
[
  {{
    "action_name": "工具名称",
    "prompts": [
      "原始查询",
      "拆解/延伸问题1",
      "拆解/延伸问题2",
      "拆解/延伸问题3"
    ]
  }}
]


## 示例

### 示例1：关于车辆规格的查询
用户：星辰电动ES9的续航里程是多少？

输出：
[
  {{
    "action_name": "本地文档搜索",
    "prompts": [
      "星辰电动ES9的续航里程是多少？",
      "星辰电动ES9的电池容量是多少？",
      "星辰电动ES9不同版本的续航里程有何区别？"
    ]
  }}
]


### 示例2：关于市场比较的查询
用户：星辰电动ES9和特斯拉Model Y相比怎么样？

输出：
[
  {{
    "action_name": "本地文档搜索",
    "prompts": [
      "星辰电动ES9的主要优势和特点是什么？",
      "星辰电动ES9的技术规格和配置有哪些？"
    ]
  }},
  {{
    "action_name": "网络搜索",
    "prompts": [
      "特斯拉Model Y主要优势和特点？",
      "特斯拉Model Y最新规格和价格",
      "特斯拉Model Y技术规格和配置有哪些"
    ]
  }}
]


### 示例3：关于日常问题
用户：你好
这种情况下都不需要调用，则输出为None

只需要输出JSON的部分，前后不要输出任何信息

'''


def middle_json_model(prompt: str) -> str:
    """调用规划模型（JSON 输出模式）。"""
    return chat(prompt, model=settings.plan_model, json_mode=True)


def extract_json_content(input_str: str) -> str | None:
    """提取字符串中第一个"["和最后一个"]"之间的内容（包括中括号）。"""
    pattern = r"(\[[\s\S]*\])"
    match = re.search(pattern, input_str)
    return match.group(1) if match else None


def _parse_actions(result: str) -> list[dict] | None:
    json_list = extract_json_content(result)
    try:
        return json.loads(json_list)
    except (TypeError, json.JSONDecodeError):
        return None


def agent_plan(query: str) -> list[dict] | None:
    """任务规划：将用户查询拆解为工具调用清单。"""
    prompt = PLAN_PROMPT_TEMPLATE.format(query, TOOL_DOC_SECTIONS, TOOL_RULES)
    result = middle_json_model(prompt)
    logger.info("plan 原始输出: %s", result)
    return _parse_actions(result)


def adjust_format(original_data: list[dict]) -> list[dict]:
    """调整数据格式，使每个 action_name 只搭配一个 prompt。"""
    adjusted_data = []
    for item in original_data:
        for prompt in item["prompts"]:
            adjusted_data.append({"action_name": item["action_name"], "prompt": prompt})
    return adjusted_data
