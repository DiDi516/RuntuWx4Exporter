# 运行单元测试
$ErrorActionPreference = "Stop"
$py = ".\.venv-pyside\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "未找到虚拟环境，请先执行: python -m venv .venv-pyside" }

& $py -m pytest @args
exit $LASTEXITCODE
