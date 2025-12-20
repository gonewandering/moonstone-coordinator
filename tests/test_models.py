import pytest
from datetime import datetime
from app.models import SensorReading


def test_sensor_reading_parsing():
    data = {
        "device": "SENSOR_001",
        "version": "1.0.0",
        "ts": 12345,
        "pm2_5": 25,
        "pm2_5_norm": 0.05,
        "gas_raw": 1500,
        "gas_norm": 0.1,
        "temp": 22.5,
        "humidity": 45.0,
        "pm_ok": True,
        "gas_ok": True,
        "dht_ok": True
    }

    reading = SensorReading(**data)

    assert reading.device == "SENSOR_001"
    assert reading.version == "1.0.0"
    assert reading.pm2_5 == 25
    assert reading.pm2_5_norm == 0.05
    assert reading.gas_raw == 1500
    assert reading.gas_norm == 0.1
    assert reading.temp == 22.5
    assert reading.humidity == 45.0
    assert reading.pm_ok is True
    assert reading.dht_ok is True
    assert reading.received_at is None


def test_sensor_reading_with_timestamp():
    now = datetime.utcnow()
    data = {
        "device": "SENSOR_001",
        "version": "1.0.0",
        "ts": 12345,
        "pm2_5": 25,
        "pm2_5_norm": 0.05,
        "gas_raw": 1500,
        "gas_norm": 0.1,
        "temp": 22.5,
        "humidity": 45.0,
        "pm_ok": True,
        "gas_ok": True,
        "dht_ok": True,
        "received_at": now
    }

    reading = SensorReading(**data)
    assert reading.received_at == now
