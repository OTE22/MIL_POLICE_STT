# Continue the already-authorized local trial after its downloads complete.
# This helper never deploys an image, changes a service, or submits a transcript.
param([int]$MaximumWaitHours = 8)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $taskRoot
$resultDirectory = Join-Path $taskRoot 'storage/model-evaluation/results'
New-Item -ItemType Directory -Force -Path $resultDirectory | Out-Null
$statusPath = Join-Path $resultDirectory 'alignment-trial-status.json'
$deadline = [DateTime]::UtcNow.AddHours($MaximumWaitHours)
function Write-TrialStatus([string]$phase, [string]$detail) {
    $status = @{ phase=$phase; detail=$detail; updated_utc=[DateTime]::UtcNow.ToString('o'); process_id=$PID }
    $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
}
try {
    Write-TrialStatus 'waiting_for_downloads' 'Waiting for the checksum-verified Arabic model and isolated alignment image.'
    $manifest = Join-Path $taskRoot 'storage/model-evaluation/arabic-alignment/EVALUATION_SOURCE.json'
    while ($true) {
        $imageId = docker image ls --filter reference=military-stt/whisperx-alignment:3.8.6 --format '{{.ID}}'
        if ($LASTEXITCODE -ne 0) { throw 'Docker is unavailable.' }
        $imageReady = -not [string]::IsNullOrWhiteSpace(($imageId -join ''))
        if ((Test-Path -LiteralPath $manifest) -and $imageReady) { break }
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Download or image preparation did not finish before the deadline.' }
        Start-Sleep -Seconds 30
    }
    Write-TrialStatus 'running' 'Running the offline CPU trial; original inputs are read-only.'
    & (Join-Path $PSScriptRoot 'run-whisperx-alignment.ps1')
    $report = Get-Content -LiteralPath (Join-Path $resultDirectory 'whisperx-arabic-alignment.json') -Raw | ConvertFrom-Json
    if (-not $report.source_unchanged -or -not $report.all_words_preserved) {
        throw 'Trial input-integrity or word-preservation verification failed.'
    }
    Write-TrialStatus 'completed' "Aligned $($report.timed_words)/$($report.input_words) words; $($report.speaker_count) speakers. Accuracy requires a labelled reference."
} catch {
    Write-TrialStatus 'failed' $_.Exception.Message
    throw
}
