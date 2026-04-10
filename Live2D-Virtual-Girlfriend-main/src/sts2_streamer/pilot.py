from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import StreamerSettings
from .sts2_client import Sts2Action


@dataclass(slots=True)
class PilotDecision:
    action: Sts2Action | None
    speech: str | None = None
    exp: str | None = None


class HeuristicPilot:
    def __init__(self, settings: StreamerSettings) -> None:
        self.settings = settings

    def decide(self, state: dict[str, Any]) -> PilotDecision:
        actions = set(state.get("available_actions") or [])
        if not actions:
            return PilotDecision(None)

        if "confirm_modal" in actions or "dismiss_modal" in actions:
            return self._handle_modal(state, actions)
        if "continue_run" in actions or "abandon_run" in actions or "open_character_select" in actions:
            return self._handle_main_menu(actions)
        if "choose_timeline_epoch" in actions:
            return PilotDecision(Sts2Action("choose_timeline_epoch", option_index=0), "先进入第一条时间线。")
        if "confirm_timeline_overlay" in actions:
            return PilotDecision(Sts2Action("confirm_timeline_overlay"), "时间线确认完毕，继续推进。")
        if "open_timeline" in actions and not self.settings.resume_existing_run:
            return PilotDecision(Sts2Action("open_timeline"), "我先把时间线展开看看。", "闪闪")
        if "select_character" in actions:
            return self._handle_character_select(state, actions)
        if "embark" in actions:
            return PilotDecision(Sts2Action("embark"), "出发，开始爬塔。", "闪闪")
        if "choose_map_node" in actions:
            return self._handle_map(state)
        if "play_card" in actions or "end_turn" in actions:
            return self._handle_combat(state, actions)
        if "claim_reward" in actions:
            return self._handle_reward_claim(state)
        if "choose_reward_card" in actions:
            return self._handle_reward_cards(state)
        if "skip_reward_cards" in actions:
            return PilotDecision(Sts2Action("skip_reward_cards"), "这一组奖励一般，先不拿。")
        if "collect_rewards_and_proceed" in actions:
            return PilotDecision(Sts2Action("collect_rewards_and_proceed"), "奖励收下，继续推进。", "闪闪")
        if "select_deck_card" in actions:
            return self._handle_card_selection(state)
        if "confirm_selection" in actions:
            return PilotDecision(Sts2Action("confirm_selection"), "确认完成，继续。")
        if "open_chest" in actions:
            return PilotDecision(Sts2Action("open_chest"), "开宝箱看看手气。", "闪闪")
        if "choose_treasure_relic" in actions:
            return self._handle_treasure_relic(state)
        if "choose_event_option" in actions:
            return self._handle_event(state)
        if "choose_rest_option" in actions:
            return self._handle_rest(state)
        if self._is_shop_actions(actions):
            return self._handle_shop(state, actions)
        if "use_potion" in actions:
            return self._handle_use_potion(state)
        if "discard_potion" in actions:
            return self._handle_discard_potion(state)
        if "proceed" in actions:
            return PilotDecision(Sts2Action("proceed"))
        if "return_to_main_menu" in actions:
            return PilotDecision(Sts2Action("return_to_main_menu"), "这一把先到这里，我们再来一轮。")

        return PilotDecision(None)

    def _handle_main_menu(self, actions: set[str]) -> PilotDecision:
        if self.settings.resume_existing_run and "continue_run" in actions:
            return PilotDecision(Sts2Action("continue_run"), "我先接着上一把继续打。", "闪闪")
        if not self.settings.resume_existing_run and "abandon_run" in actions:
            return PilotDecision(Sts2Action("abandon_run"), "旧进度先放掉，我们重新开一把。")
        if "open_character_select" in actions:
            return PilotDecision(Sts2Action("open_character_select"), "今天这把就由我来接管。", "闪闪")
        if "continue_run" in actions:
            return PilotDecision(Sts2Action("continue_run"), "我先继续现有进度。", "闪闪")
        return PilotDecision(None)

    def _handle_modal(self, state: dict[str, Any], actions: set[str]) -> PilotDecision:
        modal = state.get("modal") or {}
        modal_type = str(modal.get("type_name") or "").lower()
        if ("tutorial" in modal_type or "ftue" in modal_type) and "dismiss_modal" in actions:
            return PilotDecision(Sts2Action("dismiss_modal"), "教程提示先跳过，我们直接开打。")
        if "confirm_modal" in actions:
            return PilotDecision(Sts2Action("confirm_modal"))
        if "dismiss_modal" in actions:
            return PilotDecision(Sts2Action("dismiss_modal"))
        return PilotDecision(None)

    def _handle_character_select(self, state: dict[str, Any], actions: set[str]) -> PilotDecision:
        payload = (state.get("character_select") or {}).get("characters") or []
        unlocked = [item for item in payload if not item.get("is_locked")]
        if not unlocked:
            return PilotDecision(Sts2Action("select_character", option_index=0))

        preferred_name = self.settings.preferred_character_name
        preferred_index = self.settings.preferred_character_index
        chosen = None

        for item in unlocked:
            if str(item.get("name", "")).upper() == preferred_name or str(item.get("character_id", "")).upper() == preferred_name:
                chosen = item
                break
        if chosen is None:
            for item in unlocked:
                if int(item.get("index", -1)) == preferred_index:
                    chosen = item
                    break
        if chosen is None:
            chosen = unlocked[0]

        if chosen.get("is_selected"):
            if "embark" in actions:
                return PilotDecision(Sts2Action("embark"), "角色已经选好了，直接出发。", "闪闪")
            return PilotDecision(None)

        option_index = int(chosen.get("index", 0))
        name = str(chosen.get("name") or chosen.get("character_id") or "当前角色")
        return PilotDecision(Sts2Action("select_character", option_index=option_index), f"这把我选{name}。", "闪闪")

    def _handle_map(self, state: dict[str, Any]) -> PilotDecision:
        map_payload = state.get("map") or {}
        available = map_payload.get("available_nodes") or []
        if not available:
            return PilotDecision(Sts2Action("choose_map_node", option_index=0), "路线出来了，我先走第一条。")

        hp_ratio = self._hp_ratio(state)
        if hp_ratio < 0.45:
            weights = {"Campfire": 0, "Merchant": 1, "Monster": 2, "Unknown": 3, "Elite": 4}
        elif hp_ratio > 0.75:
            weights = {"Elite": 0, "Monster": 1, "Unknown": 2, "Campfire": 3, "Merchant": 4}
        else:
            weights = {"Monster": 0, "Unknown": 1, "Campfire": 2, "Merchant": 3, "Elite": 4}

        best = min(
            available,
            key=lambda item: (
                weights.get(str(item.get("node_type") or ""), 99),
                int(item.get("row", 999)),
                int(item.get("col", 999)),
                int(item.get("index", 999)),
            ),
        )
        option_index = int(best.get("index", 0))
        node_type = str(best.get("node_type") or "节点")
        return PilotDecision(Sts2Action("choose_map_node", option_index=option_index), f"我准备走{node_type}路线。")

    def _handle_reward_claim(self, state: dict[str, Any]) -> PilotDecision:
        reward = state.get("reward") or {}
        items = [item for item in reward.get("rewards") or [] if item.get("claimable", True)]
        if not items:
            return PilotDecision(Sts2Action("claim_reward", option_index=0))

        priority = {"RELIC": 0, "GOLD": 1, "POTION": 2, "CARD": 3}
        best = min(items, key=lambda item: (priority.get(str(item.get("type") or ""), 99), int(item.get("index", 0))))
        return PilotDecision(Sts2Action("claim_reward", option_index=int(best.get("index", 0))), "先把当前能拿的资源收下。", "闪闪")

    def _handle_reward_cards(self, state: dict[str, Any]) -> PilotDecision:
        reward = state.get("reward") or {}
        options = reward.get("card_options") or []
        if not options:
            return PilotDecision(Sts2Action("choose_reward_card", option_index=0))

        best = max(options, key=self._score_card)
        return PilotDecision(
            Sts2Action("choose_reward_card", option_index=int(best.get("index", 0))),
            f"这次我拿{best.get('name', '这张牌')}。",
            "闪闪",
        )

    def _handle_card_selection(self, state: dict[str, Any]) -> PilotDecision:
        selection = state.get("selection") or {}
        cards = selection.get("cards") or []
        if not cards:
            return PilotDecision(Sts2Action("select_deck_card", option_index=0))

        kind = str(selection.get("kind") or selection.get("type_name") or selection.get("type") or "").lower()
        prompt = str(selection.get("prompt") or "").lower()

        if "remove" in kind or "移除" in prompt:
            worst = min(cards, key=self._score_card)
            return PilotDecision(Sts2Action("select_deck_card", option_index=int(worst.get("index", 0))), f"这张{worst.get('name', '牌')}先删掉。")
        if "upgrade" in kind or "升级" in prompt:
            best = max(cards, key=self._score_upgrade_target)
            return PilotDecision(Sts2Action("select_deck_card", option_index=int(best.get("index", 0))), f"先把{best.get('name', '这张牌')}升上去。")
        if any(token in kind for token in ("transform", "enchant")) or any(token in prompt for token in ("变化", "变形", "附魔")):
            target = min(cards, key=self._score_card)
            return PilotDecision(Sts2Action("select_deck_card", option_index=int(target.get("index", 0))), f"这张{target.get('name', '牌')}价值最低，先处理它。")

        best = max(cards, key=self._score_card)
        return PilotDecision(Sts2Action("select_deck_card", option_index=int(best.get("index", 0))), f"我先选{best.get('name', '这张牌')}。")

    def _handle_treasure_relic(self, state: dict[str, Any]) -> PilotDecision:
        chest = state.get("chest") or {}
        relics = chest.get("relic_options") or []
        if not relics:
            return PilotDecision(Sts2Action("choose_treasure_relic", option_index=0), "先拿第一件遗物。", "闪闪")

        best = relics[0]
        return PilotDecision(
            Sts2Action("choose_treasure_relic", option_index=int(best.get("index", 0))),
            f"这件{best.get('name', '遗物')}先拿下。",
            "闪闪",
        )

    def _handle_event(self, state: dict[str, Any]) -> PilotDecision:
        event = state.get("event") or {}
        options = event.get("options") or []
        if not options:
            return PilotDecision(Sts2Action("choose_event_option", option_index=0), "事件先走第一项。")

        low_hp = self._hp_ratio(state) < 0.45

        def score(item: dict[str, Any]) -> tuple[int, int]:
            text = " ".join(str(item.get(key) or "") for key in ("label", "name", "description")).lower()
            value = 0
            if any(token in text for token in ("lose hp", "damage", "流血", "失去生命", "扣血")):
                value += 40 if low_hp else 12
            if any(token in text for token in ("gain", "获得", "remove", "删牌", "遗物", "金币")):
                value -= 10
            if any(token in text for token in ("leave", "跳过", "离开")):
                value += 5
            return value, int(item.get("index", 0))

        best = min(options, key=score)
        return PilotDecision(Sts2Action("choose_event_option", option_index=int(best.get("index", 0))), "事件房我先选更稳的一项。")

    def _handle_rest(self, state: dict[str, Any]) -> PilotDecision:
        rest = state.get("rest") or {}
        options = rest.get("options") or []
        low_hp = self._hp_ratio(state) < 0.45
        preferred_tokens = ("rest", "heal", "休息") if low_hp else ("smith", "upgrade", "锻造", "升级")

        for item in options:
            text = " ".join(str(item.get(key) or "") for key in ("name", "description")).lower()
            if any(token in text for token in preferred_tokens):
                return PilotDecision(Sts2Action("choose_rest_option", option_index=int(item.get("index", 0))))

        return PilotDecision(Sts2Action("choose_rest_option", option_index=0))

    def _handle_shop(self, state: dict[str, Any], actions: set[str]) -> PilotDecision:
        shop = state.get("shop") or {}
        shop_open = bool(shop.get("is_open") or shop.get("open"))
        has_affordable = self._shop_has_affordable_purchase(state)
        can_remove = self._shop_can_remove(state)

        if "remove_card_at_shop" in actions and can_remove:
            return PilotDecision(Sts2Action("remove_card_at_shop"), "能精简牌组就先精简。")
        if "buy_relic" in actions and has_affordable:
            return self._handle_buy_relic(state)
        if "buy_card" in actions and has_affordable:
            return self._handle_buy_card(state)
        if "buy_potion" in actions and has_affordable:
            return self._handle_buy_potion(state)

        if "close_shop_inventory" in actions:
            return PilotDecision(Sts2Action("close_shop_inventory"), "商店里没有合适的，先退出商品栏。")

        if "open_shop_inventory" in actions:
            if has_affordable or can_remove:
                return PilotDecision(Sts2Action("open_shop_inventory"), "我先仔细看看商店里能买什么。")
            if "proceed" in actions:
                return PilotDecision(Sts2Action("proceed"), "这家店当前买不起，继续赶路。", "闪闪")
            return PilotDecision(None)

        if shop_open and "proceed" in actions:
            return PilotDecision(Sts2Action("proceed"), "商店处理完了，继续前进。")
        if "proceed" in actions:
            return PilotDecision(Sts2Action("proceed"))
        return PilotDecision(None)

    def _handle_buy_relic(self, state: dict[str, Any]) -> PilotDecision:
        shop = state.get("shop") or {}
        relics = [item for item in shop.get("relics") or [] if self._is_affordable(state, item)]
        if not relics:
            return PilotDecision(None)
        best = relics[0]
        return PilotDecision(Sts2Action("buy_relic", option_index=int(best.get("index", 0))), "先买遗物，提升最直接。", "闪闪")

    def _handle_buy_card(self, state: dict[str, Any]) -> PilotDecision:
        shop = state.get("shop") or {}
        cards = [item for item in shop.get("cards") or [] if self._is_affordable(state, item)]
        if not cards:
            return PilotDecision(None)
        best = max(cards, key=self._score_card)
        return PilotDecision(Sts2Action("buy_card", option_index=int(best.get("index", 0))), f"我先买{best.get('name', '这张牌')}。")

    def _handle_buy_potion(self, state: dict[str, Any]) -> PilotDecision:
        shop = state.get("shop") or {}
        potions = [item for item in shop.get("potions") or [] if self._is_affordable(state, item)]
        if not potions:
            return PilotDecision(None)
        best = potions[0]
        return PilotDecision(Sts2Action("buy_potion", option_index=int(best.get("index", 0))))

    def _handle_use_potion(self, state: dict[str, Any]) -> PilotDecision:
        potions = [item for item in (state.get("run") or {}).get("potions") or [] if item.get("can_use")]
        if not potions:
            return PilotDecision(None)

        potion = potions[0]
        target_index = None
        targets = potion.get("valid_target_indices") or []
        if potion.get("requires_target"):
            target_index = int(targets[0]) if targets else None
            if target_index is None:
                return PilotDecision(None)

        return PilotDecision(
            Sts2Action("use_potion", option_index=int(potion.get("index", 0)), target_index=target_index),
            f"我先把{potion.get('name', '药水')}用掉。",
        )

    def _handle_discard_potion(self, state: dict[str, Any]) -> PilotDecision:
        potions = [item for item in (state.get("run") or {}).get("potions") or [] if item.get("can_discard")]
        if not potions:
            return PilotDecision(None)

        potion = min(potions, key=lambda item: (str(item.get("usage") or ""), int(item.get("index", 0))))
        return PilotDecision(
            Sts2Action("discard_potion", option_index=int(potion.get("index", 0))),
            f"{potion.get('name', '这瓶药')}先丢掉，给后面腾位置。",
        )

    def _handle_combat(self, state: dict[str, Any], actions: set[str]) -> PilotDecision:
        combat = state.get("combat") or {}
        hand = combat.get("hand") or []
        enemies = [enemy for enemy in combat.get("enemies") or [] if enemy.get("is_alive", True)]
        player = combat.get("player") or {}
        incoming_damage = self._incoming_damage(combat)
        current_block = int(player.get("block", 0) or 0)

        playable_cards = [card for card in hand if card.get("playable")]
        if not playable_cards:
            if "end_turn" in actions:
                return PilotDecision(Sts2Action("end_turn"), "这回合能做的不多，先过。")
            return PilotDecision(None)

        best_card = max(
            playable_cards,
            key=lambda card: self._score_combat_card(card, incoming_damage, current_block, enemies),
        )
        target_index = None
        if best_card.get("requires_target"):
            target_index = self._choose_enemy_target(best_card, enemies)

        speech = f"这张{best_card.get('name', '牌')}先打出去。"
        if incoming_damage >= 12:
            speech = "这回合伤害有点高，我得认真算一下。"

        return PilotDecision(
            Sts2Action("play_card", card_index=int(best_card.get("index", 0)), target_index=target_index),
            speech,
            "生气",
        )

    def _score_combat_card(
        self,
        card: dict[str, Any],
        incoming_damage: int,
        current_block: int,
        enemies: list[dict[str, Any]],
    ) -> int:
        score = 0
        name = str(card.get("name") or "")
        card_type = str(card.get("card_type") or "")
        rules_text = str(card.get("resolved_rules_text") or "")
        dynamic_values = card.get("dynamic_values") or []
        damage = self._find_dynamic_value(dynamic_values, "Damage")
        block = self._find_dynamic_value(dynamic_values, "Block")
        effective_incoming = max(0, incoming_damage - current_block)

        score += damage * 10
        score += min(block, effective_incoming) * 9
        score += max(0, block - effective_incoming) * 2
        score -= int(card.get("energy_cost", 0) or 0) * 3
        score -= int(card.get("star_cost", 0) or 0) * 2

        if any(max(0, int(enemy.get("current_hp", 0) or 0) - int(enemy.get("block", 0) or 0)) <= damage for enemy in enemies):
            score += 60
        if card_type == "Power":
            score += 40
        if "Bash" in name or "痛击" in name:
            score += 30
        if "易伤" in rules_text:
            score += 20
        if "力量" in rules_text:
            score += 18
        if ("Defend" in name or "防御" in name) and effective_incoming <= 0:
            score -= 20
        if card.get("costs_x") or card.get("star_costs_x"):
            score += 8
        return score

    @staticmethod
    def _find_dynamic_value(dynamic_values: list[dict[str, Any]], name: str) -> int:
        for value in dynamic_values:
            if value.get("name") == name:
                return int(value.get("current_value", 0) or 0)
        return 0

    @staticmethod
    def _incoming_damage(combat: dict[str, Any]) -> int:
        return sum(int(intent.get("total_damage", 0) or 0) for enemy in combat.get("enemies") or [] for intent in enemy.get("intents") or [])

    def _choose_enemy_target(self, card: dict[str, Any], enemies: list[dict[str, Any]]) -> int | None:
        if not enemies:
            return None

        damage = self._find_dynamic_value(card.get("dynamic_values") or [], "Damage")
        valid_target_indices = set(card.get("valid_target_indices") or [])
        targetable = [
            enemy
            for enemy in enemies
            if enemy.get("is_hittable", True) and (not valid_target_indices or int(enemy.get("index", -1)) in valid_target_indices)
        ]
        lethal_targets = [
            enemy
            for enemy in targetable
            if damage and max(0, int(enemy.get("current_hp", 0) or 0) - int(enemy.get("block", 0) or 0)) <= damage
        ]
        candidates = lethal_targets or targetable or enemies
        chosen = min(
            candidates,
            key=lambda enemy: (
                max(0, int(enemy.get("current_hp", 0) or 0) - int(enemy.get("block", 0) or 0)),
                -self._enemy_threat(enemy),
            ),
        )
        return int(chosen.get("index", 0))

    @staticmethod
    def _enemy_threat(enemy: dict[str, Any]) -> int:
        return sum(int(intent.get("total_damage", 0) or 0) for intent in enemy.get("intents") or [])

    @staticmethod
    def _score_card(card: dict[str, Any]) -> int:
        score = 0
        rarity = str(card.get("rarity") or "")
        card_type = str(card.get("card_type") or "")
        if rarity == "Rare":
            score += 100
        elif rarity == "Uncommon":
            score += 40
        elif rarity in {"Basic", "Starter"}:
            score -= 15

        if card_type == "Power":
            score += 25
        if card_type == "Curse":
            score -= 220
        if card_type == "Status":
            score -= 120

        damage = 0
        block = 0
        for dynamic in card.get("dynamic_values") or []:
            if dynamic.get("name") == "Damage":
                damage = int(dynamic.get("current_value", 0) or 0)
            elif dynamic.get("name") == "Block":
                block = int(dynamic.get("current_value", 0) or 0)
        score += damage * 8 + block * 6

        rules_text = str(card.get("resolved_rules_text") or "")
        for keyword in ("抽", "易伤", "虚弱", "力量", "能量", "格挡"):
            if keyword in rules_text:
                score += 10
        return score

    @classmethod
    def _score_upgrade_target(cls, card: dict[str, Any]) -> int:
        score = cls._score_card(card)
        name = str(card.get("name") or "")
        rules_text = str(card.get("resolved_rules_text") or "")
        if any(keyword in name for keyword in ("痛击", "Bash", "打击", "Strike")):
            score += 15
        if any(keyword in rules_text for keyword in ("易伤", "力量", "虚弱", "抽")):
            score += 20
        return score

    @staticmethod
    def _is_affordable(state: dict[str, Any], item: dict[str, Any]) -> bool:
        run = state.get("run") or {}
        gold = int(run.get("gold", 0) or 0)
        cost = int(item.get("price", item.get("cost", 0)) or 0)
        return gold >= cost

    @staticmethod
    def _hp_ratio(state: dict[str, Any]) -> float:
        run = state.get("run") or {}
        current_hp = int(run.get("current_hp", 0) or 0)
        max_hp = max(int(run.get("max_hp", 1) or 1), 1)
        return current_hp / max_hp

    @staticmethod
    def _is_shop_actions(actions: set[str]) -> bool:
        return any(
            action in actions
            for action in (
                "open_shop_inventory",
                "close_shop_inventory",
                "buy_relic",
                "buy_card",
                "buy_potion",
                "remove_card_at_shop",
            )
        )

    def _shop_has_affordable_purchase(self, state: dict[str, Any]) -> bool:
        shop = state.get("shop") or {}
        for bucket in ("cards", "relics", "potions"):
            for item in shop.get(bucket) or []:
                if self._is_affordable(state, item) and item.get("is_stocked", True):
                    return True
        return False

    def _shop_can_remove(self, state: dict[str, Any]) -> bool:
        removal = (state.get("shop") or {}).get("card_removal") or {}
        if removal.get("available") is False:
            return False
        if removal.get("used") is True:
            return False
        cost = int(removal.get("price", 0) or 0)
        gold = int((state.get("run") or {}).get("gold", 0) or 0)
        return gold >= cost
