param(
    [string]$Audio = 'desktop-agent/data/jobs/358f2c9b-7259-4e28-a914-ccd4a40e16c9/original.webm',
    [string]$Transcript = 'desktop-agent/data/jobs/358f2c9b-7259-4e28-a914-ccd4a40e16c9/result.json',
    [string]$Diarization = 'storage/model-evaluation/results/comparison-nemotron-pyannote-baseline.json',
    [string]$Image = 'military-stt/whisperx-alignment:3.8.6'
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$audioPath = (Resolve-Path (Join-Path $projectRoot $Audio)).Path
$transcriptPath = (Resolve-Path (Join-Path $projectRoot $Transcript)).Path
$diarizationPath = (Resolve-Path (Join-Path $projectRoot $Diarization)).Path
$modelPath = (Resolve-Path (Join-Path $projectRoot 'storage/model-evaluation/arabic-alignment')).Path
if (-not (Test-Path -LiteralPath (Join-Path $modelPath 'EVALUATION_SOURCE.json'))) {
    throw 'The pinned alignment model has not completed checksum verification.'
}
$resultPath = Join-Path $projectRoot 'storage/model-evaluation/results'
New-Item -ItemType Directory -Force -Path $resultPath | Out-Null
# Windows PowerShell treats redirected native stderr as error records. Model
# progress is written there too; the container exit code determines failure.
$runnerErrorPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    docker run --rm --network none --cpus 2 --memory 4g --no-healthcheck `
    --mount "type=bind,source=$audioPath,target=/input/original.webm,readonly" `
    --mount "type=bind,source=$transcriptPath,target=/input/transcript.json,readonly" `
    --mount "type=bind,source=$diarizationPath,target=/input/diarization.json,readonly" `
    --mount "type=bind,source=$modelPath,target=/alignment,readonly" `
    --mount "type=bind,source=$PSScriptRoot,target=/tools,readonly" `
    --mount "type=bind,source=$resultPath,target=/results" `
    $Image /tools/evaluate_whisperx_alignment.py `
    --audio /input/original.webm --transcript /input/transcript.json `
    --diarization /input/diarization.json --model /alignment `
    --output /results/whisperx-arabic-alignment.json
    $containerExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $runnerErrorPreference
}
if ($containerExitCode -ne 0) { throw "WhisperX alignment evaluation failed (exit $containerExitCode)." }
