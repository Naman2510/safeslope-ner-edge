$ErrorActionPreference = "Stop"
Write-Host "Testing Wokwi RFC2217 serial endpoint on localhost:4000..."
python -c "import serial; s=serial.serial_for_url('rfc2217://127.0.0.1:4001', baudrate=115200, timeout=3); print('CONNECTED'); print(repr(s.read(1000))); s.close()"
