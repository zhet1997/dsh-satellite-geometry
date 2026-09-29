param([string]$DesktopDirectory = [Environment]::GetFolderPath('Desktop'))
$ErrorActionPreference = 'Stop'
$satelliteLauncher = Join-Path $PSScriptRoot 'Start-Workbench.ps1'
$satelliteRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$satellitePowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $DesktopDirectory -PathType Container)) { throw '找不到桌面目录。' }
$satelliteShortcutPath = Join-Path $DesktopDirectory '卫星几何工作台.lnk'
$satelliteShell = New-Object -ComObject WScript.Shell
$satelliteShortcut = $satelliteShell.CreateShortcut($satelliteShortcutPath)
$satelliteShortcut.TargetPath = $satellitePowerShell
$satelliteShortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $satelliteLauncher
$satelliteShortcut.WorkingDirectory = $satelliteRoot
$satelliteShortcut.Description = '启动本机卫星几何计算服务与 DSH 对话工作台'
$satelliteShortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,20"
$satelliteShortcut.WindowStyle = 7
$satelliteShortcut.Save()
Write-Output $satelliteShortcutPath
