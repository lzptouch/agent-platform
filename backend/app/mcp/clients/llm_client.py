#!/usr/bin/env python3
"""
LLM客户端 - 集成阿里云百炼和MCP
演示LLM如何自主调用搜索工具
使用阿里云百炼原生的Function Calling功能
"""

import asyncio
import json
import os
import sys
from pathlib import Path
import httpx
from typing import Any, Dict, Optional
from openai import OpenAI
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from dotenv import load_dotenv

# 项目根目录（app/mcp/clients/ 的上三级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# MCP 搜索服务器脚本路径
MCP_SERVER_SCRIPT = str(PROJECT_ROOT / "app" / "mcp" / "servers" / "search_server.py")

# 加载环境变量（项目根目录下的 .env）
load_dotenv(PROJECT_ROOT / ".env")

class LLMWithMCP:
    """集成LLM和MCP的客户端类，使用原生工具调用"""
    
    def __init__(self):
        # 配置阿里云百炼 OpenAI兼容客户端
        self.dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self.dashscope_api_key:
            raise ValueError("请设置DASHSCOPE_API_KEY环境变量")
            
        # 使用OpenAI兼容接口
        self.client = OpenAI(
            api_key=self.dashscope_api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        
        self.model_name = "qwen-plus"  # 使用通义千问Plus模型
        self.mcp_session: Optional[ClientSession] = None
        self.mcp_read = None
        self.mcp_write = None
        
        # 工具定义将从MCP服务器自动获取
        self.tools = []
        self.mcp_tools_info = []  # 存储MCP工具的详细信息
        
    async def initialize_mcp(self):
        """初始化MCP连接并自动加载工具定义"""
        try:
            # 启动MCP服务器进程
            server_params = StdioServerParameters(
                command=sys.executable,
                args=[MCP_SERVER_SCRIPT],
                env=None
            )
            
            # 连接到MCP服务器并获取工具定义
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    # 获取工具列表
                    tools_result = await session.list_tools()
                    print(f"🔧 从MCP服务器发现 {len(tools_result.tools)} 个工具:")
                    
                    # 转换为OpenAI格式的工具定义，在这里获取握手之后的工具定义，包含功能、参数等
                    openai_tools = []
                    mcp_tools_info = []
                    
                    for tool in tools_result.tools:
                        print(f"  📦 {tool.name}: {tool.description}")
                        
                        # 构建OpenAI格式的工具定义
                        openai_tool = {
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.description
                            }
                        }
                        
                        # 处理参数定义
                        if hasattr(tool, 'inputSchema') and tool.inputSchema:
                            openai_tool["function"]["parameters"] = tool.inputSchema
                            print(f"    📋 参数: {list(tool.inputSchema.get('properties', {}).keys())}")
                        else:
                            # 默认参数结构
                            openai_tool["function"]["parameters"] = {
                                "type": "object",
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "查询参数"
                                    },
                                    "num_results": {
                                        "type": "integer",
                                        "description": "返回结果数量，默认为5",
                                        "default": 5
                                    }
                                },
                                "required": ["query"]
                            }
                            print(f"    📋 使用默认参数结构")
                        
                        openai_tools.append(openai_tool)
                        mcp_tools_info.append({
                            "name": tool.name,
                            "description": tool.description,
                            "schema": tool.inputSchema if hasattr(tool, 'inputSchema') else None
                        })
                    
                    # 更新工具定义
                    self.tools = openai_tools
                    self.mcp_tools_info = mcp_tools_info
                    print(f"✅ 成功加载 {len(self.tools)} 个工具定义")
                    
                    return True
                    
        except Exception as e:
            print(f"❌ MCP初始化失败: {str(e)}")
            # 回退到默认工具定义
            self.tools = self._get_default_tools()
            self.mcp_tools_info = [
                {"name": "web_search", "description": "执行网络搜索获取最新信息"},
                {"name": "news_search", "description": "执行新闻搜索获取最新新闻"}
            ]
            print("🔄 使用默认工具定义")
            return False

    async def close_mcp(self):
        """关闭MCP连接（现在不需要了）"""
        pass

    def _get_default_tools(self):
        """默认工具定义（作为回退）"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "执行网络搜索获取最新信息",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "搜索关键词"},
                            "num_results": {"type": "integer", "description": "结果数量", "default": 5}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "news_search", 
                    "description": "执行新闻搜索获取最新新闻",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "新闻搜索关键词"},
                            "num_results": {"type": "integer", "description": "结果数量", "default": 5}
                        },
                        "required": ["query"]
                    }
                }
            }
        ]

    def build_system_prompt(self) -> str:
        """根据可用工具动态构建系统提示词"""
        if not self.mcp_tools_info:
            return "你是一个智能助手。当需要最新信息时，请告诉用户工具正在加载中。"
        
        # 根据实际可用工具动态生成提示词
        tools_desc = []
        for i, tool in enumerate(self.mcp_tools_info, 1):
            tools_desc.append(f"{i}. {tool['name']} - {tool['description']}")
        
        tools_text = "\n".join(tools_desc)
        
        return f"""你是一个智能助手，具有以下工具能力：

{tools_text}

重要：只有在以下明确情况下才使用工具：

必须使用工具的情况：
- 用户明确要求"搜索"、"查找"、"查询"某个话题
- 用户询问"今天"、"最新"、"现在"、"当前"的信息
- 用户询问实时数据：股价、汇率、天气、新闻等
- 用户询问2023年之后的信息或事件

不要使用工具的情况：
- 解释基本概念（如"Python是什么"、"机器学习原理"等）
- 回答常识性问题
- 提供教程或指导
- 用户只是想了解某个技术或概念的基本信息

请优先使用你的知识库回答问题，只有在确实需要最新或实时信息时才调用工具。"""

    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """调用MCP工具"""
        try:
            print(f"🔧 调用MCP工具: {tool_name}, 参数: {arguments}")
            
            # 每次调用时重新建立MCP连接
            server_params = StdioServerParameters(
                command=sys.executable,
                args=[MCP_SERVER_SCRIPT],
                env=None
            )
            
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    print(f"🔧 MCP工具返回: {result}")
                    if result.content:
                        return result.content[0].text if result.content[0].type == "text" else str(result.content[0])
                    return "工具调用成功但无返回内容"
                    
        except Exception as e:
            print(f"🔧 MCP工具调用异常: {type(e).__name__}: {str(e)}")
            return f"工具调用失败: {str(e)}"

    async def simulate_mcp_call(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """模拟MCP调用（当MCP不可用时）"""
        try:
            # 使用Serper API进行搜索
            serper_api_key = os.getenv("SERPER_API_KEY")
            if not serper_api_key:
                return "搜索功能不可用：请配置SERPER_API_KEY"
            
            query = arguments.get("query", "")
            num_results = arguments.get("num_results", 5)
            
            # 选择搜索类型
            search_type = "search" if tool_name == "web_search" else "news"
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://google.serper.dev/search" if tool_name == "web_search" else "https://google.serper.dev/news",
                    headers={
                        "X-API-KEY": serper_api_key,
                        "Content-Type": "application/json"
                    },
                    json={
                        "q": query,
                        "num": num_results,
                        "hl": "zh-cn",
                        "gl": "cn"
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    results = []
                    
                    # 处理搜索结果
                    if tool_name == "web_search" and "organic" in data:
                        for item in data["organic"][:num_results]:
                            results.append({
                                "title": item.get("title", ""),
                                "link": item.get("link", ""),
                                "snippet": item.get("snippet", "")
                            })
                    elif tool_name == "news_search" and "news" in data:
                        for item in data["news"][:num_results]:
                            results.append({
                                "title": item.get("title", ""),
                                "link": item.get("link", ""),
                                "snippet": item.get("snippet", ""),
                                "date": item.get("date", "")
                            })
                    
                    # 格式化返回结果
                    if results:
                        formatted_results = []
                        for i, result in enumerate(results, 1):
                            if tool_name == "news_search" and result.get("date"):
                                formatted_results.append(
                                    f"{i}. {result['title']}\n   时间: {result['date']}\n   摘要: {result['snippet']}\n   链接: {result['link']}"
                                )
                            else:
                                formatted_results.append(
                                    f"{i}. {result['title']}\n   摘要: {result['snippet']}\n   链接: {result['link']}"
                                )
                        return f"搜索结果：\n\n" + "\n\n".join(formatted_results)
                    else:
                        return f"未找到关于'{query}'的相关信息"
                else:
                    return f"搜索失败: HTTP {response.status_code}"
                    
        except Exception as e:
            return f"搜索出错: {str(e)}"

    async def chat_with_tools(self, user_message: str) -> str:
        """与LLM对话，支持原生工具调用"""
        try:
            # 构建对话消息
            messages = [
                {"role": "system", "content": self.build_system_prompt()},
                {"role": "user", "content": user_message}
            ]
            
            # 第一次调用LLM，提供工具定义
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=self.tools,
                temperature=0.7
            )
            
            assistant_message = response.choices[0].message
            
            # 检查是否需要调用工具
            if assistant_message.tool_calls:
                # 将助手消息添加到对话历史
                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": tool_call.type,
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments
                            }
                        } for tool_call in assistant_message.tool_calls
                    ]
                })
                
                # 执行工具调用
                for tool_call in assistant_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)
                    
                    print(f"🔍 调用工具: {function_name}")
                    print(f"📝 参数: {function_args}")
                    
                    # 调用实际的工具
                    if self.mcp_session:
                        tool_result = await self.call_mcp_tool(function_name, function_args)
                    else:
                        tool_result = await self.simulate_mcp_call(function_name, function_args)
                    
                    print(f"📊 工具结果: {tool_result[:200]}...")
                    
                    # 将工具结果添加到对话历史
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result
                    })
                
                # 再次调用LLM，基于工具结果生成最终回答
                # 重要：不再提供tools参数，避免再次生成工具调用
                # 添加明确的指导消息
                messages.append({
                    "role": "system", 
                    "content": "请基于上述工具搜索结果，用中文为用户提供完整、准确的回答。不要再调用工具，直接回答即可。"
                })
                
                final_response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.7
                    # 注意：这里不传入tools参数
                )
                
                return final_response.choices[0].message.content
            else:
                # 不需要工具调用，直接返回回答
                return assistant_message.content
                
        except Exception as e:
            return f"对话失败: {str(e)}"

async def main():
    """主函数 - 演示LLM+MCP原生工具调用"""
    print("=== LLM + MCP 原生工具调用演示 ===")
    print("使用阿里云百炼的Function Calling功能")
    print("演示LLM如何自主决定何时调用搜索工具")
    print()
    
    # 创建客户端
    client = LLMWithMCP()
    
    try:
        # 尝试初始化MCP（可选）
        await client.initialize_mcp()
        
        # 演示对话
        test_questions = [
            "你好，请介绍一下自己",
            "今天有什么重要新闻？",
            "Python是什么编程语言？",
            "最新的人工智能发展趋势如何？",
            "请搜索一下最近关于ChatGPT的新闻",
            "2024年中国GDP增长情况如何？"
        ]
        
        for i, question in enumerate(test_questions, 1):
            print(f"\n--- 测试 {i} ---")
            print(f"用户: {question}")
            
            response = await client.chat_with_tools(question)
            print(f"助手: {response}")
            print("-" * 80)
    
    finally:
        # 确保关闭MCP连接
        await client.close_mcp()

if __name__ == "__main__":
    asyncio.run(main()) 