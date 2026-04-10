from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterator

import requests


@dataclass(slots=True)
class Sts2Action:
    name: str
    card_index: int | None = None
    target_index: int | None = None
    option_index: int | None = None

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"action": self.name}
        if self.card_index is not None:
            payload["card_index"] = self.card_index
        if self.target_index is not None:
            payload["target_index"] = self.target_index
        if self.option_index is not None:
            payload["option_index"] = self.option_index
        return payload


class Sts2HttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

    def get_health(self) -> dict[str, Any]:
        return self._request_json("GET", "/health")

    def get_state(self) -> dict[str, Any]:
        return self._request_json("GET", "/state")

    def get_available_actions(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/actions/available")
        return list(payload.get("actions", []))

    def act(self, action: Sts2Action) -> dict[str, Any]:
        return self._request_json("POST", "/action", action.as_payload())

    def wait_until_actionable(self, timeout_seconds: float = 20.0, interval: float = 0.35) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            state = self.get_state()
            if state.get("available_actions"):
                return state
            time.sleep(interval)
        return self.get_state()

    def iter_events(self) -> Iterator[dict[str, Any]]:
        with self.session.get(
            f"{self.base_url}/events/stream",
            stream=True,
            timeout=(3.0, 90.0),
            headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
        ) as response:
            response.raise_for_status()
            event_id = None
            event_name = None
            data_lines: list[str] = []

            for raw_line in response.iter_lines(decode_unicode=True):
                if raw_line is None:
                    continue
                line = raw_line.strip("\r")

                if not line:
                    if event_name or data_lines:
                        raw_data = "\n".join(data_lines)
                        try:
                            data = json.loads(raw_data) if raw_data else None
                        except json.JSONDecodeError:
                            data = raw_data
                        yield {"id": event_id, "event": event_name or "message", "data": data}
                    event_id = None
                    event_name = None
                    data_lines = []
                    continue

                if line.startswith(":"):
                    continue

                field, _, value = line.partition(":")
                value = value.lstrip()
                if field == "id":
                    event_id = value
                elif field == "event":
                    event_name = value
                elif field == "data":
                    data_lines.append(value)

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            json=payload,
            timeout=(3.0, 20.0),
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok", False):
            raise RuntimeError(str(body.get("error") or body))
        return body.get("data", {})
