#requires -Version 5.1
param(
    [string]$PetRoot = (Join-Path $PSScriptRoot '..\pet'),
    [string]$PythonExe = ''
)
$ErrorActionPreference='Stop'
if (-not $PythonExe) { $PythonExe=Join-Path $PetRoot '.venv\Scripts\python.exe' }
& $PythonExe (Join-Path $PSScriptRoot 'scripts\sync_sources.py') --pet $PetRoot --release $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw 'Source synchronization failed' }
Write-Host 'Source synchronized. Review and test before committing. This command never pushes.'
