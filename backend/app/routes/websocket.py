from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict, Optional, Set
import asyncio
import json
import logging

from app.services.fyers_websocket import get_websocket_manager
from app.services.signal_bus import get_signal_bus

router = APIRouter()
ws_manager = get_websocket_manager()
logger = logging.getLogger(__name__)
signal_bus = get_signal_bus()


class SocketConnectionManager:
    """Manage application WebSocket connections for a single channel."""

    def __init__(self, name: str = "default"):
        self.name = name
        self.active_connections: List[WebSocket] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        # Capture the running loop so Fyers threads / signal bus can schedule safely
        try:
            loop = asyncio.get_running_loop()
            self._loop = loop
            # Bind signal bus to this loop (alerts path)
            if self.name == "alerts":
                signal_bus.bind_loop(loop)
        except RuntimeError:
            pass

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)

    def broadcast_threadsafe(self, message: dict) -> None:
        """
        Schedule broadcast from a non-async (Fyers SDK) thread.
        Falls back silently if no loop is bound yet.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(message), loop)
        except Exception as exc:
            logger.debug(f"[{self.name}] threadsafe broadcast failed: {exc}")


market_manager = SocketConnectionManager("market")
alerts_manager = SocketConnectionManager("alerts")


async def _broadcast_strategy_alert(event: dict) -> None:
    """Push strategy-bus events onto the alerts WebSocket channel."""
    await alerts_manager.broadcast({
        "type": "alert",
        "data": {
            "type": event.get("type") or "signal",
            "message": event.get("message"),
            "source": event.get("source"),
            "symbol": event.get("symbol"),
            "score": event.get("score"),
            "timestamp": event.get("timestamp"),
        },
    })


# Register once at import so MA / intelligence can fan-out without circular imports
signal_bus.register_broadcaster(_broadcast_strategy_alert)


@router.get("/alerts/recent")
async def get_recent_alerts(limit: int = 20, source: str | None = None):
    """REST fallback for strategy/system alerts (also pushed on /ws/alerts)."""
    return {
        "success": True,
        "alerts": signal_bus.recent(limit=limit, source=source),
    }


@router.websocket("/ws/market")
async def websocket_market(websocket: WebSocket):
    """
    WebSocket endpoint for real-time market data.
    """
    await market_manager.connect(websocket)
    subscriber_registered = False

    def forward_data(message):
        market_manager.broadcast_threadsafe({
            "type": "market_update",
            "data": message,
        })

    try:
        # Register subscriber so this client receives stream updates
        ws_manager.add_subscriber("market_data", forward_data)
        subscriber_registered = True

        while True:
            data = await websocket.receive_json()

            action = data.get("action")
            if action == "subscribe":
                symbols = data.get("symbols", [])

                if not ws_manager.data_connected:
                    ws_manager.start_data_stream(symbols, on_message=forward_data)
                else:
                    ws_manager.subscribe_to_symbols(symbols)

                await websocket.send_json({
                    "type": "subscription_status",
                    "status": "success",
                    "symbols": symbols,
                })

            elif action == "unsubscribe":
                symbols = data.get("symbols", [])
                ws_manager.unsubscribe_from_symbols(symbols)
                await websocket.send_json({
                    "type": "subscription_status",
                    "status": "unsubscribed",
                    "symbols": symbols,
                })

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Market WebSocket error: {e}")
    finally:
        market_manager.disconnect(websocket)
        if subscriber_registered:
            try:
                ws_manager.remove_subscriber("market_data", forward_data)
            except Exception:
                pass


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """
    WebSocket endpoint for trade/order alerts.
    """
    await alerts_manager.connect(websocket)
    subscriber_registered = False

    def forward_alert(message):
        # Normalize Fyers order/trade payloads into a stable alert shape
        if isinstance(message, dict):
            text = (
                message.get("message")
                or message.get("reason")
                or message.get("description")
                or message.get("orderTag")
                or None
            )
            payload = {
                "type": message.get("type") or message.get("report_type") or "info",
                "message": text or json.dumps(message, default=str)[:300],
                "raw": message,
            }
        else:
            payload = {"type": "info", "message": str(message)}

        alerts_manager.broadcast_threadsafe({
            "type": "alert",
            "data": payload,
        })

    try:
        if ws_manager.order_connected:
            ws_manager.add_subscriber("orders", forward_alert)
            ws_manager.add_subscriber("trades", forward_alert)
            subscriber_registered = True

        while True:
            data = await websocket.receive_json()
            if data.get("action") == "subscribe":
                if not ws_manager.order_connected:
                    ws_manager.start_order_stream(
                        on_order=forward_alert,
                        on_trade=forward_alert,
                    )
                if not subscriber_registered:
                    ws_manager.add_subscriber("orders", forward_alert)
                    ws_manager.add_subscriber("trades", forward_alert)
                    subscriber_registered = True

                await websocket.send_json({
                    "type": "subscription_status",
                    "channel": "alerts",
                    "status": "active",
                })
            elif data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Alerts WebSocket error: {e}")
    finally:
        alerts_manager.disconnect(websocket)
        if subscriber_registered:
            try:
                ws_manager.remove_subscriber("orders", forward_alert)
                ws_manager.remove_subscriber("trades", forward_alert)
            except Exception:
                pass
