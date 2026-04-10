# 多厂商模型配置说明

当前项目已经支持两层能力：

- 直接可用：所有 OpenAI-compatible 服务，以及 Ollama
- 需要额外适配：原生 Anthropic、原生 Gemini 这类不走 OpenAI SDK 协议的厂商

这意味着：

- 如果厂商提供 OpenAI-compatible `base_url`，现在就可以直接接入
- 如果厂商没有兼容接口，需要再加一层统一客户端或适配器

## 当前已经内置的 provider 预设

- `openai`
- `openrouter`
- `deepseek`
- `groq`
- `siliconflow`
- `dashscope`
- `volcengine`
- `together`
- `mistral`
- `fireworks`
- `xai`
- `github_models`
- `azure_openai`
- `ollama`
- `custom_openai`

## 用法

1. 在 `required` / `auxiliary` 中指定 `provider`
2. 设置 `chat_model = "auto"`
3. 打开 `auto_detect_model = true`
4. 在 `providers.<name>` 中填写 `api_key` 或 `base_url`

## 示例

```toml
["required"]
provider = "openrouter"
chat_model = "auto"
auto_detect_model = true
model_purpose = "required"

["auxiliary"]
provider = "ollama"
chat_model = "auto"
auto_detect_model = true
model_purpose = "auxiliary"

["providers.openrouter"]
api_key = "你的 OpenRouter Key"

["providers.ollama"]
base_url = "http://127.0.0.1:11434"
```

## 自动识别逻辑

- `provider_type = "openai"` 时，请求 `<base_url>/models`
- `provider_type = "ollama"` 时，请求 `<base_url>/api/tags`
- `required` 会优先挑更强的主聊天模型
- `auxiliary` 会优先挑更轻、更快、更便宜的小模型

## 接任意新厂商

如果某个新厂商没内置在预设里，但它兼容 OpenAI SDK，可以直接这样加：

```toml
["required"]
provider = "my_vendor"
chat_model = "auto"
auto_detect_model = true
model_purpose = "required"

["providers.my_vendor"]
provider_type = "openai"
base_url = "https://your-openai-compatible-endpoint/v1"
api_key = "你的 Key"
```

不需要再改 Python 代码，配置层会自动：

- 补全 `base_url`
- 读取 `api_key`
- 调用模型列表接口
- 自动选一个合适的 `chat_model`

## 当前边界

- 业务调用层仍然是 `openai.OpenAI(...)`
- 所以“多厂商”当前等价于“多 OpenAI-compatible 厂商 + Ollama”
- 如果要覆盖原生 Anthropic / Gemini / 其它非兼容协议，需要把 `main.py` 和 `src/graph_rag.py` 抽成统一 LLM 客户端层，或者接入 LiteLLM 一类的适配层
