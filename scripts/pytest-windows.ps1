$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = Join-Path $ProjectRoot ".codex-runtime"

$PytestRuns = Join-Path $RuntimeRoot "pytest-runs"
$PytestCache = Join-Path $RuntimeRoot "pytest-cache"

New-Item -ItemType Directory -Force $PytestRuns | Out-Null
New-Item -ItemType Directory -Force $PytestCache | Out-Null

# Unique directory for this pytest invocation.
# Never reuse or delete a previous sandbox-created temp directory.
$RunId = [guid]::NewGuid().ToString("N")
$PytestTemp = Join-Path $PytestRuns $RunId

New-Item -ItemType Directory -Force $PytestTemp | Out-Null

Write-Host "pytest runtime:"
Write-Host "  basetemp = $PytestTemp"
Write-Host "  cache    = $PytestCache"

uv run pytest `
    --basetemp="$PytestTemp" `
    -o "cache_dir=$PytestCache" `
    @args

exit $LASTEXITCODE