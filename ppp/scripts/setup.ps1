param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$NodeExecutable,
    [Parameter(Mandatory=$true)][string]$NodeModules,
    [string]$PresentationSkillDirectory,
    [string]$SkillsDirectory,
    [string]$RuntimeDirectory
)
$ErrorActionPreference = 'Stop'
if (-not $SkillsDirectory) {
    $SkillsDirectory = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $env:USERPROFILE '.codex/skills' }
}
if (-not $RuntimeDirectory) { $RuntimeDirectory = Join-Path $env:USERPROFILE '.local/share/ppp' }
$sourceSkill = Split-Path -Parent $PSScriptRoot
$targetSkill = [System.IO.Path]::GetFullPath((Join-Path $SkillsDirectory 'ppp'))
foreach ($requiredPath in @($PythonExecutable, $NodeExecutable, $NodeModules)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) { throw "Missing runtime path: $requiredPath" }
}
$venv = Join-Path $RuntimeDirectory 'venv'
$venvPython = Join-Path $venv 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $PythonExecutable -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
& $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $sourceSkill 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed' }
if ([System.IO.Path]::GetFullPath($sourceSkill) -ne $targetSkill) {
    if (Test-Path -LiteralPath $targetSkill) {
        $backupDirectory = Join-Path $RuntimeDirectory 'skill-backups'
        New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
        $backup = Join-Path $backupDirectory "ppp-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Copy-Item -LiteralPath $targetSkill -Destination $backup -Recurse
    }
    New-Item -ItemType Directory -Path $targetSkill -Force | Out-Null
    foreach ($entry in Get-ChildItem -LiteralPath $sourceSkill -Recurse -File -Force) {
        $relativePath = $entry.FullName.Substring($sourceSkill.Length).TrimStart([char[]]'\/')
        if ($relativePath -notmatch '(^|[\\/])__pycache__([\\/]|$)' -and $relativePath -ne 'runtime.local.json') {
            $destination = Join-Path $targetSkill $relativePath
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath $entry.FullName -Destination $destination -Force
        }
    }
}
$configuration = @{
    schema = 1
    python = [System.IO.Path]::GetFullPath($venvPython)
    node = [System.IO.Path]::GetFullPath($NodeExecutable)
    node_modules = [System.IO.Path]::GetFullPath($NodeModules)
    installed_at = (Get-Date).ToString('o')
}
if (-not $PresentationSkillDirectory) {
    $presentationPattern = Join-Path $env:USERPROFILE '.codex/plugins/cache/openai-primary-runtime/presentations/*/skills/presentations/container_tools/artifact_tool_utils.mjs'
    $presentationHelper = Get-ChildItem -Path $presentationPattern -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($presentationHelper) { $PresentationSkillDirectory = Split-Path -Parent (Split-Path -Parent $presentationHelper.FullName) }
}
if ($PresentationSkillDirectory) {
    if (-not (Test-Path -LiteralPath (Join-Path $PresentationSkillDirectory 'container_tools/artifact_tool_utils.mjs'))) { throw 'Presentation finalizer not found' }
    $configuration.presentation_skill = [System.IO.Path]::GetFullPath($PresentationSkillDirectory)
    # The first-party finalizer needs the bundled Python's document libraries.
    $configuration.presentation_python = [System.IO.Path]::GetFullPath($PythonExecutable)
}
$configText = $configuration | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $targetSkill 'runtime.local.json'), $configText, (New-Object System.Text.UTF8Encoding($false)))
& (Join-Path $targetSkill 'scripts/run.ps1') doctor
if ($LASTEXITCODE -ne 0) { throw 'PPP runtime verification failed' }
Write-Output "Installed PPP: $targetSkill"
