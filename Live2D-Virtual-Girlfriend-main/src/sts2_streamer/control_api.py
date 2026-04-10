from __future__ import annotations

import logging
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

import toml
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import config.config as config_module
from config import Global
from config.provider_profiles import (
    DEFAULT_PROVIDER_PRESETS,
    discover_models_from_url,
    normalize_model_sections,
    pick_preferred_model,
)

from .config import PROJECT_ROOT, load_streamer_settings
from .runtime import StreamerRuntime
from .speaker import PersonaSpeaker


class SpeakRequest(BaseModel):
    text: str
    expression: str | None = None


class LlmSectionRequest(BaseModel):
    provider: str = ""
    provider_type: str = ""
    base_url: str = ""
    api_key: str = ""
    chat_model: str = "auto"
    auto_detect_model: bool = True
    model_purpose: str = ""


class StreamerConfigRequest(BaseModel):
    auto_play: bool = True
    auto_commentary: bool = True
    bilibili_enabled: bool = False
    bilibili_room_id: int | None = None
    bilibili_reply_probability: float = 0.35
    bilibili_max_queue: int = 20
    tts_backend: str = "edge"
    default_voice: str = "zh-CN-XiaoxiaoNeural"
    speech_rate: int = 1
    speech_volume: int = 100
    action_cooldown_seconds: float = 1.0
    commentary_cooldown_seconds: float = 4.0
    room_reply_cooldown_seconds: float = 12.0
    llm_enabled: bool = True
    llm_use_for_actions: bool = True
    llm_use_for_commentary: bool = True
    llm_use_for_danmaku: bool = True
    llm_use_for_action_commentary: bool = True
    llm_use_for_action_followup: bool = True


class DashboardConfigRequest(BaseModel):
    required: LlmSectionRequest
    auxiliary: LlmSectionRequest
    sts2_streamer: StreamerConfigRequest


class DiscoverModelsRequest(BaseModel):
    provider: str = ""
    provider_type: str = ""
    base_url: str = ""
    api_key: str = ""
    purpose: str = "required"


class ControlApiServer:
    def __init__(self, runtime: StreamerRuntime, speaker: PersonaSpeaker, host: str, port: int) -> None:
        self.runtime = runtime
        self.speaker = speaker
        self.host = host
        self.port = port
        self.app = FastAPI(title="STS2 Live2D Streamer Control")
        self._install_routes()

    def _install_routes(self) -> None:
        @self.app.get("/", response_class=HTMLResponse)
        def root():
            return self._dashboard_html()

        @self.app.get("/config", response_class=HTMLResponse)
        def config_page():
            return self._dashboard_html()

        @self.app.get("/health")
        def health():
            return {"ok": True, "runtime": self.runtime.status()}

        @self.app.get("/status")
        def status():
            return {"ok": True, "runtime": self.runtime.status()}

        @self.app.get("/api/config")
        def get_config():
            return {"ok": True, "config": self._public_config(), "runtime": self.runtime.status()}

        @self.app.post("/api/config")
        def save_config(request: DashboardConfigRequest):
            data = self._read_config()
            data["required"] = self._merge_llm_section(data.get("required"), request.required)
            data["auxiliary"] = self._merge_llm_section(data.get("auxiliary"), request.auxiliary)
            streamer = dict(data.get("sts2_streamer") or {})
            streamer.update(self._model_to_dict(request.sts2_streamer))
            if not streamer.get("bilibili_room_id"):
                streamer["bilibili_room_id"] = 0
            data["sts2_streamer"] = streamer

            self._write_config(data)
            self._reload_global_config(data)
            self.runtime.reload_settings(load_streamer_settings())
            return {"ok": True, "config": self._public_config(), "runtime": self.runtime.status()}

        @self.app.post("/api/config/reload")
        def reload_config():
            data = self._read_config()
            self._reload_global_config(data)
            self.runtime.reload_settings(load_streamer_settings())
            return {"ok": True, "config": self._public_config(), "runtime": self.runtime.status()}

        @self.app.post("/api/config/discover-models")
        def discover(request: DiscoverModelsRequest):
            provider = self._provider_preset(request.provider)
            provider_type = (request.provider_type or provider.get("provider_type") or "openai").strip().lower()
            base_url = (request.base_url or provider.get("base_url") or "").strip().rstrip("/")
            api_key = (request.api_key or self._provider_api_key(provider) or "").strip()
            models, normalized_base_url = discover_models_from_url(
                provider_type=provider_type,
                url=base_url,
                api_key=api_key or ("ollama" if provider_type == "ollama" else ""),
                timeout=5.0,
            )
            return {
                "ok": True,
                "models": models,
                "suggested_model": pick_preferred_model(models, purpose=request.purpose or "required"),
                "normalized_base_url": normalized_base_url,
            }

        @self.app.post("/pause")
        def pause():
            self.runtime.pause()
            return {"ok": True, "paused": True}

        @self.app.post("/resume")
        def resume():
            self.runtime.resume()
            return {"ok": True, "paused": False}

        @self.app.post("/speak")
        def speak(request: SpeakRequest):
            text = (request.text or "").strip()
            if not text:
                raise HTTPException(status_code=400, detail="text is required")
            self.speaker.say(text, request.expression)
            return {"ok": True}

    def start(self) -> None:
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self) -> None:
        logging.getLogger("uvicorn").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="error")
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        try:
            server.run()
        except Exception as exc:  # pragma: no cover - runtime logging
            print(f"[sts2_streamer] control api failed: {exc}")

    def _config_path(self) -> Path:
        env_path = os.getenv("LIVE2D_CONFIG_PATH", "").strip()
        return Path(env_path or PROJECT_ROOT / "config.sts2_streamer.toml").resolve()

    def _read_config(self) -> dict[str, Any]:
        path = self._config_path()
        if not path.exists():
            raise HTTPException(status_code=500, detail=f"config file not found: {path}")
        return toml.loads(path.read_text(encoding="utf-8-sig"))

    def _write_config(self, data: dict[str, Any]) -> None:
        path = self._config_path()
        path.write_text(toml.dumps(data), encoding="utf-8")

    def _reload_global_config(self, data: dict[str, Any]) -> None:
        normalized = normalize_model_sections(deepcopy(data))
        config_module.config = normalized
        for key, value in normalized.items():
            if key == "character_toml":
                continue
            setattr(Global, key, value)

    def _public_config(self) -> dict[str, Any]:
        data = self._read_config()
        return {
            "path": str(self._config_path()),
            "providers": DEFAULT_PROVIDER_PRESETS,
            "required": self._public_llm_section(data.get("required")),
            "auxiliary": self._public_llm_section(data.get("auxiliary")),
            "sts2_streamer": dict(data.get("sts2_streamer") or {}),
        }

    def _public_llm_section(self, raw_section: Any) -> dict[str, Any]:
        section = dict(raw_section or {})
        provider = self._provider_preset(str(section.get("provider") or section.get("provider_name") or ""))
        api_key = str(section.get("api_key") or self._provider_api_key(provider) or "")
        return {
            "provider": section.get("provider") or section.get("provider_name") or "",
            "provider_type": section.get("provider_type") or provider.get("provider_type") or "openai",
            "base_url": section.get("base_url") or provider.get("base_url") or "",
            "chat_model": section.get("chat_model") or "auto",
            "auto_detect_model": bool(section.get("auto_detect_model", True)),
            "model_purpose": section.get("model_purpose") or "",
            "api_key_set": bool(api_key),
        }

    def _merge_llm_section(self, raw_section: Any, request: LlmSectionRequest) -> dict[str, Any]:
        section = dict(raw_section or {})
        section["provider"] = request.provider.strip()
        section["provider_type"] = request.provider_type.strip() or "openai"
        section["base_url"] = request.base_url.strip()
        section["chat_model"] = request.chat_model.strip() or "auto"
        section["auto_detect_model"] = bool(request.auto_detect_model)
        section["model_purpose"] = request.model_purpose.strip() or section.get("model_purpose") or ""
        if request.api_key.strip():
            section["api_key"] = request.api_key.strip()
        return section

    def _provider_preset(self, provider_name: str) -> dict[str, Any]:
        name = str(provider_name or "").strip()
        config_providers = getattr(Global, "providers", {}) or {}
        return dict(config_providers.get(name) or DEFAULT_PROVIDER_PRESETS.get(name) or {})

    @staticmethod
    def _provider_api_key(provider: dict[str, Any]) -> str:
        env_name = str(provider.get("api_key_env") or "").strip()
        env_value = os.getenv(env_name, "").strip() if env_name else ""
        return env_value or str(provider.get("api_key") or "").strip()

    @staticmethod
    def _model_to_dict(model: BaseModel) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()

    @staticmethod
    def _dashboard_html() -> str:
        return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>STS2 虚拟女友直播控制台</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17202a;
      --muted: #697386;
      --line: #d9e2ec;
      --panel: rgba(255, 255, 255, 0.88);
      --blue: #1769ff;
      --green: #14a46c;
      --amber: #b66a00;
      --bg1: #eef7ff;
      --bg2: #fff2df;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font-family: "HarmonyOS Sans SC", "Microsoft YaHei UI", "Noto Sans CJK SC", sans-serif;
      background:
        radial-gradient(circle at 12% 8%, rgba(255, 197, 109, .55), transparent 30%),
        radial-gradient(circle at 88% 16%, rgba(91, 154, 255, .35), transparent 28%),
        linear-gradient(135deg, var(--bg1), var(--bg2));
    }
    header { padding: 34px clamp(20px, 4vw, 56px) 18px; }
    h1 { margin: 0; font-size: clamp(28px, 4vw, 52px); letter-spacing: -0.04em; }
    .subtitle { margin-top: 10px; color: var(--muted); max-width: 900px; line-height: 1.7; }
    main { padding: 0 clamp(20px, 4vw, 56px) 48px; display: grid; gap: 18px; }
    .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 18px; align-items: start; }
    .card {
      background: var(--panel);
      border: 1px solid rgba(255,255,255,.8);
      box-shadow: 0 24px 80px rgba(31, 49, 82, .12);
      border-radius: 28px;
      padding: 22px;
      backdrop-filter: blur(12px);
    }
    .span-4 { grid-column: span 4; }
    .span-6 { grid-column: span 6; }
    .span-8 { grid-column: span 8; }
    .span-12 { grid-column: span 12; }
    h2 { margin: 0 0 14px; font-size: 20px; }
    h3 { margin: 18px 0 10px; font-size: 16px; }
    label { display: block; margin: 12px 0 6px; color: #344055; font-size: 13px; font-weight: 700; }
    input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 11px 12px;
      background: rgba(255,255,255,.92);
      color: var(--ink);
      font-size: 14px;
      outline: none;
    }
    input:focus, select:focus { border-color: var(--blue); box-shadow: 0 0 0 4px rgba(23,105,255,.12); }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .checks { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 10px 14px; }
    .check { display: flex; align-items: center; gap: 8px; font-weight: 600; color: #344055; }
    .check input { width: auto; }
    button {
      border: 0;
      border-radius: 999px;
      padding: 12px 18px;
      font-weight: 800;
      color: white;
      background: var(--blue);
      cursor: pointer;
      box-shadow: 0 10px 28px rgba(23,105,255,.28);
    }
    button.secondary { background: #22304a; box-shadow: none; }
    button.ghost { background: white; color: var(--ink); border: 1px solid var(--line); box-shadow: none; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
    .pill { display: inline-flex; align-items: center; gap: 8px; border-radius: 999px; padding: 8px 11px; background: #fff; color: #344055; font-size: 13px; border: 1px solid var(--line); }
    .ok { color: var(--green); font-weight: 900; }
    .warn { color: var(--amber); font-weight: 900; }
    pre { margin: 0; white-space: pre-wrap; word-break: break-word; color: #263244; line-height: 1.55; }
    .guide { line-height: 1.8; color: #344055; }
    .guide b { color: var(--ink); }
    .notice { padding: 12px 14px; border-radius: 18px; background: rgba(255,255,255,.72); border: 1px dashed var(--line); color: var(--muted); }
    @media (max-width: 900px) { .span-4, .span-6, .span-8 { grid-column: span 12; } .row, .checks { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>STS2 虚拟女友直播控制台</h1>
    <div class="subtitle">配置模型、B 站弹幕、TTS 声线和自动驾驶；保存后会热重载到当前主播运行时。</div>
  </header>
  <main>
    <section class="grid">
      <div class="card span-4">
        <h2>运行状态</h2>
        <div id="statusPills"></div>
        <div class="actions">
          <button class="ghost" onclick="refresh()">刷新状态</button>
          <button class="secondary" onclick="postSimple('/pause')">暂停自动玩</button>
          <button onclick="postSimple('/resume')">恢复自动玩</button>
        </div>
      </div>

      <div class="card span-8">
        <h2>使用引导</h2>
        <div class="guide">
          <p><b>1.</b> 先在“主决策模型”里选择远端强模型厂商，比如 DeepSeek、通义千问、豆包、智谱、千帆、MiniMax、阶跃、Moonshot 或自定义 OpenAI-compatible。</p>
          <p><b>2.</b> 填 API Key 和 Base URL，点“识别模型”。如果你粘贴的是完整的 <code>/chat/completions</code> 或 <code>/models</code> 地址，系统会自动归一化成可调用的 Base URL。</p>
          <p><b>3.</b> B 站弹幕填房间号并开启；TTS 可选择 Edge 神经语音，默认 `zh-CN-XiaoxiaoNeural`。</p>
          <p><b>4.</b> 保存后不需要重启，主播会立即用新 LLM 配置；如果模型不可用，系统会安全回退启发式自动驾驶。</p>
        </div>
      </div>
    </section>

    <section class="grid">
      <div class="card span-6" id="requiredBox">
        <h2>主决策模型</h2>
        <div class="notice">用于出牌/选路/奖励决策，建议使用更强的模型。</div>
        <div data-section="required"></div>
      </div>
      <div class="card span-6" id="auxiliaryBox">
        <h2>辅助/解说模型</h2>
        <div class="notice">用于动作解说、复盘和弹幕回复，建议用便宜或本地模型。</div>
        <div data-section="auxiliary"></div>
      </div>
    </section>

    <section class="grid">
      <div class="card span-6">
        <h2>直播与弹幕</h2>
        <div class="checks">
          <label class="check"><input id="auto_play" type="checkbox"> 自动玩游戏</label>
          <label class="check"><input id="auto_commentary" type="checkbox"> 自动口播</label>
          <label class="check"><input id="bilibili_enabled" type="checkbox"> 读取 B 站弹幕</label>
          <label class="check"><input id="llm_enabled" type="checkbox"> 启用 LLM</label>
          <label class="check"><input id="llm_use_for_actions" type="checkbox"> LLM 参与决策</label>
          <label class="check"><input id="llm_use_for_commentary" type="checkbox"> LLM 参与解说</label>
          <label class="check"><input id="llm_use_for_danmaku" type="checkbox"> LLM 回复弹幕</label>
          <label class="check"><input id="llm_use_for_action_followup" type="checkbox"> 动作后复盘</label>
        </div>
        <div class="row">
          <div><label>B 站房间号</label><input id="bilibili_room_id" placeholder="例如 123456"></div>
          <div><label>弹幕回复概率 0-1</label><input id="bilibili_reply_probability" type="number" min="0" max="1" step="0.05"></div>
          <div><label>动作冷却秒</label><input id="action_cooldown_seconds" type="number" min="0.2" step="0.1"></div>
          <div><label>口播冷却秒</label><input id="commentary_cooldown_seconds" type="number" min="0" step="0.5"></div>
        </div>
      </div>

      <div class="card span-6">
        <h2>TTS 声音</h2>
        <div class="row">
          <div><label>TTS 后端</label><select id="tts_backend"><option>edge</option><option>auto</option><option>sapi</option></select></div>
          <div><label>默认声线</label><input id="default_voice" placeholder="zh-CN-XiaoxiaoNeural"></div>
          <div><label>语速</label><input id="speech_rate" type="number" min="-5" max="10" step="1"></div>
          <div><label>音量</label><input id="speech_volume" type="number" min="0" max="100" step="1"></div>
        </div>
        <div class="actions">
          <button class="ghost" onclick="testSpeak()">试听一句</button>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>保存与日志</h2>
      <div class="actions">
        <button onclick="saveConfig()">保存配置并热重载</button>
        <button class="ghost" onclick="reloadConfig()">只从文件重载</button>
      </div>
      <pre id="log">正在加载配置...</pre>
    </section>
  </main>

  <script>
    let cfg = null;
    const providers = {};
    const sectionFields = ["provider","provider_type","base_url","api_key","chat_model","auto_detect_model","model_purpose"];

    function providerOptions(selected) {
      return Object.keys(providers).map(name => `<option value="${name}" ${name===selected?'selected':''}>${name}</option>`).join("");
    }

    function renderSection(name, data) {
      const root = document.querySelector(`[data-section="${name}"]`);
      root.innerHTML = `
        <label>厂商</label><select id="${name}_provider">${providerOptions(data.provider || "")}</select>
        <div class="row">
          <div><label>协议类型</label><select id="${name}_provider_type"><option value="openai">openai</option><option value="ollama">ollama</option></select></div>
          <div><label>模型</label><input id="${name}_chat_model" list="${name}_models" placeholder="auto 或模型名"><datalist id="${name}_models"></datalist></div>
        </div>
        <label>Base URL / 完整调用 URL</label><input id="${name}_base_url" placeholder="https://.../v1 或 https://.../v1/chat/completions">
        <label>API Key <span class="pill">${data.api_key_set ? '已保存，可留空不改' : '未配置'}</span></label><input id="${name}_api_key" type="password" placeholder="留空表示不修改已保存 Key">
        <div class="row">
          <label class="check"><input id="${name}_auto_detect_model" type="checkbox"> 自动识别模型</label>
          <div><label>用途</label><select id="${name}_model_purpose"><option value="required">主决策</option><option value="auxiliary">解说/弹幕</option><option value="coding">Coding</option><option value="plan">Plan</option><option value="coding_plan">Coding Plan</option><option value="agent">Agent</option></select></div>
        </div>
        <div class="actions"><button class="ghost" onclick="discoverModels('${name}')">识别模型</button></div>
      `;
      setVal(`${name}_provider`, data.provider || "custom_openai");
      setVal(`${name}_provider_type`, data.provider_type || "openai");
      setVal(`${name}_base_url`, data.base_url || "");
      setVal(`${name}_chat_model`, data.chat_model || "auto");
      setVal(`${name}_auto_detect_model`, !!data.auto_detect_model);
      setVal(`${name}_model_purpose`, data.model_purpose || name);
      document.getElementById(`${name}_provider`).addEventListener("change", () => applyProviderPreset(name));
    }

    function applyProviderPreset(name) {
      const provider = document.getElementById(`${name}_provider`).value;
      const preset = providers[provider] || {};
      setVal(`${name}_provider_type`, preset.provider_type || "openai");
      setVal(`${name}_base_url`, preset.base_url || "");
      setVal(`${name}_chat_model`, "auto");
    }

    function setVal(id, value) {
      const el = document.getElementById(id);
      if (!el) return;
      if (el.type === "checkbox") el.checked = !!value;
      else el.value = value ?? "";
    }

    function getVal(id) {
      const el = document.getElementById(id);
      if (!el) return "";
      if (el.type === "checkbox") return el.checked;
      return el.value;
    }

    function readSection(name) {
      return {
        provider: getVal(`${name}_provider`),
        provider_type: getVal(`${name}_provider_type`),
        base_url: getVal(`${name}_base_url`),
        api_key: getVal(`${name}_api_key`),
        chat_model: getVal(`${name}_chat_model`) || "auto",
        auto_detect_model: getVal(`${name}_auto_detect_model`),
        model_purpose: getVal(`${name}_model_purpose`) || name,
      };
    }

    function readStreamer() {
      return {
        auto_play: getVal("auto_play"),
        auto_commentary: getVal("auto_commentary"),
        bilibili_enabled: getVal("bilibili_enabled"),
        bilibili_room_id: Number(getVal("bilibili_room_id") || 0),
        bilibili_reply_probability: Number(getVal("bilibili_reply_probability") || 0.35),
        bilibili_max_queue: 20,
        tts_backend: getVal("tts_backend") || "edge",
        default_voice: getVal("default_voice") || "zh-CN-XiaoxiaoNeural",
        speech_rate: Number(getVal("speech_rate") || 1),
        speech_volume: Number(getVal("speech_volume") || 100),
        action_cooldown_seconds: Number(getVal("action_cooldown_seconds") || 1),
        commentary_cooldown_seconds: Number(getVal("commentary_cooldown_seconds") || 4),
        room_reply_cooldown_seconds: 12,
        llm_enabled: getVal("llm_enabled"),
        llm_use_for_actions: getVal("llm_use_for_actions"),
        llm_use_for_commentary: getVal("llm_use_for_commentary"),
        llm_use_for_danmaku: getVal("llm_use_for_danmaku"),
        llm_use_for_action_commentary: true,
        llm_use_for_action_followup: getVal("llm_use_for_action_followup"),
      };
    }

    async function refresh() {
      const res = await fetch("/api/config");
      const payload = await res.json();
      cfg = payload.config;
      Object.assign(providers, cfg.providers || {});
      renderSection("required", cfg.required || {});
      renderSection("auxiliary", cfg.auxiliary || {});
      const s = cfg.sts2_streamer || {};
      ["auto_play","auto_commentary","bilibili_enabled","llm_enabled","llm_use_for_actions","llm_use_for_commentary","llm_use_for_danmaku","llm_use_for_action_followup"].forEach(k => setVal(k, !!s[k]));
      ["bilibili_room_id","bilibili_reply_probability","action_cooldown_seconds","commentary_cooldown_seconds","tts_backend","default_voice","speech_rate","speech_volume"].forEach(k => setVal(k, s[k]));
      renderStatus(payload.runtime);
      log(`已加载配置：${cfg.path}`);
    }

    function renderStatus(runtime) {
      const llm = runtime.llm || {};
      const required = llm.required || {};
      const auxiliary = llm.auxiliary || {};
      document.getElementById("statusPills").innerHTML = `
        <div class="pill">游戏 API：<span class="${runtime.health?.status === 'ready' ? 'ok' : 'warn'}">${runtime.health?.status || 'unknown'}</span></div>
        <div class="pill">画面：${runtime.screen || '-'}</div>
        <div class="pill">Run：${runtime.run_id || '-'}</div>
        <div class="pill">主模型：<span class="${required.enabled ? 'ok' : 'warn'}">${required.enabled ? required.model : '未启用'}</span></div>
        <div class="pill">辅助模型：<span class="${auxiliary.enabled ? 'ok' : 'warn'}">${auxiliary.enabled ? auxiliary.model : '未启用'}</span></div>
      `;
    }

    async function saveConfig() {
      const body = { required: readSection("required"), auxiliary: readSection("auxiliary"), sts2_streamer: readStreamer() };
      const res = await fetch("/api/config", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body) });
      const payload = await res.json();
      if (!payload.ok) throw new Error(JSON.stringify(payload));
      renderStatus(payload.runtime);
      log("保存成功，已热重载。");
    }

    async function reloadConfig() {
      const res = await fetch("/api/config/reload", { method: "POST" });
      const payload = await res.json();
      renderStatus(payload.runtime);
      log("已从文件重载。");
    }

    async function discoverModels(name) {
      const req = readSection(name);
      req.purpose = req.model_purpose || name;
      const res = await fetch("/api/config/discover-models", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(req) });
      const payload = await res.json();
      const list = document.getElementById(`${name}_models`);
      list.innerHTML = (payload.models || []).map(m => `<option value="${m}"></option>`).join("");
      if (payload.suggested_model) setVal(`${name}_chat_model`, payload.suggested_model);
      if (payload.normalized_base_url) setVal(`${name}_base_url`, payload.normalized_base_url);
      log(`${name} 识别到 ${payload.models?.length || 0} 个模型。${payload.suggested_model ? '推荐：' + payload.suggested_model : ''}${payload.normalized_base_url ? '\\nBase URL：' + payload.normalized_base_url : ''}`);
    }

    async function postSimple(path) {
      const res = await fetch(path, { method: "POST" });
      const payload = await res.json();
      log(JSON.stringify(payload, null, 2));
      refresh();
    }

    async function testSpeak() {
      const res = await fetch("/speak", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({ text: "这是虚拟女友直播控制台的声音测试。" }) });
      log(JSON.stringify(await res.json(), null, 2));
    }

    function log(text) { document.getElementById("log").textContent = text; }
    refresh().catch(err => log("加载失败：" + err.message));
  </script>
</body>
</html>"""
