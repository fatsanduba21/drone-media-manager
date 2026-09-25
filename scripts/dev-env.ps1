$ProjectRoot = Split-Path -Parent $PSScriptRoot

$RuntimeRoot = Join-Path $ProjectRoot ".codex-runtime"
$UvCache = Join-Path $RuntimeRoot "uv-cache"
$TempDir = Join-Path $RuntimeRoot "temp"
$PytestCache = Join-Path $RuntimeRoot "pytest-cache"
$PytestTemp = Join-Path $RuntimeRoot "pytest-temp"

New-Item -ItemType Directory -Force $UvCache | Out-Null
New-Item -ItemType Directory -Force $TempDir | Out-Null
New-Item -ItemType Directory -Force $PytestCache | Out-Null
New-Item -ItemType Directory -Force $PytestTemp | Out-Null

$env:UV_CACHE_DIR = $UvCache
$env:TEMP = $TempDir
$env:TMP = $TempDir

$env:PYTEST_ADDOPTS = "--basetemp=`"$PytestTemp`" -o cache_dir=`"$PytestCache`""


Write-Host "Windows development runtime configured:"
Write-Host "  UV_CACHE_DIR = $env:UV_CACHE_DIR"
Write-Host "  TEMP         = $env:TEMP"
Write-Host "  TMP          = $env:TMP"

if (-not (Test-Path $env:UV_CACHE_DIR)) {
    throw "UV cache directory is unavailable: $env:UV_CACHE_DIR"
}

if (-not (Test-Path $env:TEMP)) {
    throw "TEMP directory is unavailable: $env:TEMP"
}