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

## 截图识别

截图识别默认使用内置识别能力，打包后会随程序一起提供。

配置页中的「提前准备」会预先加载截图识别能力，减少第一次识别时的等待。

截图列表识别会优先使用识别框坐标做结构分析：先按行分组，再划分物品名、价格数字和单位图标区域。程序内置 poe2db 通货图标，并在启动时维护到 SQLite；同步 poe2db 经济数据只更新价格，不更新图标模板。

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

正式发布到 GitHub release 时，可以生成带公开下载地址的 manifest：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\make_release.ps1 `
  -Version 0.3.18 `
  -AppName PoE2PriceTracker-0.3.18 `
  -DownloadBaseUrl "https://github.com/bigdogaaa/PoE2PriceTracker/releases/download/v0.3.18"
```
