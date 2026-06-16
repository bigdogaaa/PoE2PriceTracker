# OCR、界面和打包策略

## OCR 路线

这个工具不要只依赖“整张图 OCR”。识别应该分层：

1. 单区域 OCR
   - 适合游戏内物品 tooltip。
   - 用户悬停后按快捷键，程序截取鼠标附近区域。
   - 优点是最快、交互最自然。
   - 缺点是对中文 OCR 引擎质量依赖较大。

2. 用户框选 item 区域和 price 区域
   - 适合 poe2db、网页表格、交易截图、聊天截图。
   - 用户第一次框出“物品名区域”和“价格区域”，软件保存模板。
   - 后续同类截图按模板裁剪，只 OCR 小区域。
   - 这是第一版后续最值得做的方向，准确率和速度都比整屏 OCR 高。

3. 结构化网页/表格解析
   - 如果来源是固定网页，比如 poe2db，可以直接读页面文本或 HTML。
   - 准确率最高，但依赖页面结构，不适合游戏内即时查询。
   - 可以作为“导入价格参考表”的独立功能。

4. 本地视觉 OCR 引擎
   - Tesseract：轻，离线，但中文小字效果一般。
   - PaddleOCR / RapidOCR：中文更强，但依赖和包体更大。
   - Windows OCR：系统集成，包体小，但 Python 调用复杂度更高。

建议顺序：

1. Tesseract + 区域框选模板
2. 如果中文小字仍不稳定，再引入 RapidOCR 或 PaddleOCR 作为可选 OCR 后端
3. 对 poe2db 这类固定页面，单独做网页/截图模板导入

## 界面路线

候选：

1. Tkinter + ttk
   - 当前方案。
   - 包体最小、无额外依赖。
   - 可以通过主题、布局、间距、表格样式明显改善。

2. ttkbootstrap
   - 推荐的下一步。
   - 基于 Tkinter，迁移成本低。
   - 体积增加小，界面能明显现代化。

3. customtkinter
   - 更现代，但控件体系和 ttk 表格结合不如 ttkbootstrap 自然。

4. PySide6 / Qt
   - 最漂亮、能力强。
   - 包体和打包体积明显增加，不适合当前“玩游戏时低占用”的目标。

建议：

先用 ttkbootstrap 重做外观；除非后续要做复杂悬浮窗、图表、可视化编辑器，再考虑 Qt。

## 打包路线

当前使用干净 `.build-venv` 构建，避免 Miniforge/Conda 把 Numpy、MKL 等重依赖打入 exe。

打包命令：

```powershell
.\scripts\build.ps1 -AppName PoE2PriceTracker-0.1.3
```

发布命令：

```powershell
.\scripts\make_release.ps1 -Version 0.1.3 -AppName PoE2PriceTracker-0.1.3
```
