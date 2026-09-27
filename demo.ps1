<# 
.SYNOPSIS
    FoodBridge Demo Script - runs full demo sequence against local backend
.DESCRIPTION
    Starts uvicorn, runs match/reset/match sequence, prints formatted JSON
.EXAMPLE
    .\demo.ps1
#>

param(
    [int]$Port = 8000,
    [string]$BackendPath = "backend"
)

$base = "http://localhost:$Port/api/foodbridge"
$health = "http://localhost:$Port/api/health"

function Json($obj) { $obj | ConvertTo-Json -Depth 10 }
function Curl($method, $url, $body = $null) {
    $params = @{ Uri = $url; Method = $method; ContentType = "application/json" }
    if ($body) { $params.Body = $body | ConvertTo-Json -Depth 10 }
    try { (Invoke-RestMethod @params) | Json } catch { Write-Error $_.Exception.Message; exit 1 }
}

Write-Host "=== Starting FoodBridge demo on port $Port ===" -ForegroundColor Cyan

# Start server in background
$server = Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "app.main:app", "--port", $Port, "--host", "127.0.0.1" -WorkingDirectory $BackendPath -PassThru -WindowStyle Hidden
Write-Host "Server PID: $($server.Id)" -ForegroundColor Gray
Start-Sleep -Seconds 4

try {
    Write-Host "`n--- Health check ---" -ForegroundColor Green
    Curl GET $health

    Write-Host "`n--- Restaurants ---" -ForegroundColor Green
    Curl GET "$base/restaurants"

    Write-Host "`n--- First match (consumes lot) ---" -ForegroundColor Green
    Curl POST "$base/match" '{"surplus_id":"food-001"}'

    Write-Host "`n--- Second match (409 - lot consumed) ---" -ForegroundColor Yellow
    Curl POST "$base/match" '{"surplus_id":"food-001"}'

    Write-Host "`n--- Demo reset ---" -ForegroundColor Cyan
    Curl POST "$base/demo/reset"

    Write-Host "`n--- Surplus after reset (available again) ---" -ForegroundColor Green
    Curl GET "$base/surplus"

    Write-Host "`n--- Match again after reset ---" -ForegroundColor Green
    Curl POST "$base/match" '{"surplus_id":"food-001"}'

    Write-Host "`n=== Demo complete ===" -ForegroundColor Cyan
}
finally {
    Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
    Write-Host "Server stopped." -ForegroundColor Gray
}