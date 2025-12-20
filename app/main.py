import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.bluetooth_manager import BluetoothManager
from app.websocket_manager import WebSocketManager
from app.wifi_manager import WiFiManager
from app.database import Database
from app.models import SensorReading, SensorConfig


class ConfigUpdateRequest(BaseModel):
    wifi_ssid: str = ""
    wifi_password: str = ""
    hostname: str = ""
    wifi_enabled: bool = False

STATIC_DIR = Path(__file__).parent / "static"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

ws_manager = WebSocketManager()
bt_manager: BluetoothManager = None
wifi_manager: WiFiManager = None
db: Database = None


def on_sensor_reading(reading: SensorReading):
    asyncio.create_task(ws_manager.broadcast(reading))
    asyncio.create_task(db.store_reading(reading))


def on_sensor_connect(device_id: str, address: str, name: str):
    logger.info(f"Sensor connected: {device_id} ({name})")
    asyncio.create_task(ws_manager.broadcast_sensor_status(device_id, address, name, True))


def on_sensor_disconnect(device_id: str, address: str, name: str):
    logger.info(f"Sensor disconnected: {device_id} ({name})")
    asyncio.create_task(ws_manager.broadcast_sensor_status(device_id, address, name, False))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bt_manager, wifi_manager, db

    # Initialize database
    db = Database()
    await db.connect()

    # Initialize Bluetooth manager
    bt_manager = BluetoothManager(
        on_reading=on_sensor_reading,
        on_sensor_connect=on_sensor_connect,
        on_sensor_disconnect=on_sensor_disconnect
    )
    await bt_manager.start()

    # Initialize WiFi manager for polling sensors over HTTP
    wifi_manager = WiFiManager(
        db=db,
        on_reading=on_sensor_reading
    )
    await wifi_manager.start()

    # Wire up BLE to check WiFi status (WiFi takes priority when available)
    bt_manager.set_wifi_check(wifi_manager.is_wifi_active)

    logger.info("Centerville Coordinator started")
    yield

    await wifi_manager.stop()
    await bt_manager.stop()
    await db.disconnect()
    logger.info("Centerville Coordinator stopped")


app = FastAPI(
    title="Centerville Coordinator",
    description="Air quality sensor coordinator with WebSocket streaming",
    version="0.1.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/kiosk")
async def kiosk():
    return FileResponse(STATIC_DIR / "kiosk.html")


@app.get("/api/status")
async def status():
    wifi_active_sensors = list(wifi_manager.get_wifi_active_sensors()) if wifi_manager else []
    return {
        "service": "Centerville Coordinator",
        "status": "running",
        "websocket_clients": ws_manager.client_count,
        "connected_sensors": len(bt_manager.connected_devices) if bt_manager else 0,
        "wifi_polling": wifi_manager._running if wifi_manager else False,
        "wifi_active_sensors": wifi_active_sensors
    }


@app.get("/api/sensors")
async def get_sensors():
    if not bt_manager:
        return JSONResponse(
            status_code=503,
            content={"error": "Bluetooth manager not initialized"}
        )
    sensors = bt_manager.get_connected_sensors()
    wifi_active = wifi_manager.get_wifi_active_sensors() if wifi_manager else set()

    # Serialize last_reading if present and add connection type
    for sensor in sensors:
        device_id = sensor.get("device")
        sensor["connection"] = "wifi" if device_id in wifi_active else "ble"
        if sensor.get("last_reading"):
            sensor["last_reading"] = sensor["last_reading"].model_dump(mode="json")
    return {"sensors": sensors}


@app.get("/api/readings")
async def get_readings(
    device: Optional[str] = Query(None, description="Filter by device ID"),
    limit: int = Query(100, ge=1, le=1000, description="Max readings to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    hours: Optional[int] = Query(None, ge=1, le=168, description="Get readings from last N hours")
):
    since = None
    if hours:
        since = datetime.utcnow() - timedelta(hours=hours)

    readings = await db.get_readings(
        device=device,
        limit=limit,
        offset=offset,
        since=since
    )
    return {
        "count": len(readings),
        "readings": readings
    }


@app.get("/api/devices")
async def get_devices():
    devices = await db.get_devices()
    counts = {}
    for device in devices:
        counts[device] = await db.get_reading_count(device)
    return {
        "devices": devices,
        "reading_counts": counts,
        "total_readings": await db.get_reading_count()
    }


@app.get("/api/config/{device}")
async def get_sensor_config(device: str):
    """Get configuration for a sensor from database"""
    config = await db.get_sensor_config(device)
    if config:
        # Don't expose password in response
        return {
            "device": config.device,
            "wifi_ssid": config.wifi_ssid,
            "wifi_configured": len(config.wifi_password) > 0,
            "hostname": config.hostname,
            "wifi_enabled": config.wifi_enabled,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None
        }
    return {"device": device, "wifi_ssid": "", "wifi_configured": False, "hostname": "", "wifi_enabled": False}


@app.put("/api/config/{device}")
async def update_sensor_config(device: str, request: ConfigUpdateRequest):
    """Update configuration for a sensor and push to device via BLE"""
    # Save to database
    config = SensorConfig(
        device=device,
        wifi_ssid=request.wifi_ssid,
        wifi_password=request.wifi_password,
        hostname=request.hostname,
        wifi_enabled=request.wifi_enabled
    )
    await db.save_sensor_config(config)

    # Try to push to sensor via BLE if connected
    pushed = False
    if bt_manager:
        import json
        config_json = json.dumps({
            "wifi_ssid": request.wifi_ssid,
            "wifi_password": request.wifi_password,
            "hostname": request.hostname,
            "wifi_enabled": request.wifi_enabled
        })
        pushed = await bt_manager.write_config(device, config_json)

    return {
        "success": True,
        "pushed_to_sensor": pushed,
        "message": "Configuration saved" + (" and pushed to sensor" if pushed else " (sensor not connected)")
    }


@app.post("/api/config/{device}/push")
async def push_sensor_config(device: str):
    """Push stored configuration to sensor via BLE"""
    config = await db.get_sensor_config(device)
    if not config:
        return JSONResponse(status_code=404, content={"error": "No configuration found for this device"})

    if not bt_manager:
        return JSONResponse(status_code=503, content={"error": "Bluetooth manager not initialized"})

    import json
    config_json = json.dumps({
        "wifi_ssid": config.wifi_ssid,
        "wifi_password": config.wifi_password,
        "hostname": config.hostname,
        "wifi_enabled": config.wifi_enabled
    })

    success = await bt_manager.write_config(device, config_json)

    if success:
        return {"success": True, "message": "Configuration pushed to sensor"}
    else:
        return JSONResponse(status_code=400, content={"error": "Failed to push configuration - sensor may not be connected"})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle any client messages
            data = await websocket.receive_text()
            # Could handle commands from clients here
            logger.debug(f"Received from client: {data}")
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
