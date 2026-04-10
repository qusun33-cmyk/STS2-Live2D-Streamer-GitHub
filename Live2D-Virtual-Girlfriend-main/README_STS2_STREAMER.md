# STS2 Live2D Streamer

This entrypoint fuses the Live2D avatar project with the STS2 HTTP mod.

## What it does

- launches or reconnects to `Slay the Spire 2`
- ensures the local STS2 mod is enabled
- drives the run with an LLM-first autopilot and a heuristic fallback
- speaks LLM-enhanced game-aware commentary through the Live2D avatar
- optionally reads Bilibili danmaku and replies in real time
- exposes a local visual control panel for LLM, danmaku, TTS, and autopilot settings

## Entrypoint

```powershell
.\launch_sts2_streamer.ps1
```

## Minimal environment

```powershell
.\.venv-sts2-streamer\Scripts\python.exe -m pip install -r requirements.sts2_streamer.txt
```

## Config

The streamer entrypoint now defaults to `config.sts2_streamer.toml`.

Key fields:

```toml
[sts2_streamer]
api_base_url = "http://127.0.0.1:8080"
game_exe_path = "F:\\SteamLibrary\\steamapps\\common\\Slay the Spire 2\\SlayTheSpire2.exe"
auto_launch_game = true
auto_install_mod = true
resume_existing_run = true
enable_debug_actions = false
auto_play = true
auto_commentary = true
bilibili_reply_probability = 0.35
bilibili_enabled = false
bilibili_room_id = 0
tts_backend = "edge"
default_voice = "zh-CN-XiaoxiaoNeural"
speech_rate = 1
speech_volume = 100
llm_enabled = true
llm_use_for_actions = true
llm_use_for_commentary = true
llm_use_for_danmaku = true
controller_host = "127.0.0.1"
controller_port = 19098
sts2_project_root = "..\\STS2-Agent-main"
mod_source_dir = "..\\STS2-Agent-main\\build\\mods\\STS2AIAgent"
```

## Visual control panel

When the streamer is running, open:

```text
http://127.0.0.1:19098/config
```

The page lets you configure:

- Main decision LLM provider, API key, base URL, and model discovery.
- Auxiliary commentary/danmaku model, including local Ollama.
- Domestic provider presets including DeepSeek, DashScope, Doubao/Volcengine, SiliconFlow, Zhipu, Zhipu Coding Plan, Baidu Qianfan, MiniMax, StepFun, StepFun Plan, Moonshot, Baichuan, Lingyiwanwu, Tencent Hunyuan, and ModelScope.
- Custom URL discovery for URLs like `/v1`, `/v1/models`, `/v1/chat/completions`, and `/api/paas/v4/chat/completions`.
- Bilibili room id, reply probability, and live toggles.
- TTS backend, voice, speed, and volume.
- Pause/resume and voice test actions.

More details are in `STS2_STREAMER_CONTROL_PANEL.md`.

## Control API

When the streamer is running:

- `GET http://127.0.0.1:19098/config`
- `GET http://127.0.0.1:19098/api/config`
- `POST http://127.0.0.1:19098/api/config`
- `POST http://127.0.0.1:19098/api/config/discover-models`
- `GET http://127.0.0.1:19098/health`
- `GET http://127.0.0.1:19098/status`
- `POST http://127.0.0.1:19098/pause`
- `POST http://127.0.0.1:19098/resume`
- `POST http://127.0.0.1:19098/speak`

Example:

```powershell
$body = '{"text":"测试语音接口已连通。","expression":"闪亮"}'
Invoke-WebRequest -Uri 'http://127.0.0.1:19098/speak' -Method Post -ContentType 'application/json' -Body $body -UseBasicParsing
```

## Notes

- The avatar voice currently uses Windows SAPI so it can run without GPT-SoVITS or Kokoro.
- The Bilibili bridge only needs a room id for public danmaku read access.
- The gameplay layer uses the real STS2 mod endpoints instead of screen OCR.
- A fuller architecture and test review is in `DESIGN_REVIEW_STS2_STREAMER.md`.
