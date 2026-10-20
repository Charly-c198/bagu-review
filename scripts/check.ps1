# 本地一键检查（与 CI 同口径）
#
#   .\scripts\check.ps1            # 后端 ruff + pytest，前端类型检查 + 构建
#   .\scripts\check.ps1 -WithE2E   # 额外跑本机 Edge 冒烟
param([switch]$WithE2E)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path (Split-Path -Parent $root) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Push-Location (Join-Path $root "backend")
try {
    & $python -m ruff --version *> $null
    if ($LASTEXITCODE -eq 0) {
        & $python -m ruff check app tests
        if ($LASTEXITCODE -ne 0) { throw "ruff 检查失败" }
    } else {
        Write-Warning "未安装 ruff，跳过 lint（pip install -r backend/requirements-dev.txt）"
    }
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "后端测试失败" }
} finally {
    Pop-Location
}

Push-Location (Join-Path $root "frontend")
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
    if ($WithE2E) {
        npm run e2e
        if ($LASTEXITCODE -ne 0) { throw "E2E 失败" }
    }
} finally {
    Pop-Location
}

Write-Host "全部检查通过" -ForegroundColor Green
