param(
  [string]$Distro = 'Ubuntu',
  [int]$DshPort = 3081,
  [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$satelliteRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$satelliteRuntime = Join-Path $satelliteRoot 'runtime'
New-Item -ItemType Directory -Force -Path $satelliteRuntime | Out-Null
trap {
  $satelliteError = $_ | Out-String
  $satelliteError | Set-Content -LiteralPath (Join-Path $satelliteRuntime 'startup-error.log') -Encoding utf8
  if (-not $NoBrowser) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("工作台未能启动。`n$($_.Exception.Message)`n`n详细信息见：$satelliteRuntime\startup-error.log", '卫星几何工作台') | Out-Null
  }
  Write-Error $satelliteError -ErrorAction Continue
  exit 1
}

# This desktop profile intentionally uses the bundled local endpoint. Remote
# deployments and non-default ports are configured manually in DSH settings.
$satelliteEnvPath = Join-Path $satelliteRoot '.env'
$satelliteConfiguredPort = '8787'
if (Test-Path -LiteralPath $satelliteEnvPath) {
  foreach ($satelliteEnvLine in (Get-Content -LiteralPath $satelliteEnvPath)) {
    if ($satelliteEnvLine -match '^\s*SATCAD_PORT\s*=\s*([^#]*)') {
      $satelliteConfiguredPort = $Matches[1].Trim().Trim('"').Trim("'")
    }
  }
}
if ($env:SATCAD_PORT) { $satelliteConfiguredPort = $env:SATCAD_PORT }
if ($satelliteConfiguredPort -and $satelliteConfiguredPort -ne '8787') {
  throw '此桌面启动器固定使用本机 8787 端口。请将 SATCAD_PORT 恢复为 8787；若需要其他端口，请手动启动 Docker Compose，并在 DSH 插件设置中填写对应服务地址。'
}

function Test-GeometryService {
  try {
    $response = Invoke-RestMethod 'http://127.0.0.1:8787/api/health' -TimeoutSec 3
    return $response.service -eq 'satellite-geometry'
  } catch { return $false }
}

# Systemd services alone do not keep WSL alive after its last client exits.
$satelliteKeepaliveFile = Join-Path $satelliteRuntime 'wsl-keepalive.pid'
$satelliteKeepalive = $null
if (Test-Path $satelliteKeepaliveFile) {
  $satelliteKeepalive = Get-CimInstance Win32_Process -Filter "ProcessId=$(Get-Content $satelliteKeepaliveFile)" -ErrorAction SilentlyContinue
}
if (-not $satelliteKeepalive -or $satelliteKeepalive.CommandLine -notmatch 'sleep infinity') {
  $satelliteKeepalive = Start-Process wsl.exe -ArgumentList @('-d', $Distro, '--cd', '/', '--exec', 'sleep', 'infinity') -WindowStyle Hidden -PassThru
  $satelliteKeepalive.Id | Set-Content $satelliteKeepaliveFile
}

if (-not (Test-GeometryService)) {
  & wsl.exe -d $Distro -u root -- systemctl start docker
  if ($LASTEXITCODE -ne 0) { throw '无法启动 WSL 中的 Docker，请检查 Ubuntu 环境。' }
  $satelliteLinuxRoot = & wsl.exe -d $Distro --exec wslpath -a ($satelliteRoot.Replace('\', '/'))
  if ($LASTEXITCODE -ne 0 -or -not $satelliteLinuxRoot) { throw '无法将工作台目录转换为 WSL 路径。' }
  $satelliteLinuxRoot = $satelliteLinuxRoot.Trim()
  & wsl.exe -d $Distro -u root --cd $satelliteLinuxRoot -- /usr/bin/docker -H unix:///var/run/docker.sock compose up -d
  if ($LASTEXITCODE -ne 0) { throw '几何服务容器启动失败。首次安装请先按 README 构建镜像。' }
  $satelliteDeadline = (Get-Date).AddSeconds(90)
  while (-not (Test-GeometryService)) {
    if ((Get-Date) -gt $satelliteDeadline) { throw '几何服务启动超时，请查看 docker compose logs。' }
    Start-Sleep -Milliseconds 700
  }
}

$satelliteDshUrl = "http://127.0.0.1:$DshPort/satellite-geometry/"
function Get-WorkbenchLaunchUrl {
  $satelliteLog = Join-Path $satelliteRuntime 'dsh.stdout.log'
  if (Test-Path $satelliteLog) {
    $satelliteMatch = [regex]::Match([string](Get-Content $satelliteLog -Raw), "http://127\.0\.0\.1:$DshPort/\?token=[^\s]+")
    if ($satelliteMatch.Success) { return $satelliteMatch.Value.Replace('/?token=', '/satellite-geometry/?token=') }
  }
  return $satelliteDshUrl
}
function Test-Workbench {
  try { return (Invoke-WebRequest (Get-WorkbenchLaunchUrl) -SessionVariable satelliteProbeSession -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}
$satelliteDshReady = $false
$satelliteDshReady = Test-Workbench
if (-not $satelliteDshReady) {
  $satelliteDshCommand = Get-Command dsh.ps1 -ErrorAction Stop
  $satelliteDshBin = Join-Path (Split-Path $satelliteDshCommand.Source -Parent) 'node_modules\@deepseek-ai\dsh\lib\bin.js'
  if (-not (Test-Path -LiteralPath $satelliteDshBin)) { throw '找不到 DSH 程序，请按 README 安装 DSH。' }
  $satelliteNode = (Get-Command node.exe -ErrorAction Stop).Source
  $satelliteProcess = Start-Process -FilePath $satelliteNode -WindowStyle Hidden -PassThru -WorkingDirectory $satelliteRoot `
    -ArgumentList @(('"{0}"' -f $satelliteDshBin), '--profile', 'satellite-geometry', '--port', "$DshPort", '--no-open') `
    -RedirectStandardOutput (Join-Path $satelliteRuntime 'dsh.stdout.log') `
    -RedirectStandardError (Join-Path $satelliteRuntime 'dsh.stderr.log')
  $satelliteProcess.Id | Set-Content -LiteralPath (Join-Path $satelliteRuntime 'dsh.pid')
  $satelliteDeadline = (Get-Date).AddSeconds(60)
  while (-not $satelliteDshReady) {
    $satelliteDshReady = Test-Workbench
    if ((Get-Date) -gt $satelliteDeadline) { throw 'DSH 工作台启动超时，请查看 runtime 目录中的日志。' }
    if (-not $satelliteDshReady) { Start-Sleep -Milliseconds 700 }
  }
}
if (-not $NoBrowser) { Start-Process (Get-WorkbenchLaunchUrl) }
Write-Output "工作台已就绪：$satelliteDshUrl"
