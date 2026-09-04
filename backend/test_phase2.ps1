$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = "local-demo-key"
$SensorId = "automated-phase2-" + (Get-Date -Format "yyyyMMdd-HHmmssfff")

Write-Host "Using sensor ID: $SensorId"
$Headers = @{
    "X-API-Key" = $ApiKey
    "Content-Type" = "application/json"
}

function Send-Telemetry {
    param(
        [string]$Name,
        [double]$TiltDelta,
        [double]$SoilMoisture,
        [double]$PorePressureKpa,
        [double]$VibrationRmsG,
        [bool]$TripwireFlag = $false
    )

    $Body = @{
        sensor_id = $SensorId
        lat = 28.6139
        lng = 77.2090
        tilt_delta = $TiltDelta
        soil_moisture = $SoilMoisture
        pore_pressure_kpa = $PorePressureKpa
        vibration_rms_g = $VibrationRmsG
        tripwire_flag = $TripwireFlag
    } | ConvertTo-Json

    $Response = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/telemetry/" `
        -Headers $Headers `
        -Body $Body

    Write-Host "$Name telemetry submitted. Event: $($Response.event_type)" -ForegroundColor Cyan

    return $Response
}

function Assert-Equal {
    param(
        [string]$Name,
        $Actual,
        $Expected
    )

    if ($Actual -ne $Expected) {
        throw "FAIL: $Name. Expected '$Expected' but got '$Actual'"
    }

    Write-Host "PASS: $Name = $Actual" -ForegroundColor Green
}

Write-Host ""
Write-Host "Starting SafeSlope Phase 2 automated test..." -ForegroundColor Yellow
Write-Host ""

# 1. Normal telemetry
Send-Telemetry `
    -Name "Normal" `
    -TiltDelta 1.0 `
    -SoilMoisture 40 `
    -PorePressureKpa 20 `
    -VibrationRmsG 0.1

# 2. Warning telemetry
Send-Telemetry `
    -Name "Warning" `
    -TiltDelta 4.0 `
    -SoilMoisture 40 `
    -PorePressureKpa 20 `
    -VibrationRmsG 0.1

# 3. Critical telemetry
Send-Telemetry `
    -Name "Critical" `
    -TiltDelta 6.0 `
    -SoilMoisture 40 `
    -PorePressureKpa 20 `
    -VibrationRmsG 0.1

# 4. Recovery telemetry
Send-Telemetry `
    -Name "Recovery" `
    -TiltDelta 1.0 `
    -SoilMoisture 40 `
    -PorePressureKpa 20 `
    -VibrationRmsG 0.1

Write-Host ""
Write-Host "Fetching latest telemetry records..." -ForegroundColor Yellow

$TelemetryResponse = Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/telemetry/?sensor_id=$SensorId" `
    -Headers $Headers

$TelemetryRecords = @($TelemetryResponse)

if ($TelemetryRecords.Count -lt 4) {
    throw "FAIL: Expected at least 4 telemetry records, got $($TelemetryRecords.Count)"
}

$LatestTelemetry = @(
    $TelemetryRecords |
        Sort-Object { [int]$_.id } |
        Select-Object -Last 4
)

Assert-Equal `
    -Name "Normal risk state" `
    -Actual $LatestTelemetry[0].risk_state `
    -Expected "NORMAL"

Assert-Equal `
    -Name "Warning risk state" `
    -Actual $LatestTelemetry[1].risk_state `
    -Expected "WARNING_PENDING"

Assert-Equal `
    -Name "Critical risk state" `
    -Actual $LatestTelemetry[2].risk_state `
    -Expected "CRITICAL_FAILURE"

Assert-Equal `
    -Name "Recovery risk state" `
    -Actual $LatestTelemetry[3].risk_state `
    -Expected "NORMAL"

Assert-Equal `
    -Name "Normal trigger cause" `
    -Actual $LatestTelemetry[0].trigger_cause `
    -Expected "NORMAL_MEASUREMENTS"

Assert-Equal `
    -Name "Warning trigger cause" `
    -Actual $LatestTelemetry[1].trigger_cause `
    -Expected "ELEVATED_TILT"

Assert-Equal `
    -Name "Critical trigger cause" `
    -Actual $LatestTelemetry[2].trigger_cause `
    -Expected "EXCESSIVE_TILT"

Assert-Equal `
    -Name "Recovery trigger cause" `
    -Actual $LatestTelemetry[3].trigger_cause `
    -Expected "NORMAL_MEASUREMENTS"

Write-Host ""
Write-Host "Fetching latest event records..." -ForegroundColor Yellow

$EventsResponse = Invoke-RestMethod `
    -Method Get `
    -Uri "$BaseUrl/events/?sensor_id=$SensorId" `
    -Headers $Headers

$Events = @($EventsResponse)

if ($Events.Count -lt 4) {
    throw "FAIL: Expected at least 4 events, got $($Events.Count)"
}

# API returns newest-first. Sort by database ID ascending,
# then select the newest four events.
$LatestEvents = @(
    $EventRecords |
        Sort-Object { [int]$_.id } -Descending |
        Select-Object -First 4 |
        Sort-Object { [int]$_.id }
)
Assert-Equal `
    -Name "Initial event" `
    -Actual $LatestEvents[0].event_type `
    -Expected "INITIAL_STATE"

Assert-Equal `
    -Name "Warning event" `
    -Actual $LatestEvents[1].event_type `
    -Expected "WARNING_ENTERED"

Assert-Equal `
    -Name "Critical event" `
    -Actual $LatestEvents[2].event_type `
    -Expected "CRITICAL_ENTERED"

Assert-Equal `
    -Name "Recovery event" `
    -Actual $LatestEvents[3].event_type `
    -Expected "CRITICAL_EXITED"

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "PHASE 2 TEST PASSED" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green