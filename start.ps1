# SIF-400 Digital Twin startup script (Windows / PowerShell)
#
#   .\start.ps1          run against the REAL SIF-400 (requires the lab wireless network)
#   .\start.ps1 -Mock    run against the bundled mock SIFMES API (no lab network needed)
#
# Opens the backend and frontend (and the mock, with -Mock) each in their own
# window so you can watch their logs and Ctrl+C them individually.
# Use .\stop.ps1 to stop everything at once.

param([switch]$Mock)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPy = Join-Path $root 'backend\venv\Scripts\python.exe'

Write-Host "Starting SIF-400 Digital Twin..." -ForegroundColor Cyan

# 1. Ensure the backend virtual environment exists and has dependencies.
#    We ALWAYS use this venv's python - never the global one - so `requests`
#    and Flask are guaranteed present.
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv (Join-Path $root 'backend\venv')
}
Write-Host "Syncing Python dependencies..." -ForegroundColor Yellow
& $venvPy -m pip install -q -r (Join-Path $root 'backend\requirements.txt')

# 2. Mock mode: start the mock API, and tell the backend to poll it.
if ($Mock) {
    Write-Host "Starting mock SIFMES API on port 8199..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$root\backend'; & '$venvPy' mock_sifmes_api.py"
    )
    Start-Sleep -Seconds 2
    # Mock data goes to a separate DB so it never pollutes the real research data.
    $backendCmd = "Set-Location '$root\backend'; " +
                  "`$env:SIF400_API_BASE = 'http://localhost:8199/api'; " +
                  "`$env:SIF400_DB = 'sif400_mock.db'; & '$venvPy' app.py"
} else {
    # No env var => backend uses its default real SIF-400 base URL.
    $backendCmd = "Set-Location '$root\backend'; " +
                  "Remove-Item Env:\SIF400_API_BASE -ErrorAction SilentlyContinue; & '$venvPy' app.py"
}

# 3. Backend on port 5001.
Write-Host "Starting Flask backend on port 5001..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @('-NoExit', '-Command', $backendCmd)

# 4. Frontend on port 3000.
Write-Host "Starting React frontend on port 3000..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$root\frontend'; if (-not (Test-Path node_modules)) { npm install }; npm start"
)

Write-Host ""
Write-Host "SIF-400 Digital Twin is starting up!" -ForegroundColor Green
Write-Host "  Backend API:  http://localhost:5001"
Write-Host "  Frontend UI:  http://localhost:3000"
if ($Mock) { Write-Host "  Mock API:     http://localhost:8199/api  (mock mode)" -ForegroundColor Magenta }
else       { Write-Host "  Data source:  http://130.130.130.199/api  (real SIF-400 - needs lab network)" }
Write-Host ""
Write-Host "Run .\stop.ps1 to stop everything."
