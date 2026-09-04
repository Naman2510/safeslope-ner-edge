from fastapi.testclient import TestClient
from backend.main import app


client = TestClient(app)

HEADERS = {
    "X-API-Key": "local-demo-key"
}


def make_payload(sensor_id, state, cause, sequence):
    return {
        "sensor_id": sensor_id,
        "lat": 23.7271,
        "lng": 92.9376,
        "tilt_delta": 5.0 if state == "CRITICAL_FAILURE" else 1.0,
        "soil_moisture": 50.0,
        "risk_state": state,
        "trigger_cause": cause,
        "packet_sequence_id": sequence,
        "mpu_ok": True,
        "moisture_valid": True,
        "pressure_valid": True,
        "acoustic_valid": True,
        "battery_valid": True
    }


def test_state_change_creates_event():
    sensor_id = "event_test_sensor"

    normal = client.post(
        "/telemetry/",
        json=make_payload(sensor_id, "NORMAL", "NONE", 1),
        headers=HEADERS
    )
    assert normal.status_code == 200

    critical = client.post(
        "/telemetry/",
        json=make_payload(
            sensor_id,
            "CRITICAL_FAILURE",
            "TILT",
            2
        ),
        headers=HEADERS
    )
    assert critical.status_code == 200

    events = client.get("/events/?limit=20")
    assert events.status_code == 200

    matching_events = [
        event
        for event in events.json()
        if event["sensor_id"] == sensor_id
    ]

    assert any(
        event["event_type"] == "CRITICAL_ENTERED"
        for event in matching_events
    )


def test_stats_endpoint():
    response = client.get("/stats/")

    assert response.status_code == 200

    data = response.json()
    assert "total_packets" in data
    assert "critical_packets" in data
    assert "warning_packets" in data
    assert "normal_packets" in data
    assert "critical_events" in data


def test_sensors_endpoint():
    response = client.get("/sensors/")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
