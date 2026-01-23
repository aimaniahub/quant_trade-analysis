"""
Fyers WebSocket Service

Provides real-time market data streaming via Fyers WebSocket APIs.
Includes Data Socket, Order Socket, and TBT Socket implementations.
"""

import asyncio
from typing import Optional, List, Dict, Callable, Any
from enum import Enum
import threading
import queue
import logging

from fyers_apiv3.FyersWebsocket import data_ws, order_ws

from app.core.config import get_settings


logger = logging.getLogger(__name__)


class DataType(str, Enum):
    """Data subscription types for Fyers WebSocket."""
    SYMBOL_UPDATE = "SymbolUpdate"
    DEPTH_UPDATE = "DepthUpdate"


class OrderDataType(str, Enum):
    """Order socket subscription types."""
    ORDERS = "OnOrders"
    TRADES = "OnTrades"
    POSITIONS = "OnPositions"
    GENERAL = "OnGeneral"
    ALL = "OnOrders,OnTrades,OnPositions,OnGeneral"


class FyersDataSocket:
    """
    Fyers Data Socket wrapper for real-time market data.
    
    Provides real-time updates for:
    - Symbol updates (LTP, OHLC, volume, etc.)
    - Depth updates (Level 2 bid/ask data)
    """
    
    def __init__(
        self,
        access_token: str,
        on_message: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        on_open: Optional[Callable] = None,
        lite_mode: bool = False
    ):
        self.access_token = access_token
        self.settings = get_settings()
        self._socket = None
        self._connected = False
        self._subscribed_symbols: List[str] = []
        self._message_queue: queue.Queue = queue.Queue()
        
        # Callbacks
        self._on_message = on_message
        self._on_error = on_error
        self._on_close = on_close
        self._on_open = on_open
        self._lite_mode = lite_mode
    
    def _handle_message(self, message: Dict):
        """Internal message handler."""
        self._message_queue.put(message)
        if self._on_message:
            self._on_message(message)
    
    def _handle_error(self, message: Dict):
        """Internal error handler."""
        logger.error(f"WebSocket error: {message}")
        if self._on_error:
            self._on_error(message)
    
    def _handle_close(self, message: str):
        """Internal close handler."""
        self._connected = False
        logger.info(f"WebSocket closed: {message}")
        if self._on_close:
            self._on_close(message)
    
    def _handle_open(self):
        """Internal open handler."""
        self._connected = True
        logger.info("WebSocket connected")
        if self._on_open:
            self._on_open()
    
    def connect(self):
        """Establish WebSocket connection."""
        try:
            self._socket = data_ws.FyersDataSocket(
                access_token=self.access_token,
                log_path="",
                litemode=self._lite_mode,
                write_to_file=False,
                reconnect=True,
                on_connect=self._handle_open,
                on_close=self._handle_close,
                on_error=self._handle_error,
                on_message=self._handle_message
            )
            self._socket.connect()
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False
    
    def subscribe(
        self,
        symbols: List[str],
        data_type: DataType = DataType.SYMBOL_UPDATE
    ):
        """
        Subscribe to real-time updates for symbols.
        
        Args:
            symbols: List of symbols to subscribe, e.g., ["NSE:SBIN-EQ"]
            data_type: Type of data (SymbolUpdate or DepthUpdate)
        """
        if self._socket and self._connected:
            # Limit to max subscriptions
            symbols = symbols[:self.settings.ws_max_subscriptions]
            self._socket.subscribe(symbols=symbols, data_type=data_type.value)
            self._subscribed_symbols.extend(symbols)
            logger.info(f"Subscribed to {len(symbols)} symbols")
    
    def unsubscribe(self, symbols: List[str]):
        """Unsubscribe from symbols."""
        if self._socket and self._connected:
            self._socket.unsubscribe(symbols=symbols)
            for s in symbols:
                if s in self._subscribed_symbols:
                    self._subscribed_symbols.remove(s)
    
    def disconnect(self):
        """Close WebSocket connection."""
        if self._socket:
            self._socket.close_connection()
            self._connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def subscribed_symbols(self) -> List[str]:
        return self._subscribed_symbols.copy()
    
    def get_latest_message(self, timeout: float = 0.1) -> Optional[Dict]:
        """Get the latest message from the queue."""
        try:
            return self._message_queue.get(timeout=timeout)
        except queue.Empty:
            return None


class FyersOrderSocket:
    """
    Fyers Order Socket wrapper for real-time order/position updates.
    
    Provides real-time updates for:
    - Orders (placed, modified, cancelled, executed)
    - Trades (trade confirmations)
    - Positions (position changes)
    - General alerts
    """
    
    def __init__(
        self,
        access_token: str,
        on_order: Optional[Callable] = None,
        on_trade: Optional[Callable] = None,
        on_position: Optional[Callable] = None,
        on_general: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        on_close: Optional[Callable] = None,
        on_open: Optional[Callable] = None
    ):
        self.access_token = access_token
        self._socket = None
        self._connected = False
        
        # Callbacks
        self._on_order = on_order
        self._on_trade = on_trade
        self._on_position = on_position
        self._on_general = on_general
        self._on_error = on_error
        self._on_close = on_close
        self._on_open = on_open
    
    def _handle_order(self, message: Dict):
        """Handle order updates."""
        if self._on_order:
            self._on_order(message)
    
    def _handle_trade(self, message: Dict):
        """Handle trade updates."""
        if self._on_trade:
            self._on_trade(message)
    
    def _handle_position(self, message: Dict):
        """Handle position updates."""
        if self._on_position:
            self._on_position(message)
    
    def _handle_general(self, message: Dict):
        """Handle general updates."""
        if self._on_general:
            self._on_general(message)
    
    def _handle_error(self, message: Dict):
        """Handle errors."""
        logger.error(f"Order socket error: {message}")
        if self._on_error:
            self._on_error(message)
    
    def _handle_close(self, message: str):
        """Handle connection close."""
        self._connected = False
        logger.info(f"Order socket closed: {message}")
        if self._on_close:
            self._on_close(message)
    
    def _handle_open(self):
        """Handle connection open."""
        self._connected = True
        logger.info("Order socket connected")
        if self._on_open:
            self._on_open()
    
    def connect(self):
        """Establish Order Socket connection."""
        try:
            self._socket = order_ws.FyersOrderSocket(
                access_token=self.access_token,
                write_to_file=False,
                log_path="",
                on_connect=self._handle_open,
                on_close=self._handle_close,
                on_error=self._handle_error,
                on_general=self._handle_general,
                on_orders=self._handle_order,
                on_positions=self._handle_position,
                on_trades=self._handle_trade
            )
            self._socket.connect()
            return True
        except Exception as e:
            logger.error(f"Failed to connect order socket: {e}")
            return False
    
    def subscribe(self, data_type: OrderDataType = OrderDataType.ALL):
        """
        Subscribe to order/trade/position updates.
        
        Args:
            data_type: Type of updates to subscribe to
        """
        if self._socket and self._connected:
            self._socket.subscribe(data_type=data_type.value)
    
    def disconnect(self):
        """Close connection."""
        if self._socket:
            self._socket.close_connection()
            self._connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._connected


class FyersWebSocketManager:
    """
    Centralized manager for Fyers WebSocket connections.
    
    Manages both data and order sockets, provides methods for
    starting/stopping streams, and distributes data to subscribers.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self._data_socket: Optional[FyersDataSocket] = None
        self._order_socket: Optional[FyersOrderSocket] = None
        self._subscribers: Dict[str, List[Callable]] = {
            "market_data": [],
            "orders": [],
            "trades": [],
            "positions": []
        }
    
    def _get_access_token(self) -> Optional[str]:
        """Get formatted access token."""
        return self.settings.get_access_token_formatted()
    
    def start_data_stream(
        self,
        symbols: List[str],
        on_message: Optional[Callable] = None,
        lite_mode: bool = False
    ) -> bool:
        """
        Start market data stream for symbols.
        
        Args:
            symbols: Symbols to stream
            on_message: Callback for data updates
            lite_mode: If True, only receive LTP updates
            
        Returns:
            True if started successfully
        """
        token = self._get_access_token()
        if not token:
            logger.error("No access token for data stream")
            return False
        
        def message_handler(msg):
            for subscriber in self._subscribers["market_data"]:
                subscriber(msg)
            if on_message:
                on_message(msg)
        
        self._data_socket = FyersDataSocket(
            access_token=token,
            on_message=message_handler,
            lite_mode=lite_mode
        )
        
        if self._data_socket.connect():
            self._data_socket.subscribe(symbols, DataType.SYMBOL_UPDATE)
            return True
        return False
    
    def start_order_stream(
        self,
        on_order: Optional[Callable] = None,
        on_trade: Optional[Callable] = None,
        on_position: Optional[Callable] = None
    ) -> bool:
        """
        Start order/trade/position updates stream.
        
        Returns:
            True if started successfully
        """
        token = self._get_access_token()
        if not token:
            logger.error("No access token for order stream")
            return False
        
        def order_handler(msg):
            for subscriber in self._subscribers["orders"]:
                subscriber(msg)
            if on_order:
                on_order(msg)
        
        def trade_handler(msg):
            for subscriber in self._subscribers["trades"]:
                subscriber(msg)
            if on_trade:
                on_trade(msg)
        
        def position_handler(msg):
            for subscriber in self._subscribers["positions"]:
                subscriber(msg)
            if on_position:
                on_position(msg)
        
        self._order_socket = FyersOrderSocket(
            access_token=token,
            on_order=order_handler,
            on_trade=trade_handler,
            on_position=position_handler
        )
        
        if self._order_socket.connect():
            self._order_socket.subscribe(OrderDataType.ALL)
            return True
        return False
    
    def subscribe_to_symbols(self, symbols: List[str]):
        """Add symbols to data stream subscription."""
        if self._data_socket and self._data_socket.is_connected:
            self._data_socket.subscribe(symbols, DataType.SYMBOL_UPDATE)
    
    def unsubscribe_from_symbols(self, symbols: List[str]):
        """Remove symbols from data stream subscription."""
        if self._data_socket and self._data_socket.is_connected:
            self._data_socket.unsubscribe(symbols)
    
    def add_subscriber(self, channel: str, callback: Callable):
        """Add a subscriber to a channel."""
        if channel in self._subscribers:
            self._subscribers[channel].append(callback)
    
    def remove_subscriber(self, channel: str, callback: Callable):
        """Remove a subscriber from a channel."""
        if channel in self._subscribers and callback in self._subscribers[channel]:
            self._subscribers[channel].remove(callback)
    
    def stop_all(self):
        """Stop all WebSocket connections."""
        if self._data_socket:
            self._data_socket.disconnect()
            self._data_socket = None
        
        if self._order_socket:
            self._order_socket.disconnect()
            self._order_socket = None
    
    @property
    def data_connected(self) -> bool:
        return self._data_socket is not None and self._data_socket.is_connected
    
    @property
    def order_connected(self) -> bool:
        return self._order_socket is not None and self._order_socket.is_connected
    
    def get_status(self) -> Dict[str, Any]:
        """Get WebSocket connection status."""
        return {
            "data_socket": {
                "connected": self.data_connected,
                "subscribed_symbols": (
                    self._data_socket.subscribed_symbols 
                    if self._data_socket else []
                )
            },
            "order_socket": {
                "connected": self.order_connected
            }
        }


# Singleton instance
_ws_manager: Optional[FyersWebSocketManager] = None


def get_websocket_manager() -> FyersWebSocketManager:
    """Get the WebSocket manager instance."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = FyersWebSocketManager()
    return _ws_manager
