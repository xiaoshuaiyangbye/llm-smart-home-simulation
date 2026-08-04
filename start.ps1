$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$deployRoot = Join-Path $projectRoot "deploy"
$composeFile = Join-Path $deployRoot "docker-compose.yml"
$deployEnv = Join-Path $deployRoot ".env"
$deployEnvExample = Join-Path $deployRoot ".env.example"
$backendEnv = Join-Path $deployRoot "backend.env"
$backendEnvExample = Join-Path $deployRoot "backend.env.example"

function Copy-ExampleIfMissing {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Target,
    [Parameter(Mandatory = $true)]
    [string]$Example
  )

  if ((-not (Test-Path $Target)) -and (Test-Path $Example)) {
    Copy-Item -Path $Example -Destination $Target
    Write-Host "Created $Target from $Example"
  }
}

function Get-EnvFileValue {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [string]$DefaultValue = ""
  )

  if (-not (Test-Path $Path)) {
    return $DefaultValue
  }

  $line = Get-Content $Path |
    Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
    Select-Object -First 1

  if (-not $line) {
    return $DefaultValue
  }

  return ($line -replace "^\s*$([regex]::Escape($Name))\s*=", "").Trim()
}

function Test-HttpReady {
  param([string]$Url)

  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
  } catch {
    return $false
  }
}

function Test-OllamaReady {
  try {
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
    return $null -ne $response.models
  } catch {
    return $false
  }
}

function Wait-OllamaReady {
  param([int]$TimeoutSeconds = 30)

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-OllamaReady) {
      return $true
    }
    Start-Sleep -Seconds 1
  }

  return $false
}

function Start-OllamaIfNeeded {
  if (Test-OllamaReady) {
    Write-Host "Ollama is already running."
    return
  }

  $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
  if (-not $ollamaCommand) {
    throw "LLM_MODE=real requires Ollama, but the 'ollama' command was not found. Install Ollama or change deploy/backend.env to LLM_MODE=mock."
  }

  Write-Host "Ollama is not running. Starting Ollama..."
  Start-Process -FilePath $ollamaCommand.Source -ArgumentList "serve" -WindowStyle Hidden
  if (-not (Wait-OllamaReady)) {
    throw "Ollama was started, but it did not become ready at http://127.0.0.1:11434 within 30 seconds. Check Ollama, then run start.bat again."
  }

  Write-Host "Ollama is ready."
}

function Invoke-CheckedCommand {
  param(
    [Parameter(Mandatory = $true)]
    [string]$FilePath,
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments
  )

  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($Arguments -join ' ')"
  }
}

function Wait-HttpReady {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [int]$TimeoutSeconds = 90
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-HttpReady -Url $Url) {
      return $true
    }
    Start-Sleep -Seconds 2
  }

  return $false
}

function Wait-DockerEngine {
  param([int]$TimeoutSeconds = 120)

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-DockerEngine) {
      return $true
    }
    Start-Sleep -Seconds 2
  }

  return $false
}

function Test-DockerEngine {
  # Use cmd redirection so PowerShell does not promote Docker's expected
  # connection error to a terminating NativeCommandError before we can retry.
  & cmd.exe /d /c "docker info >nul 2>nul"
  return $LASTEXITCODE -eq 0
}

Set-Location $projectRoot

if (-not (Test-Path $composeFile)) {
  throw "Docker Compose file was not found: $composeFile"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "Docker was not found. Install Docker Desktop first, then run start.bat again."
}

if (-not (Test-DockerEngine)) {
  Write-Host "Docker engine is not running. Starting Docker Desktop..."
  # Current Docker Desktop releases expose a supported CLI startup path.
  # Calling the launcher executable directly can exit immediately without
  # starting the backend engine.
  & docker desktop start --detach --timeout 15
  if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop could not be started through its CLI. Open Docker Desktop, check its diagnostic message, then run start.bat again."
  }

  Write-Host "Waiting for Docker engine (up to 120 seconds)..."
  if (-not (Wait-DockerEngine)) {
    throw "Docker Desktop was started, but its engine did not become ready within 120 seconds. Open Docker Desktop and check its status, then run start.bat again."
  }
}

Copy-ExampleIfMissing -Target $deployEnv -Example $deployEnvExample
Copy-ExampleIfMissing -Target $backendEnv -Example $backendEnvExample

$llmMode = Get-EnvFileValue -Path $backendEnv -Name "LLM_MODE" -DefaultValue "mock"
if ($llmMode -eq "real") {
  Start-OllamaIfNeeded
} else {
  Write-Host "LLM_MODE=$llmMode; skipping Ollama startup."
}

$frontendPort = $env:FRONTEND_PORT
if (-not $frontendPort) {
  $frontendPort = Get-EnvFileValue -Path $deployEnv -Name "FRONTEND_PORT" -DefaultValue "80"
}
if (-not $frontendPort) {
  $frontendPort = "80"
}

if ($frontendPort -eq "80") {
  $frontendUrl = "http://localhost"
} else {
  $frontendUrl = "http://localhost:$frontendPort"
}
$healthUrl = "$frontendUrl/health"

Write-Host "Starting Docker deployment..."
Push-Location $deployRoot
try {
  Invoke-CheckedCommand -FilePath "docker" -Arguments @("compose", "up", "-d", "--build")
} finally {
  Pop-Location
}

Write-Host "Waiting for service health: $healthUrl"
if (-not (Wait-HttpReady -Url $healthUrl -TimeoutSeconds 120)) {
  Write-Host "Service did not become ready in time. Recent container status:"
  Push-Location $deployRoot
  try {
    docker compose ps
  } finally {
    Pop-Location
  }
  throw "Docker services started, but health check failed: $healthUrl"
}

Write-Host ""
Write-Host "Docker deployment is running."
Write-Host "Frontend: $frontendUrl"
Write-Host "Health:   $healthUrl"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  cd deploy; docker compose logs -f"
Write-Host "  cd deploy; docker compose down"

Start-Process $frontendUrl
