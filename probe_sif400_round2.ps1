# SIF-400 API discovery probe - ROUND 2
# Captures: (a) per-endpoint help detail pages with response schemas/samples,
#           (b) live responses from the read-only endpoints we plan to use.
# Run while connected to the SIF-400 wireless network:
#   powershell -ExecutionPolicy Bypass -File .\probe_sif400_round2.ps1
# Results are saved to .\api_probe_results_round2\

$base = "http://130.130.130.199"
$outDir = Join-Path $PSScriptRoot "api_probe_results_round2"
New-Item -ItemType Directory -Force $outDir | Out-Null

# Date range for performanceAnalytics samples (last 14 days, MM/DD/YYYY per docs)
$to = (Get-Date).ToString("MM/dd/yyyy")
$from = (Get-Date).AddDays(-14).ToString("MM/dd/yyyy")

$paths = @(
    # --- Help detail pages (schemas + sample responses) ---
    "/api/Help/Api/GET-Checker",
    "/api/Help/Api/GET-Ekanban",
    "/api/Help/Api/GET-Inventory",
    "/api/Help/Api/GET-PerformanceAnalytics_paOption_from_to",
    "/api/Help/Api/GET-DatabaseConnection",
    "/api/Help/Api/GET-WarehouseStatus_stationTypeId",

    # --- Live read-only endpoint samples ---
    "/api/checker",
    "/api/ekanban",
    "/api/Inventory",
    "/api/warehouseStatus?stationTypeId=406",

    # performanceAnalytics: documented option first, then likely variants
    # (404/error responses are cheap and often list the valid options)
    "/api/performanceAnalytics?paOption=AirAndEnergy&from=$from&to=$to",
    "/api/performanceAnalytics?paOption=Energy&from=$from&to=$to",
    "/api/performanceAnalytics?paOption=Air&from=$from&to=$to",
    "/api/performanceAnalytics?paOption=Production&from=$from&to=$to",
    "/api/performanceAnalytics?paOption=OEE&from=$from&to=$to",
    "/api/performanceAnalytics"
)
# NOTE: /api/databaseConnection is intentionally NOT probed - the docs say it
# refreshes the database in use, which could disrupt a running exercise.
# NOTE: /api/movService is NOT probed - it starts/stops the Mov service.

$summary = @()
$i = 0
foreach ($p in $paths) {
    $i++
    $url = "$base$p"
    $safeName = ($p -replace '[^a-zA-Z0-9]', '_').Trim('_')
    if ($safeName.Length -gt 80) { $safeName = $safeName.Substring(0, 80) }
    $outFile = Join-Path $outDir ("{0:d2}_{1}.txt" -f $i, $safeName)

    Write-Host "Probing $url ..."
    try {
        # Ask for JSON where the server negotiates content type
        $resp = Invoke-WebRequest -Uri $url -TimeoutSec 20 -UseBasicParsing `
            -Headers @{ "Accept" = "application/json, text/html;q=0.9, */*;q=0.8" } -ErrorAction Stop
        $status = $resp.StatusCode
        $ctype = $resp.Headers['Content-Type']
        $body = $resp.Content
        if ($body.Length -gt 262144) { $body = $body.Substring(0, 262144) + "`n...[TRUNCATED]" }
        @(
            "URL: $url",
            "STATUS: $status",
            "CONTENT-TYPE: $ctype",
            "BODY:",
            $body
        ) | Out-File -FilePath $outFile -Encoding utf8
        $summary += "$status  $p  ($ctype)"
    } catch {
        $msg = $_.Exception.Message
        $status = "ERR"
        $errBody = ""
        if ($_.Exception.Response) {
            try { $status = [int]$_.Exception.Response.StatusCode } catch {}
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                $reader = New-Object System.IO.StreamReader($stream)
                $errBody = $reader.ReadToEnd()
            } catch {}
        }
        @(
            "URL: $url",
            "STATUS: $status",
            "ERROR: $msg",
            "ERROR-BODY:",
            $errBody
        ) | Out-File -FilePath $outFile -Encoding utf8
        $summary += "$status  $p  ($msg)"
    }
}

$summaryFile = Join-Path $outDir "00_SUMMARY.txt"
@(
    "SIF-400 API probe round 2 - $(Get-Date)",
    "Base: $base",
    "PA date range: $from to $to",
    "",
    "STATUS  PATH",
    "------  ----"
) + $summary | Out-File -FilePath $summaryFile -Encoding utf8

Write-Host ""
Write-Host "Done. Results saved to: $outDir"
Write-Host "Summary:"
Get-Content $summaryFile | Write-Host
