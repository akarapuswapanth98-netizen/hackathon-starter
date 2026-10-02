# Hackathon Starter - Demo Scripts

# demo.ps1 - Windows PowerShell demo (generic chat/solve flow)
# Usage: .\demo.ps1 from the repository root

Write-Host "=== Hackathon Starter Demo ===" -ForegroundColor Cyan

$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $rootDir) { $rootDir = Get-Location }
Set-Location $rootDir

Write-Host "1. Starting backend server..." -ForegroundColor Yellow
$backendJob = Start-Job -ScriptBlock {
  param($dir)
  Set-Location (Join-Path $dir "backend")
  if (-not (Test-Path "venv")) { python -m venv venv }
  .\venv\Scripts\Activate.ps1
  pip install -r requirements.txt | Out-Null
  uvicorn app.main:app --port 8000 --host 0.0.0.0
} -ArgumentList $rootDir

Start-Sleep -Seconds 5

Write-Host "2. Testing API endpoints..." -ForegroundColor Yellow
$health = Invoke-RestMethod -Uri "http://localhost:8000/api/health"
Write-Host " - health: $($health.status)" -ForegroundColor Green

$chat = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/chat" -ContentType "application/json" -Body '{"message":"Hello"}'
Write-Host " - chat ok" -ForegroundColor Green

$body = @{ query = "Summarize RAG impact"; use_agents = $true } | ConvertTo-Json
$solve = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/solve" -ContentType "application/json" -Body $body
Write-Host " - solve success: $($solve.success)" -ForegroundColor Green

Write-Host "3. Stopping backend..." -ForegroundColor Yellow
Remove-Job $backendJob -Force 2>$null
Write-Host "Done!" -ForegroundColor Cyan
