$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$projectRoot = Resolve-Path "$PSScriptRoot\.."
$runtimeRoot = Join-Path $projectRoot ".runtime"
$downloadRoot = Join-Path $runtimeRoot "downloads"
$pythonVersion = "3.13.3"
$nodeVersion = "22.16.0"
$pythonRoot = Join-Path $runtimeRoot "python"
$nodeRoot = Join-Path $runtimeRoot "node-v$nodeVersion-win-x64"
$backendRoot = Join-Path $projectRoot "backend"
$frontendRoot = Join-Path $projectRoot "frontend"
$pipCache = Join-Path $runtimeRoot "pip-cache"
$npmCache = Join-Path $runtimeRoot "npm-cache"

function Test-Executable {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [string[]]$Arguments = @("--version")
  )

  if (-not (Test-Path $Path)) {
    return $false
  }

  try {
    & $Path @Arguments | Out-Null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

function Save-Url {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [Parameter(Mandatory = $true)]
    [string]$OutFile
  )

  if (Test-Path $OutFile) {
    return
  }

  Write-Host "Downloading $Url"
  try {
    Invoke-WebRequest -Uri $Url -OutFile $OutFile
    return
  } catch {
    Write-Host "Invoke-WebRequest failed, trying curl.exe..."
  }

  $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
  if ($curl) {
    & $curl.Source -L $Url -o $OutFile
    if ($LASTEXITCODE -eq 0 -and (Test-Path $OutFile)) {
      return
    }
  }

  throw "Failed to download $Url. You can manually place the file at $OutFile and rerun this script."
}

New-Item -ItemType Directory -Force -Path $runtimeRoot, $downloadRoot, $pipCache, $npmCache | Out-Null
$env:PIP_CACHE_DIR = $pipCache

$pythonExe = Join-Path $pythonRoot "python.exe"
$pythonZip = Join-Path $downloadRoot "python-$pythonVersion-embed-amd64.zip"
$getPip = Join-Path $downloadRoot "get-pip.py"

if (-not (Test-Executable -Path $pythonExe)) {
  Save-Url `
    -Url "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-embed-amd64.zip" `
    -OutFile $pythonZip

  if (Test-Path $pythonRoot) {
    throw "Python runtime directory exists but is not usable: $pythonRoot. Remove it manually and rerun this script."
  }

  Write-Host "Extracting embedded Python $pythonVersion to $pythonRoot..."
  New-Item -ItemType Directory -Force -Path $pythonRoot | Out-Null
  Expand-Archive -Path $pythonZip -DestinationPath $pythonRoot -Force

  $pthFile = Join-Path $pythonRoot "python313._pth"
  if (Test-Path $pthFile) {
    (Get-Content $pthFile) -replace "^#import site$", "import site" | Set-Content $pthFile -Encoding ASCII
  }
}

if (-not (Test-Executable -Path $pythonExe)) {
  throw "Python runtime is not available at $pythonExe."
}

Save-Url -Url "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip

if (-not (Test-Executable -Path $pythonExe -Arguments @("-m", "pip", "--version"))) {
  Write-Host "Installing pip into embedded Python..."
  & $pythonExe $getPip --no-warn-script-location
}

Write-Host "Installing backend dependencies..."
& $pythonExe -m pip install --no-warn-script-location -r (Join-Path $backendRoot "requirements.txt")

$nodeExe = Join-Path $nodeRoot "node.exe"
$npmCmd = Join-Path $nodeRoot "npm.cmd"
$nodeZip = Join-Path $downloadRoot "node-v$nodeVersion-win-x64.zip"

if (-not ((Test-Executable -Path $nodeExe) -and (Test-Executable -Path $npmCmd))) {
  Save-Url `
    -Url "https://nodejs.org/dist/v$nodeVersion/node-v$nodeVersion-win-x64.zip" `
    -OutFile $nodeZip

  if (Test-Path $nodeRoot) {
    throw "Node.js runtime directory exists but is not usable: $nodeRoot. Remove it manually and rerun this script."
  }

  Write-Host "Extracting Node.js $nodeVersion to $runtimeRoot..."
  Expand-Archive -Path $nodeZip -DestinationPath $runtimeRoot -Force
}

if (-not ((Test-Executable -Path $nodeExe) -and (Test-Executable -Path $npmCmd))) {
  throw "Node.js runtime is not available at $nodeRoot."
}

Write-Host "Installing frontend dependencies..."
$env:PATH = "$nodeRoot;$env:PATH"
$env:npm_config_cache = $npmCache
Push-Location $frontendRoot
try {
  & $npmCmd install --cache $npmCache
} finally {
  Pop-Location
}

Write-Host ""
Write-Host "Runtime setup complete."
Write-Host "Python: $pythonExe"
Write-Host "Node:   $nodeExe"
Write-Host ""
Write-Host "Start backend:  .\scripts\start_backend.ps1"
Write-Host "Start frontend: .\scripts\start_frontend.ps1"
