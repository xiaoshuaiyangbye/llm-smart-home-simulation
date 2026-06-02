$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path "$PSScriptRoot\.."
$frontendRoot = Join-Path $projectRoot "frontend"
$runtimeRoot = Join-Path $projectRoot ".runtime"
$npmCache = Join-Path $runtimeRoot "npm-cache"
$frontendUrl = "http://localhost:5173"

function Test-HttpReady {
  param([string]$Url)

  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
  } catch {
    return $false
  }
}

Set-Location $frontendRoot

if (Test-HttpReady $frontendUrl) {
  Write-Host "Frontend is already running: $frontendUrl"
  return
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  $nodeDir = @(
    Get-ChildItem $runtimeRoot -Directory -Filter "node-v*-win-x64" -ErrorAction SilentlyContinue
    Get-ChildItem "C:\tmp" -Directory -Filter "node-v*-win-x64" -ErrorAction SilentlyContinue
  ) |
    Where-Object { Test-Path (Join-Path $_.FullName "npm.cmd") } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

  if (-not $nodeDir) {
    throw "npm was not found. Run .\scripts\setup_runtime.ps1 first, install Node.js, or place a portable Node.js win-x64 directory under C:\tmp."
  }

  $env:PATH = "$($nodeDir.FullName);$env:PATH"
}

New-Item -ItemType Directory -Force -Path $npmCache | Out-Null
$env:npm_config_cache = $npmCache

npm install --cache $npmCache
npm run dev
