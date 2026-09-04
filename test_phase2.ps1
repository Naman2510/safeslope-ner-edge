$ErrorActionPreference = "Stop"

$BaseUrl = "http://127.0.0.1:8000"
$ApiKey = "local-demo-key"
$SensorId = "automated-phase2-test"

$Headers = @{
    "X-API-Key" = $ApiKey
    "Content-Type" = "application/json"
}

function Send-Telemetry {
    param(
        [string]$Name,
        [double]$Tilt,
        [double]$SoilMoisture,
        [double]$PorePressure,
        [double]$Vibration,
        [bool]$Tripwire = $false
    )

    $Body = @{
        sensor_id = $SensorId
        tilt = $Tilt
        soil_moisture = $SoilMoisture
        pore_pressure = $PorePressure
        vibration = $Vibration
        tripwire = $Tripwire
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
    -Tilt 1.0 `
    -SoilMoisture 40 `
    -PorePressure 20 `
    -Vibration 0.1

# 2. Warning telemetry
Send-Telemetry `
    -Name "Warning" `
    -Tilt 4.0 `
    -SoilMoisture 40 `
    -PorePressure 20 `
    -Vibration 0.1

# 3. Critical telemetry
Send-Telemetry `
    -Name "Critical" `
    -Tilt 6.0 `
    -SoilMoisture 40 `
    -PorePressure 20 `
    -Vibration 0.1

# 4. Recovery telemetry
Send-Telemetry `
    -Name "Recovery" `
    -Tilt 1.0 `
    -SoilMoisture 40 `
    -PorePressure 20 `
    -Vibration 0.1

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

$LatestTelemetry = $TelemetryRecords | Select-Object -Last 4

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
    -Expected "No significant risk indicators"

Assert-Equal `
    -Name "Warning trigger cause" `
    -Actual $LatestTelemetry[1].trigger_cause `
    -Expected "Tilt threshold exceeded"

Assert-Equal `
    -Name "Critical trigger cause" `
    -Actual $LatestTelemetry[2].trigger_cause `
    -Expected "Tilt threshold exceeded"

Assert-Equal `
    -Name "Recovery trigger cause" `
    -Actual $LatestTelemetry[3].trigger_cause `
    -Expected "No significant risk indicators"

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

$LatestEvents = $Events | Select-Object -Last 4

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