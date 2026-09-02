import json
import time
import serial
import requests

SERIAL_URL = "rfc2217://127.0.0.1:4001"
BAUD = 115200
BACKEND_URL = "http://localhost:8000/api/v1/edge-telemetry"
FORWARD_TO_BACKEND = False  # Set True when the backend endpoint is running.


def run_bridge():
    print(f"[*] Connecting to Wokwi RFC2217 serial: {SERIAL_URL}")
    try:
        ser = serial.serial_for_url(SERIAL_URL, baudrate=BAUD, timeout=1)
    except Exception as exc:
        print(f"[!] Could not open serial port: {exc}")
        print("    Start the Wokwi simulator first and keep its simulator tab visible.")
        return

    print("[+] LIVE SERIAL BRIDGE CONNECTED")
    print("[+] Waiting for ESP32 output...")

    try:
        while True:
            raw = ser.readline()
            if not raw:
                continue

            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            print(line, flush=True)

            if not line.startswith("[TELEMETRY] "):
                continue

            text = line[len("[TELEMETRY] "):]
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                print("[BRIDGE] telemetry line was not valid JSON")
                continue

            if FORWARD_TO_BACKEND:
                try:
                    response = requests.post(BACKEND_URL, json=payload, timeout=1.0)
                    print(f"[BACKEND] HTTP {response.status_code}")
                except requests.RequestException as exc:
                    print(f"[BACKEND] unavailable: {exc}")

    except KeyboardInterrupt:
        print("\n[*] Stopping bridge...")
    finally:
        ser.close()


if __name__ == "__main__":
    run_bridge()
