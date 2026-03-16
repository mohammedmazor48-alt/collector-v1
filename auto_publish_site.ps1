$ErrorActionPreference = 'Stop'

$projectRoot = 'D:\openclaw\workspaces\think-tank\collector-v1'
$pythonExe = 'D:\openclaw\workspaces\think-tank\collector-v1\.venv\Scripts\python.exe'
$logDir = Join-Path $projectRoot 'knowledge-vault\logs'
$logFile = Join-Path $logDir 'auto-publish-site.log'

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$ts] $Message"
    Write-Output $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

$now = Get-Date
$hour = $now.Hour

if ($hour -lt 8 -or $hour -gt 22) {
    Write-Log "skip: outside publish window (allowed 08:00-22:59, now $($now.ToString('HH:mm:ss')))"
    exit 0
}

if (-not (Test-Path $pythonExe)) {
    Write-Log "error: python not found at $pythonExe"
    exit 1
}

Set-Location $projectRoot
Write-Log 'start: export_site_data.py'
& $pythonExe .\export_site_data.py 2>&1 | Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    Write-Log "error: export_site_data.py failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Log 'start: publish_site_data.py'
& $pythonExe .\publish_site_data.py --skip-export 2>&1 | Tee-Object -FilePath $logFile -Append
if ($LASTEXITCODE -ne 0) {
    Write-Log "error: publish_site_data.py failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Log 'done: auto publish completed'
exit 0
