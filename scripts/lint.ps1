# 运行 ruff 静态检查（--fix 可选）
param([switch]$Fix)

$ErrorActionPreference = "Stop"
$py = ".\.venv-pyside\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "未找到虚拟环境，请先执行: python -m venv .venv-pyside" }

if ($Fix) {
    & $py -m ruff check . --fix
} else {
    & $py -m ruff check .
}
exit $LASTEXITCODE
