from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
VALID_LLM_SECTIONS = {"required", "auxiliary"}


def _config_module():
    return importlib.import_module("config.config")


def _raw_config() -> dict:
    module = _config_module()
    return getattr(module, "config", {})


def _resolve_path(value: str | None) -> str:
    if not value:
        return ""
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((PROJECT_ROOT / path).resolve())


def _detect_game_exe() -> str:
    candidates = [
        os.getenv("STS2_GAME_EXE", "").strip(),
        r"F:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.exe",
        r"C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2\SlayTheSpire2.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return candidates[0] or r"F:\SteamLibrary\steamapps\common\Slay the Spire 2\SlayTheSpire2.exe"


def _detect_sts2_project_root() -> str:
    candidates = [
        os.getenv("STS2_PROJECT_ROOT", "").strip(),
        str((WORKSPACE_ROOT / "STS2-Agent-main").resolve()),
        str((PROJECT_ROOT / "STS2-Agent-main").resolve()),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return candidate
    return ""


def _detect_mod_source_dir(sts2_project_root: str) -> str:
    candidates = [os.getenv("STS2_MOD_SOURCE_DIR", "").strip()]
    if sts2_project_root:
        project_root = Path(sts2_project_root)
        candidates.extend(
            [
                str((project_root / "build" / "mods" / "STS2AIAgent").resolve()),
                str((project_root / "release" / "mod").resolve()),
                str((project_root / "mod").resolve()),
            ]
        )
    candidates.append(str((WORKSPACE_ROOT / "sts2-release-v0.5.4" / "mod").resolve()))

    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return candidate
    return ""


def _detect_start_script(sts2_project_root: str) -> str:
    if not sts2_project_root:
        return ""
    candidate = Path(sts2_project_root) / "scripts" / "start-game-session.ps1"
    if candidate.exists():
        return str(candidate.resolve())
    return ""


def _normalize_llm_section(value: str | None, default: str) -> str:
    name = str(value or default).strip().lower()
    return name if name in VALID_LLM_SECTIONS else default


@dataclass(slots=True)
class StreamerSettings:
    api_base_url: str
    game_exe_path: str
    auto_launch_game: bool
    auto_install_mod: bool
    enable_debug_actions: bool
    launch_via_steam: bool
    steam_app_id: str
    steam_executable_path: str
    resume_existing_run: bool
    auto_play: bool
    auto_commentary: bool
    poll_interval_seconds: float
    action_cooldown_seconds: float
    commentary_cooldown_seconds: float
    room_reply_cooldown_seconds: float
    bilibili_reply_probability: float
    bilibili_enabled: bool
    bilibili_room_id: int | None
    bilibili_max_queue: int
    preferred_character_index: int
    preferred_character_name: str
    tts_backend: str
    default_voice: str | None
    speech_rate: int
    speech_volume: int
    llm_enabled: bool
    llm_action_section: str
    llm_commentary_section: str
    llm_danmaku_section: str
    llm_use_for_actions: bool
    llm_use_for_commentary: bool
    llm_use_for_danmaku: bool
    llm_use_for_action_commentary: bool
    llm_use_for_action_followup: bool
    llm_timeout_seconds: float
    llm_max_context_chars: int
    sts2_project_root: str
    mod_source_dir: str
    start_script_path: str
    controller_host: str
    controller_port: int
    welcome_line: str

    @property
    def game_root(self) -> Path:
        return Path(self.game_exe_path).resolve().parent

    @property
    def mod_source_path(self) -> Path | None:
        if not self.mod_source_dir:
            return None
        path = Path(self.mod_source_dir)
        return path if path.exists() else None

    @property
    def start_script(self) -> Path | None:
        if not self.start_script_path:
            return None
        path = Path(self.start_script_path)
        return path if path.exists() else None


def load_streamer_settings() -> StreamerSettings:
    config = _raw_config()
    section = config.get("sts2_streamer") or {}
    room_id = section.get("bilibili_room_id")
    try:
        parsed_room_id = int(room_id) if room_id not in (None, "", 0) else None
    except (TypeError, ValueError):
        parsed_room_id = None

    sts2_project_root = _resolve_path(section.get("sts2_project_root")) or _detect_sts2_project_root()
    mod_source_dir = _resolve_path(section.get("mod_source_dir")) or _detect_mod_source_dir(sts2_project_root)
    start_script_path = _resolve_path(section.get("start_game_script")) or _detect_start_script(sts2_project_root)

    preferred_character_name = str(section.get("preferred_character_name", "IRONCLAD")).strip().upper()
    controller_host = str(section.get("controller_host", config.get("controller_host", "127.0.0.1")))
    controller_port = int(section.get("controller_port", config.get("controller_port", 19098)))
    welcome_line = str(section.get("welcome_line", "直播模式已连接，准备开始爬塔。")).strip()
    tts_backend = str(section.get("tts_backend", "edge")).strip().lower() or "edge"
    if tts_backend not in {"auto", "edge", "sapi"}:
        tts_backend = "edge"

    return StreamerSettings(
        api_base_url=str(section.get("api_base_url", os.getenv("STS2_API_BASE_URL", "http://127.0.0.1:8080"))).rstrip("/"),
        game_exe_path=_resolve_path(section.get("game_exe_path")) or _detect_game_exe(),
        auto_launch_game=bool(section.get("auto_launch_game", True)),
        auto_install_mod=bool(section.get("auto_install_mod", True)),
        enable_debug_actions=bool(section.get("enable_debug_actions", False)),
        launch_via_steam=bool(section.get("launch_via_steam", True)),
        steam_app_id=str(section.get("steam_app_id", "2868840")).strip() or "2868840",
        steam_executable_path=_resolve_path(section.get("steam_executable_path")),
        resume_existing_run=bool(section.get("resume_existing_run", False)),
        auto_play=bool(section.get("auto_play", True)),
        auto_commentary=bool(section.get("auto_commentary", True)),
        poll_interval_seconds=float(section.get("poll_interval_seconds", 0.8)),
        action_cooldown_seconds=float(section.get("action_cooldown_seconds", 1.0)),
        commentary_cooldown_seconds=float(section.get("commentary_cooldown_seconds", 4.0)),
        room_reply_cooldown_seconds=float(section.get("room_reply_cooldown_seconds", 10.0)),
        bilibili_reply_probability=float(section.get("bilibili_reply_probability", 0.35)),
        bilibili_enabled=bool(section.get("bilibili_enabled", False)),
        bilibili_room_id=parsed_room_id,
        bilibili_max_queue=int(section.get("bilibili_max_queue", 20)),
        preferred_character_index=int(section.get("preferred_character_index", 0)),
        preferred_character_name=preferred_character_name,
        tts_backend=tts_backend,
        default_voice=section.get("default_voice"),
        speech_rate=int(section.get("speech_rate", 1)),
        speech_volume=int(section.get("speech_volume", 100)),
        llm_enabled=bool(section.get("llm_enabled", True)),
        llm_action_section=_normalize_llm_section(section.get("llm_action_section"), "required"),
        llm_commentary_section=_normalize_llm_section(section.get("llm_commentary_section"), "auxiliary"),
        llm_danmaku_section=_normalize_llm_section(section.get("llm_danmaku_section"), "auxiliary"),
        llm_use_for_actions=bool(section.get("llm_use_for_actions", True)),
        llm_use_for_commentary=bool(section.get("llm_use_for_commentary", True)),
        llm_use_for_danmaku=bool(section.get("llm_use_for_danmaku", True)),
        llm_use_for_action_commentary=bool(section.get("llm_use_for_action_commentary", True)),
        llm_use_for_action_followup=bool(section.get("llm_use_for_action_followup", True)),
        llm_timeout_seconds=float(section.get("llm_timeout_seconds", 8.0)),
        llm_max_context_chars=int(section.get("llm_max_context_chars", 6000)),
        sts2_project_root=sts2_project_root,
        mod_source_dir=mod_source_dir,
        start_script_path=start_script_path,
        controller_host=controller_host,
        controller_port=controller_port,
        welcome_line=welcome_line,
    )
