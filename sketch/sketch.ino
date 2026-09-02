#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <ArduinoJson.h>

// SafeSlope-NER v3
// ESP32 edge node for landslide early-warning simulation.

static constexpr uint8_t MPU_ADDR = 0x68;

// ---------------- Hardware ----------------
static constexpr int PIN_BUZZER = 18;
static constexpr int PIN_LED = 19;
static constexpr int PIN_SOIL_MOISTURE = 34; // ADC1
static constexpr int PIN_PORE_PRESSURE = 35; // ADC1
static constexpr int PIN_SEISMIC_TRIP = 4;

// ---------------- Network ----------------
static const char* WIFI_SSID = "Wokwi-GUEST";
static const char* WIFI_PASSWORD = "";
// Replace with your real backend endpoint when ready.
static const char* SERVER_URL = "https://httpbin.org/post";

// ---------------- Risk thresholds ----------------
static constexpr float TILT_CRITICAL_DEG = 5.0f;
static constexpr float TILT_RECOVERY_DEG = 3.5f;
static constexpr float MOISTURE_CRITICAL_PCT = 85.0f;
static constexpr float MOISTURE_RECOVERY_PCT = 80.0f;
static constexpr float PORE_CRITICAL_KPA = 70.0f;
static constexpr float PORE_RECOVERY_KPA = 65.0f;
static constexpr uint32_t CONDITION_PERSIST_MS = 1500;
static constexpr uint32_t SEISMIC_LATCH_MS = 10000;
static constexpr uint32_t TELEMETRY_INTERVAL_MS = 2000;
static constexpr uint32_t SENSOR_INTERVAL_MS = 100;
static constexpr uint32_t SERIAL_STATUS_INTERVAL_MS = 1000;
static constexpr uint32_t WIFI_RETRY_INTERVAL_MS = 5000;
static constexpr uint32_t HTTP_TIMEOUT_MS = 1500;

// ---------------- State ----------------
enum RiskState {
  NORMAL,
  WARNING_PENDING,
  CRITICAL_FAILURE
};

struct SensorData {
  float pitchDeg = 0.0f;
  float moisturePct = 0.0f;
  float poreKpa = 0.0f;
  bool mpuOk = false;
};

SensorData sensor;

float pitchHistory[3] = {0.0f, 0.0f, 0.0f};
uint8_t filterIndex = 0;

volatile bool seismicIRQ = false;
portMUX_TYPE irqMux = portMUX_INITIALIZER_UNLOCKED;

bool seismicLatched = false;
uint32_t seismicLatchedAt = 0;

RiskState riskState = NORMAL;
String activeCause = "NORMAL";

void warningPendingReset();
uint32_t breachStartedAt = 0;

uint32_t lastSensorAt = 0;
uint32_t lastTelemetryAt = 0;
uint32_t lastSerialStatusAt = 0;
uint32_t lastWiFiRetryAt = 0;

// ---------------- Interrupt ----------------
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

// ---------------- MPU6050 ----------------
bool initMPU() {
  Wire.begin(21, 22);
  Wire.setClock(400000);

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B); // PWR_MGMT_1
  Wire.write(0x00); // wake up

  return Wire.endTransmission(true) == 0;
}

bool readMPU(int16_t& ax, int16_t& ay, int16_t& az) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);

  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  const uint8_t requested = 6;

  if (Wire.requestFrom(
        static_cast<uint8_t>(MPU_ADDR),
        requested,
        true
      ) != requested) {
    return false;
  }

  ax = (static_cast<int16_t>(Wire.read()) << 8) | Wire.read();
  ay = (static_cast<int16_t>(Wire.read()) << 8) | Wire.read();
  az = (static_cast<int16_t>(Wire.read()) << 8) | Wire.read();

  return true;
}

// ---------------- Helpers ----------------
float adcPercent(int pin) {
  return (static_cast<float>(analogRead(pin)) / 4095.0f) * 100.0f;
}

float round2(float value) {
  return roundf(value * 100.0f) / 100.0f;
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
  const bool alarm = (riskState == CRITICAL_FAILURE);

  digitalWrite(PIN_LED, alarm ? HIGH : LOW);
  digitalWrite(PIN_BUZZER, alarm ? HIGH : LOW);
}

void updateSensors() {
  int16_t rawX, rawY, rawZ;

  sensor.mpuOk = readMPU(rawX, rawY, rawZ);

  if (sensor.mpuOk) {
    const float instantPitch = atan2f(
      static_cast<float>(rawY),
      sqrtf(
        static_cast<float>(rawX) * rawX +
        static_cast<float>(rawZ) * rawZ
      )
    ) * 180.0f / PI;

    pitchHistory[filterIndex] = instantPitch;
    filterIndex = (filterIndex + 1) % 3;

    sensor.pitchDeg =
      (pitchHistory[0] +
       pitchHistory[1] +
       pitchHistory[2]) / 3.0f;
  }

  sensor.moisturePct = adcPercent(PIN_SOIL_MOISTURE);
  sensor.poreKpa = adcPercent(PIN_PORE_PRESSURE);
}

void evaluateRisk() {
  if (consumeSeismicIRQ()) {
    seismicLatched = true;
    seismicLatchedAt = millis();

    Serial.println(
      "[EVENT] MICRO_SEISMIC_FRACTURE detected; event latched"
    );
  }

  if (
    seismicLatched &&
    millis() - seismicLatchedAt > SEISMIC_LATCH_MS
  ) {
    // The event remains a recorded trigger while the alarm logic can recover
    // if all other conditions are safe.
    seismicLatched = false;

    Serial.println("[EVENT] seismic latch expired");
  }

  String cause = "NORMAL";
  bool dangerous = false;

  if (seismicLatched) {
    dangerous = true;
    cause = "MICRO_SEISMIC_FRACTURE";

  } else if (fabsf(sensor.pitchDeg) > TILT_CRITICAL_DEG) {
    dangerous = true;
    cause = "SLOPE_TILT_EXCEEDED";

  } else if (
    sensor.moisturePct > MOISTURE_CRITICAL_PCT &&
    sensor.poreKpa > PORE_CRITICAL_KPA
  ) {
    dangerous = true;
    cause = "HYDROLOGICAL_SHEAR_FAILURE";
  }

  const uint32_t now = millis();

  if (dangerous) {
    if (riskState == NORMAL) {
      riskState = WARNING_PENDING;
      breachStartedAt = now;
      activeCause = cause;

      Serial.printf(
        "[RISK] WARNING_PENDING cause=%s\n",
        activeCause.c_str()
      );

    } else if (riskState == WARNING_PENDING) {
      // If a new, higher-priority trigger arrives during pending, update cause.
      activeCause = cause;

      if (now - breachStartedAt >= CONDITION_PERSIST_MS) {
        riskState = CRITICAL_FAILURE;

        Serial.printf(
          "[RISK] CRITICAL_FAILURE cause=%s\n",
          activeCause.c_str()
        );
      }

    } else {
      // Critical state is latched until recovery criteria are met.
      // Preserve the cause that actually caused the transition.
    }

  } else {
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

// ---------------- Telemetry ----------------
String makeTelemetryJson() {
  JsonDocument doc;

  doc["node_id"] = "NER_EDGE_NODE_01";
  doc["timestamp_ms"] = millis();
  doc["pitch_deg"] = round2(sensor.pitchDeg);
  doc["soil_moisture_pct"] = round2(sensor.moisturePct);
  doc["pore_pressure_kpa"] = round2(sensor.poreKpa);
  doc["mpu_ok"] = sensor.mpuOk;
  doc["state"] = stateName(riskState);
  doc["trigger_cause"] = activeCause;

  String payload;
  serializeJson(doc, payload);

  return payload;
}

void sendTelemetry() {
  const String payload = makeTelemetryJson();

  // Always print JSON so the Wokwi Serial Monitor / RFC2217 bridge is useful
  // even when Internet access is unavailable.
  Serial.println("[TELEMETRY] " + payload);

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] skipped: WiFi not connected");
    return;
  }

  HTTPClient http;

  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);

  if (!http.begin(SERVER_URL)) {
    Serial.println("[HTTP] begin() failed");
    return;
  }

  http.addHeader("Content-Type", "application/json");

  const int code = http.POST(payload);

  Serial.printf("[HTTP] code=%d\n", code);

  http.end();
}

// ---------------- WiFi ----------------
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
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// ---------------- Status ----------------
void printStatus() {
  Serial.printf(
    "[STATUS] state=%s pitch=%.2fdeg moisture=%.1f%% pore=%.1fkPa mpu=%s wifi=%s\n",
    stateName(riskState),
    sensor.pitchDeg,
    sensor.moisturePct,
    sensor.poreKpa,
    sensor.mpuOk ? "OK" : "FAIL",
    WiFi.status() == WL_CONNECTED ? "CONNECTED" : "OFFLINE"
  );
}

// ---------------- Setup ----------------
void setup() {
  Serial.begin(115200);
  delay(300);

  Serial.println();
  Serial.println("========================================");
  Serial.println(" SafeSlope-NER v3 | EDGE NODE BOOT");
  Serial.println("========================================");

  pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_SEISMIC_TRIP, INPUT_PULLDOWN);

  digitalWrite(PIN_BUZZER, LOW);
  digitalWrite(PIN_LED, LOW);

  analogReadResolution(12);

  analogSetPinAttenuation(
    PIN_SOIL_MOISTURE,
    ADC_11db
  );

  analogSetPinAttenuation(
    PIN_PORE_PRESSURE,
    ADC_11db
  );

  attachInterrupt(
    digitalPinToInterrupt(PIN_SEISMIC_TRIP),
    onSeismicInterrupt,
    RISING
  );

  sensor.mpuOk = initMPU();

  Serial.printf(
    "[MPU6050] %s at I2C 0x68 (SDA=21 SCL=22)\n",
    sensor.mpuOk ? "OK" : "INIT FAILED"
  );

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.println(
    "[WIFI] non-blocking startup; edge sensing does not depend on WiFi"
  );
}

// ---------------- Main Loop ----------------
void loop() {
  const uint32_t now = millis();

  maintainWiFi();

  if (now - lastSensorAt >= SENSOR_INTERVAL_MS) {
    lastSensorAt = now;

    updateSensors();
    evaluateRisk();
  }

  if (now - lastSerialStatusAt >= SERIAL_STATUS_INTERVAL_MS) {
    lastSerialStatusAt = now;

    printStatus();
  }

  if (now - lastTelemetryAt >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryAt = now;

    sendTelemetry();
  }

  delay(5);
}