# 虚拟女友玩杀戮尖塔2直播

这是一个把 Live2D 虚拟角色、Slay the Spire 2 本地游戏代理、LLM 决策与解说、B 站弹幕互动配置整合到一起的直播项目。

项目目标是让一个“虚拟女友”可以在直播中游玩《杀戮尖塔 2》，根据游戏局势实时说话，并通过可视化控制台配置大模型、语音、弹幕和自动驾驶行为。

## 项目组成

- [Live2D-Virtual-Girlfriend-main](./Live2D-Virtual-Girlfriend-main)：Live2D 角色、主播运行时、可视化配置控制台、LLM/TTS/B 站弹幕配置。
- [STS2-Agent-main](./STS2-Agent-main)：Slay the Spire 2 本地 mod、HTTP API 桥、MCP/验证脚本。

## 当前能力

- Slay the Spire 2 本地 mod API 接入。
- Live2D 主播运行时与自动驾驶链路。
- 本地 Web 控制台：`http://127.0.0.1:19098/config`。
- LLM-first 玩法：出牌决策、动作前解说、动作后复盘、事件解说、弹幕回复。
- 没有可用模型时自动回退启发式自动驾驶。
- 支持国产与海外常见 OpenAI-compatible 模型厂商预设。
- 支持粘贴 Base URL 或 `/v1/chat/completions` URL 后自动归一化并识别模型。
- 支持 Edge Neural TTS 优先，失败后回退 Windows SAPI。

## 支持的模型来源

- OpenAI
- OpenRouter
- DeepSeek
- DashScope / 通义千问
- Volcengine / 豆包
- SiliconFlow
- 智谱
- 智谱 Coding Plan
- 百度千帆
- MiniMax
- 阶跃星辰
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

## 使用说明

- 控制台说明：[Live2D-Virtual-Girlfriend-main/STS2_STREAMER_CONTROL_PANEL.md](./Live2D-Virtual-Girlfriend-main/STS2_STREAMER_CONTROL_PANEL.md)
- STS2 主播说明：[Live2D-Virtual-Girlfriend-main/README_STS2_STREAMER.md](./Live2D-Virtual-Girlfriend-main/README_STS2_STREAMER.md)
- GitHub 打包说明：[README_GITHUB_PACKAGE.md](./README_GITHUB_PACKAGE.md)
- 发布说明：[PUBLISH_TO_GITHUB.md](./PUBLISH_TO_GITHUB.md)

## 发布前注意

- 不要把真实 API Key 提交到 GitHub。
- 游戏路径是本机路径，其他用户需要在 `Live2D-Virtual-Girlfriend-main/config.sts2_streamer.toml` 中自行配置。
- `.venv*`、`logs`、`temp`、缓存和临时音频已经通过 `.gitignore` 排除。

