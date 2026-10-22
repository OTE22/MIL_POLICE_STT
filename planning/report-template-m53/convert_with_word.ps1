# Convert only the generated fictional review files using a separate hidden Word instance.
# No existing Word document, production template, or global Word option is changed.
param(
    [string]$OutputDirectory = 'output',
    [string[]]$SampleNames = @('m53-blank-review', 'm53-short-example', 'm53-long-example'),
    [switch]$ReadWrite
)
$ErrorActionPreference = 'Stop'
$sampleFolder = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot $OutputDirectory)).Path
if (-not $sampleFolder.StartsWith($PSScriptRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output directory must be within this review folder'
}
if (@($SampleNames | Where-Object { $_ -notmatch '^m53-[a-z-]+$' }).Count -gt 0) { throw 'Invalid sample filename' }
$wordApp = $null
$doNotSave = 0
$pdfFormat = 17
$conversions = @()
try {
    $wordApp = New-Object -ComObject Word.Application
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $wordApp.AutomationSecurity = 3
    $version = $wordApp.Version
    foreach ($sampleName in $sampleNames) {
        $document = $null
        [string]$docxPath = Join-Path $sampleFolder ($sampleName + '.docx')
        [string]$pdfPath = Join-Path $sampleFolder ($sampleName + '.pdf')
        [string]$temporaryPdf = Join-Path $sampleFolder ($sampleName + '.' + [guid]::NewGuid().ToString('N') + '.pdf')
        $originalHash = (Get-FileHash -LiteralPath $docxPath -Algorithm SHA256).Hash
        try {
            # ReadOnly=true, AddToRecentFiles=false; app is hidden.
            $document = $wordApp.Documents.Open($docxPath, $false, (-not $ReadWrite), $false)
            # Explicit string variables and by-reference format are required by
            # this local Word COM binding. The original DOCX is never overwritten.
            # Always save to a new path: suppressed overwrite dialogs must never
            # let an old PDF masquerade as a successful fresh conversion.
            $document.SaveAs2([ref]$temporaryPdf, [ref]$pdfFormat)
            if (-not (Test-Path -LiteralPath $temporaryPdf)) { throw "PDF missing: $sampleName" }
            $pdfBytes = [System.IO.File]::ReadAllBytes($temporaryPdf)
            if ($pdfBytes.Length -lt 1000 -or [System.Text.Encoding]::ASCII.GetString($pdfBytes, 0, 5) -ne '%PDF-') {
                throw "Invalid PDF output: $sampleName"
            }
            if ((Get-FileHash -LiteralPath $docxPath -Algorithm SHA256).Hash -ne $originalHash) {
                throw "Source DOCX changed during conversion: $sampleName"
            }
            Move-Item -LiteralPath $temporaryPdf -Destination $pdfPath -Force
            $conversions += [pscustomobject]@{ file = ($sampleName + '.pdf') }
            Write-Output "Exported $sampleName"
        }
        finally {
            if ($null -ne $document) {
                $document.Close([ref]$doNotSave)
                $null = [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($document)
            }
        }
    }
    $conversionInfo = [pscustomobject]@{
        converter = "Microsoft Word $version - local desktop export"
        files = $conversions
        desktop_visual_review = 'pending; exported pages reviewed separately'
        production_server_converter = 'not installed or deployed'
    }
    $conversionInfo | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $sampleFolder 'word-conversion.json') -Encoding UTF8
}
finally {
    if ($null -ne $wordApp) {
        $wordApp.Quit([ref]$doNotSave)
        $null = [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordApp)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
