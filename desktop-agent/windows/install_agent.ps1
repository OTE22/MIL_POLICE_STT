<#
.SYNOPSIS
  Installs the Military STT AI Local Agent on a Windows investigator desktop
  as an automatically started background service (no Docker Desktop required).

.DESCRIPTION
  1. Creates C:\ProgramData\InvestigationAI\{agent,models,app}
  2. Creates a Python virtual environment and installs the agent
     (CPU or CUDA torch wheels depending on -Compute)
  3. Writes the .env configuration
  4. Registers the service:
        - with NSSM (https://nssm.cc) if nssm.exe is available        -> real Windows service
        - otherwise with Task Scheduler (runs at boot as SYSTEM)       -> no extra download
  Run from an elevated PowerShell:
     .\install_agent.ps1 -CentralUrl https://central.unit.local:8443 -Compute gpu
#>
[CmdletBinding()]
param(
    [string]$CentralUrl = "https://central.unit.local:8443",
    [ValidateSet("cpu", "gpu")] [string]$Compute = "cpu",
    [string]$InstallRoot = "C:\ProgramData\InvestigationAI",
    [string]$PythonExe = "python",
    [string]$AllowedOrigins = "",
    [switch]$SkipPip
)

$ErrorActionPreference = "Stop"
$source = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)   # desktop-agent/
$appDir = Join-Path $InstallRoot "app"
$dataDir = Join-Path $InstallRoot "agent"
$modelDir = Join-Path $InstallRoot "models"
$venv = Join-Path $InstallRoot "venv"

Write-Host "== Military STT AI Local Agent installer ($Compute) =="
foreach ($d in @($InstallRoot, $appDir, $dataDir, $modelDir)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

# ---- copy application ---------------------------------------------------
robocopy $source $appDir /MIR /XD .venv-test models data __pycache__ .pytest_cache tests /XF .env *.sqlite3 /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }

# ---- python environment -------------------------------------------------
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $PythonExe -m venv $venv
}
$py = Join-Path $venv "Scripts\python.exe"
if (-not $SkipPip) {
    & $py -m pip install --upgrade pip
    & $py -m pip install -r (Join-Path $appDir "requirements-$Compute.txt")
    & $py -m pip install -r (Join-Path $appDir "requirements.txt")
}

# ---- ffmpeg check ---------------------------------------------------------
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "ffmpeg was not found in PATH. Install FFmpeg (e.g. gyan.dev full build) and add it to the SYSTEM PATH."
}

# ---- configuration --------------------------------------------------------
$envFile = Join-Path $appDir ".env"
if (-not (Test-Path $envFile)) {
    $central = [Uri]$CentralUrl
    $origins = if ($AllowedOrigins) { $AllowedOrigins } else { "$($central.Scheme)://$($central.Host):$($central.Port),$($central.Scheme)://$($central.Host)" }
    @"
AGENT_BIND_HOST=127.0.0.1
AGENT_PORT=17117
AGENT_DEVICE_NAME=$env:COMPUTERNAME
AGENT_DATA_DIR=$dataDir
AGENT_MODEL_DIR=$modelDir
AGENT_CENTRAL_URL=$CentralUrl
AGENT_CENTRAL_PUBLIC_KEY_PATH=$InstallRoot\central_public_key.pem
AGENT_CENTRAL_VERIFY_TLS=true
AGENT_ALLOWED_ORIGINS=$origins
AGENT_STT_DEVICE=auto
AGENT_DIARIZATION_DEVICE=auto
AGENT_PRELOAD_MODELS=true
AGENT_LOG_LEVEL=INFO
"@ | Set-Content -Path $envFile -Encoding ASCII
    Write-Host "configuration written to $envFile"
}

# ---- service registration -------------------------------------------------
$serviceName = "MilitarySTTAgent"
$nssm = Get-Command nssm.exe -ErrorAction SilentlyContinue
if ($nssm) {
    & nssm.exe stop $serviceName 2>$null
    & nssm.exe remove $serviceName confirm 2>$null
    & nssm.exe install $serviceName $py "-m app.main"
    & nssm.exe set $serviceName AppDirectory $appDir
    & nssm.exe set $serviceName DisplayName "Military STT AI - Local AI Agent"
    & nssm.exe set $serviceName Description "Local speaker diarization and Arabic transcription service (loopback only)"
    & nssm.exe set $serviceName Start SERVICE_AUTO_START
    & nssm.exe set $serviceName AppStdout (Join-Path $dataDir "agent.out.log")
    & nssm.exe set $serviceName AppStderr (Join-Path $dataDir "agent.err.log")
    & nssm.exe set $serviceName AppRotateFiles 1
    & nssm.exe set $serviceName AppRotateBytes 10485760
    & nssm.exe start $serviceName
    Write-Host "Windows service '$serviceName' installed and started (NSSM)."
} else {
    $taskName = "MilitarySTTAgent"
    $action = New-ScheduledTaskAction -Execute $py -Argument "-m app.main" -WorkingDirectory $appDir
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-Host "Scheduled task '$taskName' registered (runs at boot as SYSTEM) and started."
    Write-Host "Tip: install NSSM (nssm.cc) and re-run this script to get a native Windows service instead."
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Copy the central public key to $InstallRoot\central_public_key.pem"
Write-Host "  2. Provision the models:  $py $appDir\scripts\provision_models.py  (HF_TOKEN required for the gated Cohere model)"
Write-Host "  3. Verify:                $py $appDir\scripts\healthcheck.py --load"
Write-Host "  4. Open http://127.0.0.1:17117/health"
