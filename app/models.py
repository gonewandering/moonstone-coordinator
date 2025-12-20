from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SensorReading(BaseModel):
    device: str
    version: str = "unknown"
    ts: int
    # PM sensor fields (optional - only present if sensor detected)
    pm2_5: Optional[int] = None
    pm2_5_norm: Optional[float] = None
    pm_ok: Optional[bool] = None
    # Gas sensor fields (optional - only present if sensor detected)
    gas_raw: Optional[int] = None
    gas_norm: Optional[float] = None
    gas_ok: Optional[bool] = None
    # DHT sensor fields (optional - only present if sensor detected)
    temp: Optional[float] = None
    humidity: Optional[float] = None
    dht_ok: Optional[bool] = None
    # Connectivity
    wifi_connected: bool = False
    hostname: str = ""
    received_at: Optional[datetime] = None


class SensorConfig(BaseModel):
    device: str
    wifi_ssid: str = ""
    wifi_password: str = ""
    hostname: str = ""
    wifi_enabled: bool = False
    updated_at: Optional[datetime] = None


class SensorInfo(BaseModel):
    device_id: str
    bt_address: str
    bt_name: str
    connected: bool
    last_reading: Optional[SensorReading] = None
    config: Optional[SensorConfig] = None
