"""
Enhanced MCP (Model Context Protocol) Routes.

Provides HTTP endpoints for AI agents to interact with the OptionGreek trading system.
Supports Claude Desktop, Cursor, and other MCP-compatible AI assistants.
"""

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import Any, Dict, List, Optional
import json
import asyncio

from app.services.mcp_service import get_mcp_service
from app.services.fyers_auth import get_auth_service

router = APIRouter()


def get_mcp():
    """Dependency to get MCP service."""
    return get_mcp_service()


def check_auth():
    """Dependency to check authentication status."""
    auth = get_auth_service()
    status = auth.get_auth_status()
    return status.get("authenticated", False)


@router.get("/mcp/tools")
async def list_tools(mcp=Depends(get_mcp)):
    """
    List all available tools for AI agents.
    Conforms to MCP 'tools/list' specification.
    
    Returns:
        List of tools with names, descriptions, and input schemas
    """
    return {
        "tools": mcp.get_tools_manifest()
    }


@router.post("/mcp/call")
async def call_tool(request: Request, mcp=Depends(get_mcp)):
    """
    Execute a tool call from an AI agent.
    Conforms to MCP 'tools/call' specification.
    
    Request body:
        {
            "name": "tool_name",
            "arguments": {...}
        }
    
    Returns:
        Tool execution result with content array
    """
    try:
        body = await request.json()
        tool_name = body.get("name")
        arguments = body.get("arguments", {})
        
        if not tool_name:
            raise HTTPException(status_code=400, detail="Tool name is required")
        
        result = await mcp.call_tool(tool_name, arguments)
        return result
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mcp/status")
async def get_mcp_status(is_authenticated: bool = Depends(check_auth)):
    """
    Get MCP server status and authentication state.
    
    Returns:
        Server status, authentication state, and available capabilities
    """
    auth = get_auth_service()
    auth_status = auth.get_auth_status()
    
    return {
        "server": "OptionGreek MCP Server",
        "version": "1.0.0",
        "status": "online",
        "authenticated": auth_status.get("authenticated", False),
        "user": auth_status.get("user_info", {}).get("name") if auth_status.get("authenticated") else None,
        "capabilities": [
            "portfolio_management",
            "order_execution", 
            "market_data",
            "option_chain_analysis"
        ],
        "tools_count": 12
    }


@router.get("/mcp/config")
async def get_mcp_config():
    """
    Returns configuration snippets for AI clients.
    
    Provides ready-to-use configuration for:
    - Claude Desktop
    - Cursor IDE
    - Custom MCP clients
    """
    # Base server URL (update for production)
    server_url = "http://localhost:8000/api/v1"
    
    return {
        "server_url": server_url,
        "configurations": {
            "claude_desktop": {
                "mcpServers": {
                    "optiongreek": {
                        "url": f"{server_url}/mcp",
                        "type": "http",
                        "name": "OptionGreek Trading"
                    }
                }
            },
            "cursor": {
                "mcp": {
                    "servers": {
                        "optiongreek": {
                            "url": f"{server_url}/mcp",
                            "enabled": True
                        }
                    }
                }
            }
        },
        "instructions": {
            "claude_desktop": [
                "1. Open Claude Desktop settings",
                "2. Go to MCP Servers section", 
                "3. Add new server with the configuration above",
                "4. Restart Claude Desktop"
            ],
            "cursor": [
                "1. Open Cursor settings (Cmd/Ctrl + ,)",
                "2. Search for 'MCP'",
                "3. Add the server configuration",
                "4. Reload Cursor"
            ]
        },
        "test_command": f"curl {server_url}/mcp/status"
    }


@router.post("/mcp/batch")
async def batch_call(request: Request, mcp=Depends(get_mcp)):
    """
    Execute multiple tool calls in a single request.
    Useful for reducing latency when multiple operations are needed.
    
    Request body:
        {
            "calls": [
                {"name": "tool1", "arguments": {...}},
                {"name": "tool2", "arguments": {...}}
            ]
        }
    
    Returns:
        Array of results for each tool call
    """
    try:
        body = await request.json()
        calls = body.get("calls", [])
        
        if not calls:
            raise HTTPException(status_code=400, detail="No tool calls provided")
        
        if len(calls) > 10:
            raise HTTPException(status_code=400, detail="Maximum 10 calls per batch")
        
        results = []
        for call in calls:
            tool_name = call.get("name")
            arguments = call.get("arguments", {})
            
            if not tool_name:
                results.append({"isError": True, "content": [{"type": "text", "text": "Missing tool name"}]})
                continue
            
            result = await mcp.call_tool(tool_name, arguments)
            results.append(result)
        
        return {"results": results}
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mcp/health")
async def mcp_health():
    """
    Simple health check endpoint for monitoring.
    """
    return {"status": "healthy", "service": "mcp"}
