# SIF-400 API discovery probe
# Run this while connected to the SIF-400 wireless network:
#   powershell -ExecutionPolicy Bypass -File .\probe_sif400.ps1
# Results are saved to .\api_probe_results\ - bring them back for analysis.

$base = "http://130.130.130.199"
$outDir = Join-Path $PSScriptRoot "api_probe_results"
New-Item -ItemType Directory -Force $outDir | Out-Null

# Candidate paths to try. The root and /api are most important; the rest are
# common patterns for industrial/SmartFactory (SMC SIF-400) style APIs.
$paths = @(
    "/",
    "/api",
    "/api/",
    "/api/stations",
    "/api/status",
    "/api/data",
    "/api/measurements",
    "/api/values",
    "/api/tags",
    "/api/nodes",
    "/api/devices",
    "/api/help",
    "/api/docs",
    "/api/swagger.json",
    "/api/openapi.json",
    "/api/v1",
    "/api/v1/stations",
    "/api/SIF-401",
    "/api/SIF401",
    "/api/sif401",
    "/api/stations/SIF-401",
    "/api/station/SIF-401",
    "/api/SIF-401/voltage",
    "/api/SIF-401/current",
    "/api/SIF-401/power",
    "/api/voltage",
    "/api/current",
    "/api/power",
    "/api/energy",
    "/api/sensors"
)

$summary = @()
$i = 0
foreach ($p in $paths) {
    $i++
    $url = "$base$p"
    $safeName = ($p -replace '[^a-zA-Z0-9]', '_').Trim('_')
    if ($safeName -eq '') { $safeName = 'root' }
    $outFile = Join-Path $outDir ("{0:d2}_{1}.txt" -f $i, $safeName)

    Write-Host "Probing $url ..."
    try {
        $resp = Invoke-WebRequest -Uri $url -TimeoutSec 8 -UseBasicParsing -ErrorAction Stop
        $status = $resp.StatusCode
        $ctype = $resp.Headers['Content-Type']
        # Truncate huge bodies; 100 KB is plenty to understand the schema
        $body = $resp.Content
        if ($body.Length -gt 102400) { $body = $body.Substring(0, 102400) + "`n...[TRUNCATED]" }
        @(
            "URL: $url",
            "STATUS: $status",
            "CONTENT-TYPE: $ctype",
            "HEADERS:",
            ($resp.Headers | Out-String),
            "BODY:",
            $body
        ) | Out-File -FilePath $outFile -Encoding utf8
        $summary += "$status  $p  ($ctype)"
    } catch {
        $msg = $_.Exception.Message
        $status = "ERR"
        if ($_.Exception.Response) {
            try { $status = [int]$_.Exception.Response.StatusCode } catch {}
        }
        "URL: $url`nSTATUS: $status`nERROR: $msg" | Out-File -FilePath $outFile -Encoding utf8
        $summary += "$status  $p  ($msg)"
    }
}

$summaryFile = Join-Path $outDir "00_SUMMARY.txt"
@(
    "SIF-400 API probe - $(Get-Date)",
    "Base: $base",
    "",
    "STATUS  PATH",
    "------  ----"
) + $summary | Out-File -FilePath $summaryFile -Encoding utf8

Write-Host ""
Write-Host "Done. Results saved to: $outDir"
Write-Host "Summary:"
Get-Content $summaryFile | Write-Host
