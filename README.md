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

在「配置」页可以点击「自动准备 OCR」：程序会把 Tesseract 下载到本机软件数据目录，下载中文简体与英文语言包，并自动写入配置。OCR 二进制不提交到源码仓库，正式发布时建议作为 release 资产或由程序首次运行时下载。

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

应用内预留了“检查更新”入口，读取配置里的 `update_manifest`。它支持本地路径或 HTTP(S) manifest，manifest 格式见：

```json
{
  "version": "0.1.1",
  "download_url": "https://example.com/PoE2PriceTracker-0.1.1.zip",
  "sha256": "..."
}
```

第一版只做提醒和打开下载地址，不做静默自替换，避免更新器误删正在运行的 exe。
