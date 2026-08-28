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
    [switch]$SkipPip,
    # Skip the plain-language explanation printed before each step.
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------- narration
# This runs on every investigator desktop, usually by someone who did not build the system and
# will not run it again for months. Each step says what it is about to do, why it matters, how
# to tell it worked, and what to do if it did not.
function Explain($What, $Why, $Good, $Fail) {
    if ($Quiet) { return }
    Write-Host ""
    Write-Host "  +- WHAT  $What"      -ForegroundColor DarkGray
    Write-Host "  |  WHY   $Why"       -ForegroundColor DarkGray
    Write-Host "  |  GOOD  $Good"      -ForegroundColor DarkGray
    Write-Host "  +- FAIL  $Fail"      -ForegroundColor DarkGray
    Write-Host ""
}
function Step($n, $Title) { Write-Host ""; Write-Host "== $n  $Title ==" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  [ ok ] $m"  -ForegroundColor Green }
function Warn($m) { Write-Host "  [warn] $m"  -ForegroundColor Yellow }
function Fail($m) { Write-Host ""; Write-Host "  [FAIL] $m" -ForegroundColor Red; Write-Host ""; exit 1 }
$source = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)   # desktop-agent/
$appDir = Join-Path $InstallRoot "app"
$dataDir = Join-Path $InstallRoot "agent"
$modelDir = Join-Path $InstallRoot "models"
$venv = Join-Path $InstallRoot "venv"

Write-Host ""
Write-Host "== Military STT AI - Local Agent installer for Windows ($Compute) ==" -ForegroundColor Cyan
Write-Host "   This installs the AI onto THIS desktop. Audio is processed here and never"
Write-Host "   leaves the machine; only the finished text is sent to the server."
Write-Host ""

# ---------------------------------------------------------------- 0. preflight
Step "1/6" "Checking this desktop"
Explain `
  "Check the things the installer needs: administrator rights, Python, FFmpeg, and disk space." `
  "Every later step assumes these. Finding out now takes seconds; finding out halfway through a 4 GB install wastes an hour." `
  "Four [ ok ] lines below." `
  "Each failure names exactly what to install. Install it, then run this script again - re-running is safe."

$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Fail "This must run as administrator. Right-click PowerShell and choose 'Run as administrator', then run this script again."
}
Ok "running as administrator"

$pyOk = $false
try { $pyv = & $PythonExe --version 2>&1; if ($LASTEXITCODE -eq 0) { $pyOk = $true } } catch {}
if (-not $pyOk) {
    Fail "Python was not found. Install Python 3.11 or 3.12 (64-bit) from python.org and tick 'Add python.exe to PATH' during setup."
}
Ok "Python found: $pyv"

if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Fail "FFmpeg was not found. It reads the audio files. Download a 'full' build from gyan.dev, unzip it, and add its bin folder to the SYSTEM Path. Then open a NEW PowerShell window."
}
Ok "FFmpeg found"

$drive = (Get-Item $InstallRoot -ErrorAction SilentlyContinue)
$freeGb = [math]::Round((Get-PSDrive ($InstallRoot.Substring(0,1))).Free / 1GB, 1)
if ($freeGb -lt 15) {
    Warn "only $freeGb GB free on $($InstallRoot.Substring(0,1)): - the models need about 10 GB plus room to unpack"
} else {
    Ok "$freeGb GB free for the models"
}

Step "2/6" "Creating the folders"
Explain `
  "Create the folders the agent lives in under $InstallRoot." `
  "Keeping the application, its data and the models in one place makes the agent easy to back up and to remove later." `
  "'folders ready'." `
  "If this fails the account cannot write to $InstallRoot - check you really are administrator."
foreach ($d in @($InstallRoot, $appDir, $dataDir, $modelDir)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
Ok "folders ready under $InstallRoot"

# ---- copy application ---------------------------------------------------
Step "3/6" "Copying the application"
Explain `
  "Copy the agent program onto this desktop." `
  "It runs from its own copy, so the folder you unpacked can be deleted afterwards without breaking anything." `
  "'application copied'." `
  "If this fails, the source folder is incomplete - unpack the delivered package again."
robocopy $source $appDir /MIR /XD .venv-test models data __pycache__ .pytest_cache tests /XF .env *.sqlite3 /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }

Ok "application copied"

# ---- python environment -------------------------------------------------
Step "4/6" "Installing the AI runtime"
Explain `
  "Create a private Python environment and install the AI libraries into it." `
  "THIS IS THE LONGEST STEP - typically 10-30 minutes, and longer for GPU. It downloads several gigabytes. Long silences are normal and do NOT mean it has frozen." `
  "'runtime installed'. Progress bars that pause for minutes are normal." `
  "Nearly always the network. If this desktop has no internet, prepare the environment on a connected machine and copy it, or ask for the offline package."
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $PythonExe -m venv $venv
}
$py = Join-Path $venv "Scripts\python.exe"
if (-not $SkipPip) {
    & $py -m pip install --upgrade pip
    & $py -m pip install -r (Join-Path $appDir "requirements-$Compute.txt")
    & $py -m pip install -r (Join-Path $appDir "requirements.txt")
}

Ok "runtime installed"

# ---- ffmpeg check ---------------------------------------------------------
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "ffmpeg was not found in PATH. Install FFmpeg (e.g. gyan.dev full build) and add it to the SYSTEM PATH."
}

# ---- configuration --------------------------------------------------------
Step "5/6" "Writing the configuration"
Explain `
  "Record which server this desktop reports to, and how the agent listens." `
  "The agent listens ONLY on this machine (127.0.0.1:17117). Nothing on the network can reach it - the browser on this same desktop talks to it locally." `
  "'configuration written'." `
  "If the server address is wrong you can edit $dataDir\.env afterwards and restart the service."
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

Ok "configuration written"

# ---- service registration -------------------------------------------------
Step "6/6" "Starting it automatically at every boot"
Explain `
  "Register the agent so Windows starts it by itself after every restart." `
  "The investigator must never have to start anything by hand. If NSSM is available it becomes a real Windows service; otherwise a scheduled task does the same job." `
  "'service registered' or 'scheduled task registered'." `
  "If both fail, the agent still runs manually, but it will NOT come back after a reboot - fix this before handing the desktop over."
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
Write-Host "== Installed ==" -ForegroundColor Green
Write-Host ""
Write-Host "  The agent is on this desktop and will start automatically after every reboot."
Write-Host "  It is NOT finished yet - it still needs the models and the server's key."
Write-Host ""
Write-Host "Do these four things, in order:"
Write-Host ""
Write-Host "  1. INSTALL THE SERVER'S KEY" -ForegroundColor White
Write-Host "     Copy central_public_key.pem (handed to you by whoever set up the server) to:"
Write-Host "       $InstallRoot\central_public_key.pem"
Write-Host "     Without it the agent refuses every job. The key only VERIFIES signatures,"
Write-Host "     so carrying it on a USB stick is safe."
Write-Host ""
Write-Host "  2. INSTALL THE AI MODELS" -ForegroundColor White
Write-Host "       $py $appDir\scripts\provision_models.py"
Write-Host "     Several gigabytes, and it can take a long time. The Arabic speech model is"
Write-Host "     access-controlled, so you need an HF_TOKEN from your administrator."
Write-Host ""
Write-Host "  3. CHECK IT WORKS" -ForegroundColor White
Write-Host "       $py $appDir\scripts\healthcheck.py --load"
Write-Host "     This actually loads the models, so allow a minute or two. It tells you"
Write-Host "     plainly whether each one is ready."
Write-Host ""
Write-Host "  4. SEE IT RUNNING" -ForegroundColor White
Write-Host "     Open http://127.0.0.1:17117/health in a browser on THIS desktop."
Write-Host "     That address works only here - the agent is not reachable from the network."
Write-Host ""
Write-Host "  Then sign in to the central server from this desktop's browser, open a session"
Write-Host "  and press the record button. The recording tab shows the agent's status."
Write-Host ""
Write-Host "  If something is wrong later: docs/troubleshooting.md lists the symptoms in Arabic"
Write-Host "  exactly as they appear on screen."
