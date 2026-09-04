from fastapi.testclient import TestClient
from backend.main import app


client = TestClient(app)

VALID_PAYLOAD = {
    "sensor_id": "test_sensor_001",
    "lat": 23.7271,
    "lng": 92.9376,
    "tilt_delta": 1.2,
    "soil_moisture": 45.0,
    "pitch_deg": 1.2,
    "roll_deg": 0.5,
    "pore_pressure_kpa": 20.0,
    "risk_state": "NORMAL",
    "trigger_cause": "NONE",
    "packet_sequence_id": 1,
    "mpu_ok": True,
    "moisture_valid": True,
    "pressure_valid": True,
    "acoustic_valid": True,
    "battery_valid": True
}


def test_missing_api_key_is_rejected():
    response = client.post("/telemetry/", json=VALID_PAYLOAD)

    assert response.status_code == 401


def test_invalid_api_key_is_rejected():
    response = client.post(
        "/telemetry/",
        json=VALID_PAYLOAD,
        headers={"X-API-Key": "wrong-key"}
    )

    assert response.status_code == 401


def test_valid_telemetry_is_accepted():
    response = client.post(
        "/telemetry/",
        json=VALID_PAYLOAD,
        headers={"X-API-Key": "local-demo-key"}
    )

    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "received"
    assert data["sensor_id"] == "test_sensor_001"
    assert isinstance(data["id"], int)


def test_invalid_latitude_is_rejected():
    payload = VALID_PAYLOAD.copy()
    payload["lat"] = 200

    response = client.post(
        "/telemetry/",
        json=payload,
        headers={"X-API-Key": "local-demo-key"}
    )

    assert response.status_code == 422


def test_invalid_soil_moisture_is_rejected():
    payload = VALID_PAYLOAD.copy()
    payload["soil_moisture"] = 150

    response = client.post(
        "/telemetry/",
        json=payload,
        headers={"X-API-Key": "local-demo-key"}
    )

    assert response.status_code == 422
