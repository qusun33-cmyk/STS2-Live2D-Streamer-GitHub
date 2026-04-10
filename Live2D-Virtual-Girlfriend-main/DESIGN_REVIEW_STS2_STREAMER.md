# STS2 Live2D Streamer Design Review

更新日期: 2026-04-09

## 目标

把 `Live2D-Virtual-Girlfriend-main` 的虚拟形象能力，与 `STS2-Agent-main` 的真实游戏状态/动作 API 融合成一条稳定直播链路:

- 虚拟女友能直接驱动真实的 `SlayTheSpire2.exe`
- 能根据实际战斗和路线状态做自动解说
- 能通过控制接口暂停/恢复/注入台词
- 能接 B 站弹幕并做实时口播回复

## 融合方案

没有把 STS2 逻辑塞回原项目的 LLM 对话主循环，而是单独走了 `main_sts2_streamer.py` 入口。

这样做的原因:

- 原 `main.py` 偏通用对话 Agent，依赖大模型、记忆、截图、工具调用，直播爬塔场景里链路过长。
- STS2 已经有稳定的 HTTP 状态和动作接口，没必要再做 OCR 或桌面点击。
- Live2D 项目本身的价值在于 `GUI + 字幕 + 口型 + 表情 + 本地 TTS`，这些可以直接复用。

最终架构:

- `main_sts2_streamer.py`
  - 直播专用入口
  - 自动切到 `config.sts2_streamer.toml`
  - 初始化 Live2D 形象和精简音频队列
- `src/sts2_streamer/runtime.py`
  - 直播总控
  - 检查/启动 STS2
  - 自动安装 Mod
  - 拉取状态、做自动决策、监听事件、响应弹幕
- `src/sts2_streamer/pilot.py`
  - 纯启发式自动玩家
  - 负责主菜单/角色/地图/战斗/奖励/商店/休息点/选牌逻辑
- `src/sts2_streamer/speaker.py`
  - Windows SAPI 本地语音
  - 复用 Live2D 的字幕、口型、表情链
- `src/sts2_streamer/control_api.py`
  - `health/status/pause/resume/speak`
  - 方便直播时外部控制
- `src/sts2_streamer/bilibili.py`
  - 直连 B 站直播弹幕 WebSocket
  - 收弹幕并回调给直播总控

## 核心设计判断

### 1. 游戏接入

选型: 直接复用 STS2 Mod 的 HTTP API，而不是屏幕识别。

原因:

- STS2 项目已经暴露 `GET /state`、`GET /actions/available`、`POST /action`
- 真实状态里有手牌、敌人、意图、奖励、地图节点、商店库存
- 这比 OCR 更稳定，也更适合做自动玩家

评价:

- 这是正确方向
- 后续优化重点应该放在策略，而不是输入层

### 2. 形象与语音

选型: 保留 Live2D 渲染和音频队列，替换为本地 SAPI 语音。

原因:

- 直播时更需要稳定可运行，而不是强依赖外部 TTS 服务
- SAPI 直接落 wav，再推给现有 `AudioQueueLite`，接入最短

评价:

- 适合作为第一版直播链路
- 后续可以再替换成 Kokoro / GPT-SoVITS 提升音色

### 3. 自动玩家

选型: 先用纯启发式，不接 LLM。

原因:

- 游戏动作必须低延迟、确定性、可恢复
- 启发式虽然不一定最优，但能直接跑塔

评价:

- 对“先直播起来”是合理的
- 对“高胜率构筑”还不够，需要后续继续迭代

## 已修问题

- 修复了从 `F:\codex` 启动时默认找错 `config.toml` 的问题
- `main_sts2_streamer.py` 和 `avatar_runtime.py` 现在会自动切到项目根目录
- `main_sts2_streamer.py` 自动使用 `config.sts2_streamer.toml`
- 增加了 Mod 自动安装能力，优先从 `F:\codex\workspace\sts2-release-v0.5.4\mod` 复制
- 接入了 `start-game-session.ps1` 启动脚本检测
- 自动玩家补上了 `continue_run`、时间线、角色已选中直接 `embark` 等逻辑
- 选牌逻辑改成根据 `selection.kind/prompt` 区分删牌、升级、变化
- 控制接口正式接到直播入口

## 实测结果

### 环境

- 实际游戏路径:
  - `F:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.exe`
- 实际 Mod 已加载:
  - `http://127.0.0.1:8080/health`
- 直播入口:
  - `F:\codex\workspace\Live2D-Virtual-Girlfriend-main\main_sts2_streamer.py`

### 已验证

- STS2 Mod 健康接口返回 `status=ready`
- 真实执行过 `continue_run`
- 直播入口能启动并拉起控制接口
- 控制接口已验证:
  - `POST /speak`
  - `POST /pause`
  - `POST /resume`
  - `GET /status`
- 自动玩家实机推进:
  - 从已有 run 接管
  - 观察到真实进度从第 1 层推进到第 5 层
  - 真实状态中出现过 `MAP`、`COMBAT`
  - 真实动作窗口中出现过 `play_card/end_turn/use_potion/discard_potion`

### 说明

通过自动化环境后台托管时，桌面 GUI 进程的长时间驻留不稳定；但前台运行 `main_sts2_streamer.py` 能持续进入事件循环并接管游戏。这不影响你本机实际开播使用。

## 当前剩余风险

### 1. B 站房间号未配置

当前代码路径已通，但 `config.sts2_streamer.toml` 里:

- `bilibili_enabled = false`
- `bilibili_room_id = 0`

所以还没有针对你的真实直播间做弹幕实测。

### 2. 策略仍是“能跑”优先

当前策略特点:

- 战斗会优先考虑击杀、易伤、格挡、能量效率
- 选牌/删牌/升级是启发式
- 商店优先遗物，再考虑高分卡

这适合直播首版，但不代表构筑最优。

### 3. 语音人设还比较基础

现在是:

- 本地 SAPI 语音
- 固定模板式解说
- 弹幕回复是规则驱动

如果后续要更像“虚拟女友”，应该继续加:

- 更强的人设台词库
- 战斗/路线/商店分场景口吻
- 弹幕关键词梗反应

## 直播前建议

1. 直接在项目根目录运行:

```powershell
F:\codex\workspace\Live2D-Virtual-Girlfriend-main\.venv-sts2\Scripts\python.exe main_sts2_streamer.py
```

2. 确认控制接口:

```powershell
Invoke-WebRequest http://127.0.0.1:19098/status -UseBasicParsing
```

3. 启用你的 B 站房间:

```toml
[sts2_streamer]
bilibili_enabled = true
bilibili_room_id = 你的房间号
```

## 结论

这次融合已经从“概念拼接”进入“可实际开播验证”的状态了。

目前最重要的结果不是代码结构，而是下面三点已经同时成立:

- 虚拟形象能说话
- 自动玩家能驱动真实 STS2
- 控制接口和弹幕桥的入口都已经打通

剩下最大的非代码阻塞，只剩你的真实 B 站房间号和你想要的人设/台词风格细化。
