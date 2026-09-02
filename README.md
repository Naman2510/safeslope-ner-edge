# SafeSlope-NER v3

ESP32/Wokwi edge node for a landslide early-warning prototype.

## Architecture

Sensors -> ESP32 local risk engine -> LED/buzzer -> JSON telemetry -> HTTP backend

The edge decision does **not** depend on Wi-Fi being available. Serial telemetry is printed continuously so the Wokwi Serial Monitor remains useful even if HTTP networking fails.

## Pins

| Function | ESP32 pin |
|---|---:|
| MPU6050 SDA | GPIO 21 |
| MPU6050 SCL | GPIO 22 |
| Buzzer + | GPIO 18 |
| Critical LED | GPIO 19 |
| Soil moisture | GPIO 34 |
| Pore pressure | GPIO 35 |
| Seismic trip | GPIO 4 |

## Risk logic

- Tilt critical: `abs(pitch) > 5 deg`
- Tilt recovery: `abs(pitch) < 3.5 deg`
- Hydrological failure: moisture > 85% **and** pore pressure > 70 kPa
- Hydrological recovery: moisture < 80% **and** pore pressure < 65 kPa
- Dangerous condition must persist for 1.5 s before CRITICAL_FAILURE.
- Seismic interrupt is latched for 10 s so a short button press cannot disappear between loop iterations.
- CRITICAL_FAILURE retains the cause that caused the transition.

## Build

Open this folder in VS Code, then run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build.ps1
```

The script installs ArduinoJson 7.4.3 and generates the firmware expected by `wokwi.toml`.

## Wokwi

Start the simulator from `diagram.json` with the green play button. Keep the Wokwi simulator tab visible.

The diagram config requests the Wokwi Serial Monitor with `display: "always"`.

## Live external serial terminal

With Wokwi running:

```powershell
.\run-serial.ps1
```

This connects using RFC2217 rather than a raw TCP socket.

Important: the Wokwi Serial Monitor and an external RFC2217 client are two views of the same UART stream; if Wokwi/the extension only allows one active serial consumer, use the built-in Serial Monitor as the primary display and the bridge as the external alternative.

## Backend

The firmware currently posts to `https://httpbin.org/post` as a connectivity test. Change `SERVER_URL` in `sketch/sketch.ino` to the real API when the backend is available.

The bridge's backend forwarding is disabled by default. Set `FORWARD_TO_BACKEND = True` in `bridge.py` after the FastAPI endpoint is running.

## Demo sequence

1. Start Wokwi and watch the Serial Monitor.
2. Leave both potentiometers low and keep the MPU6050 level: `NORMAL`.
3. Rotate the MPU6050 beyond ~5 degrees and hold it: `WARNING_PENDING` then `CRITICAL_FAILURE`; LED and buzzer turn on.
4. Return the MPU6050 below ~3.5 degrees and lower both analog inputs: the state recovers to `NORMAL`.
5. Alternatively set moisture >85% and pore pressure >70 kPa simultaneously.
6. Press `Seismic Trip`: the interrupt is latched and the edge node enters the warning/critical path without needing a second ESP32.

## Troubleshooting

If Wokwi says the firmware `.bin` is missing, run `./build.ps1` from the project root and restart the simulator.

If the simulator runs but the external bridge shows no data, do not change the firmware first. Check that the simulator is actively running, its tab is visible, and port 4000 is not occupied by another serial client.
