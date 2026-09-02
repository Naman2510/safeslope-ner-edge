$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$cli = Join-Path $root "arduino-cli\arduino-cli.exe"
$sketch = Join-Path $root "sketch"
$out = Join-Path $sketch "build\espressif.esp32.esp32"

if (!(Test-Path $cli)) {
    Write-Host "arduino-cli.exe not found at $cli" -ForegroundColor Red
    exit 1
}

Write-Host "[1/2] Ensuring ArduinoJson is installed..."
& $cli lib install "ArduinoJson@7.4.3"
if ($LASTEXITCODE -ne 0) { throw "ArduinoJson installation failed." }

Write-Host "[2/2] Compiling SafeSlope-NER..."
& $cli compile --fqbn espressif:esp32:esp32 --output-dir $out $sketch
if ($LASTEXITCODE -ne 0) { throw "Compilation failed." }

Write-Host "BUILD OK" -ForegroundColor Green
Write-Host "Firmware: $out\sketch.ino.bin"
