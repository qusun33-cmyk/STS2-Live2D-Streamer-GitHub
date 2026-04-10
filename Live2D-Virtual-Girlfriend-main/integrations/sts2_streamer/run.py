import json
import logging
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

try:
    import blivedm
except ImportError:  # pragma: no cover
    blivedm = None


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.toml"


@dataclass
class StreamerConfig:
    game_base_url: str
    avatar_base_url: str
    poll_interval_seconds: float
    action_interval_seconds: float
    commentary_cooldown_seconds: float
    autoplay_enabled: bool
    auto_start_game: bool
    game_exe: str
    start_game_script: str
    room_id: int | None
    bilibili_enabled: bool
    sessdata: str
    buvid3: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str


def load_config(path: Path) -> StreamerConfig:
    with path.open("rb") as f:
        data = tomllib.load(f)

    game = data.get("game", {})
    avatar = data.get("avatar", {})
    autoplay = data.get("autoplay", {})
    startup = data.get("startup", {})
    bilibili = data.get("bilibili", {})
    llm = data.get("llm", {})

    return StreamerConfig(
        game_base_url=game.get("base_url", "http://127.0.0.1:8080"),
        avatar_base_url=avatar.get("base_url", "http://127.0.0.1:19098"),
        poll_interval_seconds=float(game.get("poll_interval_seconds", 0.5)),
        action_interval_seconds=float(autoplay.get("action_interval_seconds", 0.8)),
        commentary_cooldown_seconds=float(avatar.get("commentary_cooldown_seconds", 4.0)),
        autoplay_enabled=bool(autoplay.get("enabled", True)),
        auto_start_game=bool(startup.get("auto_start_game", False)),
        game_exe=startup.get("game_exe", ""),
        start_game_script=startup.get("start_game_script", ""),
        room_id=int(bilibili.get("room_id", 0) or 0) or None,
        bilibili_enabled=bool(bilibili.get("enabled", False)),
        sessdata=bilibili.get("sessdata", ""),
        buvid3=bilibili.get("buvid3", ""),
        llm_base_url=llm.get("base_url", ""),
        llm_api_key=llm.get("api_key", ""),
        llm_model=llm.get("model", ""),
    )


class AvatarBridge:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def speak(self, text: str, interrupt: bool = False):
        if not text:
            return
        try:
            self.session.post(
                f"{self.base_url}/speak",
                json={"text": text, "interrupt": interrupt},
                timeout=10,
            ).raise_for_status()
        except Exception as exc:  # pragma: no cover
            logging.warning("Avatar speak failed: %s", exc)


class STS2Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def health(self):
        resp = self.session.get(f"{self.base_url}/health", timeout=5)
        resp.raise_for_status()
        return resp.json()["data"]

    def state(self):
        resp = self.session.get(f"{self.base_url}/state", timeout=10)
        resp.raise_for_status()
        return resp.json()["data"]

    def act(self, payload: dict):
        resp = self.session.post(f"{self.base_url}/action", json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json()["data"]


class OpenAIBrain:
    def __init__(self, config: StreamerConfig):
        self.enabled = bool(config.llm_base_url and config.llm_api_key and config.llm_model and OpenAI)
        self.model = config.llm_model
        self.client = None
        if self.enabled:
            self.client = OpenAI(base_url=config.llm_base_url, api_key=config.llm_api_key)

    def decide_action(self, state: dict):
        if not self.enabled:
            return None

        prompt = {
            "agent_view": state.get("agent_view"),
            "available_actions": state.get("available_actions"),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是杀戮尖塔2直播控制器。"
                    "只能从 available_actions 中选择动作。"
                    "只输出 JSON，格式为 "
                    "{\"action\":\"...\",\"card_index\":null,\"target_index\":null,"
                    "\"option_index\":null,\"commentary\":\"一句不超过30字的主播解说\"}。"
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )
            text = response.choices[0].message.content or ""
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1:
                return None
            return json.loads(text[start:end + 1])
        except Exception as exc:  # pragma: no cover
            logging.warning("LLM decide_action failed: %s", exc)
            return None

    def reply_danmu(self, room_message: dict):
        if not self.enabled:
            return None

        messages = [
            {
                "role": "system",
                "content": "你是正在直播杀戮尖塔2的虚拟女友主播。回复一句简短、口语化、适合直播口播的话。",
            },
            {"role": "user", "content": json.dumps(room_message, ensure_ascii=False)},
        ]
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:  # pragma: no cover
            logging.warning("LLM reply_danmu failed: %s", exc)
            return None


class FallbackBrain:
    @staticmethod
    def _best_target(card: dict):
        valid = card.get("valid_target_indices") or []
        return valid[0] if valid else None

    @staticmethod
    def _best_card(state: dict):
        combat = state.get("combat") or {}
        player = combat.get("player") or {}
        hand = combat.get("hand") or []
        enemies = combat.get("enemies") or []
        incoming = sum((intent.get("total_damage") or 0) for enemy in enemies for intent in enemy.get("intents", []))
        enemy_hp = min((enemy.get("current_hp") or 9999) for enemy in enemies if enemy.get("is_alive", True)) if enemies else 0
        current_block = player.get("block") or 0

        best = None
        best_score = -10**9
        for card in hand:
            if not card.get("playable"):
                continue

            score = 0.0
            cost = max(card.get("energy_cost") or 0, 1)
            values = {item.get("name"): item.get("current_value", item.get("base_value", 0)) for item in card.get("dynamic_values", [])}
            damage = values.get("Damage", 0)
            block = values.get("Block", 0)
            vuln = values.get("VulnerablePower", 0)

            if damage:
                score += damage * 3 / cost
                if damage >= enemy_hp:
                    score += 100
            if vuln:
                score += vuln * 6
            if block and incoming > current_block:
                score += min(block, incoming - current_block) * 2.5
            if card.get("energy_cost", 0) == 0:
                score += 4
            if "BASH" in (card.get("card_id") or ""):
                score += 3

            if score > best_score:
                best_score = score
                best = card

        return best

    def decide_action(self, state: dict):
        actions = set(state.get("available_actions") or [])

        if "choose_map_node" in actions:
            return {
                "action": "choose_map_node",
                "option_index": 0,
                "commentary": "开局先走第一格，热热身。",
            }

        if "play_card" in actions:
            best = self._best_card(state)
            if best:
                commentary = f"这张先打出去，节奏更顺。"
                return {
                    "action": "play_card",
                    "card_index": best["index"],
                    "target_index": self._best_target(best),
                    "commentary": commentary,
                }

        simple_actions = [
            ("collect_rewards_and_proceed", "奖励收下，继续往前。"),
            ("claim_reward", "先把眼前这个奖励拿了。"),
            ("choose_reward_card", "这张先拿，前期强度更稳。"),
            ("skip_reward_cards", "这波先不贪牌。"),
            ("select_deck_card", "我先点第一张，继续推进。"),
            ("confirm_selection", "确认一下，继续。"),
            ("open_chest", "开宝箱看看手气。"),
            ("choose_treasure_relic", "这件先拿上。"),
            ("choose_event_option", "事件先走第一项。"),
            ("choose_rest_option", "这层我先点第一项。"),
            ("open_shop_inventory", "先进商店看看。"),
            ("close_shop_inventory", "商店先逛到这，继续赶路。"),
            ("proceed", "继续，别停。"),
            ("confirm_modal", "这个弹窗先确认。"),
            ("dismiss_modal", "先把弹窗关掉。"),
            ("select_character", "角色保持当前这个。"),
            ("embark", "出发，开打。"),
            ("end_turn", "这回合先这样，过。"),
        ]
        for action_name, commentary in simple_actions:
            if action_name in actions:
                payload = {"action": action_name, "commentary": commentary}
                if action_name in {"claim_reward", "choose_reward_card", "select_deck_card", "choose_treasure_relic", "choose_event_option", "choose_rest_option", "select_character"}:
                    payload["option_index"] = 0
                return payload

        return None

    @staticmethod
    def state_commentary(previous: dict | None, current: dict):
        if previous is None:
            screen = current.get("screen")
            if screen == "MAP":
                return "路线出来了，我开始自己走。"
            return f"现在在 {screen}，我先接管。"

        if previous.get("screen") != current.get("screen"):
            screen = current.get("screen")
            if screen == "COMBAT":
                enemies = current.get("agent_view", {}).get("combat", {}).get("enemies", [])
                if enemies:
                    name = enemies[0].get("name", "小怪")
                    return f"遇敌了，是{name}，我开始算牌。"
                return "进战斗了，我来操作。"
            if screen == "REWARD":
                return "战斗打完，看看奖励。"
            if screen == "MAP":
                return "回到地图，继续规划路线。"
            if screen == "EVENT":
                return "事件房到了，我先看选项。"
            if screen == "SHOP":
                return "进商店了，我先看看值不值得买。"
            if screen == "REST":
                return "到了休息点，我先判断收益。"
            if screen == "GAME_OVER":
                return "这把先到这里，下一把继续。"

        if current.get("screen") == "COMBAT" and previous.get("turn") != current.get("turn"):
            turn = current.get("turn")
            return f"第{turn}回合，先看手牌怎么排。"

        return None

    @staticmethod
    def danmu_reply(room_message: dict):
        uname = room_message.get("uname", "观众")
        msg = room_message.get("msg", "")
        return f"{uname} 说得对，我先记下这条：{msg}"


class DanmuHandler(blivedm.BaseHandler if blivedm else object):
    def __init__(self, sink: "queue.Queue[dict]"):
        self.sink = sink

    async def _on_danmaku(self, client, message):  # pragma: no cover
        self.sink.put({"uname": getattr(message, "uname", "观众"), "msg": getattr(message, "msg", "")})


class BilibiliDanmuSource:
    def __init__(self, config: StreamerConfig, sink: "queue.Queue[dict]"):
        self.config = config
        self.sink = sink

    def start(self):
        if not self.config.bilibili_enabled or not self.config.room_id or blivedm is None:
            return

        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self):  # pragma: no cover
        try:
            import asyncio

            async def runner():
                session = None
                if self.config.sessdata or self.config.buvid3:
                    session = requests.Session()
                    if self.config.sessdata:
                        session.cookies.set("SESSDATA", self.config.sessdata, domain=".bilibili.com")
                    if self.config.buvid3:
                        session.cookies.set("buvid3", self.config.buvid3, domain=".bilibili.com")

                client = blivedm.BLiveClient(self.config.room_id, session=session)
                client.set_handler(DanmuHandler(self.sink))
                client.start()
                await client.join()

            asyncio.run(runner())
        except Exception as exc:
            logging.warning("Bilibili danmu source stopped: %s", exc)


class GameStreamerController:
    def __init__(self, config: StreamerConfig):
        self.config = config
        self.game = STS2Client(config.game_base_url)
        self.avatar = AvatarBridge(config.avatar_base_url)
        self.llm_brain = OpenAIBrain(config)
        self.fallback_brain = FallbackBrain()
        self.last_state = None
        self.last_action_at = 0.0
        self.last_commentary_at = 0.0
        self.danmu_queue: "queue.Queue[dict]" = queue.Queue()

    def ensure_game_ready(self):
        try:
            self.game.health()
            return
        except Exception:
            pass

        if not self.config.auto_start_game:
            raise RuntimeError("STS2 game API is not ready.")

        if self.config.start_game_script:
            cmd = [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                self.config.start_game_script,
                "-ExePath",
                self.config.game_exe,
            ]
        else:
            cmd = [self.config.game_exe]
        subprocess.Popen(cmd)

        for _ in range(60):
            try:
                self.game.health()
                return
            except Exception:
                time.sleep(2)
        raise RuntimeError("Timed out waiting for STS2 API to become ready.")

    def maybe_comment(self, text: str, interrupt: bool = False):
        now = time.time()
        if not text:
            return
        if now - self.last_commentary_at < self.config.commentary_cooldown_seconds:
            return
        self.avatar.speak(text, interrupt=interrupt)
        self.last_commentary_at = now

    def maybe_handle_danmu(self):
        if self.danmu_queue.empty():
            return
        if time.time() - self.last_commentary_at < max(self.config.commentary_cooldown_seconds, 6):
            return

        room_message = self.danmu_queue.get()
        reply = self.llm_brain.reply_danmu(room_message) or self.fallback_brain.danmu_reply(room_message)
        self.maybe_comment(reply)

    def choose_action(self, state: dict):
        decision = self.llm_brain.decide_action(state) or self.fallback_brain.decide_action(state)
        if not decision:
            return None

        payload = {"action": decision["action"]}
        for key in ("card_index", "target_index", "option_index", "command"):
            if key in decision and decision[key] is not None:
                payload[key] = decision[key]
        return payload, decision.get("commentary", "")

    def step(self):
        state = self.game.state()
        commentary = self.fallback_brain.state_commentary(self.last_state, state)
        if commentary:
            self.maybe_comment(commentary, interrupt=False)

        self.last_state = state
        self.maybe_handle_danmu()

        if not self.config.autoplay_enabled:
            return

        if time.time() - self.last_action_at < self.config.action_interval_seconds:
            return

        chosen = self.choose_action(state)
        if not chosen:
            return

        payload, action_comment = chosen
        self.last_action_at = time.time()
        if action_comment:
            self.maybe_comment(action_comment, interrupt=False)
        result = self.game.act(payload)
        self.last_state = result.get("state", self.last_state)

    def run(self):
        self.ensure_game_ready()
        BilibiliDanmuSource(self.config, self.danmu_queue).start()
        self.maybe_comment("接管完成，开始直播操作。", interrupt=False)

        while True:
            try:
                self.step()
            except requests.HTTPError as exc:
                logging.warning("Game API HTTP error: %s", exc)
            except Exception as exc:
                logging.exception("Controller loop failed: %s", exc)
            time.sleep(self.config.poll_interval_seconds)


def main():
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")
    config_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_CONFIG
    config = load_config(config_path)
    GameStreamerController(config).run()


if __name__ == "__main__":
    main()
