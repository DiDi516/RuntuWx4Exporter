# 打包 Windows 单文件 exe
# 用法: .\scripts\build.ps1  [-Name "闰土微信记录导出器"]
param([string]$Name = "闰土微信记录导出器")

$ErrorActionPreference = "Stop"
$py = ".\.venv-pyside\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "未找到虚拟环境，请先执行: python -m venv .venv-pyside" }

# 关键：--icon / --add-data 必须绝对路径，否则会被 --specpath 拼接导致找不到文件
$assets = (Resolve-Path ".\wx4app\assets").Path

& $py -m PyInstaller --noconfirm --onefile --windowed `
    --name $Name `
    --icon "$assets\logo.ico" `
    --add-data "$assets;wx4app/assets" `
    --paths . --distpath dist2 --workpath build-pyside --specpath build-pyside `
    --hidden-import wx4app.window --hidden-import wx4app.widgets `
    --hidden-import wx4app.setup --hidden-import wx4app.theme `
    --hidden-import wx4app.config --hidden-import wx4app.assets `
    --hidden-import wx4app.export_dialog --hidden-import wx4app.frameless --hidden-import wx4app.job_runner `
    --hidden-import wx4view.live --hidden-import wx4export.core `
    --hidden-import wxmanager.wx4 --hidden-import wxmanager.wx4keys `
    --hidden-import Crypto.Cipher.AES --hidden-import zstandard `
    --hidden-import PIL.Image --collect-all av `
    --exclude-module tkinter run_wx4app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }

# 覆盖旧 exe：直接删除可能被安全策略拦截，改用原子替换
New-Item -ItemType Directory -Force -Path dist | Out-Null
& $py -c "import os,sys; os.replace(sys.argv[1], sys.argv[2])" "dist2\$Name.exe" "dist\$Name.exe"

$size = [math]::Round((Get-Item "dist\$Name.exe").Length / 1MB, 1)
Write-Host "构建完成: dist\$Name.exe ($size MB)" -ForegroundColor Green
