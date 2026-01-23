from fastapi import APIRouter, Request, HTTPException
from typing import Any, Dict, List
import json

from app.services.mcp_service import get_mcp_service

router = APIRouter()
mcp_service = get_mcp_service()

@router.get("/mcp/tools")
async def list_tools():
    """
    List tools available for AI agents.
    Conforms to MCP 'tools/list'
    """
    return {
        "tools": mcp_service.get_tools_manifest()
    }

@router.post("/mcp/call")
async def call_tool(request: Request):
    """
    Execute a tool call from an AI agent.
    Conforms to MCP 'tools/call'
    """
    try:
        body = await request.json()
        tool_name = body.get("name")
        arguments = body.get("arguments", {})
        
        if not tool_name:
            raise HTTPException(status_code=400, detail="Tool name is required")
            
        result = await mcp_service.call_tool(tool_name, arguments)
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/mcp/config")
async def get_mcp_config():
    """
    Returns the Cursor/Claude configuration snippet for this MCP server.
    """
    # In a real scenario, this would be the dynamic URL of the server
    server_url = "http://localhost:8000/api/v1/mcp"
    return {
        "mcpServers": {
            "option-greek": {
                "url": server_url,
                "type": "http"
            }
        },
        "instructions": "Copy this into your Cursor or Claude Desktop config to enable OptionGreek intelligence."
    }
