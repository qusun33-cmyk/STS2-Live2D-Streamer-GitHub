from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any
from urllib import error, request


DEFAULT_PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "provider_type": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
    },
    "openrouter": {
        "provider_type": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "deepseek": {
        "provider_type": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "groq": {
        "provider_type": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
    },
    "siliconflow": {
        "provider_type": "openai",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
    },
    "dashscope": {
        "provider_type": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    "volcengine": {
        "provider_type": "openai",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key_env": "ARK_API_KEY",
    },
    "zhipu": {
        "provider_type": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "ZHIPU_API_KEY",
        "purpose": "chat",
    },
    "zhipu_coding_plan": {
        "provider_type": "openai",
        "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
        "api_key_env": "ZHIPU_API_KEY",
        "purpose": "coding_plan",
    },
    "baidu_qianfan": {
        "provider_type": "openai",
        "base_url": "https://qianfan.baidubce.com/v2",
        "api_key_env": "QIANFAN_API_KEY",
    },
    "minimax": {
        "provider_type": "openai",
        "base_url": "https://api.minimax.io/v1",
        "api_key_env": "MINIMAX_API_KEY",
    },
    "stepfun": {
        "provider_type": "openai",
        "base_url": "https://api.stepfun.ai/v1",
        "api_key_env": "STEPFUN_API_KEY",
        "purpose": "chat",
    },
    "stepfun_plan": {
        "provider_type": "openai",
        "base_url": "https://api.stepfun.ai/step_plan/v1",
        "api_key_env": "STEPFUN_API_KEY",
        "purpose": "coding_plan",
    },
    "stepfun_cn": {
        "provider_type": "openai",
        "base_url": "https://api.stepfun.com/v1",
        "api_key_env": "STEPFUN_API_KEY",
        "purpose": "chat",
    },
    "stepfun_cn_plan": {
        "provider_type": "openai",
        "base_url": "https://api.stepfun.com/step_plan/v1",
        "api_key_env": "STEPFUN_API_KEY",
        "purpose": "coding_plan",
    },
    "moonshot": {
        "provider_type": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_env": "MOONSHOT_API_KEY",
    },
    "baichuan": {
        "provider_type": "openai",
        "base_url": "https://api.baichuan-ai.com/v1",
        "api_key_env": "BAICHUAN_API_KEY",
    },
    "lingyiwanwu": {
        "provider_type": "openai",
        "base_url": "https://api.lingyiwanwu.com/v1",
        "api_key_env": "YI_API_KEY",
    },
    "tencent_hunyuan": {
        "provider_type": "openai",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "api_key_env": "HUNYUAN_API_KEY",
    },
    "modelscope": {
        "provider_type": "openai",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "api_key_env": "MODELSCOPE_API_KEY",
    },
    "together": {
        "provider_type": "openai",
        "base_url": "https://api.together.xyz/v1",
        "api_key_env": "TOGETHER_API_KEY",
    },
    "mistral": {
        "provider_type": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
    },
    "fireworks": {
        "provider_type": "openai",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "api_key_env": "FIREWORKS_API_KEY",
    },
    "xai": {
        "provider_type": "openai",
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
    },
    "github_models": {
        "provider_type": "openai",
        "base_url": "https://models.inference.ai.azure.com",
        "api_key_env": "GITHUB_TOKEN",
    },
    "azure_openai": {
        "provider_type": "openai",
        "base_url": "",
        "api_key_env": "AZURE_OPENAI_API_KEY",
    },
    "ollama": {
        "provider_type": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "api_key_env": "",
    },
    "custom_openai": {
        "provider_type": "openai",
        "base_url": "",
        "api_key_env": "",
    },
}


def normalize_model_sections(config: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(config)
    providers = _merge_provider_presets(normalized.get("providers"))
    normalized["providers"] = providers

    for section_name in ("required", "auxiliary"):
        section = normalized.get(section_name)
        if not isinstance(section, dict):
            continue
        normalized[section_name] = _resolve_profile_section(section_name, section, providers)

    return normalized


def _merge_provider_presets(raw_providers: Any) -> dict[str, dict[str, Any]]:
    merged = {name: deepcopy(value) for name, value in DEFAULT_PROVIDER_PRESETS.items()}
    if not isinstance(raw_providers, dict):
        return merged

    for name, value in raw_providers.items():
        if not isinstance(value, dict):
            continue
        merged[str(name)] = {**merged.get(str(name), {}), **value}
    return merged


def _resolve_profile_section(
    section_name: str,
    section: dict[str, Any],
    providers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    resolved = deepcopy(section)
    provider_name = str(resolved.get("provider", "")).strip()

    if provider_name:
        provider = deepcopy(providers.get(provider_name, {}))
        if provider:
            resolved["provider_name"] = provider_name
            resolved["provider_type"] = str(provider.get("provider_type", "openai"))
            resolved["base_url"] = str(
                resolved.get("base_url")
                or provider.get("base_url")
                or ""
            ).rstrip("/")
            resolved["api_key"] = str(
                resolved.get("api_key")
                or _env_value(provider.get("api_key_env"))
                or provider.get("api_key", "")
                or ""
            )

    base_url = str(resolved.get("base_url", "")).rstrip("/")
    provider_type = _detect_provider_type(str(resolved.get("provider_type", "")), base_url)
    resolved["provider_type"] = provider_type

    auto_detect = bool(resolved.get("auto_detect_model", False))
    requested_model = str(resolved.get("chat_model", "") or "").strip()
    if auto_detect or requested_model.lower() in {"", "auto", "auto:chat", "auto:tool"}:
        discovered_models = discover_models(
            provider_type=provider_type,
            base_url=base_url,
            api_key=str(resolved.get("api_key", "") or ""),
        )
        if discovered_models:
            resolved["detected_models"] = discovered_models
            resolved["chat_model"] = pick_preferred_model(
                discovered_models,
                purpose=str(resolved.get("model_purpose") or section_name),
                fallback=requested_model,
            )
    return resolved


def _env_value(name: str | None) -> str:
    if not name:
        return ""
    return os.getenv(name, "").strip()


def _detect_provider_type(explicit: str, base_url: str) -> str:
    explicit = (explicit or "").strip().lower()
    if explicit:
        return explicit
    if "11434" in base_url or base_url.endswith("/api") or "ollama" in base_url.lower():
        return "ollama"
    return "openai"


def discover_models(*, provider_type: str, base_url: str, api_key: str, timeout: float = 3.0) -> list[str]:
    if not base_url:
        return []
    if provider_type == "ollama":
        return _discover_ollama_models(_ollama_root_url(base_url), timeout=timeout)
    return _discover_openai_models(normalize_openai_base_url(base_url), api_key=api_key, timeout=timeout)


def discover_models_from_url(
    *,
    provider_type: str,
    url: str,
    api_key: str,
    timeout: float = 3.0,
) -> tuple[list[str], str]:
    if not url:
        return [], ""

    provider_type = _detect_provider_type(provider_type, url)
    normalized = _ollama_root_url(url) if provider_type == "ollama" else normalize_openai_base_url(url)
    candidates = _discovery_url_candidates(provider_type, normalized)
    seen: set[str] = set()

    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        models = discover_models(
            provider_type=provider_type,
            base_url=candidate,
            api_key=api_key,
            timeout=timeout,
        )
        if models:
            chat_base = _chat_base_url(provider_type, candidate)
            return models, chat_base
    return [], _chat_base_url(provider_type, normalized)


def _discover_openai_models(base_url: str, *, api_key: str, timeout: float) -> list[str]:
    endpoint = base_url.rstrip("/") + "/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = _fetch_json(endpoint, headers=headers, timeout=timeout)
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    models = [str(item.get("id", "")).strip() for item in data if isinstance(item, dict)]
    return [item for item in models if item]


def _discover_ollama_models(base_url: str, *, timeout: float) -> list[str]:
    endpoint = base_url.rstrip("/") + "/api/tags"
    payload = _fetch_json(endpoint, headers={"Accept": "application/json"}, timeout=timeout)
    if not isinstance(payload, dict):
        return []
    models = payload.get("models")
    if not isinstance(models, list):
        return []
    names = [str(item.get("name", "")).strip() for item in models if isinstance(item, dict)]
    return [item for item in names if item]


def _fetch_json(url: str, *, headers: dict[str, str], timeout: float) -> Any:
    req = request.Request(url=url, method="GET", headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def normalize_openai_base_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    if not value:
        return ""
    lowered = value.lower()
    for suffix in (
        "/chat/completions",
        "/completions",
        "/responses",
        "/models",
    ):
        if lowered.endswith(suffix):
            value = value[: -len(suffix)].rstrip("/")
            lowered = value.lower()
    return value


def _ollama_root_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    if value.lower().endswith("/v1"):
        return value[:-3].rstrip("/")
    return normalize_openai_base_url(value)


def _chat_base_url(provider_type: str, url: str) -> str:
    value = (url or "").strip().rstrip("/")
    if provider_type == "ollama" and value and not value.lower().endswith("/v1"):
        return value + "/v1"
    return value


def _discovery_url_candidates(provider_type: str, base_url: str) -> list[str]:
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        return []
    if provider_type == "ollama":
        return [_ollama_root_url(base_url)]

    candidates = [normalize_openai_base_url(base_url)]
    lowered = base_url.lower()
    if not any(lowered.endswith(suffix) for suffix in ("/v1", "/v2", "/v3", "/v4")):
        candidates.append(base_url.rstrip("/") + "/v1")
        candidates.append(base_url.rstrip("/") + "/v2")
    return candidates


def pick_preferred_model(models: list[str], *, purpose: str, fallback: str = "") -> str:
    if not models:
        return fallback if fallback.lower() not in {"", "auto", "auto:chat", "auto:tool"} else ""

    normalized_purpose = (purpose or "required").lower()
    scored = sorted(
        ((score_model(model, normalized_purpose), model) for model in models),
        reverse=True,
    )
    return scored[0][1]


def score_model(model_name: str, purpose: str) -> int:
    name = model_name.lower()
    score = 0

    if any(token in name for token in ("embedding", "tts", "audio", "image", "rerank", "moderation")):
        score -= 100

    if purpose in {"coding", "code", "plan", "coding_plan", "agent", "tool"}:
        for token, value in (
            ("glm-4.7", 130),
            ("glm-5", 125),
            ("step-3.5-flash-2603", 124),
            ("step-3.5-flash", 118),
            ("qwen3-coder", 128),
            ("qwen-coder", 112),
            ("deepseek-reasoner", 122),
            ("deepseek-chat", 108),
            ("kimi-k2", 116),
            ("moonshot", 98),
            ("minimax-m2.5", 118),
            ("minimax-m2.1", 112),
            ("minimax-m2", 106),
            ("ernie-code", 118),
            ("hunyuan-code", 110),
            ("coder", 88),
            ("code", 70),
        ):
            if token in name:
                score += value
        if any(token in name for token in ("embedding", "image", "tts", "audio", "rerank")):
            score -= 100
        if any(token in name for token in ("flash", "turbo", "highspeed")):
            score += 8
    elif purpose in {"required", "chat", "primary"}:
        for token, value in (
            ("gpt-5", 120),
            ("gpt-4.1", 110),
            ("gpt-4o", 105),
            ("claude-3.7", 108),
            ("claude-sonnet", 100),
            ("gemini-2.5-pro", 110),
            ("gemini-2.5-flash", 92),
            ("glm-5", 108),
            ("glm-4.7", 104),
            ("kimi-k2", 102),
            ("moonshot", 92),
            ("qwen-max", 96),
            ("qwen-plus", 92),
            ("deepseek-reasoner", 104),
            ("deepseek-chat", 90),
            ("ernie-4.5", 94),
            ("ernie-4", 90),
            ("minimax-m2.5", 98),
            ("step-3.5", 94),
            ("llama-3.3-70b", 88),
            ("mixtral-large", 85),
        ):
            if token in name:
                score += value
        if any(token in name for token in ("mini", "flash-lite", "haiku", "small", "8b", "1b")):
            score -= 20
    else:
        for token, value in (
            ("gpt-4o-mini", 110),
            ("gpt-4.1-mini", 108),
            ("gpt-5-mini", 108),
            ("haiku", 102),
            ("flash", 98),
            ("turbo", 96),
            ("instant", 94),
            ("small", 90),
            ("8b", 88),
            ("qwen-plus", 92),
            ("qwen-turbo", 96),
            ("deepseek-chat", 94),
            ("llama-3.1-8b", 90),
        ):
            if token in name:
                score += value
        if any(token in name for token in ("70b", "pro", "reasoner", "sonnet")):
            score -= 8

    score += max(0, 20 - len(name) // 8)
    return score
