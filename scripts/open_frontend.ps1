$ErrorActionPreference = "SilentlyContinue"

$frontendUrl = "http://localhost:5173"
$backendHealthUrl = "http://localhost:8000/health"

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
