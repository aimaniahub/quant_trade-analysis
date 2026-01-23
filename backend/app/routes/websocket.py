from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict
import asyncio
import json

from app.services.fyers_websocket import get_websocket_manager

router = APIRouter()
ws_manager = get_websocket_manager()


class SocketConnectionManager:
    """Manage application WebSocket connections."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                self.disconnect(connection)


app_manager = SocketConnectionManager()


@router.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    """
    WebSocket endpoint for real-time market data.
    """
    await app_manager.connect(websocket)
    
    # Callback to forward Fyers data to all connected clients
    def forward_data(message):
        asyncio.create_task(app_manager.broadcast({
            "type": "market_update",
            "data": message
        }))
    
    # Register this handler if data stream is active
    if ws_manager.data_connected:
        ws_manager.add_subscriber("market_data", forward_data)
    
    try:
        while True:
            data = await websocket.receive_json()
            
            # Handle client requests
            action = data.get("action")
            if action == "subscribe":
                symbols = data.get("symbols", [])
                
                # Start Fyers stream if not already running
                if not ws_manager.data_connected:
                    ws_manager.start_data_stream(symbols, on_message=forward_data)
                else:
                    ws_manager.subscribe_to_symbols(symbols)
                
                await websocket.send_json({
                    "type": "subscription_status",
                    "status": "success",
                    "symbols": symbols
                })
            
            elif action == "unsubscribe":
                symbols = data.get("symbols", [])
                ws_manager.unsubscribe_from_symbols(symbols)
                await websocket.send_json({
                    "type": "subscription_status",
                    "status": "unsubscribed",
                    "symbols": symbols
                })
            
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        app_manager.disconnect(websocket)
        if ws_manager.data_connected:
            ws_manager.remove_subscriber("market_data", forward_data)


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """
    WebSocket endpoint for trade alerts.
    """
    await app_manager.connect(websocket)
    
    # Callback for order/trade alerts
    def forward_alert(message):
        asyncio.create_task(app_manager.broadcast({
            "type": "alert",
            "data": message
        }))
    
    if ws_manager.order_connected:
        ws_manager.add_subscriber("orders", forward_alert)
        ws_manager.add_subscriber("trades", forward_alert)
    
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "subscribe":
                if not ws_manager.order_connected:
                    ws_manager.start_order_stream(on_order=forward_alert, on_trade=forward_alert)
                
                await websocket.send_json({
                    "type": "subscription_status",
                    "channel": "alerts",
                    "status": "active"
                })
    except WebSocketDisconnect:
        app_manager.disconnect(websocket)
        if ws_manager.order_connected:
            ws_manager.remove_subscriber("orders", forward_alert)
            ws_manager.remove_subscriber("trades", forward_alert)
    except Exception as e:
        print(f"WebSocket Error: {str(e)}")
        app_manager.disconnect(websocket)

