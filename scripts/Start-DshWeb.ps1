param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$webRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$webRuntime = Join-Path $webRoot 'runtime'
New-Item -ItemType Directory -Force $webRuntime | Out-Null
$webLog = Join-Path $webRuntime 'dsh-web.stdout.log'
function Get-WebLaunchUrl {
  $webLogs = @(Get-Item $webLog -ErrorAction SilentlyContinue) + @(Get-ChildItem (Join-Path $env:USERPROFILE '.dsh\runtime\logs') -Filter 'dsh-web-*.out.log' -File -ErrorAction SilentlyContinue)
  foreach ($webCandidate in ($webLogs | Sort-Object LastWriteTime -Descending)) {
    $webMatch = [regex]::Match([string](Get-Content $webCandidate.FullName -Raw), 'http://127\.0\.0\.1:3080/\?token=[^\s]+')
    if ($webMatch.Success) { return $webMatch.Value }
  }
}
function Test-WebReady {
  $launch = Get-WebLaunchUrl
  if (-not $launch) { return $false }
  try { return (Invoke-WebRequest $launch -SessionVariable webSession -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}
if (-not (Test-WebReady)) {
  $webCommand = Get-Command dsh.ps1 -ErrorAction Stop
  $webBin = Join-Path (Split-Path $webCommand.Source -Parent) 'node_modules\@deepseek-ai\dsh\lib\bin.js'
  $webProcess = Start-Process (Get-Command node.exe).Source -WindowStyle Hidden -PassThru -WorkingDirectory $webRoot -ArgumentList @(('"{0}"' -f $webBin), 'web', '--no-open', '--host', '127.0.0.1', '--port', '3080') -RedirectStandardOutput $webLog -RedirectStandardError (Join-Path $webRuntime 'dsh-web.stderr.log')
  $webProcess.Id | Set-Content (Join-Path $webRuntime 'dsh-web.pid')
  $webDeadline = (Get-Date).AddSeconds(60)
  while (-not (Test-WebReady)) {
    if ((Get-Date) -gt $webDeadline) { throw 'DSH startup timed out. See runtime/dsh-web.stderr.log.' }
    Start-Sleep -Milliseconds 700
  }
}
if (-not $NoBrowser) { Start-Process (Get-WebLaunchUrl) }
Write-Output 'DSH web ready: http://127.0.0.1:3080/'
