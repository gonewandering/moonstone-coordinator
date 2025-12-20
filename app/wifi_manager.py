import asyncio
import logging
from datetime import datetime
from typing import Callable, Optional

import httpx

from app.models import SensorReading, SensorConfig
from app.database import Database

logger = logging.getLogger(__name__)

# Polling interval in seconds
POLL_INTERVAL = 10

# Number of consecutive failures before marking WiFi as inactive
MAX_FAILURES = 3


class WiFiManager:
    def __init__(
        self,
        db: Database,
        on_reading: Callable[[SensorReading], None],
    ):
        self.db = db
        self.on_reading = on_reading
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        # Track WiFi-active sensors: device_id -> last successful poll time
        self._wifi_active: dict[str, datetime] = {}
        # Track consecutive failures: device_id -> failure count
        self._failure_counts: dict[str, int] = {}

    async def start(self):
        self._running = True
        self._client = httpx.AsyncClient(timeout=5.0)
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("WiFi manager started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
        logger.info("WiFi manager stopped")

    def is_wifi_active(self, device_id: str) -> bool:
        """Check if a sensor is currently reachable via WiFi."""
        return device_id in self._wifi_active

    def get_wifi_active_sensors(self) -> set[str]:
        """Get set of device IDs that are currently WiFi-active."""
        return set(self._wifi_active.keys())

    async def _poll_loop(self):
        while self._running:
            try:
                await self._poll_sensors()
            except Exception as e:
                logger.error(f"WiFi polling error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

    async def _poll_sensors(self):
        # Get all sensor configs with WiFi enabled
        configs = await self.db.get_all_sensor_configs()
        wifi_sensors = [c for c in configs if c.wifi_enabled and c.hostname]

        if not wifi_sensors:
            return

        # Poll each sensor concurrently
        tasks = [self._poll_sensor(config) for config in wifi_sensors]
        await asyncio.gather(*tasks, return_exceptions=True)

    def _mark_wifi_success(self, device_id: str):
        """Mark a sensor as WiFi-active after successful poll."""
        was_active = device_id in self._wifi_active
        self._wifi_active[device_id] = datetime.utcnow()
        self._failure_counts[device_id] = 0
        if not was_active:
            logger.info(f"Sensor {device_id}: WiFi connection established (switching from BLE)")

    def _mark_wifi_failure(self, device_id: str):
        """Track a WiFi failure for a sensor."""
        self._failure_counts[device_id] = self._failure_counts.get(device_id, 0) + 1
        if self._failure_counts[device_id] >= MAX_FAILURES:
            if device_id in self._wifi_active:
                del self._wifi_active[device_id]
                logger.info(f"Sensor {device_id}: WiFi connection lost (falling back to BLE)")

    async def _poll_sensor(self, config: SensorConfig):
        url = f"http://{config.hostname}.local/api/readings"

        try:
            response = await self._client.get(url)
            if response.status_code == 200:
                data = response.json()
                device_id = data.get("device", config.device)

                # Mark as WiFi-active
                self._mark_wifi_success(device_id)

                # Create SensorReading from response
                reading = SensorReading(
                    **data,
                    received_at=datetime.utcnow()
                )

                # Notify callback
                self.on_reading(reading)
                logger.debug(f"WiFi reading from {config.hostname}: device={reading.device}")
            else:
                logger.warning(f"Failed to poll {config.hostname}: HTTP {response.status_code}")
                self._mark_wifi_failure(config.device)

        except httpx.ConnectError:
            logger.debug(f"Cannot connect to {config.hostname}.local (sensor may be offline)")
            self._mark_wifi_failure(config.device)
        except httpx.TimeoutException:
            logger.debug(f"Timeout polling {config.hostname}.local")
            self._mark_wifi_failure(config.device)
        except Exception as e:
            logger.warning(f"Error polling {config.hostname}: {e}")
            self._mark_wifi_failure(config.device)

    async def poll_sensor_now(self, hostname: str) -> Optional[SensorReading]:
        """Manually poll a sensor by hostname. Returns the reading or None."""
        url = f"http://{hostname}.local/api/readings"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    return SensorReading(**data, received_at=datetime.utcnow())
        except Exception as e:
            logger.warning(f"Error polling {hostname}: {e}")

        return None
