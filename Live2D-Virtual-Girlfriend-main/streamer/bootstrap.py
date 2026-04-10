from __future__ import annotations

import json
import os
import sys
from queue import Queue
from types import SimpleNamespace

from config import Global
from src.tts import AudioQueue


def apply_stream_defaults() -> None:
    Global.input_box = False
    Global.always_screenshot = False
    Global.initiative_wait_range = "none"
    Global.load_model = False

    if getattr(Global, "rvc", None) is None:
        Global.rvc = SimpleNamespace(playing=False, ok=False)

    if getattr(Global, "sing", None) is None:
        Global.sing = {"volume": 0.7, "max_rms_scale": 0.2, "pitch_threshold": 260}


def _safe_load_json(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_expression_assets() -> None:
    Global.exp_queue = Queue()

    exp_path = Global.character.get("exp")
    Global.exp_map = _safe_load_json(exp_path) if exp_path else {}
    if isinstance(Global.exp_map, dict):
        Global.exp_map.setdefault("正常", "正常表情")
    else:
        Global.exp_map = {"正常": "正常表情"}

    live2d_model = Global.character["live2d_model"]
    dirname = os.path.dirname(live2d_model)
    basename = os.path.basename(live2d_model)
    cdi3_path = os.path.join(dirname, basename.split(".")[0] + ".cdi3.json")
    cdi3_json = _safe_load_json(cdi3_path)

    Global.parts = {}
    for item in cdi3_json.get("Parts", []):
        part_id = item.get("Id")
        part_name = item.get("Name")
        if part_id and part_name:
            Global.parts[part_id] = part_name

    Global.exp_params = {}
    expressions_path = os.path.join(dirname, "expressions")
    if os.path.isdir(expressions_path):
        for filename in os.listdir(expressions_path):
            if not filename.endswith(".json"):
                continue
            exp_json = _safe_load_json(os.path.join(expressions_path, filename))
            parameters = exp_json.get("Parameters", [])
            if not parameters:
                continue
            param = parameters[0]
            param_id = param.get("Id")
            param_value = param.get("Value")
            if param_id is None or param_value is None:
                continue
            Global.exp_params[filename.split(".")[0]] = [param_id, param_value]


def initialize_stream_runtime(win, settings: dict) -> None:
    _load_expression_assets()

    if "watermark" in Global.character:
        win.model.SetParameterValue(Global.character["watermark"], 1, 1)

    sample_rate = int(settings["streamer"].get("sample_rate", 24000))
    Global.audio_queue = AudioQueue(win.model, sample_rate=sample_rate)
    Global.win = win


def ensure_sts2_import_path(settings: dict) -> str | None:
    sts2_root = settings["sts2"].get("sts2_project_root") or ""
    candidates = [
        os.path.join(sts2_root, "mcp_server", "src"),
        os.path.join(settings["workspace_root"], "STS2-Agent-main", "mcp_server", "src"),
    ]

    for candidate in candidates:
        if not candidate:
            continue
        candidate = os.path.abspath(candidate)
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)
            return candidate

    return None
