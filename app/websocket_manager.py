import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket

from app.models import SensorReading

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, reading: SensorReading):
        message = json.dumps({
            "type": "reading",
            "data": reading.model_dump(mode="json")
        })
        await self._send_to_all(message)

    async def broadcast_sensor_status(self, device: str, address: str, name: str, connected: bool):
        message = json.dumps({
            "type": "sensor_status",
            "data": {
                "device": device,
                "address": address,
                "name": name,
                "connected": connected
            }
        })
        await self._send_to_all(message)

    async def _send_to_all(self, message: str):
        if not self.active_connections:
            return

        disconnected = set()

        async with self._lock:
            for connection in self.active_connections:
                try:
                    await connection.send_text(message)
                except Exception as e:
                    logger.warning(f"Failed to send to client: {e}")
                    disconnected.add(connection)

            # Clean up failed connections
            self.active_connections -= disconnected

    @property
    def client_count(self) -> int:
        return len(self.active_connections)
