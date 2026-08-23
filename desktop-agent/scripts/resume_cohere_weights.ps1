<#
.SYNOPSIS
  Resumable download of the gated Cohere STT weights over a slow / unstable link.

  Each attempt continues from the current size of model.safetensors.part (HTTP Range),
  so a dropped connection never restarts from zero. When the file reaches the expected
  size it runs finalize_cohere_weights.py (SHA-256 check + MANIFEST.json).

.USAGE
  $env:HF_TOKEN = "hf_..."      # token with access to the gated repository (not stored)
  .\scripts\resume_cohere_weights.ps1 [-ModelDir ..\models]
  # detached:  Start-Process powershell -ArgumentList "-NoProfile -File scripts\resume_cohere_weights.ps1" -WindowStyle Hidden
#>
param(
    [string]$ModelDir = (Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) "models"),
    [string]$Revision = "c3e911b42149bf7a1e53d5cef9878aee87515a23"
)
$ErrorActionPreference = "Continue"
if (-not $env:HF_TOKEN) { Write-Error "HF_TOKEN environment variable is required (gated repository)"; exit 1 }
$dir = Join-Path $ModelDir "cohere-transcribe-arabic-07-2026"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$part = Join-Path $dir "model.safetensors.part"
$final = Join-Path $dir "model.safetensors"
$url = "https://huggingface.co/CohereLabs/cohere-transcribe-arabic-07-2026/resolve/$Revision/model.safetensors"
$target = 4131862976
$log = Join-Path $dir "download.log"
$attempt = 0
while ($true) {
    if (Test-Path $final) { "already complete: $final" | Tee-Object -FilePath $log -Append; break }
    $size = if (Test-Path $part) { (Get-Item $part).Length } else { 0 }
    if ($size -ge $target) { "download complete ($size bytes)" | Tee-Object -FilePath $log -Append; break }
    $attempt++
    "$(Get-Date -Format s) attempt $attempt resuming at $size ($([math]::Round($size * 100 / $target, 1))%)" | Tee-Object -FilePath $log -Append
    & curl.exe -L -C - -sS --speed-limit 1000 --speed-time 120 -H "Authorization: Bearer $env:HF_TOKEN" -o $part $url 2>&1 | Out-File -FilePath $log -Append
    Start-Sleep -Seconds 5
}
$py = Join-Path (Split-Path -Parent $PSScriptRoot) ".venv-test\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py (Join-Path $PSScriptRoot "finalize_cohere_weights.py") --model-dir $ModelDir 2>&1 | Tee-Object -FilePath $log -Append
