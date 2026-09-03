from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict


app = FastAPI(
    title="SafeSlope-NER Local Backend",
    description="Telemetry receiver for the SafeSlope-NER landslide early-warning node",
    version="1.1.0",
)

DATABASE_PATH = Path(__file__).with_name("telemetry.db")

# Local development key only.
# Never commit a real production key to GitHub.
LOCAL_API_KEY = "local-demo-key"


class Telemetry(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Required backend contract
    sensor_id: str = Field(min_length=1, max_length=100)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    tilt_delta: float = Field(ge=-360, le=360)
    soil_moisture: float = Field(ge=0, le=100)

    # MPU6050 values
    accelerometer_x: float | None = None
    accelerometer_y: float | None = None
    accelerometer_z: float | None = None

    gyro_x: float | None = None
    gyro_y: float | None = None
    gyro_z: float | None = None

    pitch_deg: float | None = None
    roll_deg: float | None = None
    angular_shift_rate_deg_per_sec: float | None = None
    vibration_rms_g: float | None = None

    # Hydrological values
    soil_moisture_pct: float | None = Field(default=None, ge=0, le=100)
    soil_moisture_source: str | None = None
    soil_saturation_index: float | None = Field(default=None, ge=0, le=1)

    pore_pressure_kpa: float | None = Field(default=None, ge=0)
    pore_pressure_source: str | None = None
    matrix_suction_kpa: float | None = None

    # Acoustic values
    acoustic_event_rate_hz: float | None = Field(default=None, ge=0)
    acoustic_peak_mv: float | None = Field(default=None, ge=0)
    acoustic_energy: float | None = Field(default=None, ge=0)
    tripwire_flag: bool | None = None
    acoustic_source: str | None = None

    # Power and environment
    battery_voltage_v: float | None = Field(default=None, ge=0)
    battery_soc_pct: float | None = Field(default=None, ge=0, le=100)
    solar_voltage_v: float | None = Field(default=None, ge=0)
    internal_temperature_c: float | None = None

    # Edge intelligence and communication
    tinyml_anomaly_score: float | None = Field(default=None, ge=0, le=1)
    operating_alert_mode: str | None = None
    lorawan_rssi_dbm: float | None = None
    lorawan_snr_db: float | None = None
    packet_sequence_id: int | None = Field(default=None, ge=0)

    # Current project state
    risk_state: str | None = None
    trigger_cause: str | None = None

    # Device health and timing
    timestamp_ms: int | None = Field(default=None, ge=0)
    mpu_ok: bool | None = None
    moisture_valid: bool | None = None
    pressure_valid: bool | None = None
    acoustic_valid: bool | None = None
    battery_valid: bool | None = None


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    connection = get_connection()

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,

            sensor_id TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            tilt_delta REAL NOT NULL,
            soil_moisture REAL NOT NULL,

            accelerometer_x REAL,
            accelerometer_y REAL,
            accelerometer_z REAL,

            gyro_x REAL,
            gyro_y REAL,
            gyro_z REAL,

            pitch_deg REAL,
            roll_deg REAL,
            angular_shift_rate_deg_per_sec REAL,
            vibration_rms_g REAL,

            soil_moisture_pct REAL,
            soil_moisture_source TEXT,
            soil_saturation_index REAL,

            pore_pressure_kpa REAL,
            pore_pressure_source TEXT,
            matrix_suction_kpa REAL,

            acoustic_event_rate_hz REAL,
            acoustic_peak_mv REAL,
            acoustic_energy REAL,
            tripwire_flag INTEGER,
            acoustic_source TEXT,

            battery_voltage_v REAL,
            battery_soc_pct REAL,
            solar_voltage_v REAL,
            internal_temperature_c REAL,

            tinyml_anomaly_score REAL,
            operating_alert_mode TEXT,
            lorawan_rssi_dbm REAL,
            lorawan_snr_db REAL,
            packet_sequence_id INTEGER,

            risk_state TEXT,
            trigger_cause TEXT,
            timestamp_ms INTEGER,

            mpu_ok INTEGER,
            moisture_valid INTEGER,
            pressure_valid INTEGER,
            acoustic_valid INTEGER,
            battery_valid INTEGER
        )
        """
    )

    connection.commit()
    connection.close()


@app.on_event("startup")
def startup():
    initialize_database()


@app.get("/")
def root():
    return {
        "service": "SafeSlope-NER Local Backend",
        "status": "running",
        "docs": "/docs",
        "telemetry_endpoint": "/telemetry/",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "database": str(DATABASE_PATH),
    }


@app.post("/telemetry/")
def receive_telemetry(
    telemetry: Telemetry,
    x_api_key: str | None = Header(default=None),
):
    if x_api_key != LOCAL_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-API-Key",
        )

    received_at = datetime.now(timezone.utc).isoformat()
    data = telemetry.model_dump()

    connection = get_connection()

    cursor = connection.execute(
        """
        INSERT INTO telemetry (
            received_at,
            sensor_id,
            lat,
            lng,
            tilt_delta,
            soil_moisture,

            accelerometer_x,
            accelerometer_y,
            accelerometer_z,

            gyro_x,
            gyro_y,
            gyro_z,

            pitch_deg,
            roll_deg,
            angular_shift_rate_deg_per_sec,
            vibration_rms_g,

            soil_moisture_pct,
            soil_moisture_source,
            soil_saturation_index,

            pore_pressure_kpa,
            pore_pressure_source,
            matrix_suction_kpa,

            acoustic_event_rate_hz,
            acoustic_peak_mv,
            acoustic_energy,
            tripwire_flag,
            acoustic_source,

            battery_voltage_v,
            battery_soc_pct,
            solar_voltage_v,
            internal_temperature_c,

            tinyml_anomaly_score,
            operating_alert_mode,
            lorawan_rssi_dbm,
            lorawan_snr_db,
            packet_sequence_id,

            risk_state,
            trigger_cause,
            timestamp_ms,

            mpu_ok,
            moisture_valid,
            pressure_valid,
            acoustic_valid,
            battery_valid
        )
        VALUES (
            :received_at,
            :sensor_id,
            :lat,
            :lng,
            :tilt_delta,
            :soil_moisture,

            :accelerometer_x,
            :accelerometer_y,
            :accelerometer_z,

            :gyro_x,
            :gyro_y,
            :gyro_z,

            :pitch_deg,
            :roll_deg,
            :angular_shift_rate_deg_per_sec,
            :vibration_rms_g,

            :soil_moisture_pct,
            :soil_moisture_source,
            :soil_saturation_index,

            :pore_pressure_kpa,
            :pore_pressure_source,
            :matrix_suction_kpa,

            :acoustic_event_rate_hz,
            :acoustic_peak_mv,
            :acoustic_energy,
            :tripwire_flag,
            :acoustic_source,

            :battery_voltage_v,
            :battery_soc_pct,
            :solar_voltage_v,
            :internal_temperature_c,

            :tinyml_anomaly_score,
            :operating_alert_mode,
            :lorawan_rssi_dbm,
            :lorawan_snr_db,
            :packet_sequence_id,

            :risk_state,
            :trigger_cause,
            :timestamp_ms,

            :mpu_ok,
            :moisture_valid,
            :pressure_valid,
            :acoustic_valid,
            :battery_valid
        )
        """,
        {
            "received_at": received_at,
            **data,
        },
    )

    connection.commit()
    record_id = cursor.lastrowid
    connection.close()

    print(
        f"[TELEMETRY] "
        f"id={record_id} "
        f"sensor={telemetry.sensor_id} "
        f"tilt={telemetry.tilt_delta:.2f} "
        f"moisture={telemetry.soil_moisture:.2f} "
        f"state={telemetry.risk_state}"
    )

    return {
        "status": "received",
        "id": record_id,
        "sensor_id": telemetry.sensor_id,
    }


@app.get("/telemetry/")
def list_telemetry(
    limit: int = Query(default=100, ge=1, le=1000),
):
    connection = get_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM telemetry
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    connection.close()

    return [dict(row) for row in rows]


@app.delete("/telemetry/")
def delete_telemetry():
    connection = get_connection()
    connection.execute("DELETE FROM telemetry")
    connection.commit()
    connection.close()

    return {
        "status": "cleared",
    }