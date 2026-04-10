# STS2 Live2D Streamer

这个集成把两个项目拆成两层：

1. `avatar_runtime.py`
   负责 Live2D 形象、字幕、口型和本地中文女声播报。
   默认读取 [config.sts2_streamer.toml](/F:/codex/workspace/Live2D-Virtual-Girlfriend-main/config.sts2_streamer.toml)。

2. `integrations/sts2_streamer/run.py`
   负责读取 STS2 Mod 的 HTTP 状态接口、自动出牌/推进流程、生成解说，并可选读取 B 站弹幕。

## 关键接口

- STS2 游戏 Mod：
  - `GET /health`
  - `GET /state`
  - `POST /action`
- Live2D 头像端：
  - `GET /health`
  - `POST /speak`
  - `POST /interrupt`

## 启动

```powershell
powershell -ExecutionPolicy Bypass -File .\launch_sts2_streamer.ps1
```

如果要先重编译并覆盖安装 STS2 Mod：

```powershell
powershell -ExecutionPolicy Bypass -File .\launch_sts2_streamer.ps1 -BuildMod
```

## B 站弹幕

把 [config.example.toml](/F:/codex/workspace/Live2D-Virtual-Girlfriend-main/integrations/sts2_streamer/config.example.toml) 复制为同目录下的 `config.toml` 后，填写：

- `bilibili.enabled = true`
- `bilibili.room_id = 你的直播间房间号`
- 如需登录态能力，再填 `sessdata` / `buvid3`

## LLM 可选增强

如果你填入 `llm.base_url`、`llm.api_key`、`llm.model`，控制端会优先用大模型做：

- 动作决策
- 弹幕回复

如果不填，会自动退回到内置启发式策略，仍然可以自己开局、走图、打基础战斗、拿奖励和推进流程。
