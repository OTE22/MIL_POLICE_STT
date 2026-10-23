param(
    [string]$BaseImage = 'military-stt/desktop-agent:1.0.0-cpu',
    [string]$Image = 'military-stt/desktop-agent:nemotron-candidate'
)
$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$evaluation = Join-Path $workspace 'storage/model-evaluation'
$source = Join-Path $evaluation 'nemo-source'
$wheels = Join-Path $evaluation 'wheels'
$revision = '16b0ff2584c6355c53cbd6c28f0f431a76b24956'
$wheelName = 'lhotse-2.0.0a6-py3-none-any.whl'
$wheelSha256 = '15145bd072a3d6c5f6b52b07e40f0425f7189ec3a409fedd416c04331422cac3'
New-Item -ItemType Directory -Force -Path $evaluation, $wheels | Out-Null
if (-not (Test-Path -LiteralPath $source)) {
    & git clone --filter=blob:none --no-checkout --depth 1 https://github.com/NVIDIA-NeMo/Speech.git $source
    if ($LASTEXITCODE -ne 0) { throw 'Could not fetch the official NeMo source.' }
    & git -C $source sparse-checkout set nemo
    if ($LASTEXITCODE -ne 0) { throw 'Could not configure the sparse NeMo checkout.' }
    & git -C $source fetch --depth 1 origin $revision
    if ($LASTEXITCODE -ne 0) { throw 'Could not fetch the pinned NeMo revision.' }
    & git -C $source checkout --detach $revision
    if ($LASTEXITCODE -ne 0) { throw 'Could not check out the pinned NeMo revision.' }
}
$actualRevision = (& git -C $source rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualRevision -ne $revision) { throw 'Existing NeMo checkout does not match the approved revision.' }
$sourceChanges = & git -C $source status --porcelain --untracked-files=normal
if ($LASTEXITCODE -ne 0 -or $sourceChanges) { throw 'NeMo source must be an unmodified official checkout.' }
$wheel = Join-Path $wheels $wheelName
if (-not (Test-Path -LiteralPath $wheel)) {
    $release = Invoke-RestMethod 'https://pypi.org/pypi/lhotse/2.0.0a6/json'
    $artifact = $release.urls | Where-Object { $_.filename -eq $wheelName }
    if ($artifact.digests.sha256 -ne $wheelSha256) { throw 'PyPI artifact differs from the approved Lhotse wheel.' }
    Invoke-WebRequest -Uri $artifact.url -OutFile $wheel
}
if ((Get-FileHash -LiteralPath $wheel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $wheelSha256) { throw 'Lhotse wheel checksum mismatch.' }
$dockerArguments = @('build', '--network', 'none', '--build-context', "nemo_source=$source", '--build-context', "nemo_wheels=$wheels", '--build-arg', "BASE_IMAGE=$BaseImage", '-f', (Join-Path $PSScriptRoot 'nemotron-agent-runtime.Dockerfile'), '-t', $Image, (Join-Path $workspace 'desktop-agent'))
& docker @dockerArguments
if ($LASTEXITCODE -ne 0) { throw 'Candidate image build failed.' }
Write-Output "Built $Image with pinned NeMo $revision and Lhotse 2.0.0a6. No deployment or model selection was performed."
