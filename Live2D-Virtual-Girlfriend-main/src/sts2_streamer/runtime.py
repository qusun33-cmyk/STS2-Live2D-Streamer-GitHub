from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .bilibili import BilibiliDanmakuClient, DanmakuMessage
from .config import StreamerSettings
from .llm_brain import StreamerLlmBrain
from .pilot import HeuristicPilot, PilotDecision
from .speaker import PersonaSpeaker
from .sts2_client import Sts2Action, Sts2HttpClient


class StreamerRuntime:
    def __init__(self, settings: StreamerSettings, speaker: PersonaSpeaker) -> None:
        self.settings = settings
        self.speaker = speaker
        self.client = Sts2HttpClient(settings.api_base_url)
        self.pilot = HeuristicPilot(settings)
        self.llm = StreamerLlmBrain(settings)
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.last_action_at = 0.0
        self.last_commentary_at = 0.0
        self.last_room_reply_at = 0.0
        self.game_process = None
        self.danmaku_client: BilibiliDanmakuClient | None = None
        self.last_run_id: str | None = None
        self.last_state: dict[str, Any] = {}
        self._last_decision_key: tuple[Any, ...] | None = None
        self._same_decision_count = 0
        self._danmaku_queue: deque[dict[str, Any]] = deque(maxlen=max(1, settings.bilibili_max_queue))
        self._danmaku_lock = threading.Lock()

    def start(self) -> None:
        if self.settings.auto_launch_game:
            self._ensure_game_running()
        elif not self._health_ready():
            raise RuntimeError("STS2 API is not ready and auto_launch_game is disabled.")

        if self.settings.bilibili_enabled and self.settings.bilibili_room_id:
            self.danmaku_client = BilibiliDanmakuClient(self.settings.bilibili_room_id, self._on_danmaku)
            self.danmaku_client.start()

        if self.settings.welcome_line:
            self._emit_commentary(self.settings.welcome_line, None, force=True)

        threading.Thread(target=self._event_loop, daemon=True).start()
        threading.Thread(target=self._pilot_loop, daemon=True).start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.danmaku_client is not None:
            self.danmaku_client.stop()

    def pause(self) -> None:
        self.pause_event.set()

    def resume(self) -> None:
        self.pause_event.clear()

    def reload_settings(self, settings: StreamerSettings) -> None:
        self.settings = settings
        self.speaker.settings = settings
        self.client = Sts2HttpClient(settings.api_base_url)
        self.pilot = HeuristicPilot(settings)
        self.llm = StreamerLlmBrain(settings)

    def status(self) -> dict[str, Any]:
        try:
            health = self.client.get_health()
        except Exception as exc:
            health = {"status": "unavailable", "error": str(exc)}

        with self._danmaku_lock:
            danmaku_queue_size = len(self._danmaku_queue)

        return {
            "paused": self.pause_event.is_set(),
            "api_base_url": self.settings.api_base_url,
            "health": health,
            "bilibili_enabled": self.settings.bilibili_enabled,
            "bilibili_room_id": self.settings.bilibili_room_id,
            "bilibili_queue_size": danmaku_queue_size,
            "mod_source_dir": self.settings.mod_source_dir,
            "llm": self.llm.status(),
            "screen": self.last_state.get("screen"),
            "run_id": self.last_state.get("run_id"),
            "available_actions": list(self.last_state.get("available_actions") or []),
        }

    def _ensure_game_running(self) -> None:
        if self._health_ready():
            return

        self._ensure_mod_installed()
        self._enable_mods_in_settings()

        if self._health_ready():
            return

        if self.settings.start_script is not None:
            self._launch_via_start_script()
        else:
            self._launch_game_directly()

        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            if self._health_ready():
                return
            time.sleep(2.0)
        raise RuntimeError("STS2 mod HTTP API did not become ready in time.")

    def _ensure_mod_installed(self) -> None:
        if not self.settings.auto_install_mod or self.settings.mod_source_path is None:
            return

        source_dir = self.settings.mod_source_path
        target_dir = self.settings.game_root / "mods"
        target_dir.mkdir(parents=True, exist_ok=True)

        for name in ("STS2AIAgent.dll", "STS2AIAgent.pck", "mod_id.json"):
            source_path = source_dir / name
            if not source_path.exists():
                continue
            target_path = target_dir / name
            if target_path.exists():
                same_size = target_path.stat().st_size == source_path.stat().st_size
                same_time = int(target_path.stat().st_mtime) >= int(source_path.stat().st_mtime)
                if same_size and same_time:
                    continue
            shutil.copy2(source_path, target_path)

    def _enable_mods_in_settings(self) -> None:
        settings_paths = [
            Path(os.environ["APPDATA"]) / "SlayTheSpire2" / "steam",
            Path(os.environ["APPDATA"]) / "SlayTheSpire2" / "default",
        ]
        for root in settings_paths:
            if not root.exists():
                continue
            for settings_path in root.rglob("settings.save"):
                try:
                    data = json.loads(settings_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                data["mod_settings"] = {"mods_enabled": True}
                settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        app_id_path = self.settings.game_root / "steam_appid.txt"
        if not app_id_path.exists():
            app_id_path.write_text(self.settings.steam_app_id, encoding="ascii")

    def _launch_via_start_script(self) -> None:
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.settings.start_script),
            "-ExePath",
            self.settings.game_exe_path,
            "-Attempts",
            "80",
            "-DelaySeconds",
            "2",
            "-ApiPort",
            str(self._api_port()),
            "-AppId",
            self.settings.steam_app_id,
        ]
        if self.settings.enable_debug_actions:
            command.append("-EnableDebugActions")
        if not self.settings.launch_via_steam:
            command.append("-DisableSteamLaunch")
        if self.settings.steam_executable_path:
            command.extend(["-SteamExecutablePath", self.settings.steam_executable_path])

        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if completed.returncode != 0 and not self._health_ready():
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Failed to launch STS2 via start script: {stderr}")

    def _launch_game_directly(self) -> None:
        self.game_process = subprocess.Popen(
            [self.settings.game_exe_path],
            env={
                **os.environ,
                "STS2_API_PORT": str(self._api_port()),
                "STS2_ENABLE_DEBUG_ACTIONS": "1" if self.settings.enable_debug_actions else "0",
            },
        )

    def _health_ready(self) -> bool:
        try:
            health = self.client.get_health()
        except Exception:
            return False
        return str(health.get("status", "")).lower() == "ready"

    def _event_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                for event in self.client.iter_events():
                    if self.stop_event.is_set():
                        return
                    self._handle_game_event(event)
            except Exception as exc:  # pragma: no cover
                print(f"[sts2_streamer] event stream reconnecting: {exc}")
                time.sleep(2.0)

    def _pilot_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.pause_event.is_set():
                    time.sleep(0.2)
                    continue

                state = self.client.get_state()
                self.last_state = state
                self._maybe_comment_run_start(state)
                self._maybe_handle_danmaku(state)

                if not self.settings.auto_play:
                    time.sleep(self.settings.poll_interval_seconds)
                    continue

                if time.monotonic() - self.last_action_at < self.settings.action_cooldown_seconds:
                    time.sleep(0.15)
                    continue

                decision_source = "llm"
                decision = self.llm.decide_action(state)
                if decision is None or decision.action is None:
                    decision_source = "heuristic"
                    decision = self.pilot.decide(state)

                decision = self._coerce_stuck_decision(state, decision)
                if decision.action is None:
                    time.sleep(self.settings.poll_interval_seconds)
                    continue

                pre_speech, pre_exp = self._compose_action_commentary(
                    state=state,
                    decision=decision,
                    source=decision_source,
                )
                if pre_speech:
                    self._emit_commentary(pre_speech, pre_exp)

                print(
                    "[sts2_streamer] action="
                    f"{decision.action.name} screen={state.get('screen')} "
                    f"available={state.get('available_actions')}"
                )
                response = self.client.act(decision.action)
                self.last_action_at = time.monotonic()

                response_state = response.get("state") or {}
                if response_state:
                    self.last_state = response_state
                if response.get("status") == "pending" or not (response_state.get("available_actions") or []):
                    self.last_state = self.client.wait_until_actionable(timeout_seconds=12.0)

                post_speech, post_exp = self._compose_action_followup(
                    before_state=state,
                    action=decision.action,
                    after_state=self.last_state,
                    source=decision_source,
                    had_pre_speech=bool(pre_speech),
                )
                if post_speech:
                    self._emit_commentary(post_speech, post_exp, force=True)
            except Exception as exc:  # pragma: no cover
                print(f"[sts2_streamer] pilot loop error: {exc}")
                time.sleep(1.0)

    def _coerce_stuck_decision(self, state: dict[str, Any], decision: PilotDecision) -> PilotDecision:
        if decision.action is None:
            self._last_decision_key = None
            self._same_decision_count = 0
            return decision

        key = (
            state.get("run_id"),
            state.get("screen"),
            tuple(sorted(state.get("available_actions") or [])),
            decision.action.name,
            decision.action.option_index,
            decision.action.card_index,
            decision.action.target_index,
        )
        if key == self._last_decision_key:
            self._same_decision_count += 1
        else:
            self._last_decision_key = key
            self._same_decision_count = 1

        if (
            self._same_decision_count >= 5
            and "proceed" in set(state.get("available_actions") or [])
            and decision.action.name != "proceed"
        ):
            return PilotDecision(Sts2Action("proceed"), "这里像是卡住了，我先往前推进。", None)
        return decision

    def _handle_game_event(self, event: dict[str, Any]) -> None:
        if not self.settings.auto_commentary or not self._can_comment():
            return

        event_name = str(event.get("event") or "")
        data = event.get("data") or {}
        speech, exp = self.llm.build_event_commentary(
            event_name=event_name,
            data=data if isinstance(data, dict) else {"raw": data},
            state=self.last_state,
        )
        if not speech:
            speech, exp = self._fallback_event_commentary(event_name, data if isinstance(data, dict) else {})

        if speech:
            self._emit_commentary(speech, exp)

    def _fallback_event_commentary(self, event_name: str, data: dict[str, Any]) -> tuple[str | None, str | None]:
        if event_name == "combat_started":
            return "战斗开始了，这把我认真打。", None
        if event_name == "combat_turn_changed":
            return f"来到第 {data.get('to', '?')} 回合，我继续算牌。", None
        if event_name == "reward_decision_required":
            return "奖励界面来了，让我挑一挑。", None
        if event_name == "route_decision_required":
            return "该选路线了，我先看看怎么走。", None
        if event_name == "combat_ended":
            return "这场战斗打完了，我们继续推进。", None
        if event_name == "event_state_changed":
            return "事件房到了，我先读一下。", None
        if event_name == "shop_inventory_opened":
            return "商店开了，我先看看值不值得买。", None
        if event_name == "rest_decision_required":
            return "休息点到了，我算算该回血还是升级。", None
        return None, None

    def _on_danmaku(self, message: DanmakuMessage) -> None:
        payload = {
            "room_id": message.room_id,
            "username": message.username,
            "text": message.text,
            "received_at": time.time(),
        }
        with self._danmaku_lock:
            self._danmaku_queue.append(payload)

    def _maybe_handle_danmaku(self, state: dict[str, Any]) -> None:
        if time.monotonic() - self.last_room_reply_at < self.settings.room_reply_cooldown_seconds:
            return

        candidate = None
        with self._danmaku_lock:
            if self._danmaku_queue:
                candidate = self._danmaku_queue.popleft()
        if candidate is None:
            return

        if self.settings.bilibili_reply_probability < 1.0:
            bucket = int(self.settings.bilibili_reply_probability * 100)
            sample_key = (candidate["username"], candidate["text"], int(candidate["received_at"] // 10))
            if hash(sample_key) % 100 >= bucket:
                return

        response = self.llm.reply_danmaku(candidate, state)
        if not response:
            response = self._build_danmaku_reply(candidate, state)
        if response:
            self.last_room_reply_at = time.monotonic()
            self._emit_commentary(response, None, force=True)

    @staticmethod
    def _build_danmaku_reply(message: dict[str, Any], state: dict[str, Any]) -> str:
        run = state.get("run") or {}
        floor = run.get("floor", "?")
        current_hp = run.get("current_hp", "?")
        max_hp = run.get("max_hp", "?")
        text = str(message.get("text") or "").strip()
        username = str(message.get("username") or "观众")

        if any(keyword in text for keyword in ("加油", "稳住", "冲", "打爆")):
            return f"{username}，我看见啦，这把我尽量稳着打。"
        if any(keyword in text for keyword in ("几血", "血量", "状态")):
            return f"{username}，我现在第 {floor} 层，血量是 {current_hp}/{max_hp}。"
        if "路线" in text:
            return f"{username}，路线我在盯，尽量给你走得漂亮一点。"
        return f"{username}，弹幕我收到了，我边打边陪你们聊。"

    def _maybe_comment_run_start(self, state: dict[str, Any]) -> None:
        run_id = state.get("run_id")
        if not run_id or run_id == self.last_run_id:
            return
        self.last_run_id = str(run_id)
        if run_id == "run_unknown":
            return

        speech, exp = self.llm.build_event_commentary(
            event_name="run_started",
            data={"run_id": run_id, "screen": state.get("screen")},
            state=state,
        )
        if not speech:
            speech, exp = "新的一把开始了，今天这塔我来爬。", None
        self._emit_commentary(speech, exp, force=True)

    def _api_port(self) -> int:
        try:
            return int(self.settings.api_base_url.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            return 8080

    def _compose_action_commentary(
        self,
        *,
        state: dict[str, Any],
        decision: PilotDecision,
        source: str,
    ) -> tuple[str | None, str | None]:
        if not self.settings.auto_commentary or not self._can_comment():
            return None, None

        speech = (decision.speech or "").strip() or None
        expression = decision.exp
        llm_speech, llm_expression = self.llm.build_action_commentary(
            state=state,
            decision=decision,
            source=source,
        )
        if llm_speech:
            speech = llm_speech
            expression = llm_expression or expression
        return speech, expression

    def _compose_action_followup(
        self,
        *,
        before_state: dict[str, Any],
        action: Sts2Action,
        after_state: dict[str, Any],
        source: str,
        had_pre_speech: bool,
    ) -> tuple[str | None, str | None]:
        if not self.settings.auto_commentary:
            return None, None
        significant = self._should_comment_after_action(before_state, after_state)
        if not significant and had_pre_speech:
            return None, None
        if not significant and not self._can_comment():
            return None, None
        return self.llm.build_action_followup(
            before_state=before_state,
            action=action,
            after_state=after_state,
            source=source,
        )

    def _should_comment_after_action(self, before_state: dict[str, Any], after_state: dict[str, Any]) -> bool:
        if before_state.get("screen") != after_state.get("screen"):
            return True

        before_combat = before_state.get("combat") or {}
        after_combat = after_state.get("combat") or {}
        before_player = before_combat.get("player") or {}
        after_player = after_combat.get("player") or {}

        if self._enemy_summary(before_combat) != self._enemy_summary(after_combat):
            return True

        before_hp = int(before_player.get("current_hp") or 0)
        after_hp = int(after_player.get("current_hp") or 0)
        return before_hp != after_hp

    @staticmethod
    def _enemy_summary(combat: dict[str, Any]) -> tuple[int, int]:
        enemies = [
            enemy
            for enemy in combat.get("enemies") or []
            if isinstance(enemy, dict) and enemy.get("is_alive", True)
        ]
        count = len(enemies)
        total_hp = sum(int(enemy.get("current_hp") or 0) for enemy in enemies)
        return count, total_hp

    def _can_comment(self) -> bool:
        return time.monotonic() - self.last_commentary_at >= self.settings.commentary_cooldown_seconds

    def _emit_commentary(self, speech: str | None, expression: str | None, *, force: bool = False) -> None:
        text = (speech or "").strip()
        if not text:
            return
        if not force and not self._can_comment():
            return
        self.last_commentary_at = time.monotonic()
        self.speaker.say(text, expression)
