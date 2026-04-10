from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class PlannedAction:
    action: str
    kwargs: dict[str, Any]
    line: str | None = None
    dedupe_key: str | None = None


class Sts2Director:
    def __init__(self, settings: dict, narration_hub):
        self._settings = settings["sts2"]
        self._workspace_root = settings["workspace_root"]
        self._narration = narration_hub
        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self._client = None
        self._api_error_type = Exception
        self._poll_interval = float(self._settings.get("poll_interval_seconds", 1.1))
        self._action_interval = float(self._settings.get("action_interval_seconds", 0.8))
        self._last_action_at = 0.0
        self._last_launch_attempt = 0.0
        self._last_state_digest: dict[str, Any] = {}
        self._last_status: dict[str, Any] = {
            "running": False,
            "paused": False,
            "screen": None,
            "floor": None,
            "last_action": None,
            "last_error": None,
        }

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="sts2-director")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)

    def pause(self) -> None:
        self._paused = True
        self._last_status["paused"] = True

    def resume(self) -> None:
        self._paused = False
        self._last_status["paused"] = False

    def get_status(self) -> dict[str, Any]:
        return dict(self._last_status)

    def _run(self) -> None:
        while self._running:
            try:
                if not self._ensure_client_ready():
                    time.sleep(2.0)
                    continue

                state = self._client.get_state()
                self._update_status_from_state(state)
                self._narrate_state_changes(state)

                if self._paused:
                    time.sleep(self._poll_interval)
                    continue

                if time.monotonic() - self._last_action_at < self._action_interval:
                    time.sleep(self._poll_interval)
                    continue

                plan = self._choose_action(state)
                if plan is not None:
                    self._execute_plan(plan)
            except self._api_error_type as exc:
                self._last_status["last_error"] = str(exc)
                time.sleep(1.2)
            except Exception as exc:  # pragma: no cover - runtime safety
                self._last_status["last_error"] = str(exc)
                print(f"[streamer] STS2 director error: {exc}")
                time.sleep(2.0)

            time.sleep(self._poll_interval)

    def _ensure_client_ready(self) -> bool:
        if self._client is None:
            self._client = self._create_client()

        try:
            self._client.get_health()
            self._last_status["running"] = True
            return True
        except Exception:
            self._last_status["running"] = False

        if self._settings.get("auto_install_mod", True):
            self._install_mod_files()

        if self._settings.get("auto_launch_game", True):
            now = time.monotonic()
            if now - self._last_launch_attempt >= 15:
                self._launch_game()
                self._last_launch_attempt = now

        return False

    def _create_client(self):
        client_module = importlib.import_module("sts2_mcp.client")
        self._api_error_type = getattr(client_module, "Sts2ApiError", Exception)
        client_cls = getattr(client_module, "Sts2Client")
        return client_cls(base_url=self._settings["api_base_url"])

    def _install_mod_files(self) -> None:
        source_dir = self._settings.get("mod_source_dir") or ""
        game_root = self._settings.get("game_root") or ""
        if not source_dir or not game_root or not os.path.isdir(source_dir):
            return

        target_dir = os.path.join(game_root, "mods")
        os.makedirs(target_dir, exist_ok=True)

        for filename in os.listdir(source_dir):
            source = os.path.join(source_dir, filename)
            target = os.path.join(target_dir, filename)
            if os.path.isdir(source):
                if os.path.exists(target):
                    shutil.rmtree(target)
                shutil.copytree(source, target)
                continue
            shutil.copy2(source, target)

    def _launch_game(self) -> None:
        exe_path = self._settings.get("game_exe") or ""
        sts2_project_root = self._settings.get("sts2_project_root") or ""
        script_path = os.path.join(sts2_project_root, "scripts", "start-game-session.ps1")
        if not exe_path or not os.path.exists(exe_path):
            return

        if os.path.exists(script_path):
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    script_path,
                    "-ExePath",
                    exe_path,
                    "-Attempts",
                    "80",
                    "-DelaySeconds",
                    "2",
                ],
                cwd=sts2_project_root or self._workspace_root,
            )
            return

        subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))

    def _update_status_from_state(self, state: dict[str, Any]) -> None:
        run = state.get("run") or {}
        self._last_status.update(
            {
                "running": True,
                "paused": self._paused,
                "screen": state.get("screen"),
                "floor": run.get("floor"),
            }
        )

    def _narrate_state_changes(self, state: dict[str, Any]) -> None:
        screen = state.get("screen")
        run = state.get("run") or {}
        combat = state.get("combat") or {}
        floor = run.get("floor")
        turn = state.get("turn")

        if screen != self._last_state_digest.get("screen"):
            line = {
                "MAIN_MENU": "已经回到主菜单，准备重新开一把。",
                "CHARACTER_SELECT": "来到角色选择界面，准备开局。",
                "MAP": "回到地图，开始规划路线。",
                "COMBAT": "进入战斗了，我来看看这回合怎么打。",
                "EVENT": "触发事件了，先读一下选项。",
                "SHOP": "到商店了，看看有没有值的东西。",
                "REST": "来到休息点，考虑回血还是升级。",
                "REWARD": "奖励界面到了，先拿该拿的东西。",
                "CHEST": "发现宝箱了，看看能开出什么。",
                "CARD_SELECTION": "现在在选牌界面，我会做一轮取舍。",
                "MODAL": "有弹窗拦住了，我先处理一下。",
                "GAME_OVER": "这一把结束了，我们准备下一把。",
            }.get(screen)
            if line:
                self._narration.submit(line, priority=2, source="sts2", dedupe_key=f"screen:{screen}")

        if floor and floor != self._last_state_digest.get("floor"):
            self._narration.submit(
                f"来到第{floor}层。",
                priority=1,
                source="sts2",
                dedupe_key=f"floor:{floor}",
            )

        if screen == "COMBAT" and turn and turn != self._last_state_digest.get("turn"):
            enemy_summary = self._summarize_enemy_intents(combat)
            line = f"第{turn}回合。{enemy_summary}" if enemy_summary else f"第{turn}回合开始。"
            self._narration.submit(line, priority=1, source="sts2", dedupe_key=f"turn:{turn}")

        self._last_state_digest = {
            "screen": screen,
            "floor": floor,
            "turn": turn,
        }

    def _summarize_enemy_intents(self, combat: dict[str, Any]) -> str:
        enemies = combat.get("enemies") or []
        alive = [enemy for enemy in enemies if enemy.get("is_alive")]
        if not alive:
            return ""

        parts: list[str] = []
        for enemy in alive[:2]:
            intents = enemy.get("intents") or []
            total_damage = sum((intent.get("total_damage") or 0) for intent in intents)
            if total_damage > 0:
                parts.append(f"{enemy.get('name', '敌人')}打算打{total_damage}点")
            else:
                intent_name = enemy.get("move_id") or enemy.get("intent") or "有动作"
                parts.append(f"{enemy.get('name', '敌人')}{intent_name}")
        return "，".join(parts)

    def _choose_action(self, state: dict[str, Any]) -> PlannedAction | None:
        screen = state.get("screen")

        if screen == "MAIN_MENU":
            return self._choose_main_menu_action(state)
        if screen == "CHARACTER_SELECT":
            return self._choose_character_select_action(state)
        if screen == "MAP":
            return self._choose_map_action(state)
        if screen == "COMBAT":
            return self._choose_combat_action(state)
        if screen == "REWARD":
            return self._choose_reward_action(state)
        if screen == "CARD_SELECTION":
            return self._choose_selection_action(state)
        if screen == "EVENT":
            return self._choose_event_action(state)
        if screen == "REST":
            return self._choose_rest_action(state)
        if screen == "SHOP":
            return self._choose_shop_action(state)
        if screen == "CHEST":
            return self._choose_chest_action(state)
        if screen == "MODAL":
            return self._choose_modal_action(state)
        if screen == "GAME_OVER":
            return self._choose_game_over_action(state)
        return None

    def _choose_main_menu_action(self, state: dict[str, Any]) -> PlannedAction | None:
        actions = set(state.get("available_actions") or [])
        if self._settings.get("resume_existing_run") and "continue_run" in actions:
            return PlannedAction("continue_run", {}, "先接着上一把继续。", "continue_run")
        if "open_character_select" in actions:
            return PlannedAction("open_character_select", {}, "准备直接开始新的一把。", "open_character_select")
        if "close_main_menu_submenu" in actions:
            return PlannedAction("close_main_menu_submenu", {}, None, "close_main_menu_submenu")
        return None

    def _choose_character_select_action(self, state: dict[str, Any]) -> PlannedAction | None:
        actions = set(state.get("available_actions") or [])
        payload = state.get("character_select") or {}
        preferred = str(self._settings.get("preferred_character", "IRONCLAD")).upper()
        selected_character = payload.get("selected_character_id")
        characters = payload.get("characters") or []

        if "select_character" in actions and selected_character != preferred:
            for character in characters:
                if character.get("character_id", "").upper() != preferred:
                    continue
                if character.get("is_locked"):
                    break
                return PlannedAction(
                    "select_character",
                    {"option_index": int(character["index"])},
                    f"这一把先用{character.get('name', preferred)}。",
                    f"character:{preferred}",
                )

        if "embark" in actions and payload.get("can_embark"):
            return PlannedAction("embark", {}, "角色锁定，准备出发。", "embark")
        return None

    def _choose_map_action(self, state: dict[str, Any]) -> PlannedAction | None:
        if "choose_map_node" not in set(state.get("available_actions") or []):
            return None

        payload = state.get("map") or {}
        available_nodes = payload.get("available_nodes") or []
        if not available_nodes:
            return None

        hp_ratio = self._hp_ratio(state)
        gold = (state.get("run") or {}).get("gold", 0)
        weights = {
            "Monster": 5,
            "Event": 6,
            "Shop": 8 if gold >= 120 else 3,
            "Rest": 10 if hp_ratio < 0.55 else 4,
            "Treasure": 9,
            "Elite": 8 if hp_ratio > 0.7 else 2,
            "Boss": 12,
        }

        best = max(
            available_nodes,
            key=lambda node: (
                weights.get(node.get("node_type"), 4),
                -abs(int(node.get("col", 0)) - 3),
            ),
        )
        line = f"下一步走{self._node_type_name(best.get('node_type'))}路线。"
        return PlannedAction(
            "choose_map_node",
            {"option_index": int(best["index"])},
            line,
            f"map:{best.get('row')}:{best.get('col')}",
        )

    def _choose_combat_action(self, state: dict[str, Any]) -> PlannedAction | None:
        actions = set(state.get("available_actions") or [])
        combat = state.get("combat") or {}
        player = combat.get("player") or {}
        hand = [card for card in (combat.get("hand") or []) if card.get("playable")]
        enemies = [enemy for enemy in (combat.get("enemies") or []) if enemy.get("is_alive")]
        threat = self._incoming_damage(enemies)

        best_card = None
        best_target = None
        best_score = -10**9

        for card in hand:
            target = self._pick_target(card, enemies)
            score = self._score_combat_card(card, target, threat, player)
            if score > best_score:
                best_score = score
                best_card = card
                best_target = target

        if best_card is not None and best_score > 0 and "play_card" in actions:
            kwargs = {"card_index": int(best_card["index"])}
            if best_card.get("requires_target") and best_target is not None:
                kwargs["target_index"] = int(best_target["index"])
            line = f"这回合先打出{best_card.get('name', '卡牌')}。"
            return PlannedAction("play_card", kwargs, line, f"combat:{best_card.get('index')}:{state.get('turn')}")

        if "end_turn" in actions:
            return PlannedAction("end_turn", {}, "这回合没更好的牌了，先结束回合。", f"end_turn:{state.get('turn')}")
        return None

    def _choose_reward_action(self, state: dict[str, Any]) -> PlannedAction | None:
        actions = set(state.get("available_actions") or [])
        reward = state.get("reward") or {}

        if reward.get("pending_card_choice") and reward.get("card_options"):
            options = reward.get("card_options") or []
            best = max(options, key=lambda option: self._score_reward_card(option))
            best_score = self._score_reward_card(best)
            if best_score >= 10 and "choose_reward_card" in actions:
                return PlannedAction(
                    "choose_reward_card",
                    {"option_index": int(best["index"])},
                    f"奖励牌我先拿{best.get('name', '这张牌')}。",
                    f"reward_card:{best.get('card_id')}",
                )
            if "skip_reward_cards" in actions:
                return PlannedAction("skip_reward_cards", {}, "这组奖励牌一般，先跳过。", "skip_reward_cards")

        claimable_rewards = [item for item in (reward.get("rewards") or []) if item.get("claimable")]
        if claimable_rewards and "claim_reward" in actions:
            best = max(claimable_rewards, key=lambda item: self._reward_priority(item.get("reward_type")))
            return PlannedAction(
                "claim_reward",
                {"option_index": int(best["index"])},
                f"先把{best.get('reward_type', '奖励')}收下。",
                f"claim_reward:{best.get('index')}",
            )

        if "collect_rewards_and_proceed" in actions and reward.get("can_proceed"):
            return PlannedAction("collect_rewards_and_proceed", {}, "奖励拿完了，继续前进。", "collect_rewards")
        if "proceed" in actions and reward.get("can_proceed"):
            return PlannedAction("proceed", {}, None, "reward_proceed")
        return None

    def _choose_selection_action(self, state: dict[str, Any]) -> PlannedAction | None:
        actions = set(state.get("available_actions") or [])
        selection = state.get("selection") or {}
        cards = selection.get("cards") or []
        prompt = f"{selection.get('kind', '')} {selection.get('prompt', '')}".strip()
        prompt_upper = prompt.upper()

        if selection.get("requires_confirmation") and selection.get("can_confirm") and "confirm_selection" in actions:
            return PlannedAction("confirm_selection", {}, "选好了，确认。", f"confirm_selection:{prompt}")

        if "select_deck_card" not in actions or not cards:
            return None

        if any(keyword in prompt_upper for keyword in ("REMOVE", "DELETE", "PURGE")) or "移除" in prompt or "删除" in prompt:
            chosen = max(cards, key=self._score_remove_card)
            line = f"这里把{chosen.get('name', '这张牌')}去掉。"
        elif any(keyword in prompt_upper for keyword in ("UPGRADE", "ENCHANT", "SMITH")) or "升级" in prompt or "锻造" in prompt:
            chosen = max(cards, key=self._score_upgrade_card)
            line = f"这里优先升级{chosen.get('name', '这张牌')}。"
        else:
            chosen = max(cards, key=self._score_selection_card)
            line = f"这里先选{chosen.get('name', '这张牌')}。"

        return PlannedAction(
            "select_deck_card",
            {"option_index": int(chosen["index"])},
            line,
            f"selection:{chosen.get('card_id')}:{prompt}",
        )

    def _choose_event_action(self, state: dict[str, Any]) -> PlannedAction | None:
        if "choose_event_option" not in set(state.get("available_actions") or []):
            return None

        payload = state.get("event") or {}
        options = [option for option in (payload.get("options") or []) if not option.get("is_locked")]
        if not options:
            if "proceed" in set(state.get("available_actions") or []):
                return PlannedAction("proceed", {}, None, "event_proceed")
            return None

        best = max(options, key=self._score_event_option)
        return PlannedAction(
            "choose_event_option",
            {"option_index": int(best["index"])},
            f"这个事件我选{best.get('title') or '当前最优解'}。",
            f"event:{payload.get('event_id')}:{best.get('index')}",
        )

    def _choose_rest_action(self, state: dict[str, Any]) -> PlannedAction | None:
        if "choose_rest_option" not in set(state.get("available_actions") or []):
            if "proceed" in set(state.get("available_actions") or []):
                return PlannedAction("proceed", {}, None, "rest_proceed")
            return None

        hp_ratio = self._hp_ratio(state)
        options = [option for option in (state.get("rest") or {}).get("options", []) if option.get("is_enabled")]
        if not options:
            return None

        def rest_score(option: dict[str, Any]) -> float:
            title = f"{option.get('option_id', '')} {option.get('title', '')} {option.get('description', '')}"
            score = 0.0
            if hp_ratio < 0.55 and any(word in title for word in ("休息", "治疗", "HEAL", "SLEEP")):
                score += 30
            if hp_ratio >= 0.55 and any(word in title for word in ("锻造", "升级", "SMITH", "UPGRADE")):
                score += 25
            if "回忆" in title or "回想" in title:
                score += 8
            return score

        chosen = max(options, key=rest_score)
        return PlannedAction(
            "choose_rest_option",
            {"option_index": int(chosen["index"])},
            f"休息点我选{chosen.get('title', '当前选项')}。",
            f"rest:{chosen.get('option_id')}",
        )

    def _choose_shop_action(self, state: dict[str, Any]) -> PlannedAction | None:
        actions = set(state.get("available_actions") or [])
        payload = state.get("shop") or {}
        gold = (state.get("run") or {}).get("gold", 0)

        if not payload.get("is_open") and payload.get("can_open") and "open_shop_inventory" in actions:
            return PlannedAction("open_shop_inventory", {}, "先打开商店库存看一眼。", "shop_open")

        if payload.get("is_open"):
            affordable_relics = [
                relic for relic in (payload.get("relics") or [])
                if relic.get("available") and relic.get("price", 10**9) <= gold
            ]
            if affordable_relics and "buy_relic" in actions:
                chosen = min(affordable_relics, key=lambda item: item.get("price", 10**9))
                return PlannedAction(
                    "buy_relic",
                    {"option_index": int(chosen["index"])},
                    f"这个遗物价格合适，先拿下{chosen.get('name', '遗物')}。",
                    f"shop_relic:{chosen.get('name')}",
                )

            removal = payload.get("card_removal") or {}
            if removal.get("available") and removal.get("price", 10**9) <= gold and "remove_card_at_shop" in actions:
                return PlannedAction("remove_card_at_shop", {}, "这波直接花钱删张废牌。", "shop_remove")

            affordable_cards = [
                card for card in (payload.get("cards") or [])
                if card.get("available") and card.get("price", 10**9) <= gold
            ]
            if affordable_cards and "buy_card" in actions:
                chosen = max(affordable_cards, key=lambda item: self._score_reward_card(item) - item.get("price", 0) * 0.08)
                if self._score_reward_card(chosen) >= 15:
                    return PlannedAction(
                        "buy_card",
                        {"option_index": int(chosen["index"])},
                        f"这张牌值得买，先拿{chosen.get('name', '它')}。",
                        f"shop_card:{chosen.get('card_id')}",
                    )

            if payload.get("can_close") and "close_shop_inventory" in actions:
                return PlannedAction("close_shop_inventory", {}, None, "shop_close")

        if "proceed" in actions:
            return PlannedAction("proceed", {}, "商店看完了，继续走。", "shop_proceed")
        return None
