# STS2 Live2D Virtual Girlfriend Streamer

一个把 `Live2D 虚拟女友` 和 `Slay the Spire 2 AI Agent` 融合到一起的完整项目。

这个仓库包含两部分：

- [Live2D-Virtual-Girlfriend-main](./Live2D-Virtual-Girlfriend-main)
  Live2D 形象、主播运行时、可视化控制台、LLM/TTS/B站弹幕配置。
- [STS2-Agent-main](./STS2-Agent-main)
  Slay the Spire 2 本地 mod、HTTP API、MCP/验证脚本。

## 现在已经有什么

- 可运行的 STS2 自动主播链路
- 本地可视化控制台：`http://127.0.0.1:19098/config`
- LLM-first 玩法：决策、动作前解说、动作后复盘、弹幕回复
- 多厂商模型入口
- 国产模型厂商预设
- 自定义 URL 自动识别模型能力

## 控制台支持的模型来源

- OpenAI
- OpenRouter
- DeepSeek
- DashScope / 通义
- Volcengine / 豆包
- SiliconFlow
- 智谱
- 智谱 Coding Plan
- 百度千帆
- MiniMax
- 阶跃
- 阶跃 Plan
- Moonshot / Kimi
- 百川
- 零一万物
- 腾讯混元
- ModelScope
- Ollama
- 自定义 OpenAI-compatible URL

## 快速启动

```powershell
cd .\Live2D-Virtual-Girlfriend-main
uv venv .venv-sts2-streamer --python 3.11
uv pip install --python .\.venv-sts2-streamer\Scripts\python.exe -r requirements.sts2_streamer.txt
.\launch_sts2_streamer.ps1
```

启动后打开：

```text
http://127.0.0.1:19098/config
```

## 文档入口

- [README_GITHUB_PACKAGE.md](./README_GITHUB_PACKAGE.md)
- [PUBLISH_TO_GITHUB.md](./PUBLISH_TO_GITHUB.md)
- [Live2D 控制台说明](./Live2D-Virtual-Girlfriend-main/STS2_STREAMER_CONTROL_PANEL.md)
- [STS2 主播 README](./Live2D-Virtual-Girlfriend-main/README_STS2_STREAMER.md)

## 发布前注意

- 不要把真实 API Key 提交到 GitHub。
- 游戏路径是本机路径，公开仓库建议改成示例路径或在文档里说明用户自行配置。
- `.venv*`、`logs`、`temp`、缓存和临时音频已经通过 `.gitignore` 排除。
