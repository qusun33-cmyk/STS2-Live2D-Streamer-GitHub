# GitHub 打包说明

项目名称：虚拟女友玩杀戮尖塔2直播

这个目录是整理后可直接上传到 GitHub 的发布包，包含 Live2D 虚拟女友主播端和 Slay the Spire 2 游戏代理端。

## 包含内容

- `Live2D-Virtual-Girlfriend-main`：主播端、可视化控制台、LLM/TTS/B 站弹幕配置。
- `STS2-Agent-main`：Slay the Spire 2 mod、本地 HTTP API 和验证脚本。
- `README.md`：GitHub 首页说明。
- `PUBLISH_TO_GITHUB.md`：发布到 GitHub 的说明。
- `.gitignore`：排除虚拟环境、缓存、日志、临时音频和构建产物。

## 不包含内容

- Python 虚拟环境：`.venv*`
- 日志和临时文件：`logs`、`temp`
- Python 缓存：`__pycache__`
- Node 缓存或依赖：`node_modules`
- 真实 API Key

## 使用入口

启动主播：

```powershell
cd .\Live2D-Virtual-Girlfriend-main
.\launch_sts2_streamer.ps1
```

打开可视化控制台：

```text
http://127.0.0.1:19098/config
```

详细说明请看根目录 [README.md](./README.md)。

