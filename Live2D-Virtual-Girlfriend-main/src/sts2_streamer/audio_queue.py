from __future__ import annotations

import time
from queue import Queue
from threading import Thread

import numpy as np
import sounddevice as sd

from animator.animator import LipSyncHandler
from config import Global


class AudioQueueLite:
    def __init__(self, model, sample_rate: int = 24000) -> None:
        self.q: dict[int, Queue] = {}
        self.model = model
        self.sample_rate = sample_rate
        self.lip_sync = LipSyncHandler()
        self.stream = sd.OutputStream(samplerate=self.sample_rate, channels=1, dtype=np.int16)
        self.stream.start()
        Thread(target=self.process, daemon=True).start()

    def process(self) -> None:
        while True:
            while not self.q:
                time.sleep(0.01)
            idx = list(self.q.keys())[0]

            Global.animator2.cancel_fade_out()

            while self.q:
                audio_chunk, subtitle = self.q[idx].get()
                if audio_chunk is None:
                    del self.q[idx]
                    if self.q:
                        idx = list(self.q.keys())[0]
                        time.sleep(0.2)
                        continue
                    break

                if not Global.exp_queue.empty():
                    exp_name = Global.exp_queue.get()
                    if exp_name in Global.exp_params:
                        Global.sounds_player.play("exp.wav")
                        Global.expression_animator.add(Global.exp_params[exp_name], Global.exp_fadeout)

                if subtitle:
                    Global.func_queue2.add(Global.animator1.animate_subtitle, subtitle)
                self.stream.write(audio_chunk)
                self.lip_sync.update_mouth_sync(audio_chunk)

            Global.animator2.schedule_fade_out()
            self.model.SetParameterValue("ParamMouthOpenY", 0.0)

    def create(self, idx: int) -> None:
        self.q[idx] = Queue()

    def add(self, idx: int, audio_chunk, subtitle) -> None:
        self.q[idx].put((audio_chunk, subtitle))
