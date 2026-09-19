<#
.SYNOPSIS
  START HERE on Windows. Run this first if you do not know what to install.

.DESCRIPTION
  Explains the two machine roles, checks whether THIS desktop is ready, and prints the exact
  command to run next. It changes nothing.

  Open PowerShell as administrator and run:
      Set-ExecutionPolicy -Scope Process Bypass
      .\START-HERE.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

function Ok($m)   { Write-Host "  [ ok ] $m"  -ForegroundColor Green }
function No($m)   { Write-Host "  [ no ] $m"  -ForegroundColor Red }
function Warn($m) { Write-Host "  [warn] $m"  -ForegroundColor Yellow }
function Info($m) { Write-Host "  [info] $m"  -ForegroundColor DarkGray }
# NOT named H: `h` is the built-in alias for Get-History, and aliases outrank
# functions in command resolution, so every heading called Get-History instead.
function Section($m) { Write-Host ""; Write-Host $m -ForegroundColor Cyan }

Write-Host ""
Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host "  Military STT AI - where to start" -ForegroundColor Cyan
Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host @"

This system runs on TWO kinds of machine. You install a different thing on
each, and THE SERVER MUST BE DONE FIRST.

  1. THE SERVER - one machine for the whole unit
     Holds the cases, the transcripts and the person registry. Investigators
     reach it with a browser. Nobody records audio on it.
     The server runs on LINUX. It is not installed from Windows.
     Whoever installs it chooses PRODUCTION or DEVELOPMENT first:

         sudo ./deploy-central.sh --environment production  --hostname ... --cert ... --key ...
         sudo ./deploy-central.sh --environment development --hostname localhost

     Production keeps all AI on the local network and refuses to issue an
     official report until the approved Word template is uploaded.
     See deploy/README.md for the full comparison.

  2. THE INVESTIGATOR DESKTOP - one install per interviewing computer
     Runs the AI that turns speech into text. THE AUDIO NEVER LEAVES THIS
     MACHINE - only the finished text is sent to the server. That is why the
     AI is installed on every desktop instead of once on the server.

  This Windows script installs role 2.
"@

Section "Is this desktop ready?"
Write-Host "  Checking what is installed here. Nothing is changed." -ForegroundColor DarkGray
Write-Host ""

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) { Ok "running as administrator" }
else { No "NOT administrator - right-click PowerShell and 'Run as administrator'" }

# A command that resolves is not a command that works: Windows ships a Microsoft Store stub
# named python.exe that appears on PATH and does nothing. Require a real version string.
$pyOk = $false; $pyVer = ""
try { $pyVer = (& python --version 2>&1 | Out-String).Trim() } catch { $pyVer = "" }
if ($pyVer -match '^Python 3\.(11|12|13)') { $pyOk = $true; Ok "Python found: $pyVer" }
elseif ($pyVer -match '^Python 3\.') { Warn "Python found but untested here: $pyVer  (3.11 or 3.12 recommended)"; $pyOk = $true }
else {
    No "Python 3 is not usable. Install 3.11 or 3.12 (64-bit) from python.org and TICK 'Add python.exe to PATH'."
    if ($pyVer) { Write-Host "         it answered: $pyVer" -ForegroundColor DarkGray }
}

$ff = Get-Command ffprobe -ErrorAction SilentlyContinue
if ($ff) { Ok "FFmpeg found" }
else { No "FFmpeg not found. Download a 'full' build from gyan.dev, unzip, add its bin folder to the SYSTEM Path, then open a NEW PowerShell." }

$gpu = $null
try { $gpu = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1) } catch {}
if ($gpu) { Ok "NVIDIA GPU found: $gpu" }
else { Info "No NVIDIA GPU detected - use 'cpu' below. It works everywhere, just slower." }
$compute = if ($gpu) { "gpu" } else { "cpu" }

$freeGb = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($freeGb -lt 20) { Warn "only $freeGb GB free on C: - allow about 20 GB for the models" }
else { Ok "$freeGb GB free on C:" }

Section "What to run next"
Write-Host @"

  From an ELEVATED PowerShell, in the folder you unpacked:

      Set-ExecutionPolicy -Scope Process Bypass
      ..\desktop-agent\windows\install_agent.ps1 ``
          -CentralUrl https://central.unit.local:8443 ``
          -Compute $compute

  Replace central.unit.local with your server's address - the same one
  investigators type into their browser.

  Needs: Python, FFmpeg, and the server address.  Takes: 15-40 minutes,
  almost all of it downloading the AI libraries. Long silences are normal.

  Docker Desktop is NOT required on an investigator desktop.
"@

Section "Then three more things, in order"
Write-Host @"

  1. Copy central_public_key.pem from the server to
       C:\ProgramData\InvestigationAI\central_public_key.pem
     Without it the agent refuses every job.

  2. Install the AI models (several gigabytes, needs an HF_TOKEN from your
     administrator for the Arabic speech model):
       C:\ProgramData\InvestigationAI\venv\Scripts\python.exe ``
         C:\ProgramData\InvestigationAI\app\scripts\provision_models.py

  3. Check it works:
       C:\ProgramData\InvestigationAI\venv\Scripts\python.exe ``
         C:\ProgramData\InvestigationAI\app\scripts\healthcheck.py --load

  Then open http://127.0.0.1:17117/health in a browser ON THIS DESKTOP.
  That address works only here - the agent is not reachable from the network.

  Full guide:  docs\windows-installation.md
  Problems:    docs\troubleshooting.md   (symptoms in Arabic, as they appear)
"@

if (-not $isAdmin -or -not $pyOk -or -not $ff) {
    Write-Host ""
    Write-Host "  Fix the [ no ] items above first, then run this again." -ForegroundColor Yellow
    Write-Host ""
}
