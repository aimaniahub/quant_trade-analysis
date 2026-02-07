"""
Enhanced Model Context Protocol (MCP) Service for OptionGreek.

This service exposes trading intelligence and account operations as AI-consumable tools,
following the MCP standard for integration with Claude Desktop, Cursor, and other AI assistants.

Tools available:
- get_profile: Get user profile and account details
- get_funds: Get available funds and margin information
- get_holdings: Get stock holdings (long-term positions)
- get_positions: Get open positions with P&L
- get_orders: Get today's order history
- get_trades: Get executed trades
- place_order: Place buy/sell orders
- modify_order: Modify pending orders
- cancel_order: Cancel pending orders
- get_quotes: Get real-time quotes
- get_option_chain_analysis: Analyze option chain with Greeks
"""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime

from app.services.fyers_market import get_market_service
from app.services.fyers_orders import get_order_service, OrderType, OrderSide, ProductType
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
            # Profile & Account
            {
                "name": "get_profile",
                "description": "Get user profile and account details including name, email, and broker info.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_funds",
                "description": "Get available funds, margins, and buying power for trading.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            
            # Portfolio & Positions
            {
                "name": "get_holdings",
                "description": "Get stock holdings (long-term positions/CNC). Returns invested value, current value, and P&L.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_positions",
                "description": "Get open positions (intraday and F&O). Shows real-time P&L for each position.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            
            # Orders & Trades
            {
                "name": "get_orders",
                "description": "Get all orders placed today. Includes pending, completed, and rejected orders.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "get_trades",
                "description": "Get all executed trades for today. Shows fill prices, quantities, and timestamps.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            },
            
            # Order Management
            {
                "name": "place_order",
                "description": "Place a buy or sell order. Supports market, limit, stop-loss orders for equity and F&O.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading symbol, e.g., 'NSE:SBIN-EQ' for equity, 'NSE:NIFTY24FEB22000CE' for options"
                        },
                        "qty": {
                            "type": "integer",
                            "description": "Quantity to trade (lot size for F&O)"
                        },
                        "side": {
                            "type": "string",
                            "enum": ["BUY", "SELL"],
                            "description": "Order side: BUY or SELL"
                        },
                        "order_type": {
                            "type": "string", 
                            "enum": ["MARKET", "LIMIT", "STOP_LIMIT", "STOP_MARKET"],
                            "description": "Order type"
                        },
                        "product_type": {
                            "type": "string",
                            "enum": ["INTRADAY", "CNC", "MARGIN"],
                            "description": "Product type: INTRADAY for day trading, CNC for delivery, MARGIN for F&O"
                        },
                        "limit_price": {
                            "type": "number",
                            "description": "Limit price (required for LIMIT orders)"
                        },
                        "stop_price": {
                            "type": "number",
                            "description": "Stop/trigger price (required for STOP orders)"
                        }
                    },
                    "required": ["symbol", "qty", "side", "order_type", "product_type"]
                }
            },
            {
                "name": "modify_order",
                "description": "Modify a pending order. Can change price or quantity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "The order ID to modify"
                        },
                        "qty": {
                            "type": "integer",
                            "description": "New quantity (optional)"
                        },
                        "limit_price": {
                            "type": "number",
                            "description": "New limit price (optional)"
                        }
                    },
                    "required": ["order_id"]
                }
            },
            {
                "name": "cancel_order",
                "description": "Cancel a pending order.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "The order ID to cancel"
                        }
                    },
                    "required": ["order_id"]
                }
            },
            
            # Market Data
            {
                "name": "get_quotes",
                "description": "Get real-time quotes for one or more symbols. Returns LTP, open, high, low, close, volume.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbols": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of symbols, e.g., ['NSE:SBIN-EQ', 'NSE:RELIANCE-EQ']"
                        }
                    },
                    "required": ["symbols"]
                }
            },
            {
                "name": "get_option_chain_analysis",
                "description": "Analyze the option chain for an index/stock. Returns strikes with OI, IV, Greeks, and PCR.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Underlying symbol, e.g., 'NSE:NIFTY50-INDEX' or 'NSE:SBIN-EQ'"
                        },
                        "strike_count": {
                            "type": "integer",
                            "description": "Number of strikes above/below ATM to analyze (default: 10)"
                        }
                    },
                    "required": ["symbol"]
                }
            },
            
            # Portfolio Summary (combined view)
            {
                "name": "get_portfolio_summary",
                "description": "Get a complete summary: funds, holdings, positions, and today's P&L in one call.",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a specific tool called by the AI agent.
        Returns MCP-formatted response with content array.
        """
        try:
            # Profile & Account
            if tool_name == "get_profile":
                return await self._get_profile()
            
            elif tool_name == "get_funds":
                return await self._get_funds()
            
            # Portfolio & Positions
            elif tool_name == "get_holdings":
                return await self._get_holdings()
            
            elif tool_name == "get_positions":
                return await self._get_positions()
            
            # Orders & Trades
            elif tool_name == "get_orders":
                return await self._get_orders()
            
            elif tool_name == "get_trades":
                return await self._get_trades()
            
            # Order Management
            elif tool_name == "place_order":
                return await self._place_order(arguments)
            
            elif tool_name == "modify_order":
                return await self._modify_order(arguments)
            
            elif tool_name == "cancel_order":
                return await self._cancel_order(arguments)
            
            # Market Data
            elif tool_name == "get_quotes":
                return await self._get_quotes(arguments)
            
            elif tool_name == "get_option_chain_analysis":
                return await self._get_option_chain_analysis(arguments)
            
            # Combined Summary
            elif tool_name == "get_portfolio_summary":
                return await self._get_portfolio_summary()
            
            else:
                return self._error_response(f"Tool '{tool_name}' not found")

        except Exception as e:
            return self._error_response(str(e))

    # ========== Tool Implementations ==========

    async def _get_profile(self) -> Dict[str, Any]:
        """Get user profile."""
        fyers = self.auth_service.get_fyers_model()
        if not fyers:
            return self._error_response("Not authenticated. Please login first.")
        
        try:
            response = fyers.get_profile()
            if response.get("s") == "ok":
                data = response.get("data", {})
                return self._success_response(
                    f"**User Profile**\n"
                    f"- Name: {data.get('name', 'N/A')}\n"
                    f"- Email: {data.get('email_id', 'N/A')}\n"
                    f"- Client ID: {data.get('fy_id', 'N/A')}\n"
                    f"- PAN: {data.get('pan', 'N/A')}"
                )
            return self._error_response(response.get("message", "Failed to fetch profile"))
        except Exception as e:
            return self._error_response(str(e))

    async def _get_funds(self) -> Dict[str, Any]:
        """Get available funds."""
        fyers = self.auth_service.get_fyers_model()
        if not fyers:
            return self._error_response("Not authenticated. Please login first.")
        
        try:
            response = fyers.funds()
            if response.get("s") == "ok":
                fund_limit = response.get("fund_limit", [])
                
                # Parse fund data
                equity_fund = next((f for f in fund_limit if f.get("title") == "Total Balance"), {})
                available = equity_fund.get("equityAmount", 0)
                
                return self._success_response(
                    f"**Available Funds**\n"
                    f"- Total Balance: ₹{available:,.2f}\n"
                    f"- Margin Used: Check positions for details\n"
                    f"- Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            return self._error_response(response.get("message", "Failed to fetch funds"))
        except Exception as e:
            return self._error_response(str(e))

    async def _get_holdings(self) -> Dict[str, Any]:
        """Get stock holdings."""
        result = self.order_service.get_holdings()
        
        if result.get("success"):
            holdings = result.get("holdings", [])
            if not holdings:
                return self._success_response("No holdings found in your portfolio.")
            
            # Format holdings
            lines = ["**Stock Holdings**\n"]
            total_invested = 0
            total_current = 0
            
            for h in holdings[:10]:  # Limit to 10 for readability
                symbol = h.get("symbol", "Unknown")
                qty = h.get("quantity", 0)
                avg_price = h.get("costPrice", 0)
                ltp = h.get("ltp", 0)
                pnl = h.get("pl", 0)
                pnl_pct = h.get("pnlPercentage", 0)
                
                invested = qty * avg_price
                current = qty * ltp
                total_invested += invested
                total_current += current
                
                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(f"{emoji} **{symbol}**: {qty} @ ₹{avg_price:.2f} → ₹{ltp:.2f} (P&L: ₹{pnl:,.2f})")
            
            if len(holdings) > 10:
                lines.append(f"\n... and {len(holdings) - 10} more holdings")
            
            total_pnl = total_current - total_invested
            lines.append(f"\n**Total**: Invested ₹{total_invested:,.2f} | Current ₹{total_current:,.2f} | P&L ₹{total_pnl:,.2f}")
            
            return self._success_response("\n".join(lines))
        
        return self._error_response(result.get("error", "Failed to fetch holdings"))

    async def _get_positions(self) -> Dict[str, Any]:
        """Get open positions."""
        result = self.order_service.get_positions()
        
        if result.get("success"):
            positions = result.get("positions", [])
            if not positions:
                return self._success_response("No open positions.")
            
            lines = ["**Open Positions**\n"]
            total_pnl = 0
            
            for p in positions:
                symbol = p.get("symbol", "Unknown")
                qty = p.get("netQty", 0)
                if qty == 0:
                    continue
                    
                avg_price = p.get("avgPrice", 0)
                ltp = p.get("ltp", 0)
                pnl = p.get("pl", 0)
                product = p.get("productType", "")
                
                total_pnl += pnl
                side = "LONG" if qty > 0 else "SHORT"
                emoji = "🟢" if pnl >= 0 else "🔴"
                
                lines.append(f"{emoji} **{symbol}** ({product}): {side} {abs(qty)} @ ₹{avg_price:.2f} | LTP ₹{ltp:.2f} | P&L ₹{pnl:,.2f}")
            
            lines.append(f"\n**Total P&L**: ₹{total_pnl:,.2f}")
            
            return self._success_response("\n".join(lines))
        
        return self._error_response(result.get("error", "Failed to fetch positions"))

    async def _get_orders(self) -> Dict[str, Any]:
        """Get today's orders."""
        result = self.order_service.get_orders()
        
        if result.get("success"):
            orders = result.get("orders", [])
            if not orders:
                return self._success_response("No orders placed today.")
            
            lines = ["**Today's Orders**\n"]
            
            for o in orders[:10]:
                symbol = o.get("symbol", "Unknown")
                side = "BUY" if o.get("side") == 1 else "SELL"
                qty = o.get("qty", 0)
                price = o.get("limitPrice", 0) or o.get("tradedPrice", 0)
                status = o.get("status", 0)
                order_id = o.get("id", "")[:8]
                
                status_map = {1: "⏳ Pending", 2: "✅ Filled", 3: "❌ Rejected", 4: "🚫 Cancelled"}
                status_str = status_map.get(status, f"Status {status}")
                
                lines.append(f"- [{order_id}] {side} {qty} {symbol} @ ₹{price:.2f} - {status_str}")
            
            if len(orders) > 10:
                lines.append(f"\n... and {len(orders) - 10} more orders")
            
            return self._success_response("\n".join(lines))
        
        return self._error_response(result.get("error", "Failed to fetch orders"))

    async def _get_trades(self) -> Dict[str, Any]:
        """Get executed trades."""
        result = self.order_service.get_trades()
        
        if result.get("success"):
            trades = result.get("trades", [])
            if not trades:
                return self._success_response("No trades executed today.")
            
            lines = ["**Today's Trades**\n"]
            
            for t in trades[:10]:
                symbol = t.get("symbol", "Unknown")
                side = "BUY" if t.get("side") == 1 else "SELL"
                qty = t.get("tradedQty", 0)
                price = t.get("tradePrice", 0)
                time = t.get("orderDateTime", "")
                
                lines.append(f"- {side} {qty} {symbol} @ ₹{price:.2f} ({time})")
            
            if len(trades) > 10:
                lines.append(f"\n... and {len(trades) - 10} more trades")
            
            return self._success_response("\n".join(lines))
        
        return self._error_response(result.get("error", "Failed to fetch trades"))

    async def _place_order(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Place an order."""
        symbol = args.get("symbol")
        qty = args.get("qty")
        side = args.get("side", "").upper()
        order_type = args.get("order_type", "").upper()
        product_type = args.get("product_type", "INTRADAY").upper()
        limit_price = args.get("limit_price", 0)
        stop_price = args.get("stop_price", 0)
        
        # Map string values to enums
        side_map = {"BUY": OrderSide.BUY, "SELL": OrderSide.SELL}
        type_map = {"MARKET": OrderType.MARKET, "LIMIT": OrderType.LIMIT, 
                    "STOP_LIMIT": OrderType.STOP_LIMIT, "STOP_MARKET": OrderType.STOP_MARKET}
        product_map = {"INTRADAY": ProductType.INTRADAY, "CNC": ProductType.CNC, 
                       "MARGIN": ProductType.MARGIN}
        
        if side not in side_map:
            return self._error_response(f"Invalid side: {side}. Use BUY or SELL.")
        if order_type not in type_map:
            return self._error_response(f"Invalid order type: {order_type}.")
        
        result = self.order_service.place_order(
            symbol=symbol,
            qty=qty,
            side=side_map[side],
            order_type=type_map[order_type],
            product_type=product_map.get(product_type, ProductType.INTRADAY),
            limit_price=limit_price,
            stop_price=stop_price
        )
        
        if result.get("success"):
            order_id = result.get("order_id", "N/A")
            return self._success_response(
                f"✅ **Order Placed Successfully**\n"
                f"- Order ID: {order_id}\n"
                f"- {side} {qty} {symbol}\n"
                f"- Type: {order_type} | Product: {product_type}"
            )
        
        return self._error_response(result.get("error", "Failed to place order"))

    async def _modify_order(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Modify an order."""
        order_id = args.get("order_id")
        qty = args.get("qty")
        limit_price = args.get("limit_price")
        
        if not order_id:
            return self._error_response("Order ID is required.")
        
        result = self.order_service.modify_order(
            order_id=order_id,
            qty=qty,
            limit_price=limit_price
        )
        
        if result.get("success"):
            return self._success_response(f"✅ Order {order_id} modified successfully.")
        
        return self._error_response(result.get("error", "Failed to modify order"))

    async def _cancel_order(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Cancel an order."""
        order_id = args.get("order_id")
        
        if not order_id:
            return self._error_response("Order ID is required.")
        
        result = self.order_service.cancel_order(order_id)
        
        if result.get("success"):
            return self._success_response(f"✅ Order {order_id} cancelled successfully.")
        
        return self._error_response(result.get("error", "Failed to cancel order"))

    async def _get_quotes(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get real-time quotes."""
        symbols = args.get("symbols", [])
        
        if not symbols:
            return self._error_response("At least one symbol is required.")
        
        result = self.market_service.get_quotes(symbols)
        
        if result.get("success"):
            quotes = result.get("quotes", [])
            lines = ["**Real-Time Quotes**\n"]
            
            for q in quotes:
                symbol = q.get("symbol", "Unknown")
                ltp = q.get("ltp", 0)
                change = q.get("ch", 0)
                change_pct = q.get("chp", 0)
                
                emoji = "🟢" if change >= 0 else "🔴"
                lines.append(f"{emoji} **{symbol}**: ₹{ltp:.2f} ({change_pct:+.2f}%)")
            
            return self._success_response("\n".join(lines))
        
        return self._error_response(result.get("error", "Failed to fetch quotes"))

    async def _get_option_chain_analysis(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get option chain analysis."""
        symbol = args.get("symbol")
        strike_count = args.get("strike_count", 10)
        
        if not symbol:
            return self._error_response("Symbol is required.")
        
        result = self.market_service.get_option_chain(symbol, strike_count)
        
        if result.get("success"):
            spot = result.get("spot_price", 0)
            atm_strike = result.get("atm_strike", 0)
            chain = result.get("chain", [])[:5]  # Top 5 for readability
            
            lines = [
                f"**Option Chain: {symbol}**\n",
                f"- Spot: ₹{spot:,.2f}",
                f"- ATM Strike: ₹{atm_strike:,.0f}\n",
                "| Strike | CE OI | CE LTP | PE LTP | PE OI |",
                "|--------|-------|--------|--------|-------|"
            ]
            
            for strike in chain:
                s = strike.get("strike", 0)
                ce_oi = strike.get("ce_oi", 0)
                ce_ltp = strike.get("ce_ltp", 0)
                pe_ltp = strike.get("pe_ltp", 0)
                pe_oi = strike.get("pe_oi", 0)
                lines.append(f"| {s:.0f} | {ce_oi:,} | ₹{ce_ltp:.2f} | ₹{pe_ltp:.2f} | {pe_oi:,} |")
            
            return self._success_response("\n".join(lines))
        
        return self._error_response(result.get("error", "Failed to fetch option chain"))

    async def _get_portfolio_summary(self) -> Dict[str, Any]:
        """Get complete portfolio summary."""
        # Get all data
        positions_result = self.order_service.get_positions()
        holdings_result = self.order_service.get_holdings()
        
        positions = positions_result.get("positions", []) if positions_result.get("success") else []
        holdings = holdings_result.get("holdings", []) if holdings_result.get("success") else []
        
        # Calculate totals
        positions_pnl = sum(p.get("pl", 0) for p in positions if p.get("netQty", 0) != 0)
        holdings_count = len(holdings)
        positions_count = len([p for p in positions if p.get("netQty", 0) != 0])
        
        lines = [
            "**Portfolio Summary**\n",
            f"📊 **Positions**: {positions_count} open | Today's P&L: ₹{positions_pnl:,.2f}",
            f"📈 **Holdings**: {holdings_count} stocks",
            f"\n⏰ Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ]
        
        return self._success_response("\n".join(lines))

    # ========== Helper Methods ==========

    def _success_response(self, text: str) -> Dict[str, Any]:
        """Create a successful MCP response."""
        return {
            "content": [{"type": "text", "text": text}]
        }

    def _error_response(self, error: str) -> Dict[str, Any]:
        """Create an error MCP response."""
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"❌ Error: {error}"}]
        }


# Singleton instance
_mcp_service = None


def get_mcp_service():
    global _mcp_service
    if _mcp_service is None:
        _mcp_service = MCPService()
    return _mcp_service
