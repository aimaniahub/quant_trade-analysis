"""
Fyers Orders Service

Provides methods for order management including placing, modifying,
and cancelling orders, as well as fetching orderbook, tradebook, and positions.
"""

from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime

from fyers_apiv3 import fyersModel

from app.core.config import get_settings
from app.services.fyers_auth import get_auth_service


class OrderType(int, Enum):
    """Order types for Fyers API."""
    LIMIT = 1
    MARKET = 2
    STOP_LIMIT = 3
    STOP_MARKET = 4


class OrderSide(int, Enum):
    """Order sides."""
    BUY = 1
    SELL = -1


class ProductType(str, Enum):
    """Product types."""
    INTRADAY = "INTRADAY"
    CNC = "CNC"  # Cash & Carry (delivery)
    MARGIN = "MARGIN"
    CO = "CO"  # Cover Order
    BO = "BO"  # Bracket Order


class OrderValidity(str, Enum):
    """Order validity types."""
    DAY = "DAY"
    IOC = "IOC"  # Immediate or Cancel


class FyersOrderService:
    """Service for order management via Fyers API."""
    
    def __init__(self):
        self.settings = get_settings()
        self.auth_service = get_auth_service()
    
    def _get_fyers(self) -> Optional[fyersModel.FyersModel]:
        """Get authenticated Fyers model."""
        return self.auth_service.get_fyers_model()
    
    # ============ Order Placement ============
    
    def place_order(
        self,
        symbol: str,
        qty: int,
        side: OrderSide,
        order_type: OrderType = OrderType.MARKET,
        product_type: ProductType = ProductType.INTRADAY,
        limit_price: float = 0,
        stop_price: float = 0,
        validity: OrderValidity = OrderValidity.DAY,
        stop_loss: float = 0,
        take_profit: float = 0,
        disclosed_qty: int = 0
    ) -> Dict[str, Any]:
        """
        Place a single order.
        
        Args:
            symbol: Trading symbol, e.g., "NSE:SBIN-EQ"
            qty: Order quantity
            side: BUY or SELL
            order_type: LIMIT, MARKET, STOP_LIMIT, STOP_MARKET
            product_type: INTRADAY, CNC, MARGIN, CO, BO
            limit_price: Limit price (for limit orders)
            stop_price: Stop price (for stop orders)
            validity: DAY or IOC
            stop_loss: Stop loss price (for CO/BO)
            take_profit: Take profit price (for BO)
            disclosed_qty: Disclosed quantity
            
        Returns:
            Dict with order response
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            data = {
                "symbol": symbol,
                "qty": qty,
                "type": order_type.value,
                "side": side.value,
                "productType": product_type.value,
                "limitPrice": limit_price,
                "stopPrice": stop_price,
                "validity": validity.value,
                "disclosedQty": disclosed_qty,
                "offlineOrder": False,
                "stopLoss": stop_loss,
                "takeProfit": take_profit
            }
            
            response = fyers.place_order(data)
            
            if response.get("s") == "ok":
                return {
                    "success": True,
                    "order_id": response.get("id"),
                    "message": response.get("message", "Order placed successfully"),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message", "Order placement failed"),
                    "code": response.get("code")
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def place_basket_orders(self, orders: List[Dict]) -> Dict[str, Any]:
        """
        Place multiple orders at once (max 10).
        
        Args:
            orders: List of order dictionaries
            
        Returns:
            Dict with basket order response
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            # Limit to 10 orders
            orders = orders[:10]
            response = fyers.place_basket_orders(orders)
            
            return {
                "success": True,
                "data": response,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ============ Order Modification ============
    
    def modify_order(
        self,
        order_id: str,
        order_type: Optional[OrderType] = None,
        limit_price: Optional[float] = None,
        qty: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Modify an existing order.
        
        Args:
            order_id: The order ID to modify
            order_type: New order type (optional)
            limit_price: New limit price (optional)
            qty: New quantity (optional)
            
        Returns:
            Dict with modification response
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            data = {"id": order_id}
            
            if order_type is not None:
                data["type"] = order_type.value
            if limit_price is not None:
                data["limitPrice"] = limit_price
            if qty is not None:
                data["qty"] = qty
            
            response = fyers.modify_order(data)
            
            if response.get("s") == "ok":
                return {
                    "success": True,
                    "order_id": order_id,
                    "message": "Order modified successfully"
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message", "Modification failed")
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ============ Order Cancellation ============
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel a pending order.
        
        Args:
            order_id: The order ID to cancel
            
        Returns:
            Dict with cancellation response
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            data = {"id": order_id}
            response = fyers.cancel_order(data)
            
            if response.get("s") == "ok":
                return {
                    "success": True,
                    "order_id": order_id,
                    "message": "Order cancelled successfully"
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message", "Cancellation failed")
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def cancel_basket_orders(self, order_ids: List[str]) -> Dict[str, Any]:
        """
        Cancel multiple orders.
        
        Args:
            order_ids: List of order IDs to cancel
            
        Returns:
            Dict with cancellation response
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            data = [{"id": oid} for oid in order_ids]
            response = fyers.cancel_basket_orders(data)
            
            return {
                "success": True,
                "data": response,
                "cancelled_count": len(order_ids)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ============ Order/Trade/Position Queries ============
    
    def get_orders(self) -> Dict[str, Any]:
        """
        Get all orders for the day (orderbook).
        
        Returns:
            Dict with order list
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated", "orders": []}
        
        try:
            response = fyers.orderbook()
            
            if response.get("s") == "ok":
                orders = response.get("orderBook", [])
                return {
                    "success": True,
                    "orders": orders,
                    "count": len(orders),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message"),
                    "orders": []
                }
        except Exception as e:
            return {"success": False, "error": str(e), "orders": []}
    
    def get_trades(self) -> Dict[str, Any]:
        """
        Get all trades for the day (tradebook).
        
        Returns:
            Dict with trade list
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated", "trades": []}
        
        try:
            response = fyers.tradebook()
            
            if response.get("s") == "ok":
                trades = response.get("tradeBook", [])
                return {
                    "success": True,
                    "trades": trades,
                    "count": len(trades),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message"),
                    "trades": []
                }
        except Exception as e:
            return {"success": False, "error": str(e), "trades": []}
    
    def get_positions(self) -> Dict[str, Any]:
        """
        Get current positions.
        
        Returns:
            Dict with positions list
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated", "positions": []}
        
        try:
            response = fyers.positions()
            
            if response.get("s") == "ok":
                positions = response.get("netPositions", [])
                return {
                    "success": True,
                    "positions": positions,
                    "count": len(positions),
                    "total_pnl": sum(p.get("pl", 0) for p in positions),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message"),
                    "positions": []
                }
        except Exception as e:
            return {"success": False, "error": str(e), "positions": []}
    
    def get_holdings(self) -> Dict[str, Any]:
        """
        Get holdings (delivery positions).
        
        Returns:
            Dict with holdings list
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated", "holdings": []}
        
        try:
            response = fyers.holdings()
            
            if response.get("s") == "ok":
                holdings = response.get("holdings", [])
                return {
                    "success": True,
                    "holdings": holdings,
                    "count": len(holdings),
                    "total_value": sum(h.get("holdingType", 0) for h in holdings),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message"),
                    "holdings": []
                }
        except Exception as e:
            return {"success": False, "error": str(e), "holdings": []}
    
    # ============ Position Management ============
    
    def exit_position(self, position_id: str) -> Dict[str, Any]:
        """
        Exit/square-off a position.
        
        Args:
            position_id: Position identifier (symbol-productType)
            
        Returns:
            Dict with exit response
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            data = {"id": position_id}
            response = fyers.exit_positions(data)
            
            if response.get("s") == "ok":
                return {
                    "success": True,
                    "message": "Position exited successfully"
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message", "Exit failed")
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def exit_all_positions(self) -> Dict[str, Any]:
        """
        Exit all open positions.
        
        Returns:
            Dict with exit response
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            # Exit all positions
            response = fyers.exit_positions(data={})
            
            return {
                "success": True,
                "message": "All positions exit initiated",
                "data": response
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def convert_position(
        self,
        symbol: str,
        qty: int,
        from_product: ProductType,
        to_product: ProductType,
        position_side: int = 1  # 1 for long, -1 for short
    ) -> Dict[str, Any]:
        """
        Convert position from one product type to another.
        
        Args:
            symbol: Position symbol
            qty: Quantity to convert
            from_product: Current product type
            to_product: Target product type
            position_side: 1 for long, -1 for short
            
        Returns:
            Dict with conversion response
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            data = {
                "symbol": symbol,
                "positionSide": position_side,
                "convertQty": qty,
                "convertFrom": from_product.value,
                "convertTo": to_product.value
            }
            
            response = fyers.convert_position(data)
            
            if response.get("s") == "ok":
                return {
                    "success": True,
                    "message": "Position converted successfully"
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message", "Conversion failed")
                }
        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton instance
_order_service: Optional[FyersOrderService] = None


def get_order_service() -> FyersOrderService:
    """Get the order service instance."""
    global _order_service
    if _order_service is None:
        _order_service = FyersOrderService()
    return _order_service
