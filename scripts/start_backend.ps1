$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path "$PSScriptRoot\.."
$backendRoot = Join-Path $projectRoot "backend"
$runtimePython = Join-Path $projectRoot ".runtime\python\python.exe"
$runtimeRoot = Join-Path $projectRoot ".runtime"
$pipCache = Join-Path $runtimeRoot "pip-cache"
$venvRoot = Join-Path $backendRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$backendHost = $env:BACKEND_HOST
$backendPort = $env:BACKEND_PORT

if (-not $backendHost) {
  $backendHost = "127.0.0.1"
}

if (-not $backendPort) {
  $backendPort = "8000"
}

$backendHealthUrl = "http://localhost:$backendPort/health"

function Test-HttpReady {
  param([string]$Url)

  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
  } catch {
    return $false
  }
}

function Test-Python {
  param([string]$Path)

  if (-not (Test-Path $Path)) {
    return $false
  }

  try {
    & $Path --version 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

function Resolve-BasePython {
  if (Test-Python $runtimePython) {
    return $runtimePython
  }

  $command = Get-Command python -ErrorAction SilentlyContinue
  if ($command -and $command.Source -notlike "*\Microsoft\WindowsApps\python.exe" -and (Test-Python $command.Source)) {
    return $command.Source
  }

  throw "No usable Python runtime was found. Run .\scripts\setup_runtime.ps1 first, or install Python 3.10+ and reopen PowerShell."
}

Set-Location $backendRoot
New-Item -ItemType Directory -Force -Path $pipCache | Out-Null
$env:PIP_CACHE_DIR = $pipCache

if (Test-HttpReady $backendHealthUrl) {
  Write-Host "Backend is already running: $backendHealthUrl"
  return
}

if (Test-Python $venvPython) {
  $pythonToUse = $venvPython
} elseif (Test-Python $runtimePython) {
  $pythonToUse = $runtimePython
} else {
  if (Test-Path $venvRoot) {
    $resolvedVenv = Resolve-Path $venvRoot
    if (-not $resolvedVenv.Path.StartsWith($backendRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to remove unexpected virtual environment path: $resolvedVenv"
    }

    Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
  }

  $basePython = Resolve-BasePython
  & $basePython -m venv $venvRoot
  $pythonToUse = $venvPython
}

& $pythonToUse -m pip install --no-warn-script-location -r requirements.txt
& $pythonToUse -m uvicorn app.main:app --reload --host $backendHost --port $backendPort
