#requires -Version 5.1
param(
    [string]$PetRoot = (Join-Path $PSScriptRoot "..\pet"),
    [string]$PythonExe = "",
    [switch]$BridgeOnly
)
$ErrorActionPreference = "Stop"
$PetRoot = [IO.Path]::GetFullPath($PetRoot)
if (-not $BridgeOnly) {
    if (-not (Test-Path -LiteralPath (Join-Path $PetRoot "run_server.py"))) { throw "PetRoot must contain run_server.py" }
    $meta = Get-Content -LiteralPath (Join-Path $PetRoot "pyproject.toml") -Raw
    if ($meta -notmatch '(?m)^version\s*=\s*"1\.2\.1"') { throw "Runtime overlay supports Open-LLM-VTuber 1.2.1 only" }
}
if (-not $PythonExe) { $PythonExe = Join-Path $PetRoot ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $PythonExe)) { throw "Python not found. Create .venv first, or pass -PythonExe." }
$PythonExe = [IO.Path]::GetFullPath($PythonExe)
$bridge = Join-Path $PetRoot "bridge"
New-Item -ItemType Directory -Force -Path $bridge | Out-Null
$source = Join-Path $PSScriptRoot "bridge"
Get-ChildItem -LiteralPath $source -Recurse -File | Where-Object {
    $_.Extension -in '.py','.md','.yml' -and $_.FullName -notmatch '[\\/](data|state|logs|__pycache__)[\\/]'
} | ForEach-Object {
    $rel = $_.FullName.Substring($source.Length).TrimStart([char[]]"\/")
    $dest = Join-Path $bridge $rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
    if ([IO.Path]::GetFullPath($_.FullName) -ne [IO.Path]::GetFullPath($dest)) { Copy-Item -LiteralPath $_.FullName -Destination $dest -Force }
}
$cfg = Join-Path $bridge 'config.json'
if (-not (Test-Path -LiteralPath $cfg)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config\config.example.json') -Destination $cfg
}
if (-not $BridgeOnly) {
    $runtime = Join-Path $PSScriptRoot 'runtime\open_llm_vtuber'
    $backup = Join-Path $bridge ('data\backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    Get-ChildItem -LiteralPath $runtime -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($runtime.Length).TrimStart([char[]]"\/")
        $dest = Join-Path $PetRoot ('src\open_llm_vtuber\' + $rel)
        if (Test-Path -LiteralPath $dest) {
            $bak = Join-Path $backup $rel
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $bak) | Out-Null
            Copy-Item -LiteralPath $dest -Destination $bak
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
    }
}
# Host tools may require absolute paths. Generate them locally, never commit them.
$generated = Join-Path $bridge 'data\generated'
New-Item -ItemType Directory -Force -Path $generated | Out-Null
$mcp = @{ mcp_servers = @{ 'msg-bridge' = @{ command=$PythonExe; args=@((Join-Path $bridge 'server.py')) } } }
$mcp | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $generated 'mcp_servers.ready.json') -Encoding UTF8
$dsh = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config\cordis.patch.example.yml') -Raw -Encoding UTF8
$dsh = $dsh.Replace('<PYTHON_EXE>',$PythonExe).Replace('<BRIDGE_SERVER>',(Join-Path $bridge 'server.py'))
$dsh | Set-Content -LiteralPath (Join-Path $generated 'cordis.patch.ready.yml') -Encoding UTF8
$workspace = Join-Path (Split-Path -Parent $PetRoot) 'pet_workspace'
New-Item -ItemType Directory -Force -Path $workspace | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $workspace 'AGENTS.md'))) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'config\AGENTS.example.md') -Destination (Join-Path $workspace 'AGENTS.md')
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '启动桌宠客户端.cmd') -Destination $PetRoot -Force
Write-Host "Installed bridge + runtime. Existing config/persona preserved."
Write-Host "Generated MCP/DSH snippets: $generated"
Write-Host "Check: & '$PythonExe' '$bridge\doctor.py'"
