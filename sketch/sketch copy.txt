#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <ArduinoJson.h>

// ============================================================
// SafeSlope-NER v3
// ESP32 edge node for landslide early-warning simulation.
//
// Current Wokwi hardware:
// - ESP32 DevKit
// - MPU6050
// - Soil-moisture potentiometer
// - Pore-pressure potentiometer
// - Seismic/acoustic tripwire pushbutton
// - LED
// - Active buzzer
//
// Important:
// Potentiometers and the tripwire are simulation inputs.
// They are not real soil, piezometer, or geophone sensors.
// ============================================================


// ---------------- Hardware ----------------

static constexpr uint8_t MPU_ADDR = 0x68;

static constexpr int PIN_BUZZER = 18;
static constexpr int PIN_LED = 19;

static constexpr int PIN_SOIL_MOISTURE = 34;
static constexpr int PIN_PORE_PRESSURE = 35;

static constexpr int PIN_SEISMIC_TRIP = 4;


// ---------------- Network ----------------

static const char* WIFI_SSID = "Wokwi-GUEST";
static const char* WIFI_PASSWORD = "";

// Teammate backend endpoint.
static const char* SERVER_URL =
  "https://unknown-remold-lavish.ngrok-free.dev/telemetry/";

// Development API key supplied by the backend team.
// Do not commit a real production key to GitHub.
static const char* SERVICE_API_KEY =
  "local-demo-key";

// Fixed demo coordinates approved by the backend team.
static constexpr float DEVICE_LATITUDE = 23.7271f;
static constexpr float DEVICE_LONGITUDE = 92.9376f;


// ---------------- Risk thresholds ----------------

static constexpr float TILT_CRITICAL_DEG = 5.0f;
static constexpr float TILT_RECOVERY_DEG = 3.5f;

static constexpr float MOISTURE_CRITICAL_PCT = 85.0f;
static constexpr float MOISTURE_RECOVERY_PCT = 80.0f;

static constexpr float PORE_CRITICAL_KPA = 70.0f;
static constexpr float PORE_RECOVERY_KPA = 65.0f;

static constexpr uint32_t CONDITION_PERSIST_MS = 1500;
static constexpr uint32_t SEISMIC_LATCH_MS = 10000;


// ---------------- Timing ----------------

static constexpr uint32_t TELEMETRY_INTERVAL_MS = 2000;
static constexpr uint32_t SENSOR_INTERVAL_MS = 100;
static constexpr uint32_t SERIAL_STATUS_INTERVAL_MS = 1000;
static constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 5000;

// This timeout allows HTTPS TLS handshake to complete in
// Wokwi emulation without blocking for too long.
static constexpr uint32_t HTTP_TIMEOUT_MS = 8000;


// ---------------- MPU6050 configuration ----------------

// MPU6050 default ranges:
// Accelerometer: +/-2g
// Gyroscope: +/-250 degrees/second
static constexpr float MPU_ACCEL_SCALE = 16384.0f;
static constexpr float MPU_GYRO_SCALE = 131.0f;

// Number of samples used for vibration RMS.
static constexpr uint8_t VIBRATION_WINDOW_SIZE = 20;


// ---------------- Risk state ----------------

enum RiskState {
  NORMAL,
  WARNING_PENDING,
  CRITICAL_FAILURE
};


// ---------------- Sensor data ----------------

struct SensorData {
  // Raw accelerometer values in g.
  float accelXG = 0.0f;
  float accelYG = 0.0f;
  float accelZG = 0.0f;

  // Raw gyroscope values in degrees per second.
  float gyroXDps = 0.0f;
  float gyroYDps = 0.0f;
  float gyroZDps = 0.0f;

  // Derived motion values.
  float pitchDeg = 0.0f;
  float rollDeg = 0.0f;
  float angularRateDps = 0.0f;
  float vibrationRmsG = 0.0f;

  // Simulated hydrological values.
  float moisturePct = 0.0f;
  float poreKpa = 0.0f;

  bool mpuOk = false;
};

SensorData sensor;


// ---------------- Sensor filtering ----------------

// Existing three-sample pitch moving average.
float pitchHistory[3] = {
  0.0f,
  0.0f,
  0.0f
};

uint8_t filterIndex = 0;


// ---------------- Vibration processing ----------------

float vibrationHistory[VIBRATION_WINDOW_SIZE] = {
  0.0f
};

uint8_t vibrationIndex = 0;
uint8_t vibrationCount = 0;


// ---------------- Seismic interrupt state ----------------

volatile bool seismicIRQ = false;

portMUX_TYPE irqMux = portMUX_INITIALIZER_UNLOCKED;

bool seismicLatched = false;
uint32_t seismicLatchedAt = 0;


// ---------------- Risk state variables ----------------

RiskState riskState = NORMAL;

String activeCause = "NORMAL";


// ---------------- Telemetry state ----------------

uint32_t packetSequenceId = 0;


// ---------------- Timing state ----------------

uint32_t breachStartedAt = 0;

uint32_t lastSensorAt = 0;
uint32_t lastTelemetryAt = 0;
uint32_t lastSerialStatusAt = 0;
uint32_t lastWiFiRetryAt = 0;


// ============================================================
// Interrupt handling
// ============================================================

void IRAM_ATTR onSeismicInterrupt() {
  portENTER_CRITICAL_ISR(&irqMux);

  seismicIRQ = true;

  portEXIT_CRITICAL_ISR(&irqMux);
}


bool consumeSeismicIRQ() {
  bool triggered;

  portENTER_CRITICAL(&irqMux);

  triggered = seismicIRQ;
  seismicIRQ = false;

  portEXIT_CRITICAL(&irqMux);

  return triggered;
}


// ============================================================
// MPU6050 initialization
// ============================================================

bool initMPU() {
  Wire.begin(21, 22);
  Wire.setClock(400000);

  // Wake up MPU6050.
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);
  Wire.write(0x00);

  if (Wire.endTransmission(true) != 0) {
    return false;
  }

  // Configure accelerometer range to +/-2g.
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1C);
  Wire.write(0x00);

  if (Wire.endTransmission(true) != 0) {
    return false;
  }

  // Configure gyroscope range to +/-250 degrees/second.
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x1B);
  Wire.write(0x00);

  if (Wire.endTransmission(true) != 0) {
    return false;
  }

  return true;
}


// ============================================================
// MPU6050 reading
// ============================================================

bool readMPU(
  int16_t& ax,
  int16_t& ay,
  int16_t& az,
  int16_t& gx,
  int16_t& gy,
  int16_t& gz
) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);

  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  const uint8_t requested = 14;

  if (
    Wire.requestFrom(
      static_cast<uint8_t>(MPU_ADDR),
      requested,
      true
    ) != requested
  ) {
    return false;
  }

  ax = (static_cast<int16_t>(Wire.read()) << 8) | Wire.read();
  ay = (static_cast<int16_t>(Wire.read()) << 8) | Wire.read();
  az = (static_cast<int16_t>(Wire.read()) << 8) | Wire.read();

  // Skip MPU6050 temperature bytes.
  Wire.read();
  Wire.read();

  gx = (static_cast<int16_t>(Wire.read()) << 8) | Wire.read();
  gy = (static_cast<int16_t>(Wire.read()) << 8) | Wire.read();
  gz = (static_cast<int16_t>(Wire.read()) << 8) | Wire.read();

  return true;
}


// ============================================================
// Helpers
// ============================================================

float adcPercent(int pin) {
  return (
    static_cast<float>(analogRead(pin)) / 4095.0f
  ) * 100.0f;
}


float round2(float value) {
  return roundf(value * 100.0f) / 100.0f;
}
float calculateVibrationRms(
  float axG,
  float ayG,
  float azG
) {
  const float dynamicX = axG;
  const float dynamicY = ayG;
  const float dynamicZ = azG - VIBRATION_BASELINE_G;

  return sqrtf(
    (
      dynamicX * dynamicX +
      dynamicY * dynamicY +
      dynamicZ * dynamicZ
    ) / 3.0f
  );
}


const char* stateName(RiskState state) {
  switch (state) {
    case WARNING_PENDING:
      return "WARNING_PENDING";

    case CRITICAL_FAILURE:
      return "CRITICAL_FAILURE";

    default:
      return "NORMAL";
  }
}


void setOutputs() {
  const bool alarm = riskState == CRITICAL_FAILURE;

  digitalWrite(PIN_LED, alarm ? HIGH : LOW);
  digitalWrite(PIN_BUZZER, alarm ? HIGH : LOW);
}


// ============================================================
// Sensor processing
// ============================================================

void updateSensors() {
  int16_t rawAx;
  int16_t rawAy;
  int16_t rawAz;
  int16_t rawGx;
  int16_t rawGy;
  int16_t rawGz;

  sensor.mpuOk = readMPU(
    rawAx,
    rawAy,
    rawAz,
    rawGx,
    rawGy,
    rawGz
  );

  if (sensor.mpuOk) {
    sensor.accelXG =
      static_cast<float>(rawAx) / ACCEL_SCALE_G;

    sensor.accelYG =
      static_cast<float>(rawAy) / ACCEL_SCALE_G;

    sensor.accelZG =
      static_cast<float>(rawAz) / ACCEL_SCALE_G;

    sensor.gyroXDps =
      static_cast<float>(rawGx) / GYRO_SCALE_DPS;

    sensor.gyroYDps =
      static_cast<float>(rawGy) / GYRO_SCALE_DPS;

    sensor.gyroZDps =
      static_cast<float>(rawGz) / GYRO_SCALE_DPS;

    const float instantPitch =
      atan2f(
        sensor.accelYG,
        sqrtf(
          sensor.accelXG * sensor.accelXG +
          sensor.accelZG * sensor.accelZG
        )
      ) * 180.0f / PI;

    const float instantRoll =
      atan2f(
        sensor.accelXG,
        sensor.accelZG
      ) * 180.0f / PI;

    pitchHistory[filterIndex] = instantPitch;
    filterIndex = (filterIndex + 1) % 3;

    sensor.pitchDeg =
      (
        pitchHistory[0] +
        pitchHistory[1] +
        pitchHistory[2]
      ) / 3.0f;

    sensor.rollDeg = instantRoll;

    sensor.angularRateDps =
      sqrtf(
        sensor.gyroXDps * sensor.gyroXDps +
        sensor.gyroYDps * sensor.gyroYDps +
        sensor.gyroZDps * sensor.gyroZDps
      );

    sensor.vibrationRmsG =
      calculateVibrationRms(
        sensor.accelXG,
        sensor.accelYG,
        sensor.accelZG
      );
  }
  else {
    sensor.accelXG = 0.0f;
    sensor.accelYG = 0.0f;
    sensor.accelZG = 0.0f;

    sensor.gyroXDps = 0.0f;
    sensor.gyroYDps = 0.0f;
    sensor.gyroZDps = 0.0f;

    sensor.pitchDeg = 0.0f;
    sensor.rollDeg = 0.0f;
    sensor.angularRateDps = 0.0f;
    sensor.vibrationRmsG = 0.0f;
  }

  // These remain simulated Wokwi inputs for now.
  sensor.moisturePct = adcPercent(PIN_SOIL_MOISTURE);
  sensor.poreKpa = adcPercent(PIN_PORE_PRESSURE);
}


// ============================================================
// Risk evaluation
// ============================================================

void evaluateRisk() {
  // ----------------------------------------------------------
  // Consume seismic interrupt.
  // ----------------------------------------------------------

  if (consumeSeismicIRQ()) {
    seismicLatched = true;
    seismicLatchedAt = millis();

    Serial.println(
      "[EVENT] MICRO_SEISMIC_FRACTURE detected; event latched"
    );
  }


  // ----------------------------------------------------------
  // Expire seismic latch after the configured period.
  // ----------------------------------------------------------

  if (
    seismicLatched &&
    millis() - seismicLatchedAt > SEISMIC_LATCH_MS
  ) {
    seismicLatched = false;

    Serial.println("[EVENT] seismic latch expired");
  }


  String cause = "NORMAL";
  bool dangerous = false;


  // ----------------------------------------------------------
  // Seismic trigger has the highest priority.
  // ----------------------------------------------------------

  if (seismicLatched) {
    dangerous = true;
    cause = "MICRO_SEISMIC_FRACTURE";
  }

  // ----------------------------------------------------------
  // Tilt trigger.
  // ----------------------------------------------------------

  else if (fabsf(sensor.pitchDeg) > TILT_CRITICAL_DEG) {
    dangerous = true;
    cause = "SLOPE_TILT_EXCEEDED";
  }

  // ----------------------------------------------------------
  // Hydrological trigger.
  // ----------------------------------------------------------

  else if (
    sensor.moisturePct > MOISTURE_CRITICAL_PCT &&
    sensor.poreKpa > PORE_CRITICAL_KPA
  ) {
    dangerous = true;
    cause = "HYDROLOGICAL_SHEAR_FAILURE";
  }


  const uint32_t now = millis();


  // ----------------------------------------------------------
  // Dangerous condition detected.
  // ----------------------------------------------------------

  if (dangerous) {
    if (riskState == NORMAL) {
      riskState = WARNING_PENDING;
      breachStartedAt = now;
      activeCause = cause;

      Serial.printf(
        "[RISK] WARNING_PENDING cause=%s\n",
        activeCause.c_str()
      );
    }

    else if (riskState == WARNING_PENDING) {
      // Update the cause if another trigger becomes active.
      activeCause = cause;

      if (now - breachStartedAt >= CONDITION_PERSIST_MS) {
        riskState = CRITICAL_FAILURE;

        Serial.printf(
          "[RISK] CRITICAL_FAILURE cause=%s\n",
          activeCause.c_str()
        );
      }
    }

    else {
      // CRITICAL_FAILURE remains active until recovery criteria
      // are satisfied.
    }
  }


  // ----------------------------------------------------------
  // No dangerous condition currently detected.
  // ----------------------------------------------------------

  else {
    const bool recovered =
      fabsf(sensor.pitchDeg) < TILT_RECOVERY_DEG &&
      sensor.moisturePct < MOISTURE_RECOVERY_PCT &&
      sensor.poreKpa < PORE_RECOVERY_KPA;

    if (recovered) {
      if (riskState != NORMAL) {
        Serial.println(
          "[RISK] recovery criteria satisfied; returning NORMAL"
        );
      }

      riskState = NORMAL;

      warningPendingReset();

      activeCause = "NORMAL";
    }
  }

  setOutputs();
}


void warningPendingReset() {
  breachStartedAt = 0;
}


// ============================================================
// Telemetry JSON
// ============================================================

String makeTelemetryJson() {
  JsonDocument doc;

  // ----------------------------------------------------------
  // Required backend fields.
  // ----------------------------------------------------------

  doc["sensor_id"] = "sensor_042";
  doc["lat"] = DEVICE_LATITUDE;
  doc["lng"] = DEVICE_LONGITUDE;

  // Required backend field.
  // For this prototype, pitch is used as the tilt delta.
  doc["tilt_delta"] = round2(sensor.pitchDeg);

  // Required backend field.
  doc["soil_moisture"] = round2(sensor.moisturePct);


  // ----------------------------------------------------------
  // Optional fields confirmed by the backend team.
  // ----------------------------------------------------------

  doc["risk_state"] = stateName(riskState);
  doc["trigger_cause"] = activeCause;

  doc["pitch_deg"] = round2(sensor.pitchDeg);
  doc["roll_deg"] = round2(sensor.rollDeg);

  doc["pore_pressure_kpa"] =
    round2(sensor.poreKpa);

  doc["packet_sequence_id"] =
    ++packetSequenceId;

  doc["mpu_ok"] = sensor.mpuOk;


  // ----------------------------------------------------------
  // Node metadata.
  // ----------------------------------------------------------

  doc["node_id"] = "NER_EDGE_NODE_01";
  doc["timestamp_ms"] = millis();


  // ----------------------------------------------------------
  // Raw acceleration.
  // ----------------------------------------------------------

  doc["accel_x_g"] = round2(sensor.accelXG);
  doc["accel_y_g"] = round2(sensor.accelYG);
  doc["accel_z_g"] = round2(sensor.accelZG);

  doc["accelerometer_x"] = round2(sensor.accelXG);
  doc["accelerometer_y"] = round2(sensor.accelYG);
  doc["accelerometer_z"] = round2(sensor.accelZG);


  // ----------------------------------------------------------
  // Raw angular velocity.
  // ----------------------------------------------------------

  doc["gyro_x_dps"] = round2(sensor.gyroXDps);
  doc["gyro_y_dps"] = round2(sensor.gyroYDps);
  doc["gyro_z_dps"] = round2(sensor.gyroZDps);

  doc["gyro_x"] = round2(sensor.gyroXDps);
  doc["gyro_y"] = round2(sensor.gyroYDps);
  doc["gyro_z"] = round2(sensor.gyroZDps);


  // ----------------------------------------------------------
  // Derived motion features.
  // ----------------------------------------------------------

  doc["angular_rate_dps"] =
    round2(sensor.angularRateDps);

  doc["angular_shift_rate_deg_per_sec"] =
    round2(sensor.angularRateDps);

  doc["vibration_rms_g"] =
    round2(sensor.vibrationRmsG);


  // ----------------------------------------------------------
  // Hydrological feature metadata.
  // ----------------------------------------------------------

  doc["soil_moisture_pct"] =
    round2(sensor.moisturePct);

  doc["soil_moisture_source"] =
    "simulated_potentiometer";

  doc["soil_saturation_index"] =
    round2(sensor.moisturePct / 100.0f);

  doc["pore_pressure_source"] =
    "simulated_potentiometer";


  // ----------------------------------------------------------
  // Acoustic/seismic feature metadata.
  // ----------------------------------------------------------

  doc["tripwire_flag"] = seismicLatched;

  doc["acoustic_source"] =
    "simulated_tripwire";


  // ----------------------------------------------------------
  // Validity flags.
  // ----------------------------------------------------------

  doc["moisture_valid"] = true;
  doc["pressure_valid"] = true;
  doc["acoustic_valid"] = true;


  String payload;

  serializeJson(doc, payload);

  return payload;
}


// ============================================================
// HTTP telemetry transmission
// ============================================================

void sendTelemetry() {
  const String payload = makeTelemetryJson();

  // Always print telemetry locally, even if Wi-Fi or HTTP fails.
  Serial.println("[TELEMETRY] " + payload);


  // Do not attempt HTTP until Wi-Fi is connected.
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] skipped: WiFi not connected");
    return;
  }


  // HTTPS client for the ngrok endpoint.
  //
  // setInsecure() is acceptable for this Wokwi demonstration.
  // For production hardware, use a verified root certificate.
  WiFiClientSecure client;

  client.setInsecure();


  HTTPClient http;

  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  static constexpr float ACCEL_SCALE_G = 16384.0f;  // MPU6050 ±2g
  static constexpr float GYRO_SCALE_DPS = 131.0f;   // MPU6050 ±250 dps

  static constexpr float VIBRATION_BASELINE_G = 1.0f;
  static constexpr float VIBRATION_CRITICAL_RMS_G = 0.15f;

  static constexpr float ANGULAR_RATE_CRITICAL_DPS = 45.0f;
  http.setTimeout(HTTP_TIMEOUT_MS);


  if (!http.begin(client, SERVER_URL)) {
    Serial.println("[HTTP] begin() failed");
    return;
  }


  // Required headers.
  http.addHeader("Content-Type", "application/json");

  http.addHeader(
    "X-API-Key",
    SERVICE_API_KEY
  );

  // Prevent the ngrok browser warning from affecting requests.
  http.addHeader(
    "ngrok-skip-browser-warning",
    "true"
  );


  const int code = http.POST(payload);
  Serial.print("[HTTP] status: ");
  Serial.println(code);

  String response = http.getString();

  Serial.print("[HTTP] response: ");
  Serial.println(response);
  http.end();



  if (code > 0) {
    const String response = http.getString();

    Serial.printf(
      "[HTTP] status: %d\n",
      code
    );

    Serial.println(
      "[HTTP] response: " + response
    );
  }

  else {
    Serial.printf(
      "[HTTP] request failed: %s\n",
      http.errorToString(code).c_str()
    );
  }


  http.end();
}


// ============================================================
// Wi-Fi maintenance
// ============================================================

void maintainWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  const uint32_t now = millis();

  if (now - lastWiFiRetryAt < WIFI_RETRY_INTERVAL_MS) {
    return;
  }

  lastWiFiRetryAt = now;

  Serial.println("[WIFI] attempting connection...");

  WiFi.disconnect();

  WiFi.begin(
    WIFI_SSID,
    WIFI_PASSWORD
  );
}


// ============================================================
// Serial status
// ============================================================

void printStatus() {
  Serial.printf(
    "[STATUS] "
    "state=%s "
    "pitch=%.2fdeg "
    "roll=%.2fdeg "
    "angular_rate=%.2fdps "
    "vibration=%.4fg "
    "moisture=%.1f%% "
    "pore=%.1fkPa "
    "mpu=%s "
    "wifi=%s\n",

    stateName(riskState),

    sensor.pitchDeg,
    sensor.rollDeg,
    sensor.angularRateDps,
    sensor.vibrationRmsG,

    sensor.moisturePct,
    sensor.poreKpa,

    sensor.mpuOk ? "OK" : "FAIL",

    WiFi.status() == WL_CONNECTED
      ? "CONNECTED"
      : "OFFLINE"
  );
}


// ============================================================
// Setup
// ============================================================

void setup() {
  Serial.println("### THIS IS THE NEW SKETCH BUILD ###");
  Serial.begin(115200);
  Serial.println("### UPDATED SKETCH VERSION 2026 ###");

  delay(300);

  Serial.println();

  Serial.println("========================================");
  Serial.println(" SafeSlope-NER v3 | EDGE NODE BOOT");
  Serial.println("========================================");


  // Output pins.
  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_LED, OUTPUT);

  // Simulated seismic/acoustic tripwire.
  pinMode(
    PIN_SEISMIC_TRIP,
    INPUT_PULLDOWN
  );

  digitalWrite(PIN_BUZZER, LOW);
  digitalWrite(PIN_LED, LOW);


  // ADC configuration.
  analogReadResolution(12);

  analogSetPinAttenuation(
    PIN_SOIL_MOISTURE,
    ADC_11db
  );

  analogSetPinAttenuation(
    PIN_PORE_PRESSURE,
    ADC_11db
  );


  // Seismic interrupt.
  attachInterrupt(
    digitalPinToInterrupt(PIN_SEISMIC_TRIP),
    onSeismicInterrupt,
    RISING
  );


  // MPU6050.
  sensor.mpuOk = initMPU();

  Serial.printf(
    "[MPU6050] %s at I2C 0x68 (SDA=21 SCL=22)\n",
    sensor.mpuOk ? "OK" : "INIT FAILED"
  );


  // Wi-Fi startup is non-blocking.
  WiFi.mode(WIFI_STA);

  WiFi.begin(
    WIFI_SSID,
    WIFI_PASSWORD
  );

  Serial.println(
    "[WIFI] non-blocking startup; "
    "edge sensing does not depend on WiFi"
  );
}


// ============================================================
// Main loop
// ============================================================

void loop() {
  const uint32_t now = millis();


  // Maintain Wi-Fi without blocking the sensing loop.
  maintainWiFi();


  // Sensor sampling and risk evaluation.
  if (now - lastSensorAt >= SENSOR_INTERVAL_MS) {
    lastSensorAt = now;

    updateSensors();

    // Existing detection and alarm logic.
    evaluateRisk();
  }


  // Human-readable status output.
  if (
    now - lastSerialStatusAt >=
    SERIAL_STATUS_INTERVAL_MS
  ) {
    lastSerialStatusAt = now;

    printStatus();
  }


  // Telemetry transmission.
  if (
    now - lastTelemetryAt >=
    TELEMETRY_INTERVAL_MS
  ) {
    lastTelemetryAt = now;

    sendTelemetry();
  }


  // Small yield delay.
  delay(5);
}