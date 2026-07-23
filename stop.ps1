# SIF-400 Digital Twin stop script (Windows / PowerShell)
# Stops the backend, the mock API, and the React frontend.

Write-Host "Stopping SIF-400 Digital Twin..." -ForegroundColor Cyan

# Match on the command line so we only touch this project's processes, not
# unrelated python/node instances.
$patterns = @('app.py', 'mock_sifmes_api.py', 'react-scripts')

$procs = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match 'python|node' } |
    Where-Object {
        $cl = $_.CommandLine
        $cl -and ($patterns | Where-Object { $cl -like "*$_*" })
    }

if (-not $procs) {
    Write-Host "Nothing to stop - no matching processes found." -ForegroundColor Yellow
    return
}

foreach ($p in $procs) {
    Write-Host "  Stopping PID $($p.ProcessId): $($p.Name)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "All services stopped." -ForegroundColor Green
