import atexit
import json
import os
import sys
import time
from pathlib import Path
from queue import Queue


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.sts2_streamer.toml"
os.chdir(ROOT_DIR)

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if "LIVE2D_CONFIG_PATH" not in os.environ and DEFAULT_CONFIG_PATH.exists():
    os.environ["LIVE2D_CONFIG_PATH"] = str(DEFAULT_CONFIG_PATH)

import live2d.v3 as live2d
from PyQt5.QtWidgets import QApplication

from config import Global
from gui.gui import Live2DCanvas
from src.sts2_streamer import StreamerRuntime, load_streamer_settings
from src.sts2_streamer.audio_queue import AudioQueueLite
from src.sts2_streamer.control_api import ControlApiServer
from src.sts2_streamer.speaker import PersonaSpeaker


class _DummyRvc:
    playing = False


def _load_character_metadata() -> None:
    Global.exp_queue = Queue()

    if Global.character.get("watermark"):
        Global.model.SetParameterValue(Global.character["watermark"], 1, 1)

    live2d_model = Global.character["live2d_model"]
    dirname = os.path.dirname(live2d_model)
    basename = os.path.basename(live2d_model)
    cdi3_path = os.path.join(dirname, basename.split(".")[0] + ".cdi3.json")
    with open(cdi3_path, "r", encoding="utf-8") as handle:
        cdi3_json = json.load(handle)
    Global.parts = {item["Id"]: item["Name"] for item in cdi3_json["Parts"]}

    Global.exp_params = {}
    expressions_path = os.path.join(dirname, "expressions")
    if os.path.exists(expressions_path):
        for filename in os.listdir(expressions_path):
            if not filename.endswith(".json"):
                continue
            exp_path = os.path.join(expressions_path, filename)
            with open(exp_path, "r", encoding="utf-8") as handle:
                exp_json = json.load(handle)
            Global.exp_params[filename.split(".")[0]] = [
                exp_json["Parameters"][0]["Id"],
                exp_json["Parameters"][0]["Value"],
            ]


def _wait_for_model(app: QApplication, window: Live2DCanvas) -> None:
    deadline = time.time() + 10.0
    while window.model is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    if window.model is None:
        raise RuntimeError("Live2D model did not initialize in time.")


if __name__ == "__main__":
    Global.load_model = False
    Global.input_box = False
    Global.initiative_wait_range = "none"
    Global.rvc = _DummyRvc()

    settings = load_streamer_settings()
    if not Path(settings.game_exe_path).exists():
        raise FileNotFoundError(f"STS2 game executable not found: {settings.game_exe_path}")

    live2d.init()
    app = QApplication(sys.argv)
    window = Live2DCanvas()
    window.show()
    Global.win = window

    _wait_for_model(app, window)
    _load_character_metadata()

    Global.audio_queue = AudioQueueLite(window.model, sample_rate=24000)

    speaker = PersonaSpeaker(settings)
    runtime = StreamerRuntime(settings, speaker)
    control_api = ControlApiServer(runtime, speaker, host=settings.controller_host, port=settings.controller_port)
    atexit.register(runtime.stop)
    app.aboutToQuit.connect(runtime.stop)
    runtime.start()
    control_api.start()

    sys.exit(app.exec())
