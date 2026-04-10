import base64
import os
import random
import subprocess
import tempfile

import numpy as np
import soundfile as sf

from config import Global


def _resample_int16(audio, src_rate, dst_rate):
    if src_rate == dst_rate or len(audio) == 0:
        return audio.astype(np.int16, copy=False)

    duration = len(audio) / float(src_rate)
    dst_len = max(1, int(round(duration * dst_rate)))
    src_idx = np.linspace(0, len(audio) - 1, num=len(audio), dtype=np.float64)
    dst_idx = np.linspace(0, len(audio) - 1, num=dst_len, dtype=np.float64)
    resampled = np.interp(dst_idx, src_idx, audio.astype(np.float32))
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def _synthesize_wav(text, output_path, voice_name, rate, volume):
    text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    voice_name = voice_name.replace("'", "''")
    script = f"""
Add-Type -AssemblyName System.Speech
$text = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{text_b64}'))
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
    $synth.SelectVoice('{voice_name}')
}} catch {{
}}
$synth.Rate = {int(rate)}
$synth.Volume = {int(volume)}
$synth.SetOutputToWaveFile('{output_path}')
$synth.Speak($text)
$synth.Dispose()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
    )


def speak_text(text, expression=None, voice_name=None, rate=None, volume=None):
    if not text or not getattr(Global, "audio_queue", None):
        return False

    if expression and getattr(Global, "exp_params", None) and expression in Global.exp_params:
        Global.exp_queue.put(expression)

    voice_name = voice_name or getattr(Global, "local_tts_voice", "Microsoft Huihui Desktop")
    rate = getattr(Global, "local_tts_rate", 0) if rate is None else rate
    volume = getattr(Global, "local_tts_volume", 100) if volume is None else volume

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_path = temp_file.name

    try:
        _synthesize_wav(text, temp_path, voice_name, rate, volume)
        audio, sample_rate = sf.read(temp_path, dtype="int16")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    if isinstance(audio, np.ndarray) and audio.ndim > 1:
        audio = audio.mean(axis=1).astype(np.int16)

    target_rate = Global.audio_queue.sample_rate
    audio = _resample_int16(np.asarray(audio, dtype=np.int16), sample_rate, target_rate)

    idx = random.randint(10001, 99999)
    Global.audio_queue.create(idx)

    total_samples = max(1, len(audio))
    chunk_size = max(2048, target_rate // 10)
    subtitle_text = ""
    prev_char_index = 0

    for start in range(0, len(audio), chunk_size):
        end = min(start + chunk_size, len(audio))
        chunk = audio[start:end]
        subtitle = None

        char_index = int(end / total_samples * len(text))
        add_text = text[prev_char_index:char_index]
        if add_text:
            subtitle = (subtitle_text, add_text)
            subtitle_text += add_text
            prev_char_index = char_index

        Global.audio_queue.add(idx, chunk, subtitle)

    if prev_char_index < len(text):
        Global.audio_queue.add(idx, np.zeros(1, dtype=np.int16), (subtitle_text, text[prev_char_index:]))

    Global.audio_queue.add(idx, None, None)
    return True
