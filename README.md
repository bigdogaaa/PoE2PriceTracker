# PoE2 Price Tracker

一个优先使用本地截图与本地数据库的 Windows 桌面价格追踪工具。第一版目标是：

- 截图识别 `item` 和 `price`
- 为每个物品保存本地历史价格
- 通过快捷键或输入物品名快速查询
- 支持 PyInstaller 打包为 Windows exe

## 运行

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m poe2_price_tracker
```

也可以直接在当前环境运行：

```powershell
.\scripts\run.ps1
```

## 快捷键

默认快捷键：

- `Ctrl+Alt+P`：截取鼠标附近区域，识别物品名并查询本地价格
- `Ctrl+Alt+O`：截取鼠标附近区域，识别物品名和价格，确认后入库
- `Ctrl+Alt+F`：聚焦搜索框

快捷键不会向游戏发送输入，只在工具侧触发截图和查询。

## OCR

OCR 默认使用本地 Tesseract。程序会优先查找已配置路径、打包内置路径、系统常见安装路径。

在「配置」页可以点击「自动准备 OCR」：程序会从配置的 OCR 包地址下载到本机软件数据目录，自动解压或静默安装，并补齐中文简体与英文语言包。

默认 OCR 包地址指向本项目 Gitee release 附件：

```text
https://gitee.com/BiGDoGaaa/poe2-price-tracker/releases/download/ocr/tesseract-win64-chi-sim.zip
```

OCR 二进制不提交到源码仓库。发布 OCR 包时，zip 内需要包含 `tesseract.exe`，程序会自动递归查找并配置。

## 数据位置

默认数据目录：

```text
%LOCALAPPDATA%\PoE2PriceTracker
```

包含：

- `prices.sqlite3`
- `screenshots\`
- `config.json`

## 打包

安装构建依赖后运行：

```powershell
.\scripts\test.ps1
.\scripts\build.ps1 -AppName PoE2PriceTracker
```

生成物：

```text
dist\PoE2PriceTracker.exe
```

打包脚本会使用干净的 `.build-venv`，避免 Conda/Miniforge 环境把 Numpy、MKL 等大依赖打进 exe。

如需安装包，可以用 Inno Setup 打开：

```text
installer\PoE2PriceTracker.iss
```

## 更新

应用内“检查更新”会读取配置里的 `update_manifest`。它支持本地路径或 HTTP(S) manifest，manifest 格式见：

```json
{
  "version": "0.1.1",
  "download_url": "https://example.com/PoE2PriceTracker-0.1.1.zip",
  "sha256": "..."
}
```

更新流程：检查版本、下载 zip、校验 sha256、解压到本机更新目录，然后提示启动新版并退出当前版本。它不会覆盖正在运行的 exe。

正式发布到 Gitee release 时，可以生成带公开下载地址的 manifest：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\make_release.ps1 `
  -Version 0.2.4 `
  -AppName PoE2PriceTracker-0.2.4 `
  -DownloadBaseUrl "https://gitee.com/BiGDoGaaa/poe2-price-tracker/releases/download/v0.2.4"
```
