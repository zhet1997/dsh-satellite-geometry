param([string]$Distro = 'Ubuntu')
$ErrorActionPreference = 'Stop'
$satelliteRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location (Join-Path $satelliteRoot 'web')
try {
  & npm.cmd ci
  if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败' }
  & npm.cmd run build
  if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally { Pop-Location }
Push-Location (Join-Path $satelliteRoot 'plugin')
try {
  & npm.cmd ci
  if ($LASTEXITCODE -ne 0) { throw 'DSH 插件依赖安装失败' }
  & npm.cmd run build
  if ($LASTEXITCODE -ne 0) { throw 'DSH 插件构建失败' }
  & npm.cmd run install:profile
  if ($LASTEXITCODE -ne 0) { throw 'DSH 插件配置安装失败' }
} finally { Pop-Location }
$satelliteLinuxRoot = & wsl.exe -d $Distro --exec wslpath -a ($satelliteRoot.Replace('\', '/'))
if ($LASTEXITCODE -ne 0 -or -not $satelliteLinuxRoot) { throw '无法将工作台目录转换为 WSL 路径。' }
$satelliteLinuxRoot = $satelliteLinuxRoot.Trim()
& wsl.exe -d $Distro -u root -- systemctl start docker
if ($LASTEXITCODE -ne 0) { throw 'Docker 未能启动' }
& wsl.exe -d $Distro -u root --cd $satelliteLinuxRoot -- /usr/bin/docker -H unix:///var/run/docker.sock build --network host -t dsh-satellite-geometry:0.3.0 .
if ($LASTEXITCODE -ne 0) { throw '容器构建失败' }
