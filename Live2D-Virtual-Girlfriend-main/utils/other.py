import io
import wave
import time
import ctypes
import base64
from threading import Thread

import numpy as np
import sounddevice as sd
from PIL import Image, ImageGrab

from config import Global

try:
    import pyaudio
except ImportError:  # pragma: no cover - optional runtime dependency
    pyaudio = None

try:
    import pyautogui
except ImportError:  # pragma: no cover - optional runtime dependency
    pyautogui = None

def terminate_thread(thread):
    if not thread.is_alive():
        return
    
    exc = ctypes.py_object(SystemExit)
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread.ident), exc)
    if res > 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(thread.ident, None)

def wait_send_over():
    while True:
        flag = check_send_over()
        if flag:
            break
        time.sleep(1)

def check_send_over():
    flag = True
    for i in Global.func_queue1.t:
        if i.is_alive():
            flag = False
    
    if Global.audio_queue.q:
        flag = False
    elif Global.send_text_thread and Global.send_text_thread.is_alive():
        flag = False
    elif Global.rvc.playing:
        flag = False
    
    return flag

def capture_screen(max_pixels=None, web=False):
    if web:
        Global.web_request_photo()
        image_path = Global.received_photo.get()
        screenshot = Image.open(image_path)
    else:
        if pyautogui is not None:
            screenshot = pyautogui.screenshot()
        else:
            screenshot = ImageGrab.grab()
        
    width, height = screenshot.size
    current_pixels = width * height

    if max_pixels:
        if current_pixels > max_pixels:
            scale_factor = (max_pixels / current_pixels) ** 0.5
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            screenshot = screenshot.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    buffered = io.BytesIO()
    screenshot.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str

class sounds_player:
    def __init__(self):
        self.p = pyaudio.PyAudio() if pyaudio is not None else None
        self.cache = {}
    
    def load(self, id, path, volume):
        with wave.open(path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            
        audio_data = np.frombuffer(frames, dtype=np.int16)
        audio_data = (audio_data * volume).astype(audio_data.dtype)
        
        with wave.open(path, 'rb') as wf:
            audio_info = {
                'data': audio_data.tobytes(),
                'channels': wf.getnchannels(),
                'sample_width': wf.getsampwidth(),
                'framerate': wf.getframerate()
            }
        
        if self.p is not None:
            stream = self.p.open(
                format=self.p.get_format_from_width(audio_info['sample_width']),
                channels=audio_info['channels'],
                rate=audio_info['framerate'],
                output=True
            )
        else:
            stream = None

        self.cache[id] = (audio_info['data'], stream, audio_info)
    
    def play(self, id):
        Thread(target=self._play, args=(id,)).start()
    
    def _play(self, id):
        audio_data, stream, audio_info = self.cache[id]
        if stream is not None:
            stream.write(audio_data)
            return

        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        if audio_info['channels'] > 1:
            audio_array = audio_array.reshape(-1, audio_info['channels'])

        sd.play(audio_array, samplerate=audio_info['framerate'], blocking=True)
