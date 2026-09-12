param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CommandArguments)
$ErrorActionPreference = 'Stop'
$skillDirectory = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $skillDirectory 'runtime.local.json'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Run setup.ps1 with the actual Python, Node and NodeModules paths first.' }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
foreach ($runtimePath in @($config.python, $config.node, $config.node_modules)) {
    if (-not (Test-Path -LiteralPath $runtimePath)) { throw "Runtime missing: $runtimePath. Rerun setup.ps1." }
}
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUNTIME_NODE_MODULES = $config.node_modules
if (-not $CommandArguments -or $CommandArguments[0] -eq 'help') {
    Write-Output 'PPP: doctor | prepare | erase | budget | render | trace | merge | export | finalize | svg | compare | audit. Default budget: 1000 native graphics. Add --help after a command.'
    exit 0
}
$remaining = @()
if ($CommandArguments.Count -gt 1) { $remaining = $CommandArguments[1..($CommandArguments.Count-1)] }
switch ($CommandArguments[0]) {
    'export' { & $config.node (Join-Path $PSScriptRoot 'scene_to_pptx.mjs') @remaining }
    'finalize' {
        if ($remaining.Count -ge 3) {
            & $config.python (Join-Path $PSScriptRoot 'budget_vectorize.py') audit $remaining[1]
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        & $config.node (Join-Path $PSScriptRoot 'finalize_pptx.mjs') @remaining
    }
    'budget' { & $config.python (Join-Path $PSScriptRoot 'budget_vectorize.py') @remaining }
    'render' { & $config.node (Join-Path $PSScriptRoot 'render_pptx.mjs') @remaining }
    'svg' { & $config.python (Join-Path $PSScriptRoot 'svg_to_scene.py') @remaining }
    'doctor' {
        & $config.python (Join-Path $PSScriptRoot 'ppp.py') doctor
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $config.python -c 'from rapidocr_onnxruntime import RapidOCR; engine=RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1); print("OCR model initialization: OK")'
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $config.node (Join-Path $PSScriptRoot 'check_node.mjs')
    }
    default { & $config.python (Join-Path $PSScriptRoot 'ppp.py') @CommandArguments }
}
exit $LASTEXITCODE
