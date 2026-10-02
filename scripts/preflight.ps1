# Preflight for Windows (wrapper around scripts/preflight.py).
# Usage: powershell -File scripts/preflight.ps1  (from repo root)
# If npm.ps1 fails with "running scripts is disabled", use npm.cmd instead.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
Set-Location $root
python scripts/preflight.py
exit $LASTEXITCODE
