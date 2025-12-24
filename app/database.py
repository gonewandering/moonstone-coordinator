import aiosqlite
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.models import SensorReading, SensorConfig

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "centerville.db"


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._create_tables()
        logger.info(f"Database connected: {self.db_path}")

    async def disconnect(self):
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Database disconnected")

    async def _create_tables(self):
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                received_at TEXT NOT NULL,
                pm2_5 INTEGER,
                pm2_5_norm REAL,
                gas_raw INTEGER,
                gas_norm REAL,
                temp REAL,
                humidity REAL,
                pm_ok INTEGER,
                gas_ok INTEGER,
                dht_ok INTEGER
            )
        """)
        await self._connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_readings_device ON readings(device)
        """)
        await self._connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_readings_received_at ON readings(received_at)
        """)
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS sensor_configs (
                device TEXT PRIMARY KEY,
                wifi_ssid TEXT,
                wifi_password TEXT,
                hostname TEXT,
                wifi_enabled INTEGER DEFAULT 0,
                background_color TEXT DEFAULT '',
                updated_at TEXT
            )
        """)
        # Add background_color column if it doesn't exist (migration)
        try:
            await self._connection.execute("ALTER TABLE sensor_configs ADD COLUMN background_color TEXT DEFAULT ''")
        except Exception:
            pass  # Column already exists
        await self._connection.commit()

    async def store_reading(self, reading: SensorReading):
        await self._connection.execute("""
            INSERT INTO readings (
                device, timestamp, received_at, pm2_5, pm2_5_norm,
                gas_raw, gas_norm, temp, humidity, pm_ok, gas_ok, dht_ok
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            reading.device,
            reading.ts,
            reading.received_at.isoformat() if reading.received_at else datetime.utcnow().isoformat(),
            reading.pm2_5,
            reading.pm2_5_norm,
            reading.gas_raw,
            reading.gas_norm,
            reading.temp,
            reading.humidity,
            1 if reading.pm_ok else (0 if reading.pm_ok is False else None),
            1 if reading.gas_ok else (0 if reading.gas_ok is False else None),
            1 if reading.dht_ok else (0 if reading.dht_ok is False else None)
        ))
        await self._connection.commit()

    async def get_readings(
        self,
        device: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        since: Optional[datetime] = None
    ) -> list[dict]:
        query = "SELECT * FROM readings WHERE 1=1"
        params = []

        if device:
            query += " AND device = ?"
            params.append(device)

        if since:
            query += " AND received_at >= ?"
            params.append(since.isoformat())

        query += " ORDER BY received_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await self._connection.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_devices(self) -> list[str]:
        cursor = await self._connection.execute(
            "SELECT DISTINCT device FROM readings ORDER BY device"
        )
        rows = await cursor.fetchall()
        return [row["device"] for row in rows]

    async def get_reading_count(self, device: Optional[str] = None) -> int:
        if device:
            cursor = await self._connection.execute(
                "SELECT COUNT(*) as count FROM readings WHERE device = ?",
                (device,)
            )
        else:
            cursor = await self._connection.execute(
                "SELECT COUNT(*) as count FROM readings"
            )
        row = await cursor.fetchone()
        return row["count"]

    async def get_sensor_config(self, device: str) -> Optional[SensorConfig]:
        cursor = await self._connection.execute(
            "SELECT * FROM sensor_configs WHERE device = ?",
            (device,)
        )
        row = await cursor.fetchone()
        if row:
            return SensorConfig(
                device=row["device"],
                wifi_ssid=row["wifi_ssid"] or "",
                wifi_password=row["wifi_password"] or "",
                hostname=row["hostname"] or "",
                wifi_enabled=bool(row["wifi_enabled"]),
                background_color=row["background_color"] or "" if "background_color" in row.keys() else "",
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
            )
        return None

    async def save_sensor_config(self, config: SensorConfig):
        await self._connection.execute("""
            INSERT OR REPLACE INTO sensor_configs (
                device, wifi_ssid, wifi_password, hostname, wifi_enabled, background_color, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            config.device,
            config.wifi_ssid,
            config.wifi_password,
            config.hostname,
            1 if config.wifi_enabled else 0,
            config.background_color,
            datetime.utcnow().isoformat()
        ))
        await self._connection.commit()

    async def get_all_sensor_configs(self) -> list[SensorConfig]:
        cursor = await self._connection.execute("SELECT * FROM sensor_configs")
        rows = await cursor.fetchall()
        return [
            SensorConfig(
                device=row["device"],
                wifi_ssid=row["wifi_ssid"] or "",
                wifi_password=row["wifi_password"] or "",
                hostname=row["hostname"] or "",
                wifi_enabled=bool(row["wifi_enabled"]),
                background_color=row["background_color"] or "" if "background_color" in row.keys() else "",
                updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None
            )
            for row in rows
        ]
