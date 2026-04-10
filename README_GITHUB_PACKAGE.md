# STS2 Live2D Virtual Girlfriend Streamer

This package combines two local projects:

- `Live2D-Virtual-Girlfriend-main`: Live2D avatar, STS2 streamer runtime, visual control panel, LLM/TTS/Bilibili configuration.
- `STS2-Agent-main`: Slay the Spire 2 mod and local HTTP API bridge used by the streamer.

## Quick Start

1. Install Python dependencies for the streamer:

```powershell
cd .\Live2D-Virtual-Girlfriend-main
uv venv .venv-sts2-streamer --python 3.11
uv pip install --python .\.venv-sts2-streamer\Scripts\python.exe -r requirements.sts2_streamer.txt
```

2. Update the game path in:

```text
Live2D-Virtual-Girlfriend-main\config.sts2_streamer.toml
```

3. Start the streamer:

```powershell
cd .\Live2D-Virtual-Girlfriend-main
.\launch_sts2_streamer.ps1
```

4. Open the visual control panel:

```text
http://127.0.0.1:19098/config
```

## LLM Configuration

Use the control panel to select a provider, enter an API key, detect models, and save. It supports provider presets for OpenAI-compatible vendors, Ollama, and common Chinese model vendors including DeepSeek, DashScope, Volcengine/Doubao, SiliconFlow, Zhipu, Baidu Qianfan, MiniMax, StepFun, Moonshot/Kimi, Baichuan, Lingyiwanwu, Tencent Hunyuan, and ModelScope.

The system is LLM-first for gameplay decisions, action commentary, post-action review, event commentary, and Bilibili danmaku replies. If no model is available, it falls back to heuristic autopilot.

## Notes Before Publishing

- Do not commit real API keys. Use the visual panel locally or environment variables.
- Keep `.venv*`, `logs`, and `temp` out of Git.
- The default Windows game path is machine-specific and should be changed by each user.
- See `Live2D-Virtual-Girlfriend-main\STS2_STREAMER_CONTROL_PANEL.md` for the control panel guide.
