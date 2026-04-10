import logging
import os
import sys
import time
from pathlib import Path
from threading import Thread

ROOT_DIR = Path(__file__).resolve().parent
os.chdir(ROOT_DIR)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.sts2_streamer.toml"
if "LIVE2D_CONFIG_PATH" not in os.environ and DEFAULT_CONFIG_PATH.exists():
    os.environ["LIVE2D_CONFIG_PATH"] = str(DEFAULT_CONFIG_PATH)

import live2d.v3 as live2d
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from PyQt5.QtWidgets import QApplication

from config import Global
from gui.gui import Live2DCanvas
from src.local_speech import speak_text
from src.tts import AudioQueue
from utils.func_queue import FuncQueue
from utils.other import terminate_thread


class DummyRvc:
    ok = False
    playing = False


class SpeakRequest(BaseModel):
    text: str
    expression: str | None = None
    interrupt: bool = True


class AvatarController:
    def interrupt_output(self):
        if getattr(Global, "animator2", None):
            Global.animator2.schedule_fade_out()

        if getattr(Global, "func_queue1", None) and Global.func_queue1.t:
            for thread in Global.func_queue1.t:
                terminate_thread(thread)
            Global.func_queue1.__init__()

        if getattr(Global, "audio_queue", None) and Global.audio_queue.q:
            Global.audio_queue.q = {}

        if Global.send_text_thread:
            terminate_thread(Global.send_text_thread)
            Global.send_text_thread = None

        if Global.sing_song_thread and getattr(Global, "rvc", None) and Global.rvc.playing:
            terminate_thread(Global.sing_song_thread)
            Global.sing_song_thread = None

    def speak(self, text=None, img=None, tool=True, web=False, expression=None, interrupt=True):
        if not text:
            return False

        if interrupt:
            self.interrupt_output()

        return speak_text(text, expression=expression)


controller = AvatarController()
api = FastAPI(title="Live2D Avatar Runtime")


@api.get("/health")
def health():
    return {
        "ok": True,
        "ready": getattr(Global, "audio_queue", None) is not None,
        "character": Global.character["name"],
        "config_path": getattr(Global, "character_toml", None),
        "voice": getattr(Global, "local_tts_voice", "Microsoft Huihui Desktop"),
    }


@api.post("/interrupt")
def interrupt():
    controller.interrupt_output()
    return {"ok": True}


@api.post("/speak")
def speak(request: SpeakRequest):
    if not getattr(Global, "audio_queue", None):
        raise HTTPException(status_code=503, detail="Audio queue is not ready yet.")

    ok = controller.speak(
        text=request.text,
        expression=request.expression,
        interrupt=request.interrupt,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to synthesize speech.")

    return {"ok": True}


def run_api():
    logging.getLogger("uvicorn").setLevel(logging.ERROR)
    logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
    host = getattr(Global, "controller_host", "127.0.0.1")
    port = int(getattr(Global, "controller_port", 19098))
    uvicorn.run(api, host=host, port=port, log_level="error")


def wait_for_model(qt_app, win, timeout=10.0):
    deadline = time.time() + timeout
    while win.model is None and time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.05)

    if win.model is None:
        raise RuntimeError("Live2D model initialization timed out.")


if __name__ == "__main__":
    live2d.init()
    qt_app = QApplication(sys.argv)
    win = Live2DCanvas()
    win.show()
    Global.win = win

    wait_for_model(qt_app, win)

    if "voice" in Global.character:
        Global.audio_queue = AudioQueue(win.model, sample_rate=24000)
    else:
        Global.audio_queue = AudioQueue(win.model, sample_rate=32000)

    Global.func_queue3 = FuncQueue()
    Global.rvc = DummyRvc()
    Global.my_agent = controller
    Global.send_audio_text = controller.speak

    Thread(target=run_api, daemon=True).start()

    sys.exit(qt_app.exec())
