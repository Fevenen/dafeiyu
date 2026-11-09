#requires -Version 5.1
<#
  sync.ps1 — 把正在运行的代码同步到发布仓库，然后提示提交。

  用法（在 release 目录或任意位置）：
    powershell -ExecutionPolicy Bypass -File .\sync.ps1
    powershell -ExecutionPolicy Bypass -File .\sync.ps1 -Push

  做三件事：
    1. pet\bridge\*.py / *.md  →  release\bridge\
    2. 检查 release\bridge 与 pet\bridge 还有没有差异
    3. （-Push）git add/commit/push
#>

param(
    [string]$PetBridge = "D:\project\MP\pet\bridge",
    [string]$Release = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [switch]$Push,
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"
function Info($m) { Write-Host "  $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }

if (-not (Test-Path $PetBridge)) { throw "找不到 pet\bridge: $PetBridge" }
$dst = Join-Path $Release "bridge"

Write-Host "`n=== 同步 pet\bridge -> release\bridge ===`n"
Info "源: $PetBridge"
Info "目标: $dst"

# 1. 同步代码与文档（不含 state/logs/__pycache__/config.json）
$files = Get-ChildItem $PetBridge -File | Where-Object {
    $_.Extension -in ".py", ".md" -and $_.Name -notlike "config.json"
}
foreach ($f in $files) {
    Copy-Item $f.FullName (Join-Path $dst $f.Name) -Force
}
Ok ("同步 {0} 个文件" -f $files.Count)

# 2. _v0 目录
$srcV0 = Join-Path $PetBridge "_v0"
$dstV0 = Join-Path $dst "_v0"
if (Test-Path $srcV0) {
    New-Item -ItemType Directory -Force -Path $dstV0 | Out-Null
    Get-ChildItem $srcV0 -File | Where-Object { $_.Extension -eq ".py" } | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $dstV0 $_.Name) -Force
    }
    Ok "_v0 已同步"
}

# 3. 差异检查
Push-Location $Release
try {
    $git = "git"
    $status = & $git status --short 2>&1
    if ($status) {
        Write-Host "`n  变更："
        $status | ForEach-Object { Write-Host "    $_" }
    } else {
        Ok "没有变更"
    }

    if ($Push -and $status) {
        if (-not $Message) { $Message = "chore: 同步 pet\bridge" }
        & $git add -A | Out-Null
        & $git commit -m $Message | Out-Null
        & $git push | Out-Null
        Ok "已提交并推送：$Message"
    } elseif ($status) {
        Info "确认无误后执行："
        Info "  git add -A; git commit -m `"你的说明`"; git push"
    }
} finally {
    Pop-Location
}
