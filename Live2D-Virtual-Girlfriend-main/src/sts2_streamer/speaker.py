from __future__ import annotations

import asyncio
import base64
import itertools
import os
import subprocess
import tempfile
from pathlib import Path
from queue import Queue
from threading import Thread

import numpy as np
import soundfile as sf

from config import Global
try:
    import edge_tts
except Exception:  # pragma: no cover - optional dependency
    edge_tts = None

from .config import StreamerSettings


class PersonaSpeaker:
    def __init__(self, settings: StreamerSettings) -> None:
        self.settings = settings
        self.queue: Queue[tuple[str, str | None]] = Queue()
        self.counter = itertools.count(1)
        Thread(target=self._worker, daemon=True).start()

    def say(self, text: str, exp: str | None = None) -> None:
        text = (text or "").strip()
        if text:
            self.queue.put((text, exp))

    def _worker(self) -> None:
        while True:
            text, exp = self.queue.get()
            try:
                if exp:
                    Global.exp_queue.put(exp)
                Global.sounds_player.play("click.wav")
                Global.bubble_widget.show_bubble(text)
                self._enqueue_wav(self._synthesize(text), subtitle=text)
            except Exception as exc:  # pragma: no cover - runtime logging
                print(f"[sts2_streamer] speech failed: {exc}")

    def _synthesize(self, text: str) -> Path:
        backend = (self.settings.tts_backend or "edge").lower()
        if backend in {"auto", "edge"}:
            try:
                return self._synthesize_edge(text)
            except Exception as exc:
                print(f"[sts2_streamer] edge tts failed, falling back to sapi: {exc}")

        return self._synthesize_sapi(text)

    def _synthesize_edge(self, text: str) -> Path:
        if edge_tts is None:
            raise RuntimeError("edge-tts is not installed.")

        output_dir = Path("temp")
        output_dir.mkdir(exist_ok=True)
        fd, wav_path = tempfile.mkstemp(prefix="sts2_vtuber_", suffix=".wav", dir=output_dir)
        os.close(fd)
        voice = (self.settings.default_voice or "").strip() or "zh-CN-XiaoxiaoNeural"
        rate = self._edge_rate()
        volume = self._edge_volume()
        asyncio.run(edge_tts.Communicate(text=text, voice=voice, rate=rate, volume=volume).save(wav_path))
        return Path(wav_path)

    def _synthesize_sapi(self, text: str) -> Path:
        output_dir = Path("temp")
        output_dir.mkdir(exist_ok=True)
        fd, wav_path = tempfile.mkstemp(prefix="sts2_vtuber_", suffix=".wav", dir=output_dir)
        os.close(fd)

        text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        path_b64 = base64.b64encode(str(wav_path).encode("utf-8")).decode("ascii")
        voice_name = (self.settings.default_voice or "").strip() or getattr(Global, "local_tts_voice", "")
        voice_b64 = base64.b64encode(voice_name.encode("utf-8")).decode("ascii")

        script = f"""
Add-Type -AssemblyName System.Speech
$text = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{text_b64}'))
$path = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{path_b64}'))
$voice = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{voice_b64}'))
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($voice) {{
  try {{ $synth.SelectVoice($voice) }} catch {{ }}
}}
$synth.Rate = {self.settings.speech_rate}
$synth.Volume = {self.settings.speech_volume}
$synth.SetOutputToWaveFile($path)
$synth.Speak($text)
$synth.Dispose()
"""
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return Path(wav_path)

    def _edge_rate(self) -> str:
        step = int(self.settings.speech_rate)
        percent = max(-50, min(100, step * 10))
        return f"{percent:+d}%"

    def _edge_volume(self) -> str:
        volume = int(self.settings.speech_volume)
        delta = max(-100, min(100, volume - 100))
        return f"{delta:+d}%"

    def _enqueue_wav(self, wav_path: Path, subtitle: str) -> None:
        audio, sample_rate = sf.read(wav_path, dtype="int16")
        if audio.ndim > 1:
            audio = audio.mean(axis=1).astype("int16")

        target_rate = Global.audio_queue.sample_rate
        if sample_rate != target_rate and len(audio) > 0:
            audio = self._resample(audio, sample_rate, target_rate)

        idx = next(self.counter)
        Global.audio_queue.create(idx)
        chunk_size = 2048
        first_chunk = True
        for start in range(0, len(audio), chunk_size):
            chunk = np.ascontiguousarray(audio[start:start + chunk_size])
            chunk_subtitle = ("", subtitle) if first_chunk else None
            first_chunk = False
            Global.audio_queue.add(idx, chunk, chunk_subtitle)
        Global.audio_queue.add(idx, None, None)

    @staticmethod
    def _resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        if source_rate == target_rate or len(audio) == 0:
            return audio.astype("int16")

        duration = len(audio) / float(source_rate)
        target_length = max(1, int(duration * target_rate))
        source_x = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        target_x = np.linspace(0.0, 1.0, num=target_length, endpoint=False)
        resampled = np.interp(target_x, source_x, audio.astype(np.float32))
        return np.clip(resampled, -32768, 32767).astype("int16")
