#requires -Version 5.1
param(
    [string]$PetRoot = (Join-Path $PSScriptRoot '..\..\pet'),
    [string]$TavernRoot = (Join-Path $PSScriptRoot '..\..\SillyTavern'),
    [string]$UserHandle = 'default-user'
)
$ErrorActionPreference = 'Stop'
$PetRoot = [IO.Path]::GetFullPath($PetRoot)
$TavernRoot = [IO.Path]::GetFullPath($TavernRoot)
if ($UserHandle -notmatch '^[A-Za-z0-9_-]+$') { throw 'Invalid Tavern user handle' }
$package = Join-Path $TavernRoot 'package.json'
if (-not (Test-Path -LiteralPath $package)) { throw 'SillyTavern source not found; pass -TavernRoot.' }
$version = (Get-Content -LiteralPath $package -Raw -Encoding UTF8 | ConvertFrom-Json).version
if ($version -ne '1.19.0') { throw 'This extension is verified against SillyTavern 1.19.0.' }
$source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\sillytavern-extension'))
$destination = [IO.Path]::GetFullPath((Join-Path $TavernRoot ('data\' + $UserHandle + '\extensions\dafeiyu-tavern')))
$expected = [IO.Path]::GetFullPath((Join-Path $TavernRoot 'data')) + [IO.Path]::DirectorySeparatorChar
if (-not $destination.StartsWith($expected, [StringComparison]::OrdinalIgnoreCase)) { throw 'Extension destination escaped Tavern data directory' }
$backup = Join-Path $PetRoot ('bridge\data\backups\tavern-extension-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $destination -Force | Out-Null
foreach ($name in @('manifest.json','index.js','controller.js','snapshot.js','style.css','README.md','LICENSE')) {
    $file = Join-Path $source $name
    if (-not (Test-Path -LiteralPath $file)) { throw ('Missing extension file: ' + $file) }
    $target = Join-Path $destination $name
    if (Test-Path -LiteralPath $target) {
        New-Item -ItemType Directory -Path $backup -Force | Out-Null
        Copy-Item -LiteralPath $target -Destination (Join-Path $backup $name)
    }
    Copy-Item -LiteralPath $file -Destination $target -Force
}
Write-Host ('Installed extension: ' + $destination)
Write-Host 'Reload the Tavern page. The companion starts OFF; enable it from the whale button above the input.'
Write-Host 'Tavern core, API settings, character cards and chats were not modified.'
