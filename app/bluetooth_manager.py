import asyncio
import json
import logging
from datetime import datetime
from typing import Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from app.models import SensorReading

# Store event loop reference for callbacks
_loop: asyncio.AbstractEventLoop = None

logger = logging.getLogger(__name__)

# UUIDs must match the ESP32 sensor
SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
CHARACTERISTIC_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
CONFIG_CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a9"

# Device name prefixes to look for
DEVICE_NAME_PREFIXES = ["Centerville Sensor", "centerville-sensor"]


class BluetoothManager:
    def __init__(
        self,
        on_reading: Callable[[SensorReading], None],
        on_sensor_connect: Callable[[str, str, str], None] = None,
        on_sensor_disconnect: Callable[[str, str, str], None] = None
    ):
        self.on_reading = on_reading
        self.on_sensor_connect = on_sensor_connect
        self.on_sensor_disconnect = on_sensor_disconnect
        self.connected_devices: dict[str, dict] = {}
        self._running = False
        self._tasks: list[asyncio.Task] = []
        # Callback to check if WiFi is active for a device (set by main.py)
        self._is_wifi_active: Callable[[str], bool] | None = None

    def set_wifi_check(self, is_wifi_active: Callable[[str], bool]):
        """Set callback to check if a sensor is WiFi-active."""
        self._is_wifi_active = is_wifi_active

    async def start(self):
        global _loop
        _loop = asyncio.get_event_loop()
        self._running = True
        logger.info("BLE manager started")
        asyncio.create_task(self._discovery_loop())

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()

        # Disconnect all clients
        for addr, info in list(self.connected_devices.items()):
            client = info.get("client")
            if client and client.is_connected:
                try:
                    await client.disconnect()
                except Exception:
                    pass

        self.connected_devices.clear()
        logger.info("BLE manager stopped")

    async def _discovery_loop(self):
        while self._running:
            try:
                await self._discover_sensors()
            except Exception as e:
                logger.error(f"Discovery error: {e}")
            await asyncio.sleep(10)

    async def _discover_sensors(self):
        logger.info("Scanning for Centerville sensors...")

        devices = await BleakScanner.discover(timeout=5.0)

        for device in devices:
            name = device.name or ""
            if any(name.startswith(prefix) for prefix in DEVICE_NAME_PREFIXES):
                if device.address not in self.connected_devices:
                    logger.info(f"Found sensor: {name} ({device.address})")
                    task = asyncio.create_task(self._connect_sensor(device))
                    self._tasks.append(task)

    async def _connect_sensor(self, device: BLEDevice):
        address = device.address
        name = device.name or address

        # Extract device ID from name like "Centerville Sensor (ABC123)"
        device_id = address
        if "(" in name and ")" in name:
            device_id = name.split("(")[-1].rstrip(")")

        try:
            client = BleakClient(device)
            await client.connect()

            if not client.is_connected:
                logger.warning(f"Failed to connect to {name}")
                return

            self.connected_devices[address] = {
                "device_id": device_id,
                "name": name,
                "client": client,
                "connected": True,
                "last_reading": None
            }

            logger.info(f"Connected to {name}")

            # Notify connect callback
            if self.on_sensor_connect:
                self.on_sensor_connect(device_id, address, name)

            # Subscribe to notifications
            def notification_handler(sender, data):
                asyncio.run_coroutine_threadsafe(
                    self._handle_notification(address, data),
                    _loop
                )

            await client.start_notify(CHARACTERISTIC_UUID, notification_handler)

            # Keep connection alive
            while self._running and client.is_connected:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error with {name}: {e}")
        finally:
            # Cleanup on disconnect
            logger.info(f"Disconnected from {name}")
            if address in self.connected_devices:
                info = self.connected_devices[address]
                client = info.get("client")
                if client and client.is_connected:
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

                # Notify disconnect callback
                if self.on_sensor_disconnect:
                    self.on_sensor_disconnect(info.get("device_id", address), address, info.get("name", address))

                del self.connected_devices[address]

    async def _handle_notification(self, address: str, data: bytes):
        try:
            json_str = data.decode("utf-8")
            logger.debug(f"BLE received raw data: {json_str}")
            parsed = json.loads(json_str)
            reading = SensorReading(
                **parsed,
                received_at=datetime.utcnow()
            )

            # Update last reading (always track even if WiFi-active)
            if address in self.connected_devices:
                self.connected_devices[address]["last_reading"] = reading

            # Check if WiFi is active for this sensor - if so, skip BLE reading
            if self._is_wifi_active and self._is_wifi_active(reading.device):
                logger.debug(f"Skipping BLE reading for {reading.device} (WiFi active)")
                return

            # Notify callback
            self.on_reading(reading)
            logger.debug(f"BLE reading from {reading.device}")

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON from {address}: {data}")
        except Exception as e:
            logger.error(f"Error processing notification: {e}")

    def get_connected_sensors(self) -> list[dict]:
        return [
            {
                "device": info.get("device_id", addr),
                "address": addr,
                "name": info["name"],
                "connected": info["connected"],
                "last_reading": info.get("last_reading")
            }
            for addr, info in self.connected_devices.items()
        ]

    async def write_config(self, device_id: str, config_json: str) -> bool:
        """Write configuration to a sensor via BLE"""
        # Find the sensor by device_id
        address = None
        for addr, info in self.connected_devices.items():
            if info.get("device_id") == device_id:
                address = addr
                break

        if not address:
            logger.error(f"Sensor {device_id} not found or not connected")
            return False

        client = self.connected_devices[address].get("client")
        if not client or not client.is_connected:
            logger.error(f"Sensor {device_id} client not connected")
            return False

        try:
            logger.info(f"Writing config to {device_id}: {config_json}")
            await client.write_gatt_char(CONFIG_CHAR_UUID, config_json.encode("utf-8"))
            logger.info(f"Config written successfully to {device_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to write config to {device_id}: {e}")
            return False

    async def read_config(self, device_id: str) -> str | None:
        """Read configuration from a sensor via BLE"""
        # Find the sensor by device_id
        address = None
        for addr, info in self.connected_devices.items():
            if info.get("device_id") == device_id:
                address = addr
                break

        if not address:
            logger.error(f"Sensor {device_id} not found or not connected")
            return None

        client = self.connected_devices[address].get("client")
        if not client or not client.is_connected:
            logger.error(f"Sensor {device_id} client not connected")
            return None

        try:
            data = await client.read_gatt_char(CONFIG_CHAR_UUID)
            config_json = data.decode("utf-8")
            logger.info(f"Config read from {device_id}: {config_json}")
            return config_json
        except Exception as e:
            logger.error(f"Failed to read config from {device_id}: {e}")
            return None
