#!/usr/bin/env python3
"""
MCP服务器实现 - 搜索工具
提供Google搜索功能，通过Serper.dev API实现
"""

import os
from typing import Any, Dict, List
import httpx
from fastmcp import FastMCP
from mcp.types import TextContent
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 创建MCP服务器实例
mcp = FastMCP("Search Tools Server")

class SearchTool:
    """搜索工具类，封装Serper.dev API"""
    
    def __init__(self):
        self.api_key = os.getenv("SERPER_API_KEY")
        self.base_url = "https://google.serper.dev/search"
        
    async def search(self, query: str, num_results: int = 10) -> Dict[str, Any]:
        """执行搜索查询"""
        if not self.api_key:
            return {"error": "SERPER_API_KEY not configured"}
        
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }
        
        payload = {
            "q": query,
            "num": num_results,
            "gl": "cn",  # 地理位置：中国
            "hl": "zh-cn"  # 语言：中文
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as e:
            return {"error": f"HTTP error: {str(e)}"}
        except Exception as e:
            return {"error": f"Search failed: {str(e)}"}

# 创建搜索工具实例
search_tool = SearchTool()

@mcp.tool()
async def web_search(query: str, num_results: int = 10) -> List[TextContent]:
    """
    执行网络搜索
    
    Args:
        query: 搜索查询词
        num_results: 返回结果数量，默认10条
    
    Returns:
        搜索结果列表
    """
    result = await search_tool.search(query, num_results)
    
    if "error" in result:
        return [TextContent(
            type="text",
            text=f"搜索失败: {result['error']}"
        )]
    
    # 格式化搜索结果
    formatted_results = []
    
    # 添加搜索摘要
    if "searchParameters" in result:
        search_info = f"搜索查询: {result['searchParameters'].get('q', query)}\n"
        search_info += f"搜索时间: {result.get('searchMetadata', {}).get('createdAt', 'N/A')}\n\n"
        formatted_results.append(search_info)
    
    # 处理有机搜索结果
    if "organic" in result:
        formatted_results.append("=== 搜索结果 ===\n")
        for i, item in enumerate(result["organic"][:num_results], 1):
            title = item.get("title", "无标题")
            link = item.get("link", "#")
            snippet = item.get("snippet", "无描述")
            
            result_text = f"{i}. **{title}**\n"
            result_text += f"   链接: {link}\n"
            result_text += f"   摘要: {snippet}\n\n"
            formatted_results.append(result_text)
    

    
    # 处理知识图谱
    if "knowledgeGraph" in result:
        kg = result["knowledgeGraph"]
        formatted_results.append("=== 知识图谱 ===\n")
        formatted_results.append(f"标题: {kg.get('title', '')}\n")
        formatted_results.append(f"类型: {kg.get('type', '')}\n")
        formatted_results.append(f"描述: {kg.get('description', '')}\n\n")
    
    return [TextContent(
        type="text",
        text="".join(formatted_results)
    )]

@mcp.tool()
async def news_search(query: str, num_results: int = 10) -> List[TextContent]:
    """
    执行新闻搜索
    
    Args:
        query: 搜索查询词
        num_results: 返回结果数量，默认10条
    
    Returns:
        新闻搜索结果列表
    """
    if not search_tool.api_key:
        return [TextContent(
            type="text",
            text="搜索失败: SERPER_API_KEY not configured"
        )]
    
    headers = {
        "X-API-KEY": search_tool.api_key,
        "Content-Type": "application/json"
    }
    
    payload = {
        "q": query,
        "num": num_results,
        "gl": "cn",
        "hl": "zh-cn"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://google.serper.dev/news",
                headers=headers,
                json=payload,
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()
            
        # 格式化新闻结果
        formatted_results = []
        formatted_results.append(f"新闻搜索: {query}\n\n")
        
        if "news" in result:
            formatted_results.append("=== 新闻结果 ===\n")
            for i, item in enumerate(result["news"][:num_results], 1):
                title = item.get("title", "无标题")
                link = item.get("link", "#")
                snippet = item.get("snippet", "无描述")
                source = item.get("source", "未知来源")
                date = item.get("date", "未知时间")
                
                result_text = f"{i}. **{title}**\n"
                result_text += f"   来源: {source} | 时间: {date}\n"
                result_text += f"   链接: {link}\n"
                result_text += f"   摘要: {snippet}\n\n"
                formatted_results.append(result_text)
        
        return [TextContent(
            type="text",
            text="".join(formatted_results)
        )]
        
    except Exception as e:
        return [TextContent(
            type="text",
            text=f"新闻搜索失败: {str(e)}"
        )]

@mcp.tool()
async def weather_search(city: str) -> List[TextContent]:
    """
    查询天气信息
    
    Args:
        city: 城市名称
    
    Returns:
        天气查询结果
    """
    # 使用搜索API查询天气信息
    query = f"{city} 天气 今天"
    result = await search_tool.search(query, 3)
    
    if "error" in result:
        return [TextContent(
            type="text",
            text=f"天气查询失败: {result['error']}"
        )]
    
    # 格式化天气结果
    formatted_results = []
    formatted_results.append(f"🌤️ {city} 天气信息\n\n")
    
    if "organic" in result:
        for i, item in enumerate(result["organic"][:3], 1):
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            link = item.get("link", "")
            
            if "天气" in title or "温度" in snippet:
                result_text = f"{i}. {title}\n"
                result_text += f"   信息: {snippet}\n"
                result_text += f"   来源: {link}\n\n"
                formatted_results.append(result_text)
    
    if len(formatted_results) == 1:  # 只有标题，没有找到天气信息
        formatted_results.append("未找到详细天气信息，建议查看专业天气网站。")
    
    return [TextContent(
        type="text",
        text="".join(formatted_results)
    )]

def main():
    """启动MCP服务器"""
    print("启动MCP搜索工具服务器...")
    print("可用工具:")
    print("- web_search: 网络搜索")
    print("- news_search: 新闻搜索")
    print("- weather_search: 天气查询")
    print("按 Ctrl+C 停止服务器")
    
    # 运行MCP服务器
    mcp.run()

if __name__ == "__main__":
    main() 