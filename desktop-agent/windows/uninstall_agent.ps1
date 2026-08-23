# Removes the Local Agent service / scheduled task (keeps models and data unless -Purge).
param([string]$InstallRoot = "C:\ProgramData\InvestigationAI", [switch]$Purge)
$ErrorActionPreference = "SilentlyContinue"
if (Get-Command nssm.exe) { nssm.exe stop MilitarySTTAgent; nssm.exe remove MilitarySTTAgent confirm }
Unregister-ScheduledTask -TaskName MilitarySTTAgent -Confirm:$false
if ($Purge) { Remove-Item -Recurse -Force $InstallRoot }
Write-Host "Local Agent removed."
