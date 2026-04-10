from __future__ import annotations

import base64
import os
import subprocess
import threading
import time
from typing import Iterable

import numpy as np
import soundfile as sf

from config import Global


def _encode_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def _resample_int16(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate or len(audio) == 0:
        return audio.astype(np.int16, copy=False)

    duration = len(audio) / float(source_rate)
    target_length = max(int(round(duration * target_rate)), 1)
    source_positions = np.linspace(0.0, len(audio) - 1, num=len(audio), dtype=np.float32)
    target_positions = np.linspace(0.0, len(audio) - 1, num=target_length, dtype=np.float32)
    resampled = np.interp(target_positions, source_positions, audio.astype(np.float32))
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def _split_subtitle_chunks(text: str, max_chunk_chars: int = 10) -> list[str]:
    pieces: list[str] = []
    buffer = ""
    punctuations = "，。！？；,.!?~…"

    for char in text:
        buffer += char
        if char in punctuations or len(buffer) >= max_chunk_chars:
            stripped = buffer.strip()
            if stripped:
                pieces.append(stripped)
            buffer = ""

    if buffer.strip():
        pieces.append(buffer.strip())

    return pieces or [text.strip() or "..."]


def _assign_audio_segments(audio: np.ndarray, pieces: Iterable[str]) -> list[tuple[np.ndarray, tuple[str, str] | None]]:
    parts = list(pieces)
    if len(audio) == 0:
        return [(np.zeros(1, dtype=np.int16), ("", "".join(parts)))]

    boundaries = np.linspace(0, len(audio), num=len(parts) + 1, dtype=np.int64)
    scheduled: list[tuple[np.ndarray, tuple[str, str] | None]] = []
    prefix = ""

    for index, piece in enumerate(parts):
        start = int(boundaries[index])
        end = int(boundaries[index + 1])
        if end <= start:
            end = min(start + 1, len(audio))
        segment = audio[start:end]
        subtitle = (prefix, piece)
        prefix += piece
        scheduled.append((segment, subtitle))

    return scheduled


class StreamSpeaker:
    def __init__(self, settings: dict):
        self._settings = settings["streamer"]
        self._sample_rate = int(self._settings.get("sample_rate", 24000))
        self._tts_engine = str(self._settings.get("tts_engine", "system_sapi")).strip().lower()
        self._tts_voice = str(self._settings.get("tts_voice", "")).strip()
        self._tts_rate = int(self._settings.get("tts_rate", 0))
        self._tts_volume = int(self._settings.get("tts_volume", 100))
        self._temp_dir = self._settings["temp_dir"]
        self._speech_gap_seconds = float(self._settings.get("speech_gap_seconds", 0.4))
        self._lock = threading.Lock()
        self._sequence = 0
        os.makedirs(self._temp_dir, exist_ok=True)

    def speak(
        self,
        text: str,
        *,
        mood: str | None = None,
        expression: str | None = None,
        source: str | None = None,
    ) -> None:
        cleaned = " ".join((text or "").split()).strip()
        if not cleaned:
            return

        with self._lock:
            self._sequence += 1
            if expression:
                self._set_expression(expression)

            bubble_text = cleaned if len(cleaned) <= 40 else cleaned[:37] + "..."
            if getattr(Global, "bubble_widget", None) is not None:
                Global.bubble_widget.show_bubble(bubble_text)

            try:
                if self._tts_engine == "system_sapi":
                    self._speak_via_sapi(cleaned)
                else:
                    self._show_text_only(cleaned)
            except Exception as exc:
                print(f"[streamer] TTS fallback to subtitles: {exc}")
                self._show_text_only(cleaned)

            time.sleep(self._speech_gap_seconds)

    def _set_expression(self, expression: str) -> None:
        if not getattr(Global, "exp_queue", None):
            return
        if expression in getattr(Global, "exp_params", {}):
            Global.exp_queue.put(expression)

    def _speak_via_sapi(self, text: str) -> None:
        wav_path = os.path.join(self._temp_dir, f"speech_{int(time.time() * 1000)}_{self._sequence}.wav")
        self._synthesize_to_wave(text, wav_path)

        audio, sample_rate = sf.read(wav_path, dtype="int16", always_2d=False)
        if isinstance(audio, np.ndarray) and audio.ndim > 1:
            audio = audio[:, 0]
        audio = np.asarray(audio, dtype=np.int16)
        audio = _resample_int16(audio, int(sample_rate), self._sample_rate)
        self._enqueue_audio_with_subtitles(text, audio)

    def _synthesize_to_wave(self, text: str, wav_path: str) -> None:
        text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        voice_b64 = base64.b64encode(self._tts_voice.encode("utf-8")).decode("ascii")
        wav_b64 = base64.b64encode(wav_path.encode("utf-8")).decode("ascii")

        script = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$text = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{text_b64}'))
$voiceName = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{voice_b64}'))
$wavPath = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{wav_b64}'))
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($voiceName) {{
    $synth.SelectVoice($voiceName)
}}
$synth.Rate = {self._tts_rate}
$synth.Volume = {self._tts_volume}
$synth.SetOutputToWaveFile($wavPath)
$synth.Speak($text)
$synth.Dispose()
"""

        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                _encode_powershell(script),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _enqueue_audio_with_subtitles(self, text: str, audio: np.ndarray) -> None:
        if getattr(Global, "audio_queue", None) is None:
            self._show_text_only(text)
            return

        queue_id = int(time.time() * 1000) + self._sequence
        Global.audio_queue.create(queue_id)

        for chunk, subtitle in _assign_audio_segments(audio, _split_subtitle_chunks(text)):
            Global.audio_queue.add(queue_id, chunk, subtitle)

        Global.audio_queue.add(queue_id, None, None)

    def _show_text_only(self, text: str) -> None:
        if getattr(Global, "animator2", None) is not None:
            Global.animator2.cancel_fade_out()
        if getattr(Global, "func_queue2", None) is not None and getattr(Global, "animator1", None) is not None:
            Global.func_queue2.add(Global.animator1.animate_subtitle, ("", text))
        if getattr(Global, "animator2", None) is not None:
            Global.animator2.schedule_fade_out()
