# STS2 虚拟女友直播控制台

启动主播后打开：

```text
http://127.0.0.1:19098/config
```

这个页面用于可视化配置整条直播链路：

- 主决策模型：用于出牌、选路、奖励选择等核心决策。
- 辅助/解说模型：用于动作前口播、动作后复盘和弹幕回复。
- 直播与弹幕：控制自动玩、自动口播、B 站弹幕房间号、回复概率和冷却时间。
- TTS 声音：控制 `edge` / `sapi` 后端、声线、语速和音量。
- 状态面板：显示 STS2 mod API、当前楼层/画面、LLM 是否启用。

## 推荐配置

主决策模型建议使用远端强模型：

```text
provider: openrouter / openai / deepseek / dashscope / siliconflow / custom_openai
base_url: 按页面预设或厂商 OpenAI-compatible 地址
api_key: 你的厂商 Key
chat_model: auto 或点击“识别模型”后选择
```

辅助/解说模型建议使用本地或便宜模型：

```text
provider: ollama
base_url: http://127.0.0.1:11434
chat_model: auto 或本机模型名
```

如果没有 API Key，也没有启动 Ollama，页面会显示模型未启用；这时系统会自动回退到启发式驾驶，不会中断游戏。

## 已内置的国产厂商入口

控制台的厂商下拉框已经内置这些常用入口：

- `deepseek`: `https://api.deepseek.com/v1`
- `dashscope`: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- `volcengine`: `https://ark.cn-beijing.volces.com/api/v3`
- `siliconflow`: `https://api.siliconflow.cn/v1`
- `zhipu`: `https://open.bigmodel.cn/api/paas/v4`
- `zhipu_coding_plan`: `https://open.bigmodel.cn/api/coding/paas/v4`
- `baidu_qianfan`: `https://qianfan.baidubce.com/v2`
- `minimax`: `https://api.minimax.io/v1`
- `stepfun`: `https://api.stepfun.ai/v1`
- `stepfun_plan`: `https://api.stepfun.ai/step_plan/v1`
- `stepfun_cn`: `https://api.stepfun.com/v1`
- `stepfun_cn_plan`: `https://api.stepfun.com/step_plan/v1`
- `moonshot`: `https://api.moonshot.cn/v1`
- `baichuan`: `https://api.baichuan-ai.com/v1`
- `lingyiwanwu`: `https://api.lingyiwanwu.com/v1`
- `tencent_hunyuan`: `https://api.hunyuan.cloud.tencent.com/v1`
- `modelscope`: `https://api-inference.modelscope.cn/v1`

如果某个厂商更新了域名或你有代理网关，选择 `custom_openai`，把完整 URL 粘贴到 Base URL 输入框里即可。系统会自动处理这些常见格式：

- `https://example.com/v1`
- `https://example.com/v1/models`
- `https://example.com/v1/chat/completions`
- `https://example.com/api/paas/v4/chat/completions`

识别成功后，控制台会把输入框改写成真正可保存的 Base URL，并给出推荐模型。

## 操作流程

1. 启动游戏和主播：运行 `STS2Streamer` 或 `launch_sts2_streamer.ps1`。
2. 打开控制台：访问 `http://127.0.0.1:19098/config`。
3. 选择主决策模型厂商，填入 API Key。
4. 点击“识别模型”，选择推荐模型或手动填模型名。
5. 配置 B 站房间号、TTS 声线和自动驾驶开关。
6. 点击“保存配置并热重载”。
7. 回到状态面板确认主模型或辅助模型显示为“启用”。

## 常见问题

- `Ollama` 识别不到模型：先启动 Ollama，并确保 `http://127.0.0.1:11434/api/tags` 能返回模型列表。
- OpenRouter / OpenAI 未启用：确认 API Key 已填，或者在系统环境变量中设置对应 Key。
- 保存后没变化：点击“只从文件重载”，或重启 `STS2Streamer`。
- 弹幕不工作：确认 `读取 B 站弹幕` 已开启，并填写真实 B 站直播房间号。
