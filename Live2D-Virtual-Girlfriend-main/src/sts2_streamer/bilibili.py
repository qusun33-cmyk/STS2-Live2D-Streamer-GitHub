from __future__ import annotations

import json
import struct
import threading
import time
import zlib
from dataclasses import dataclass
from typing import Callable

import requests
import websocket


@dataclass(slots=True)
class DanmakuMessage:
    room_id: int
    username: str
    text: str


class BilibiliDanmakuClient:
    def __init__(self, room_id: int, on_message: Callable[[DanmakuMessage], None]) -> None:
        self.room_id = room_id
        self.on_message = on_message
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                real_room_id, host, port, token = self._resolve_connection()
                self._run_socket(real_room_id, host, port, token)
            except Exception as exc:  # pragma: no cover - runtime logging
                print(f"[sts2_streamer] bilibili reconnect after error: {exc}")
                time.sleep(5.0)

    def _resolve_connection(self) -> tuple[int, str, int, str]:
        init_resp = requests.get(
            "https://api.live.bilibili.com/room/v1/Room/room_init",
            params={"id": self.room_id},
            timeout=10,
        )
        init_resp.raise_for_status()
        init_data = init_resp.json()["data"]
        real_room_id = int(init_data["room_id"])

        info_resp = requests.get(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo",
            params={"id": real_room_id, "type": 0},
            timeout=10,
        )
        info_resp.raise_for_status()
        info_data = info_resp.json()["data"]
        host = info_data["host_list"][0]["host"]
        port = int(info_data["host_list"][0]["wss_port"])
        token = str(info_data["token"])
        return real_room_id, host, port, token

    def _run_socket(self, real_room_id: int, host: str, port: int, token: str) -> None:
        ws = websocket.create_connection(f"wss://{host}:{port}/sub", timeout=20)
        try:
            auth_payload = {
                "uid": 0,
                "roomid": real_room_id,
                "protover": 2,
                "platform": "web",
                "type": 2,
                "key": token,
            }
            ws.send_binary(self._pack(7, json.dumps(auth_payload).encode("utf-8")))

            last_heartbeat = 0.0
            while not self._stop.is_set():
                if time.monotonic() - last_heartbeat > 25.0:
                    ws.send_binary(self._pack(2, b""))
                    last_heartbeat = time.monotonic()
                frame = ws.recv()
                if isinstance(frame, str):
                    frame = frame.encode("utf-8")
                for packet in self._unpack(frame):
                    self._handle_packet(real_room_id, packet)
        finally:
            ws.close()

    def _handle_packet(self, room_id: int, packet: tuple[int, int, bytes]) -> None:
        version, operation, body = packet
        if operation != 5:
            return

        if version == 2:
            decompressed = zlib.decompress(body)
            for nested in self._unpack(decompressed):
                self._handle_packet(room_id, nested)
            return

        payload = json.loads(body.decode("utf-8", errors="ignore"))
        if payload.get("cmd") != "DANMU_MSG":
            return

        info = payload.get("info") or []
        text = info[1] if len(info) > 1 else ""
        user = info[2][1] if len(info) > 2 and len(info[2]) > 1 else "观众"
        if text:
            self.on_message(DanmakuMessage(room_id=room_id, username=str(user), text=str(text)))

    @staticmethod
    def _pack(operation: int, body: bytes) -> bytes:
        header_len = 16
        packet_len = header_len + len(body)
        return struct.pack(">IHHII", packet_len, header_len, 1, operation, 1) + body

    @staticmethod
    def _unpack(data: bytes):
        offset = 0
        packets = []
        while offset + 16 <= len(data):
            packet_len, header_len, version, operation, _ = struct.unpack(">IHHII", data[offset:offset + 16])
            body = data[offset + header_len:offset + packet_len]
            packets.append((version, operation, body))
            offset += packet_len
        return packets
