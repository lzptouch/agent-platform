"""MCP Server 管理接口。"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_mcp_manager
from app.schemas.mcp import (
    McpCallRequest,
    McpCallResponse,
    McpServerDetail,
    McpServerInfo,
    McpServerListResponse,
    McpToolInfo,
)
from app.services.mcp_manager import MCPManager

router = APIRouter(prefix="/mcp_servers", tags=["mcp"])


@router.get("", response_model=McpServerListResponse, summary="列出全部 MCP Server")
def list_servers(manager: MCPManager = Depends(get_mcp_manager)) -> McpServerListResponse:
    servers = [McpServerInfo(**s) for s in manager.list_servers()]
    return McpServerListResponse(total=len(servers), servers=servers)


@router.post("/reload", summary="重新扫描 MCP Server 目录（清空工具缓存）")
def reload_servers(manager: MCPManager = Depends(get_mcp_manager)) -> dict:
    manager._tools_cache.clear()
    return {"reloaded": len(manager.SERVER_REGISTRY), "servers": list(manager.SERVER_REGISTRY)}


@router.get("/{name}", response_model=McpServerDetail, summary="单个 Server 详情 + 工具列表")
def get_server(name: str, manager: MCPManager = Depends(get_mcp_manager)) -> McpServerDetail:
    try:
        info = next(s for s in manager.list_servers() if s["name"] == name)
    except StopIteration:
        raise HTTPException(status_code=404, detail=f"MCP Server 不存在: {name}")
    try:
        tools = [McpToolInfo(**t) for t in manager.list_tools(name)]
        return McpServerDetail(**info, tools=tools)
    except Exception as exc:  # noqa: BLE001
        return McpServerDetail(**info, tools=[], error=f"{type(exc).__name__}: {exc}")


@router.post("/{name}/start", summary="启用一个 MCP Server")
def start_server(name: str, manager: MCPManager = Depends(get_mcp_manager)) -> dict:
    try:
        return manager.start(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"启动失败: {type(exc).__name__}: {exc}")


@router.post("/{name}/stop", summary="停用一个 MCP Server")
def stop_server(name: str, manager: MCPManager = Depends(get_mcp_manager)) -> dict:
    try:
        return manager.stop(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{name}/tools", summary="获取 Server 注册的工具列表（静态反射，无需启动子进程）")
def list_tools(name: str, manager: MCPManager = Depends(get_mcp_manager)) -> dict:
    try:
        tools = manager.list_tools(name)
        return {"server": name, "tool_count": len(tools), "tools": tools}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.post("/{name}/call", response_model=McpCallResponse, summary="调用某个 MCP 工具")
def call_tool(
    name: str,
    payload: McpCallRequest,
    manager: MCPManager = Depends(get_mcp_manager),
) -> McpCallResponse:
    try:
        result = manager.call_tool(name, payload.tool, payload.arguments)
        error = result if result.startswith("MCP 工具调用") else None
        return McpCallResponse(server=name, tool=payload.tool, result=result, error=error)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
