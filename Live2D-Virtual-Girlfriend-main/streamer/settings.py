from __future__ import annotations

import os
from copy import deepcopy

from config import Global

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKSPACE_ROOT = os.path.abspath(os.path.join(ROOT_DIR, ".."))

DEFAULT_STREAMER = {
    "sample_rate": 24000,
    "tts_engine": "system_sapi",
    "tts_voice": "",
    "tts_rate": 0,
    "tts_volume": 100,
    "speech_gap_seconds": 0.4,
    "dedupe_window_seconds": 12.0,
    "temp_dir": os.path.join("temp", "streamer"),
    "api_host": "127.0.0.1",
    "api_port": 9988,
    "welcome_line": "直播系统已启动，准备开始爬塔。",
}

DEFAULT_STS2 = {
    "enable": True,
    "auto_launch_game": True,
    "auto_install_mod": True,
    "resume_existing_run": False,
    "api_base_url": "http://127.0.0.1:8080",
    "preferred_character": "IRONCLAD",
    "poll_interval_seconds": 1.1,
    "action_interval_seconds": 0.8,
    "game_exe": "",
    "game_root": "",
    "sts2_project_root": "",
    "mod_source_dir": "",
}

DEFAULT_BILIBILI = {
    "enable": False,
    "room_id": 0,
    "sessdata": "",
    "reply_probability": 0.35,
    "min_seconds_between_replies": 18.0,
}


def _merge_defaults(defaults: dict, override: object) -> dict:
    result = deepcopy(defaults)
    if isinstance(override, dict):
        result.update(override)
    return result


def resolve_path(path_value: str | None, base_dir: str = ROOT_DIR) -> str:
    if not path_value:
        return ""
    if os.path.isabs(path_value):
        return os.path.normpath(path_value)
    return os.path.normpath(os.path.join(base_dir, path_value))


def _guess_sts2_project_root() -> str:
    candidates = [
        os.path.join(WORKSPACE_ROOT, "STS2-Agent-main"),
        os.path.join(ROOT_DIR, "..", "STS2-Agent-main"),
    ]
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        if os.path.isdir(candidate):
            return candidate
    return ""


def _guess_mod_source_dir(sts2_project_root: str) -> str:
    candidates = [
        os.path.join(WORKSPACE_ROOT, "sts2-release-v0.5.4", "mod"),
        os.path.join(sts2_project_root, "build", "mods", "STS2AIAgent"),
        os.path.join(sts2_project_root, "release", "mod"),
    ]
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        if os.path.isdir(candidate):
            return candidate
    return ""


def load_settings() -> dict:
    streamer = _merge_defaults(DEFAULT_STREAMER, getattr(Global, "streamer", {}))
    sts2 = _merge_defaults(DEFAULT_STS2, getattr(Global, "sts2_stream", {}))
    bilibili = _merge_defaults(DEFAULT_BILIBILI, getattr(Global, "bilibili", {}))

    streamer["temp_dir"] = resolve_path(streamer.get("temp_dir"))

    sts2["sts2_project_root"] = resolve_path(sts2.get("sts2_project_root")) or _guess_sts2_project_root()
    sts2["game_exe"] = resolve_path(sts2.get("game_exe"))
    sts2["game_root"] = resolve_path(sts2.get("game_root"))
    if not sts2["game_root"] and sts2["game_exe"]:
        sts2["game_root"] = os.path.dirname(sts2["game_exe"])

    sts2["mod_source_dir"] = resolve_path(sts2.get("mod_source_dir"))
    if not sts2["mod_source_dir"]:
        sts2["mod_source_dir"] = _guess_mod_source_dir(sts2["sts2_project_root"])

    return {
        "root_dir": ROOT_DIR,
        "workspace_root": WORKSPACE_ROOT,
        "streamer": streamer,
        "sts2": sts2,
        "bilibili": bilibili,
    }
