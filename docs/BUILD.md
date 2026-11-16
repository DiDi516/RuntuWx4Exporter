# 构建与打包

## 1. 准备

```powershell
python -m venv .venv-pyside
.\.venv-pyside\Scripts\python -m pip install -r requirements-dev.txt
```

## 2. 生成图标（可选，仓库已含）

```powershell
.\.venv-pyside\Scripts\python -c "from PIL import Image; im=Image.open('wx4app/assets/logo.png'); im.convert('RGBA').save('wx4app/assets/logo.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
```

## 3. 打包

```powershell
$assets = (Resolve-Path .\wx4app\assets).Path
.\.venv-pyside\Scripts\python -m PyInstaller --noconfirm --onefile --windowed `
  --name "闰土微信记录导出器" `
  --icon "$assets\logo.ico" `
  --add-data "$assets;wx4app/assets" `
  --paths . --distpath dist --workpath build-pyside --specpath build-pyside `
  --hidden-import wx4app.window --hidden-import wx4app.widgets `
  --hidden-import wx4app.setup --hidden-import wx4app.theme `
  --hidden-import wx4app.config --hidden-import wx4app.assets `
  --hidden-import wx4app.export_dialog --hidden-import wx4app.frameless `
  --hidden-import wx4view.live --hidden-import wx4export.core `
  --hidden-import wxmanager.wx4 --hidden-import wxmanager.wx4keys `
  --hidden-import Crypto.Cipher.AES --hidden-import zstandard `
  --hidden-import PIL.Image --collect-all av `
  --exclude-module tkinter run_wx4app.py
```

产物：`dist\闰土微信记录导出器.exe`（约 80 MB，单文件）。

## 4. 必须知道的坑

1. **`--icon` / `--add-data` 用绝对路径**：相对路径会被 `--specpath` 拼接导致 `FileNotFoundError`。
2. **覆盖旧 exe**：本机安全策略会拦截删除（`trash` 失败）。
   先打包到 `dist2`，再：
   ```powershell
   python -c "import os;os.replace(r'dist2\闰土微信记录导出器.exe', r'dist\闰土微信记录导出器.exe')"
   ```
3. **资源路径**：代码里用 `wx4app.assets.resource_path()`，已兼容 `sys._MEIPASS`。
4. **onefile 有父子进程**：验证窗口要按标题枚举，不能只查启动 PID。

## 5. 验收清单

- [ ] 双击 exe：出现「连接微信数据」页，能列出候选账号
- [ ] 进入主界面：会话列表有头像、点击会话能渲染消息
- [ ] 导出图片/记录/文件：进度条正常、完成可打开目录
- [ ] 一键导出全部：可取消、zip 可解压
- [ ] 关闭程序无崩溃、无残留进程
