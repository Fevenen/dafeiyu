#requires -Version 5.1
<#
  大肥鱼桌宠 · 依赖安装
  自动：桌宠本体 + Python 依赖 + SnowLuma + bridge + 模型/音色/Live2D + 配置

  用法：
    powershell -ExecutionPolicy Bypass -File .\deps\bootstrap.ps1
    powershell -ExecutionPolicy Bypass -File .\deps\bootstrap.ps1 -Root "D:\my-pet-stack"
#>

param(
    [string]$Root = (Join-Path (Split-Path -Parent $PSScriptRoot) ".."),
    [string]$OlvRepo = "https://github.com/Open-LLM-VTuber/Open-LLM-VTuber.git",
    [string]$SnowLumaSlug = "SnowLumaDevs/SnowLuma",
    [string]$AssetBase = "https://github.com/Fevenen/dafeiyu/releases/download/v0.1.0"
)

$ErrorActionPreference = "Stop"

function Info($m) { Write-Host "  $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Die($m) { Write-Host "  [ERROR] $m" -ForegroundColor Red; exit 1 }

$Root = [System.IO.Path]::GetFullPath($Root)
$petDir = Join-Path $Root "pet"
$v0Dir = Join-Path $Root "v0"
$snowDir = Join-Path $v0Dir "SnowLuma"
$wsDir = Join-Path $Root "pet_workspace"
$repoDir = Split-Path -Parent $PSScriptRoot

Write-Host "`n=== 大肥鱼桌宠 · 依赖安装 ==="
Info "安装目录: $Root"

# ---------- 1. 基础工具 ----------
Write-Host "`n[1/8] 检查基础工具"
$missing = @()
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { $missing += "git" }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { $missing += "python" }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { $missing += "uv" }
if ($missing.Count -gt 0) {
    Warn ("缺少: " + ($missing -join ", "))
    if ($missing -contains "git") { Info "  winget install --id Git.Git -e" }
    if ($missing -contains "python") { Info "  winget install --id Python.Python.3.11 -e" }
    if ($missing -contains "uv") { Info '  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"' }
    Die "装完上面的工具、重开终端后再跑本脚本"
}
Ok "git / python / uv 都在"

# ffmpeg：edge-tts 转 wav 要用，没有就提示（不强制）
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Warn "没找到 ffmpeg（edge-tts 需要它把 mp3 转 wav）"
    Info "安装：winget install --id Gyan.FFmpeg -e  装完重开终端"
    Info "或者：用 sherpa 本地音色（不需要 ffmpeg，见 docs/tts.md）"
} else {
    Ok "ffmpeg 已安装"
}

# ---------- 2. 桌宠本体 ----------
Write-Host "`n[2/8] Open-LLM-VTuber"
if (Test-Path (Join-Path $petDir "run_server.py")) {
    Ok "已存在: $petDir"
} else {
    Info "git clone $OlvRepo"
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    git clone --depth 1 $OlvRepo $petDir
    if ($LASTEXITCODE -ne 0) { Die "克隆失败：检查网络或仓库地址" }
    Ok "已克隆到 $petDir"
}

# ---------- 3. Python 依赖 ----------
Write-Host "`n[3/8] 安装 Python 依赖（可能几分钟）"
Push-Location $petDir
try {
    uv sync
    if ($LASTEXITCODE -ne 0) { Warn "uv sync 失败，可手动执行：cd $petDir; uv sync" } else { Ok "桌宠依赖装好" }
    uv pip install requests pypinyin rapidfuzz mcp | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "bridge 依赖（requests / pypinyin / rapidfuzz / mcp）已装" } else { Warn "bridge 依赖失败，可手动：uv pip install requests pypinyin rapidfuzz mcp" }
} finally { Pop-Location }

# ---------- 4. SnowLuma ----------
Write-Host "`n[4/8] SnowLuma（QQ 协议端）"
$qqProc = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(QQ|QQNT|QQProtect)' }
if (-not $qqProc) {
    Warn "没检测到正在运行的 QQ 客户端。"
    Info "SnowLuma 不负责登录：它注入『已经登录』的 QQ。"
    Info "先打开官方 QQ 并登录，再运行桌宠（详见 docs/qq-setup.md）"
}
if (Test-Path (Join-Path $snowDir "launcher.bat")) {
    Ok "已存在: $snowDir"
} else {
    New-Item -ItemType Directory -Force -Path $v0Dir | Out-Null
    $api = "https://api.github.com/repos/$SnowLumaSlug/releases/latest"
    try {
        Info "查询最新 Release"
        $rel = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "bootstrap" } -TimeoutSec 30
        $asset = $rel.assets | Where-Object { $_.name -match '(win|windows)' } | Select-Object -First 1
        if (-not $asset) { $asset = $rel.assets | Select-Object -First 1 }
        if (-not $asset) { throw "Release 里没有可下载的文件" }
        $zip = Join-Path $env:TEMP $asset.name
        Info "下载 $($asset.name)（$([math]::Round($asset.size/1MB)) MB）"
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -TimeoutSec 900
        Expand-Archive -Path $zip -DestinationPath $snowDir -Force
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        $inner = Get-ChildItem $snowDir -Directory | Where-Object { Test-Path (Join-Path $_.FullName "launcher.bat") } | Select-Object -First 1
        if ($inner) {
            Get-ChildItem $inner.FullName | Move-Item -Destination $snowDir -Force
            Remove-Item $inner.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path (Join-Path $snowDir "launcher.bat")) { Ok "SnowLuma 已就绪" }
        else { Warn "解压完成但没找到 launcher.bat，请手动检查 $snowDir" }
    } catch {
        Warn "自动下载失败：$($_.Exception.Message)"
        Info "请手动下载：https://github.com/$SnowLumaSlug/releases"
        Info "解压到：$snowDir（里面要有 launcher.bat）"
    }
}

# ---------- 5. bridge ----------
Write-Host "`n[5/8] 复制 bridge 代码"
$bridgeSrc = Join-Path $repoDir "bridge"
$bridgeDst = Join-Path $petDir "bridge"
if (Test-Path $bridgeSrc) {
    New-Item -ItemType Directory -Force -Path $bridgeDst | Out-Null
    Copy-Item (Join-Path $bridgeSrc "*.py") $bridgeDst -Force
    Copy-Item (Join-Path $bridgeSrc "dsh_persona.md") $bridgeDst -Force -ErrorAction SilentlyContinue
    Ok "已复制到 $bridgeDst"
} else {
    Warn "找不到 $bridgeSrc，跳过"
}

# ---------- 6. 模型 / 音色 / Live2D（Release 附件） ----------
Write-Host "`n[6/8] 下载模型 / 音色 / Live2D"
$assets = @(
    @{ file = "tts-bronya.zip";      dest = (Join-Path $petDir "models\sherpa\bronya");                                  check = "bronya.onnx" },
    @{ file = "asr-sensevoice.zip";  dest = (Join-Path $petDir "models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"); check = "model.int8.onnx" },
    @{ file = "live2d-whale.zip";    dest = (Join-Path $petDir "live2d-models\ds-whale-girl");                            check = "runtime" }
)
foreach ($a in $assets) {
    if (Test-Path (Join-Path $a.dest $a.check)) {
        Ok "已存在: $($a.file)"
        continue
    }
    $url = "$AssetBase/$($a.file)"
    try {
        Info "下载 $($a.file) …"
        $zip = Join-Path $env:TEMP $a.file
        Invoke-WebRequest -Uri $url -OutFile $zip -TimeoutSec 1800
        New-Item -ItemType Directory -Force -Path $a.dest | Out-Null
        Expand-Archive -Path $zip -DestinationPath $a.dest -Force
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        Ok "已解压到 $($a.dest)"
    } catch {
        Warn "下载失败：$($a.file) —— $($_.Exception.Message)"
        Info "可从 Release 页面手动下载并解压到：$($a.dest)"
    }
}

# ---------- 7. 配置 + 工作区 ----------
Write-Host "`n[7/8] 生成配置和工作区"

# conf.yaml：没有就从模板生成（之后要自己填模型/API key）
$confPath = Join-Path $petDir "conf.yaml"
$confTpl = Join-Path $petDir "config_templates\conf.default.yaml"
if ((-not (Test-Path $confPath)) -and (Test-Path $confTpl)) {
    Copy-Item $confTpl $confPath
    Ok "已从模板生成 conf.yaml（记得填模型/API key）"
}
# 默认语音改成 edge-tts + 晓伊（需要 ffmpeg；没有会用 sherpa，见 docs/tts.md）
if (Test-Path $confPath) {
    $txt = Get-Content $confPath -Raw -Encoding UTF8
    $txt = $txt -replace "(?m)^(\s*)tts_model:\s*'[^']*'", "`$1tts_model: 'edge_tts'"
    $txt = $txt -replace "zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural"
    Set-Content -Path $confPath -Value $txt -Encoding UTF8 -NoNewline
    Ok "语音默认：edge-tts / zh-CN-XiaoyiNeural（晓伊）"
}

$cfgPath = Join-Path $bridgeDst "config.json"
if (-not (Test-Path $cfgPath)) {
    $venvPy = Join-Path $petDir ".venv\Scripts\python.exe"
    $token = Read-Host "SnowLuma 的 Access Token（没设就回车跳过）"
    $cfg = [ordered]@{
        onebot     = [ordered]@{ url = "http://127.0.0.1:3000"; token = $token }
        python_exe = $venvPy
        pet_root   = $petDir
        pet_api    = "http://127.0.0.1:12393"
    }
    $cfg | ConvertTo-Json -Depth 4 | Set-Content -Path $cfgPath -Encoding UTF8
    Ok "已写入 $cfgPath"
} else { Ok "config.json 已存在（不覆盖）" }

New-Item -ItemType Directory -Force -Path $wsDir | Out-Null
$agents = Join-Path $wsDir "AGENTS.md"
$agentsSrc = Join-Path $repoDir "config\AGENTS.example.md"
if ((Test-Path $agentsSrc) -and (-not (Test-Path $agents))) {
    Copy-Item $agentsSrc $agents
    Ok "工作区人设: $agents"
}

# 自动把 msg-bridge 加进桌宠的 mcp_servers.json
$mcpPath = Join-Path $petDir "mcp_servers.json"
$mcpServers = [ordered]@{}
if (Test-Path $mcpPath) {
    try {
        $old = Get-Content $mcpPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($old.mcp_servers) {
            foreach ($prop in $old.mcp_servers.PSObject.Properties) {
                $mcpServers[$prop.Name] = $prop.Value
            }
        }
    } catch {
        Warn "现有 mcp_servers.json 解析失败，将重建（原文件备份为 .bak）"
        Copy-Item $mcpPath "$mcpPath.bak" -Force
    }
}
$mcpServers["msg-bridge"] = [ordered]@{
    command = (Join-Path $petDir ".venv\Scripts\python.exe")
    args    = @((Join-Path $bridgeDst "server.py"))
}
$mcpObj = [ordered]@{ mcp_servers = $mcpServers }
$mcpObj | ConvertTo-Json -Depth 8 | Set-Content -Path $mcpPath -Encoding UTF8
Ok "已写入 mcp_servers.json（msg-bridge）"

$launcher = Join-Path $repoDir "启动桌宠客户端.cmd"
if ((Test-Path $launcher) -and (-not (Test-Path (Join-Path $petDir "启动桌宠客户端.cmd")))) {
    Copy-Item $launcher $petDir
    Ok "启动脚本已放到桌宠目录"
}

# ---------- 8. 收尾 ----------
Write-Host "`n[8/8] 完成。接下来手工做："
Write-Host "  1) 启动 SnowLuma 并登录 QQ：$snowDir\launcher.bat"
Write-Host "  2) 配模型（README「接你自己的本地模型」）：编辑 $petDir\conf.yaml"
Write-Host "  3) 把 msg-bridge 加进 $petDir\mcp_servers.json（模板：config\mcp_servers.example.json）"
Write-Host "  4) 双击 $petDir\启动桌宠客户端.cmd"
Write-Host "  5) 浏览器打开 http://127.0.0.1:12393 （不需要 Electron 也能用）"
Write-Host ""
Info "QQ 登录后自检：python $petDir\bridge\_mcp_selftest.py"
Write-Host ""
