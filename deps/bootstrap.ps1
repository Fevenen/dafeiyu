#requires -Version 5.1
param(
    [string]$Root = (Join-Path $PSScriptRoot '..\..'),
    [string]$OlvRepo = 'https://github.com/Open-LLM-VTuber/Open-LLM-VTuber.git'
)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root)
$pet = Join-Path $Root 'pet'
$expectedCommit = '3afa41014b4548a0842e9ee2f576f4b164b48886'
foreach ($command in 'git','uv') {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Install $command first" }
}
if (-not (Test-Path -LiteralPath (Join-Path $pet 'run_server.py'))) {
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    & git clone --branch v1.2.1 --depth 1 --recurse-submodules $OlvRepo $pet
    if ($LASTEXITCODE -ne 0) { throw 'Open-LLM-VTuber clone failed' }
    $actual = & git -C $pet rev-parse HEAD
    if ($actual.Trim() -ne $expectedCommit) { throw 'Unexpected upstream revision; refusing runtime overlay' }
}
Push-Location $pet
try {
    & uv sync
    if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
    $python = Join-Path $pet '.venv\Scripts\python.exe'
    & uv pip install --python $python -r (Join-Path $PSScriptRoot '..\requirements.txt') 'mcp>=1.6,<2'
    if ($LASTEXITCODE -ne 0) { throw 'Bridge dependency install failed' }
    if (-not (Test-Path -LiteralPath 'conf.yaml')) {
        Copy-Item -LiteralPath 'config_templates\conf.default.yaml' -Destination 'conf.yaml'
    }
} finally { Pop-Location }
& (Join-Path $PSScriptRoot '..\install.ps1') -PetRoot $pet -PythonExe $python
Write-Host 'Next: configure the LLM/TTS/character in conf.yaml and QQ endpoint in bridge/config.json.'
Write-Host 'No QQ credentials, voice models or Live2D assets are downloaded by this installer.'
