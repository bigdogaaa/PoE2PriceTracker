# Gitee 版本检查与夸克手动下载

当前发布模型：

- Gitee 仓库 `BiGDoGaaa/poe2pricetracker_version_info`：只保存 `latest.json`，作为默认版本检查源。
- GitHub Release：保存软件本体，作为自动更新下载源。
- 夸克网盘：保存软件包或分享页，作为用户手动下载入口，用于提升手动下载稳定性。

默认客户端会读取：

```text
https://gitee.com/BiGDoGaaa/poe2pricetracker_version_info/raw/master/latest.json
```

## latest.json 字段

- `download_url` / `download_urls`：自动下载地址，默认只放 GitHub Release 文件。
- `manual_urls`：手动下载地址，放夸克网盘分享链接。
- `sha256` / `size`：基于 GitHub 上同一个软件包计算，自动下载时严格校验。

客户端检测到新版本后：

- 配置页“检查更新”会提示是否有新版本。
- 手动检查更新弹窗里会显示醒目的“打开夸克网盘下载”按钮。
- 配置页“检查更新”旁边有“手动下载最新版”按钮；只有检测到新版本且清单中有夸克链接时才可点击。

## 统一发布脚本

推荐使用：

```powershell
$env:GITHUB_TOKEN="你的 GitHub token"
$env:GITEE_TOKEN="你的 Gitee token"

python scripts\publish_release_channels.py `
  --version 0.4.9 `
  --asset dist\PoE2PriceTracker-0.4.9.exe `
  --quark-url "https://pan.quark.cn/s/xxxx" `
  --notes "更新说明"
```

脚本会：

1. 生成 `release/latest.json`。
2. 发布或更新 GitHub Release，并上传 exe 与 `latest.json`。
3. 在 Gitee 仓库创建或更新 `latest.json`。
4. 在 `manual_urls` 中写入夸克链接。

## Gitee 初始化

`poe2pricetracker_version_info` 新仓库可以是空仓库。发布脚本通过 Gitee API 创建 `latest.json`；后续再次发布时会自动更新这个文件。

默认参数：

```text
--gitee-repo BiGDoGaaa/poe2pricetracker_version_info
--gitee-branch master
--gitee-path latest.json
```

## 接入夸克上传 API

如果后续有可用的夸克上传接口，可以先写一个单独命令完成上传，并把分享链接打印到 stdout。然后用：

```powershell
$env:QUARK_UPLOAD_COMMAND="python scripts\your_quark_upload.py"

python scripts\publish_release_channels.py `
  --version 0.4.9 `
  --asset dist\PoE2PriceTracker-0.4.9.exe `
  --notes "更新说明"
```

脚本会把以下环境变量传给上传命令：

- `POE2_RELEASE_ASSET`：本地软件包路径。
- `POE2_RELEASE_VERSION`：版本号。

上传命令只要输出一个 `http://` 或 `https://` 链接，发布脚本就会自动把它写进 `manual_urls`。
