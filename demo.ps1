# Hackathon Starter - Demo Scripts
# Windows PowerShell and Unix Shell scripts for common operations

# ============================================================
# demo.ps1 - Windows PowerShell demo script
# ============================================================

# This script runs a complete FoodBridge match cycle with demo reset
# Usage: .\demo.ps1 from the repository root

Write-Host "=== Hackathon Starter Demo ===" -ForegroundColor Cyan
Write-Host ""

# Ensure we're in the right directory
$rootDir = "C:\Users\akara\hackathon-starter"
Set-Location $rootDir

# Backend setup and start
Write-Host "1. Starting backend server..." -ForegroundColor Yellow
Write-Host "   cd backend && pip install -r requirements.txt" -NoNewline
Write-Host ""

# Start backend in background
$backendCmd = "& {
    python -m venv venv
    .\venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    uvicorn app.main:app --port 8000 --host 0.0.0.0
}"

Write-Host "   Starting uvicorn server on port 8000..." -ForegroundColor Yellow
$backendProcess = Start-Job -ScriptBlock $backendCmd

# Wait for server to start
Start-Sleep -Seconds 5

# Test basic endpoints
Write-Host ""
Write-Host "2. Testing API endpoints..." -ForegroundColor Yellow

# Health check
Write-Host "   GET /api/health" -NoNewline
$health = Invoke-RestMethod -Uri "http://localhost:8000/api/health"
Write-Host " - Status: $($health.status)" -ForegroundColor Green

# List restaurants
Write-Host "   GET /api/foodbridge/restaurants" -NoNewline
$rests = Invoke-RestMethod -Uri "http://localhost:8000/api/foodbridge/restaurants"
Write-Host " - Found $($rests.restaurants.length) restaurant(s)" -ForegroundColor Green

# List surplus (available by default)
Write-Host "   GET /api/foodbridge/surplus" -NoNewline
$surplus = Invoke-RestMethod -Uri "http://localhost:8000/api/foodbridge/surplus"
Write-Host " - Found $($surplus.surplus.length) surplus lot(s)" -ForegroundColor Green

# Run a match
Write-Host "   POST /api/foodbridge/match" -NoNewline
$match = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/foodbridge/match" -Body @{surplus_id="food-001"} | ConvertFrom-Json
Write-Host " - Success: $($match.success)" -ForegroundColor Green
Write-Host "   Workflow ID: $($match.workflow_id)" -ForegroundColor Cyan
Write-Host "   Total allocated: $($match.total_allocated) meals" -ForegroundColor Cyan

# Demo reset
Write-Host ""
Write-Host "3. Running demo reset..." -ForegroundColor Yellow
$reset = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/foodbridge/demo/reset"
Write-Host " - Success: $($reset.success) - $($reset.message)" -ForegroundColor Green

# Run another match after reset
Write-Host ""
Write-Host "4. Running match after reset..." -ForegroundColor Yellow
$match2 = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/foodbridge/match" -Body @{surplus_id="food-001"} | ConvertFrom-Json
Write-Host " - Success: $($match2.success)" -ForegroundColor Green
Write-Host "   Total allocated: $($match2.total_allocated) meals" -ForegroundColor Cyan

# Cleanup
Write-Host ""
Write-Host "5. Stopping backend..." -ForegroundColor Yellow
Remove-Job $backendProcess -Force 2>$null
Write-Host "   Done!" -ForegroundColor Cyan