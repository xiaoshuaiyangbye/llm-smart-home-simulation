$ErrorActionPreference = "SilentlyContinue"

$projectRoot = Resolve-Path "$PSScriptRoot\.."
$deployEnv = Join-Path $projectRoot "deploy\.env"
$frontendPort = $env:FRONTEND_PORT

if (-not $frontendPort -and (Test-Path $deployEnv)) {
  $frontendPort = Get-Content $deployEnv |
    Where-Object { $_ -match "^\s*FRONTEND_PORT\s*=" } |
    Select-Object -First 1
  if ($frontendPort) {
    $frontendPort = ($frontendPort -replace "^\s*FRONTEND_PORT\s*=", "").Trim()
  }
}

if (-not $frontendPort) {
  $frontendPort = "80"
}

if ($frontendPort -eq "80") {
  $frontendUrl = "http://localhost"
} else {
  $frontendUrl = "http://localhost:$frontendPort"
}
$backendHealthUrl = "$frontendUrl/health"

function Wait-HttpReady {
  param(
    [string]$Url,
    [int]$TimeoutSeconds
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        return $true
      }
    } catch {
      Start-Sleep -Seconds 1
    }
  }

  return $false
}

Write-Host "Waiting for backend: $backendHealthUrl"
Wait-HttpReady -Url $backendHealthUrl -TimeoutSeconds 45 | Out-Null

Write-Host "Waiting for frontend: $frontendUrl"
Wait-HttpReady -Url $frontendUrl -TimeoutSeconds 75 | Out-Null

Write-Host "Opening frontend: $frontendUrl"
Start-Process $frontendUrl
