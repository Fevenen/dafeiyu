#requires -Version 5.1
<#
  大肥鱼桌宠桥接 —— 安装脚本
  作用：检查目录、生成配置文件、写工作区人设。不会覆盖已有文件。
#>

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Info($msg) { Write-Host "  $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [ERROR] $msg" -ForegroundColor Red; exit 1 }

Write-Host "`n=== 大肥鱼桌宠桥接 · 安装 ===`n"

# 1. 找到桌宠根目录（本脚本应放在桌宠根目录或仓库根的上一级）
$petRoot = $null
foreach ($cand in @((Join-Path $here ".."), (Join-Path $here "."), "D:\project\MP\pet")) {
    $p = [System.IO.Path]::GetFullPath($cand)
    if (Test-Path (Join-Path $p "run_server.py")) { $petRoot = $p; break }
}
if (-not $petRoot) { Fail "找不到桌宠根目录（应包含 run_server.py）。请把本脚本放到桌宠目录下运行。" }
Ok "桌宠目录: $petRoot"

$venvPy = Join-Path $petRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Fail "找不到 .venv\Scripts\python.exe，请先按 Open-LLM-VTuber 文档创建虚拟环境。" }
Ok "Python: $venvPy"

# 2. 放 bridge 代码
$bridgeDst = Join-Path $petRoot "bridge"
$bridgeSrc = Join-Path $here "bridge"
if (Test-Path $bridgeSrc) {
    if (-not (Test-Path $bridgeDst)) { New-Item -ItemType Directory -Path $bridgeDst | Out-Null }
    Copy-Item (Join-Path $bridgeSrc "*.py") $bridgeDst -Force
    if (Test-Path (Join-Path $bridgeSrc "dsh_persona.md")) {
        Copy-Item (Join-Path $bridgeSrc "dsh_persona.md") $bridgeDst -Force
    }
    Ok "bridge 代码已复制到 $bridgeDst"
} else {
    Warn "当前目录没有 bridge 子目录，跳过复制（如果你想原地使用，可忽略）"
}

# 3. 生成 bridge\config.json
$cfgPath = Join-Path $bridgeDst "config.json"
if (-not (Test-Path $cfgPath)) {
    $token = Read-Host "SnowLuma 的 Access Token（没设就回车跳过）"
    $cfg = [ordered]@{
        onebot     = [ordered]@{ url = "http://127.0.0.1:3000"; token = $token }
        python_exe = $venvPy
        pet_root   = $petRoot
        pet_api    = "http://127.0.0.1:12393"
    }
    $cfg | ConvertTo-Json -Depth 4 | Set-Content -Path $cfgPath -Encoding UTF8
    Ok "已生成 $cfgPath"
} else {
    Ok "已存在 $cfgPath（不覆盖）"
}

# 4. 创建工作区人设
$ws = Join-Path (Split-Path $petRoot) "pet_workspace"
if (-not (Test-Path $ws)) { New-Item -ItemType Directory -Path $ws | Out-Null }
$agents = Join-Path $ws "AGENTS.md"
$agentsSrc = Join-Path $here "config\AGENTS.example.md"
if ((Test-Path $agentsSrc) -and (-not (Test-Path $agents))) {
    Copy-Item $agentsSrc $agents
    Ok "已创建工作区人设: $agents"
} else {
    Ok "工作区人设已存在或模板缺失（跳过）"
}

# 5. 生成 mcp_servers.json 片段（提示用户手动合并）
$mcpEx = Join-Path $here "config\mcp_servers.example.json"
if (Test-Path $mcpEx) {
    $txt = Get-Content $mcpEx -Raw
    $txt = $txt.Replace("<你的 python 路径>", (Split-Path $venvPy)).Replace("<桌宠目录>", $petRoot)
    $out = Join-Path $here "config\mcp_servers.ready.json"
    $txt | Set-Content -Path $out -Encoding UTF8
    Ok "已生成 mcp_servers 片段: $out（把它合并进 $petRoot\mcp_servers.json 的 mcp_servers 里）"
}

Write-Host "`n=== 接下来手工做三件事 ===`n"
Write-Host "  1) 合并 MCP 配置：把 config\mcp_servers.ready.json 里的 msg-bridge 塞进 $petRoot\mcp_servers.json"
Write-Host "  2) （可选）DSH 集成：把 config\cordis.patch.example.yml 追加到 C:\Users\<你>\.dsh\profiles\desktop\cordis.patch.yml"
Write-Host "     并把 config\AGENTS.example.md 的人格文本粘进预设的 prefix"
Write-Host "  3) 启动：双击桌宠根目录的 启动桌宠客户端.cmd（需先把本仓库的启动脚本复制过去）"
Write-Host ""
