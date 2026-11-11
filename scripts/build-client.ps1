#requires -Version 5.1
param(
    [string]$PetRoot = (Join-Path $PSScriptRoot '..\..\pet'),
    [string]$NodeDir = '',
    [switch]$ApplyOnly
)
$ErrorActionPreference = 'Stop'
$PetRoot = [IO.Path]::GetFullPath($PetRoot)
$client = Join-Path $PetRoot 'pet-web'
$expectedCommit = 'd176e7df2366952e3bacbf12cf9a8b18a4315932'
$overlay = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\frontend'))
if (-not (Test-Path -LiteralPath (Join-Path $client 'package.json'))) {
    if ($ApplyOnly) { throw 'Client source is missing; ApplyOnly does not download it.' }
    if (Test-Path -LiteralPath $client) { throw 'Existing incomplete pet-web directory; choose a clean client source location.' }
    & git clone --no-checkout 'https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web.git' $client
    if ($LASTEXITCODE -ne 0) { throw 'Client clone failed' }
    & git -C $client checkout --detach $expectedCommit
    if ($LASTEXITCODE -ne 0) { throw 'Pinned client checkout failed' }
    & git -C $client submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) { throw 'Client submodule setup failed' }
}
$package = Get-Content -LiteralPath (Join-Path $client 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($package.version -ne '1.2.1') { throw 'Client overlay supports version 1.2.1 only.' }
$backup = Join-Path $PetRoot ('bridge\data\backups\client-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
Get-ChildItem -LiteralPath $overlay -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($overlay.Length).TrimStart([char[]]"\/")
    $destination = Join-Path $client $rel
    if (Test-Path -LiteralPath $destination) {
        $saved = Join-Path $backup $rel
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $saved) | Out-Null
        Copy-Item -LiteralPath $destination -Destination $saved
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
}
if ($ApplyOnly) { Write-Host 'Client source overlay applied; rebuild before use.'; return }
$oldPath = $env:PATH
$oldElectronMode = $env:ELECTRON_RUN_AS_NODE
try {
    if ($NodeDir) { $env:PATH = [IO.Path]::GetFullPath($NodeDir) + ';' + $env:PATH }
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js LTS or pass -NodeDir.' }
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
    Push-Location $client
    try {
        if (-not (Test-Path -LiteralPath 'node_modules\.bin\electron-vite.cmd')) {
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw 'Client dependencies failed' }
        }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Client build failed' }
        & npx.cmd --no-install electron-builder --dir --publish never
        if ($LASTEXITCODE -ne 0) { throw 'Client packaging failed; close old desktop client before retrying.' }
    } finally { Pop-Location }
} finally {
    $env:PATH = $oldPath
    $env:ELECTRON_RUN_AS_NODE = $oldElectronMode
}
Write-Host ('Client ready: ' + (Join-Path $client 'release\1.2.1\win-unpacked\open-llm-vtuber-electron.exe'))
