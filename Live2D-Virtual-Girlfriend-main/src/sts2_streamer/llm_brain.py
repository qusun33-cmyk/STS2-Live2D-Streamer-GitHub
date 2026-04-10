from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from config import Global
from config.provider_profiles import DEFAULT_PROVIDER_PRESETS, discover_models, pick_preferred_model

from .config import StreamerSettings
from .pilot import PilotDecision
from .sts2_client import Sts2Action

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


OPTION_INDEX_ACTIONS = {
    "choose_map_node",
    "choose_reward_card",
    "claim_reward",
    "choose_treasure_relic",
    "choose_event_option",
    "choose_rest_option",
    "select_deck_card",
    "select_character",
    "choose_timeline_epoch",
    "discard_potion",
    "use_potion",
    "open_character_select",
}

AUTO_PROVIDER_ORDER = (
    "openai",
    "openrouter",
    "deepseek",
    "groq",
    "siliconflow",
    "dashscope",
    "volcengine",
    "zhipu",
    "zhipu_coding_plan",
    "baidu_qianfan",
    "minimax",
    "stepfun",
    "stepfun_plan",
    "stepfun_cn",
    "stepfun_cn_plan",
    "moonshot",
    "baichuan",
    "lingyiwanwu",
    "tencent_hunyuan",
    "modelscope",
    "together",
    "mistral",
    "fireworks",
    "xai",
    "github_models",
    "azure_openai",
    "ollama",
)


@dataclass(slots=True)
class ChatBackend:
    section_name: str
    provider_name: str
    provider_type: str
    base_url: str
    api_key: str
    model: str
    client: Any = None
    auto_selected: bool = False
    detected_models: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.client is not None and bool(self.model)


class StreamerLlmBrain:
    def __init__(self, settings: StreamerSettings) -> None:
        self.settings = settings
        self.persona_name = str(Global.character.get("name") or "虚拟女友")
        self.user_name = str(getattr(Global, "user_name", "主播") or "主播")
        exp_params = getattr(Global, "exp_params", None) or {}
        self.valid_expressions = sorted(set(exp_params.keys()) | {"闂棯", "鐢熸皵", "姝ｅ父"})
        self.providers = getattr(Global, "providers", {}) or {}
        self.backends = {
            "required": self._build_backend("required"),
            "auxiliary": self._build_backend("auxiliary"),
        }

    def status(self) -> dict[str, Any]:
        return {
            name: {
                "enabled": backend.enabled,
                "provider_name": backend.provider_name,
                "provider_type": backend.provider_type,
                "model": backend.model,
                "base_url": backend.base_url,
                "auto_selected": backend.auto_selected,
                "detected_models": backend.detected_models[:8],
            }
            for name, backend in self.backends.items()
        }

    def decide_action(self, state: dict[str, Any]) -> PilotDecision | None:
        if not (self.settings.llm_enabled and self.settings.llm_use_for_actions):
            return None

        backend = self._pick_backend(self.settings.llm_action_section)
        if backend is None:
            return None

        prompt = {
            "screen": state.get("screen"),
            "available_actions": state.get("available_actions") or [],
            "state": self._build_action_snapshot(state),
        }
        system_prompt = (
            f"你现在扮演 {self.persona_name}，正在直播《杀戮尖塔2》。"
            "你必须严格从 available_actions 里选择一个合法动作。"
            "优先保证动作安全、稳定、合法，其次再追求强度。"
            "只输出 JSON，不要解释。格式为 "
            '{"action":"...", "card_index":null, "target_index":null, "option_index":null, '
            '"commentary":"一句不超过28字的简短口播", "expression":"表情名或空字符串"}'
        )
        text = self._chat_json(
            backend,
            system_prompt=system_prompt,
            user_payload=prompt,
            temperature=0.15,
            max_tokens=220,
        )
        if text is None:
            return None

        payload = self._extract_json_object(text)
        if not isinstance(payload, dict):
            return None

        action = self._parse_action_payload(payload, state)
        if action is None:
            return None

        commentary = self._clean_text(payload.get("commentary"), 28)
        expression = self._pick_expression(payload.get("expression"))
        return PilotDecision(action=action, speech=commentary or None, exp=expression)

    def build_event_commentary(
        self,
        *,
        event_name: str,
        data: dict[str, Any],
        state: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        if not (self.settings.llm_enabled and self.settings.llm_use_for_commentary):
            return None, None

        backend = self._pick_backend(self.settings.llm_commentary_section)
        if backend is None:
            return None, None

        prompt = {
            "event": event_name,
            "event_data": data,
            "state": self._build_commentary_snapshot(state),
        }
        system_prompt = (
            f"你是 {self.persona_name}，正在直播《杀戮尖塔2》。"
            "请根据当前事件给出一句适合口播的中文解说，长度不超过26字。"
            "如果这个事件不值得说话，就返回空 commentary。"
            "只输出 JSON，格式为 "
            '{"commentary":"...", "expression":"表情名或空字符串"}'
        )
        text = self._chat_json(
            backend,
            system_prompt=system_prompt,
            user_payload=prompt,
            temperature=0.55,
            max_tokens=120,
        )
        if text is None:
            return None, None

        payload = self._extract_json_object(text)
        if not isinstance(payload, dict):
            return None, None

        commentary = self._clean_text(payload.get("commentary"), 26)
        expression = self._pick_expression(payload.get("expression"))
        return commentary or None, expression

    def build_action_commentary(
        self,
        *,
        state: dict[str, Any],
        decision: PilotDecision,
        source: str,
    ) -> tuple[str | None, str | None]:
        if not (
            self.settings.llm_enabled
            and self.settings.llm_use_for_commentary
            and self.settings.llm_use_for_action_commentary
        ):
            return None, None

        backend = self._pick_backend(self.settings.llm_commentary_section)
        if backend is None or decision.action is None:
            return None, None

        prompt = {
            "decision_source": source,
            "state": self._build_commentary_snapshot(state),
            "planned_action": self._serialize_action(decision.action),
            "fallback_commentary": decision.speech,
        }
        system_prompt = (
            f"你是 {self.persona_name}，正在直播《杀戮尖塔2》。"
            "马上要执行一个已经确定的动作。"
            "请用一句自然、像主播边打边说的话，解释这一步准备做什么以及为什么这么做。"
            "内容必须和 planned_action 严格一致，不能提前编造结果。"
            "长度不超过30字。"
            "只输出 JSON，格式为 "
            '{"commentary":"...", "expression":"表情名或空字符串"}'
        )
        text = self._chat_json(
            backend,
            system_prompt=system_prompt,
            user_payload=prompt,
            temperature=0.45,
            max_tokens=120,
        )
        if text is None:
            return None, None

        payload = self._extract_json_object(text)
        if not isinstance(payload, dict):
            return None, None

        commentary = self._clean_text(payload.get("commentary"), 30)
        expression = self._pick_expression(payload.get("expression"))
        return commentary or None, expression

    def build_action_followup(
        self,
        *,
        before_state: dict[str, Any],
        action: Sts2Action,
        after_state: dict[str, Any],
        source: str,
    ) -> tuple[str | None, str | None]:
        if not (
            self.settings.llm_enabled
            and self.settings.llm_use_for_commentary
            and self.settings.llm_use_for_action_followup
        ):
            return None, None

        backend = self._pick_backend(self.settings.llm_commentary_section)
        if backend is None:
            return None, None

        prompt = {
            "decision_source": source,
            "action": self._serialize_action(action),
            "before": self._build_commentary_snapshot(before_state),
            "after": self._build_commentary_snapshot(after_state),
        }
        system_prompt = (
            f"你是 {self.persona_name}，正在直播《杀戮尖塔2》。"
            "现在一个动作已经执行完了。"
            "请只根据 before 和 after 的真实变化，说一句动作后的复盘口播。"
            "可以说伤害、场面压力、是否稳住了，但不能编造未发生的信息。"
            "如果变化太小不值得说，就返回空 commentary。"
            "长度不超过26字。"
            "只输出 JSON，格式为 "
            '{"commentary":"...", "expression":"表情名或空字符串"}'
        )
        text = self._chat_json(
            backend,
            system_prompt=system_prompt,
            user_payload=prompt,
            temperature=0.4,
            max_tokens=120,
        )
        if text is None:
            return None, None

        payload = self._extract_json_object(text)
        if not isinstance(payload, dict):
            return None, None

        commentary = self._clean_text(payload.get("commentary"), 26)
        expression = self._pick_expression(payload.get("expression"))
        return commentary or None, expression

    def reply_danmaku(self, message: dict[str, Any], state: dict[str, Any]) -> str | None:
        if not (self.settings.llm_enabled and self.settings.llm_use_for_danmaku):
            return None

        backend = self._pick_backend(self.settings.llm_danmaku_section)
        if backend is None:
            return None

        prompt = {
            "viewer_message": message,
            "current_state": self._build_commentary_snapshot(state),
        }
        system_prompt = (
            f"你是 {self.persona_name}，正在直播《杀戮尖塔2》，要一边打牌一边和观众聊天。"
            "请口语化地回复这条弹幕，像主播临场接话，不要书面腔。"
            "长度不超过36字。"
        )
        text = self._chat_text(
            backend,
            system_prompt=system_prompt,
            user_payload=prompt,
            temperature=0.75,
            max_tokens=120,
        )
        if not text:
            return None
        return self._clean_text(text, 36)

    def _pick_backend(self, preferred_section: str) -> ChatBackend | None:
        preferred = self.backends.get(preferred_section)
        if preferred and preferred.enabled:
            return preferred
        for fallback_name in ("auxiliary", "required"):
            backend = self.backends.get(fallback_name)
            if backend and backend.enabled:
                return backend
        return None

    def _build_backend(self, section_name: str) -> ChatBackend:
        section = dict(getattr(Global, section_name, {}) or {})
        explicit = self._backend_from_section(section_name, section, auto_selected=False)
        if explicit.enabled:
            return explicit
        discovered = self._auto_discover_backend(section_name, section)
        if discovered is not None:
            return discovered
        return explicit

    def _backend_from_section(
        self,
        section_name: str,
        section: dict[str, Any],
        *,
        auto_selected: bool,
    ) -> ChatBackend:
        provider_name = str(section.get("provider_name") or section.get("provider") or section_name).strip()
        provider = self._provider_preset(provider_name)
        provider_type = str(section.get("provider_type") or provider.get("provider_type") or "openai").strip().lower()
        base_url = str(section.get("base_url") or provider.get("base_url") or "").strip().rstrip("/")
        api_key = str(section.get("api_key") or self._provider_api_key(provider) or "").strip()
        model = self._normalize_model_name(section.get("chat_model"))

        if provider_type == "ollama" and base_url and not base_url.endswith("/v1"):
            base_url = base_url + "/v1"
        if provider_type == "ollama" and not api_key:
            api_key = "ollama"

        detected_models: list[str] = []
        if base_url and not model and (api_key or provider_type == "ollama"):
            detected_models = discover_models(
                provider_type=provider_type,
                base_url=self._discovery_base_url(provider_type, base_url),
                api_key=api_key,
                timeout=2.5,
            )
            if detected_models:
                model = pick_preferred_model(
                    detected_models,
                    purpose=str(section.get("model_purpose") or section_name),
                )

        client = self._make_client(provider_type, base_url, api_key, model)
        return ChatBackend(
            section_name=section_name,
            provider_name=provider_name,
            provider_type=provider_type,
            base_url=base_url,
            api_key=api_key,
            model=model,
            client=client,
            auto_selected=auto_selected,
            detected_models=detected_models,
        )

    def _auto_discover_backend(self, section_name: str, section: dict[str, Any]) -> ChatBackend | None:
        candidates: list[str] = []
        explicit_provider = str(section.get("provider") or section.get("provider_name") or "").strip()
        if explicit_provider:
            candidates.append(explicit_provider)
        for name in AUTO_PROVIDER_ORDER:
            if name not in candidates:
                candidates.append(name)
        for name in self.providers.keys():
            name = str(name)
            if name not in candidates:
                candidates.append(name)

        for provider_name in candidates:
            provider = self._provider_preset(provider_name)
            provider_type = str(provider.get("provider_type") or "openai").strip().lower()
            base_url = str(provider.get("base_url") or "").strip().rstrip("/")
            api_key = self._provider_api_key(provider)
            if provider_type == "ollama":
                if base_url and not base_url.endswith("/v1"):
                    base_url = base_url + "/v1"
                api_key = api_key or "ollama"
            elif not api_key:
                continue

            if not base_url:
                continue

            detected_models = discover_models(
                provider_type=provider_type,
                base_url=self._discovery_base_url(provider_type, base_url),
                api_key=api_key,
                timeout=1.5,
            )
            if not detected_models:
                continue

            model = pick_preferred_model(
                detected_models,
                purpose=str(section.get("model_purpose") or section_name),
            )
            client = self._make_client(provider_type, base_url, api_key, model)
            if client is None:
                continue

            return ChatBackend(
                section_name=section_name,
                provider_name=provider_name,
                provider_type=provider_type,
                base_url=base_url,
                api_key=api_key,
                model=model,
                client=client,
                auto_selected=True,
                detected_models=detected_models,
            )
        return None

    def _provider_preset(self, provider_name: str) -> dict[str, Any]:
        name = str(provider_name or "").strip()
        if not name:
            return {}
        return dict(self.providers.get(name) or DEFAULT_PROVIDER_PRESETS.get(name) or {})

    @staticmethod
    def _provider_api_key(provider: dict[str, Any]) -> str:
        env_name = str(provider.get("api_key_env") or "").strip()
        env_value = str(os.getenv(env_name, "") or "").strip() if env_name else ""
        return env_value or str(provider.get("api_key") or "").strip()

    @staticmethod
    def _discovery_base_url(provider_type: str, base_url: str) -> str:
        if provider_type == "ollama" and base_url.rstrip("/").endswith("/v1"):
            return base_url.rstrip("/")[:-3].rstrip("/")
        return base_url

    @staticmethod
    def _normalize_model_name(value: Any) -> str:
        model = str(value or "").strip()
        return "" if model.lower() in {"auto", "auto:chat", "auto:tool"} else model

    @staticmethod
    def _make_client(provider_type: str, base_url: str, api_key: str, model: str) -> Any:
        model = StreamerLlmBrain._normalize_model_name(model)
        if OpenAI is None or not base_url or not model:
            return None
        if provider_type != "ollama" and not api_key:
            return None
        try:
            return OpenAI(base_url=base_url, api_key=api_key or "not-needed")
        except Exception:
            return None

    def _chat_json(
        self,
        backend: ChatBackend,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        temperature: float,
        max_tokens: int,
    ) -> str | None:
        return self._chat_text(
            backend,
            system_prompt=system_prompt,
            user_payload=user_payload,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _chat_text(
        self,
        backend: ChatBackend,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        temperature: float,
        max_tokens: int,
    ) -> str | None:
        if not backend.enabled:
            return None
        try:
            response = backend.client.chat.completions.create(
                model=backend.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False)[: self.settings.llm_max_context_chars],
                    },
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.settings.llm_timeout_seconds,
            )
        except Exception:
            return None

        try:
            content = response.choices[0].message.content
        except Exception:
            return None
        if isinstance(content, list):
            joined: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    joined.append(str(item.get("text") or ""))
            return "".join(joined).strip() or None
        return str(content or "").strip() or None

    def _build_action_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        screen = str(state.get("screen") or "").upper()
        run = state.get("run") or {}
        snapshot: dict[str, Any] = {
            "screen": screen,
            "run_id": state.get("run_id"),
            "available_actions": state.get("available_actions") or [],
            "run": {
                "floor": run.get("floor"),
                "current_hp": run.get("current_hp"),
                "max_hp": run.get("max_hp"),
                "gold": run.get("gold"),
            },
        }

        if screen == "COMBAT":
            combat = state.get("combat") or {}
            snapshot["turn"] = state.get("turn")
            snapshot["combat"] = {
                "player": {
                    "current_hp": (combat.get("player") or {}).get("current_hp"),
                    "block": (combat.get("player") or {}).get("block"),
                    "energy": (combat.get("player") or {}).get("energy"),
                },
                "enemies": [
                    {
                        "index": enemy.get("index"),
                        "name": enemy.get("name"),
                        "current_hp": enemy.get("current_hp"),
                        "block": enemy.get("block"),
                        "intents": enemy.get("intents"),
                    }
                    for enemy in combat.get("enemies") or []
                    if enemy.get("is_alive", True)
                ],
                "hand": [
                    {
                        "index": card.get("index"),
                        "name": card.get("name"),
                        "energy_cost": card.get("energy_cost"),
                        "star_cost": card.get("star_cost"),
                        "requires_target": card.get("requires_target"),
                        "valid_target_indices": card.get("valid_target_indices"),
                        "rules_text": card.get("resolved_rules_text") or card.get("rules_text"),
                        "dynamic_values": card.get("dynamic_values"),
                        "playable": card.get("playable"),
                    }
                    for card in combat.get("hand") or []
                ],
            }
        elif screen == "MAP":
            map_payload = state.get("map") or {}
            snapshot["map"] = {
                "available_nodes": map_payload.get("available_nodes"),
                "current_node": map_payload.get("current_node"),
            }
        elif screen == "REWARD":
            reward = state.get("reward") or {}
            snapshot["reward"] = {
                "rewards": reward.get("rewards"),
                "card_options": reward.get("card_options"),
            }
        elif screen == "SHOP":
            shop = state.get("shop") or {}
            snapshot["shop"] = {
                "gold": run.get("gold"),
                "cards": shop.get("cards"),
                "relics": shop.get("relics"),
                "potions": shop.get("potions"),
                "card_removal": shop.get("card_removal"),
                "is_open": shop.get("is_open") or shop.get("open"),
            }
        elif screen == "EVENT":
            event = state.get("event") or {}
            snapshot["event"] = {
                "name": event.get("name"),
                "description": event.get("description"),
                "options": event.get("options"),
            }
        elif screen == "REST":
            rest = state.get("rest") or {}
            snapshot["rest"] = {"options": rest.get("options")}
        elif screen == "SELECTION":
            selection = state.get("selection") or {}
            snapshot["selection"] = {
                "kind": selection.get("kind") or selection.get("type_name"),
                "prompt": selection.get("prompt"),
                "cards": selection.get("cards"),
            }
        elif screen == "CHARACTER_SELECT":
            selection = state.get("character_select") or {}
            snapshot["character_select"] = {"characters": selection.get("characters")}

        return snapshot

    def _build_commentary_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
        snapshot = self._build_action_snapshot(state)
        screen = str(state.get("screen") or "").upper()
        if screen == "COMBAT":
            combat = snapshot.get("combat") or {}
            hand = combat.get("hand") or []
            if len(hand) > 5:
                combat["hand"] = hand[:5]
            snapshot["combat"] = combat
        return snapshot

    @staticmethod
    def _serialize_action(action: Sts2Action) -> dict[str, Any]:
        return {
            "action": action.name,
            "card_index": action.card_index,
            "target_index": action.target_index,
            "option_index": action.option_index,
        }

    def _parse_action_payload(self, payload: dict[str, Any], state: dict[str, Any]) -> Sts2Action | None:
        action_name = str(payload.get("action") or "").strip()
        if not action_name:
            return None

        available_actions = set(state.get("available_actions") or [])
        if action_name not in available_actions:
            return None

        card_index = self._parse_optional_int(payload.get("card_index"))
        target_index = self._parse_optional_int(payload.get("target_index"))
        option_index = self._parse_optional_int(payload.get("option_index"))

        if action_name == "play_card":
            combat = state.get("combat") or {}
            hand = combat.get("hand") or []
            card = next(
                (
                    item
                    for item in hand
                    if int(item.get("index", -1)) == card_index and item.get("playable")
                ),
                None,
            )
            if card is None:
                return None
            valid_targets = card.get("valid_target_indices") or []
            if card.get("requires_target"):
                if target_index not in valid_targets:
                    target_index = valid_targets[0] if valid_targets else None
                    if target_index is None:
                        return None
            else:
                target_index = None
            return Sts2Action("play_card", card_index=card_index, target_index=target_index)

        if action_name in OPTION_INDEX_ACTIONS and option_index is None:
            option_index = 0

        return Sts2Action(
            action_name,
            card_index=card_index,
            target_index=target_index,
            option_index=option_index,
        )

    @staticmethod
    def _parse_optional_int(value: Any) -> int | None:
        if value in (None, "", "null"):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _pick_expression(self, value: Any) -> str | None:
        candidate = str(value or "").strip()
        if not candidate:
            return None
        return candidate if candidate in self.valid_expressions else None

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any] | None:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _clean_text(value: Any, max_chars: int) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\s+", "", text)
        return text[:max_chars]
