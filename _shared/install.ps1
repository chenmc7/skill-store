# install.ps1 —— 把本包内的 7 个 skill 安装到 WorkBuddy / Claude Code 的 skills 目录
# 用法：
#   powershell -ExecutionPolicy Bypass -File _shared\install.ps1
#   powershell -ExecutionPolicy Bypass -File _shared\install.ps1 -Copy        # 复制而非建链接
#   powershell -ExecutionPolicy Bypass -File _shared\install.ps1 -Target D:\some\skills

param(
    [string]$Target = "$env:USERPROFILE\.workbuddy\skills",
    [switch]$Copy
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$skills = @(
    'business-lecture-orchestrator', 'courseware-notes', 'lecture-notes-zh',
    'rigorous-derivation', 'exam-problems',
    'investment-lecture-orchestrator', 'platform-economy-orchestrator'
)

Write-Host "== 安装讲义 skill 包 ==" -ForegroundColor Cyan
Write-Host "包根目录：$root"
Write-Host "目标目录：$Target`n"

New-Item -ItemType Directory -Force -Path $Target | Out-Null

foreach ($s in $skills) {
    $src = Join-Path $root $s
    $dst = Join-Path $Target $s
    if (-not (Test-Path $src)) { Write-Warning "缺少 $s，跳过"; continue }
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    if ($Copy) {
        Copy-Item -Recurse $src $dst
        Write-Host "  [复制] $s"
    } else {
        New-Item -ItemType Junction -Path $dst -Target $src | Out-Null
        Write-Host "  [链接] $s"
    }
}

Write-Host "`n== 环境自检 ==" -ForegroundColor Cyan
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
& $py (Join-Path $root "_shared\doctor.py")

Write-Host "`n安装完成。若自检有缺失项，请按其提示补齐后再开工。" -ForegroundColor Green
