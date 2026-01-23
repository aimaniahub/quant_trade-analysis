import json
from typing import Any, Dict, List, Optional
from app.services.fyers_market import get_market_service
from app.services.fyers_orders import get_order_service
from app.services.fyers_auth import get_auth_service

class MCPService:
    """
    Model Context Protocol (MCP) Service for OptionGreek.
    Exposes trading intelligence and account operations as AI-consumable tools.
    """
    
    def __init__(self):
        self.market_service = get_market_service()
        self.order_service = get_order_service()
        self.auth_service = get_auth_service()

    def get_tools_manifest(self) -> List[Dict[str, Any]]:
        """
        Returns the list of tools available for the AI agent.
        Conforms to MCP 'list_tools' specification.
        """
        return [
            {
                "name": "get_option_chain_analysis",
                "description": "Analyze the option chain for a specific symbol to detect anomalies, premium behavior, and market structure.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Trading symbol (e.g., NSE:NIFTY50-INDEX)"},
                        "strike_count": {"type": "integer", "description": "Number of strikes above/below ATM to analyze"}
                    },
                    "required": ["symbol"]
                }
            },
            {
                "name": "get_portfolio_summary",
                "description": "Get a summary of current holdings, positions, and available funds.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "place_trading_order",
                "description": "Place a buy or sell order. Use with caution.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "Stock/Index symbol"},
                        "qty": {"type": "integer", "description": "Quantity to trade"},
                        "side": {"type": "integer", "description": "1 for Buy, -1 for Sell"},
                        "type": {"type": "integer", "description": "1 for Limit, 2 for Market"}
                    },
                    "required": ["symbol", "qty", "side", "type"]
                }
            }
        ]

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a specific tool called by the AI agent.
        """
        try:
            if tool_name == "get_option_chain_analysis":
                symbol = arguments.get("symbol")
                strike_count = arguments.get("strike_count", 10)
                result = self.market_service.get_option_chain(symbol, strike_count)
                if result.get("success"):
                    # Summarize for the LLM
                    return {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Successfully fetched option chain for {symbol}. Spot: {result.get('spot_price')}. Analyze the following strikes for anomalies: {json.dumps(result.get('chain')[:5])}..."
                            }
                        ]
                    }
                return {"isError": True, "content": [{"type": "text", "text": result.get("error", "Unknown error")}]}

            elif tool_name == "get_portfolio_summary":
                funds = self.order_service.get_funds()
                positions = self.order_service.get_positions()
                holdings = self.order_service.get_holdings()
                
                summary = {
                    "available_cash": funds.get("available_cash", 0),
                    "positions_count": len(positions.get("netPositions", [])),
                    "holdings_count": len(holdings.get("holdings", []))
                }
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Portfolio Summary: {json.dumps(summary, indent=2)}"
                        }
                    ]
                }

            elif tool_name == "place_trading_order":
                # In a real MCP server, we might want manual confirmation for orders
                # But here we implement the tool as requested
                result = self.order_service.place_order(
                    symbol=arguments["symbol"],
                    qty=arguments["qty"],
                    side=arguments["side"],
                    type=arguments["type"]
                )
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Order placement result: {json.dumps(result)}"
                        }
                    ]
                }

            return {"isError": True, "content": [{"type": "text", "text": f"Tool {tool_name} not found"}]}

        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": str(e)}]}

# Singleton instance
_mcp_service = None

def get_mcp_service():
    global _mcp_service
    if _mcp_service is None:
        _mcp_service = MCPService()
    return _mcp_service
