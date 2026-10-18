#!/usr/bin/env python3
"""
简化版演示：阿里云百炼原生工具调用
展示LLM如何自主决定何时调用工具
"""

import asyncio
import json
import os
import httpx
from openai import OpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class SimpleToolDemo:
    """简化的工具调用演示"""
    
    def __init__(self):
        # 配置阿里云百炼
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("请设置DASHSCOPE_API_KEY环境变量")
            
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        
        # 定义搜索工具
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "执行网络搜索获取最新信息。当需要查找实时、最新或未知信息时使用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "搜索关键词"
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
        ]
    
    def print_json(self, title: str, data: any, max_length: int = 1000):
        """格式化打印JSON数据"""
        print(f"\n📋 {title}:")
        print("=" * 60)
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(json_str) > max_length:
            print(json_str[:max_length] + "...\n[截断显示]")
        else:
            print(json_str)
        print("=" * 60)
    
    async def search_with_serper(self, query: str) -> str:
        """使用Serper API搜索"""
        api_key = os.getenv("SERPER_API_KEY")
        if not api_key:
            return "搜索功能需要配置SERPER_API_KEY"
        
        print(f"\n🌐 开始调用Serper API搜索...")
        print(f"   查询: {query}")
        
        try:
            async with httpx.AsyncClient() as client:
                request_data = {"q": query, "num": 3, "hl": "zh-cn"}
                print(f"   请求数据: {request_data}")
                
                response = await client.post(
                    "https://google.serper.dev/search",
                    headers={
                        "X-API-KEY": api_key,
                        "Content-Type": "application/json"
                    },
                    json=request_data,
                    timeout=10.0
                )
                
                print(f"   响应状态码: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # 打印原始搜索结果
                    self.print_json("Serper API 原始响应", data, 2000)
                    
                    results = []
                    organic_results = data.get("organic", [])
                    print(f"\n📊 处理搜索结果，找到 {len(organic_results)} 条结果")
                    
                    for i, item in enumerate(organic_results[:3], 1):
                        title = item.get('title', '')
                        snippet = item.get('snippet', '')
                        link = item.get('link', '')
                        
                        print(f"   结果 {i}: {title[:50]}...")
                        results.append(f"• {title}\n  {snippet}")
                    
                    formatted_result = "搜索结果：\n\n" + "\n\n".join(results) if results else "未找到相关信息"
                    
                    print(f"\n📝 格式化后的搜索结果:")
                    print("-" * 40)
                    print(formatted_result)
                    print("-" * 40)
                    
                    return formatted_result
                else:
                    error_msg = f"搜索失败: HTTP {response.status_code}"
                    print(f"   ❌ {error_msg}")
                    return error_msg
                    
        except Exception as e:
            error_msg = f"搜索出错: {str(e)}"
            print(f"   ❌ {error_msg}")
            return error_msg
    
    async def chat_with_tools(self, message: str) -> str:
        """智能对话，自动判断是否需要工具"""
        print(f"\n💭 用户输入: {message}")
        
        # 构建请求消息
        request_messages = [
            {"role": "system", "content": "你是一个智能助手。当需要最新信息或实时数据时，使用搜索工具。"},
            {"role": "user", "content": message}
        ]
        
        print(f"\n🤖 调用LLM (模型: qwen-plus)")
        print(f"   消息数量: {len(request_messages)}")
        print(f"   可用工具数量: {len(self.tools)}")
        
        # 第一步：让LLM决定是否需要调用工具
        response = self.client.chat.completions.create(
            model="qwen-plus",
            messages=request_messages,
            tools=self.tools,
            temperature=0.7
        )
        
        # 打印LLM原始响应
        response_dict = response.model_dump()
        self.print_json("LLM 原始响应", response_dict)
        
        assistant_msg = response.choices[0].message
        
        print(f"\n🔍 分析LLM响应:")
        print(f"   内容长度: {len(assistant_msg.content or '') if assistant_msg.content else 0}")
        print(f"   是否有工具调用: {'是' if assistant_msg.tool_calls else '否'}")
        
        # 检查是否需要调用工具
        if assistant_msg.tool_calls:
            print(f"   工具调用数量: {len(assistant_msg.tool_calls)}")
            
            for i, tool_call in enumerate(assistant_msg.tool_calls, 1):
                print(f"\n🔧 工具调用 {i}:")
                print(f"   ID: {tool_call.id}")
                print(f"   类型: {tool_call.type}")
                print(f"   函数名: {tool_call.function.name}")
                print(f"   参数 (原始): {tool_call.function.arguments}")
                
                try:
                    parsed_args = json.loads(tool_call.function.arguments)
                    print(f"   参数 (解析): {parsed_args}")
                except json.JSONDecodeError as e:
                    print(f"   参数解析失败: {e}")
            
            # 准备对话历史
            messages = [
                {"role": "system", "content": "你是一个智能助手。当需要最新信息或实时数据时，使用搜索工具。"},
                {"role": "user", "content": message},
                {
                    "role": "assistant",
                    "content": assistant_msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in assistant_msg.tool_calls
                    ]
                }
            ]
            
            print(f"\n📝 构建对话历史，当前消息数量: {len(messages)}")
            
            # 执行工具调用
            for i, tool_call in enumerate(assistant_msg.tool_calls, 1):
                print(f"\n🚀 执行工具调用 {i}/{len(assistant_msg.tool_calls)}")
                
                function_args = json.loads(tool_call.function.arguments)
                query = function_args.get("query", "")
                
                print(f"   执行函数: {tool_call.function.name}")
                print(f"   查询参数: {query}")
                
                # 调用搜索工具
                search_result = await self.search_with_serper(query)
                
                print(f"\n✅ 工具调用完成")
                print(f"   结果长度: {len(search_result)} 字符")
                
                # 添加工具结果到对话历史
                tool_message = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": search_result
                }
                messages.append(tool_message)
                
                print(f"   已添加工具结果到对话历史")
            
            print(f"\n🔄 基于工具结果调用LLM生成最终回答")
            print(f"   对话历史长度: {len(messages)} 条消息")
            
            # 基于搜索结果生成最终回答
            final_response = self.client.chat.completions.create(
                model="qwen-plus",
                messages=messages,
                temperature=0.7
            )
            
            # 打印最终LLM响应
            final_response_dict = final_response.model_dump()
            self.print_json("最终LLM响应", final_response_dict)
            
            final_content = final_response.choices[0].message.content
            print(f"\n✨ 最终回答长度: {len(final_content)} 字符")
            
            return final_content
        else:
            print("💬 LLM决定直接回答，无需调用工具")
            print(f"   回答长度: {len(assistant_msg.content)} 字符")
            return assistant_msg.content

async def main():
    """演示原生工具调用"""
    print("=" * 80)
    print("🎯 阿里云百炼原生工具调用详细演示")
    print("🔍 展示LLM如何智能决定何时调用搜索工具")
    print("📊 包含完整的日志和原始数据输出")
    print("=" * 80)
    
    demo = SimpleToolDemo()
    
    # 测试问题
    questions = [
        "你好，你是谁？",                    # 应该直接回答
        "什么是Python？",                   # 应该直接回答  
        "今天的重要新闻有哪些？",            # 应该调用搜索
        "最新的AI发展如何？",               # 应该调用搜索
    ]
    
    for i, question in enumerate(questions, 1):
        print(f"\n{'🎬 测试场景 ' + str(i):=^80}")
        print(f"预期行为: {['直接回答', '直接回答', '调用搜索', '调用搜索'][i-1]}")
        
        answer = await demo.chat_with_tools(question)
        
        print(f"\n🎭 最终输出:")
        print("─" * 60)
        print(answer)
        print("─" * 60)
        print(f"{'测试场景 ' + str(i) + ' 完成':=^80}")

if __name__ == "__main__":
    asyncio.run(main()) 