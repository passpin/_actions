"""Optional Geometry Dash / Geode localhost transport.

This module intentionally has no dependency on Geode or on the installed game.
The accompanying Windows Geode mod implements the server side. The transport
is request/response JSONL, one request per TCP connection, protocol v1.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Mapping


class GeodeBridgeError(RuntimeError):
    """A Geode bridge request failed."""


class GeodeUnavailable(GeodeBridgeError):
    """The local Geode bridge cannot be reached."""


class GeodeProtocolError(GeodeBridgeError):
    """The bridge returned an invalid response."""


class GeodeBridge:
    """Client for the optional local Geode mod.

    Obtain connection details using :meth:`from_session_file`. That file is
    written inside the Geode mod's save directory on every game launch.

    The mod must be explicitly enabled; no game is started automatically.
    """

    def __init__(self, *, token: str, port: int = 18731, timeout: float = 5.0) -> None:
        if not isinstance(token, str) or not token:
            raise ValueError("token must be a non-empty string")
        if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError("port must be an integer between 1 and 65535")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.token = token
        self.port = port
        self.timeout = float(timeout)
        self._request_id = 0

    @classmethod
    def from_session_file(cls, path: str | Path, *, timeout: float = 5.0) -> "GeodeBridge":
        """Read a session descriptor produced by the Geode mod.

        Only loopback connections are accepted, including if the session file
        has been modified by another program.
        """
        descriptor = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(descriptor, dict) or descriptor.get("host") != "127.0.0.1":
            raise GeodeProtocolError("session must specify host 127.0.0.1")
        if descriptor.get("protocol") != 1:
            raise GeodeProtocolError("unsupported Geode bridge protocol version")
        return cls(token=descriptor["token"], port=descriptor["port"], timeout=timeout)

    def call(self, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Execute one documented RPC operation and return its result object."""
        if not isinstance(method, str) or not method or len(method) > 64:
            raise ValueError("method must be a non-empty short string")
        if params is not None and not isinstance(params, Mapping):
            raise TypeError("params must be a mapping")
        self._request_id += 1
        identifier = self._request_id
        request = {"id": identifier, "token": self.token, "method": method, "params": dict(params or {})}
        raw = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(raw) > 16_384:
            raise ValueError("request is too large")
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.sendall(raw)
                chunks: list[bytes] = []
                total = 0
                while True:
                    piece = sock.recv(4096)
                    if not piece:
                        raise GeodeProtocolError("connection closed without a complete response")
                    if b"\n" in piece:
                        part = piece.split(b"\n", 1)[0]
                        if total + len(part) > 1_048_576:
                            raise GeodeProtocolError("response exceeds 1 MiB")
                        chunks.append(part)
                        break
                    chunks.append(piece)
                    total += len(piece)
                    if total > 1_048_576:
                        raise GeodeProtocolError("response exceeds 1 MiB")
        except (ConnectionError, OSError, TimeoutError) as exc:
            raise GeodeUnavailable(f"unable to reach Geode on 127.0.0.1:{self.port}: {exc}") from exc
        try:
            response = json.loads(b"".join(chunks).decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise GeodeProtocolError("response is not valid UTF-8 JSON") from exc
        if not isinstance(response, dict) or response.get("id") != identifier or not isinstance(response.get("ok"), bool):
            raise GeodeProtocolError("response envelope is invalid or ID mismatched")
        if not response["ok"]:
            raise GeodeBridgeError(str(response.get("error", "unknown bridge error")))
        result = response.get("result")
        if not isinstance(result, dict):
            raise GeodeProtocolError("success response must contain an object result")
        return result

    def ping(self) -> dict[str, Any]:
        return self.call("ping")

    def bridge_health(self) -> dict[str, Any]:
        """Read transport and main-thread dispatch counters without touching GD state.

        This method, like ping(), works even if the game's main-thread queue
        is not currently advancing. It does not prove gameplay state access.
        """
        return self.call("bridge_health")

    def status(self) -> dict[str, Any]:
        """Read current PlayLayer and primary player state (without changing it)."""
        return self.call("status")

    def items(self, *item_ids: int) -> dict[int, int]:
        """Read current per-attempt Item values; requires a running PlayLayer."""
        if not item_ids or len(item_ids) > 128:
            raise ValueError("request between 1 and 128 item IDs")
        if any(type(x) is not int or not (1 <= x <= 9999) for x in item_ids):
            raise ValueError("item IDs must be integers in 1..9999")
        values = self.call("items", {"ids": list(item_ids)})["values"]
        return {int(key): int(value) for key, value in values.items()}

    def reset_level(self) -> dict[str, Any]:
        """Ask the running game to restart the current attempt."""
        return self.call("reset_level")

    def input(self, *, down: bool, button: int = 1, player: int = 1) -> dict[str, Any]:
        """Send an immediate button transition to the active game.

        This is *not* a frame/tick-scheduled replay. Timing depends on when
        the game's main-thread task queue handles the request.

        button: 1=jump, 2=left, 3=right (the latter two are platformer controls).
        player: 1 or 2.
        """
        if type(down) is not bool:
            raise TypeError("down must be bool")
        if type(button) is not int or button not in (1, 2, 3):
            raise ValueError("button must be 1 (jump), 2 (left), or 3 (right)")
        if type(player) is not int or player not in (1, 2):
            raise ValueError("player must be 1 or 2")
        return self.call("input", {"down": down, "button": button, "player": player})

    def schedule_inputs(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Queue input transitions for future ``PlayLayer.postUpdate`` callbacks.

        Each event contains ``update`` (> current update counter), ``down``
        (bool), ``button`` (1..3), and ``player`` (1..2). The update counter is
        **not a physics tick** and does not have GDR/GDR2 timing semantics.
        Events at the same update execute in supplied order. Resetting the
        level clears the queue. The caller should inspect ``status()`` to find
        the current counter before scheduling.
        """
        if not isinstance(events, list) or not (1 <= len(events) <= 128):
            raise ValueError("events must be a list of 1..128 input events")
        canonical: list[dict[str, Any]] = []
        for i, event in enumerate(events):
            if not isinstance(event, dict):
                raise TypeError(f"events[{i}] must be a dictionary")
            update = event.get("update")
            down = event.get("down")
            button = event.get("button", 1)
            player = event.get("player", 1)
            if type(update) is not int or not (1 <= update <= 2**53):
                raise ValueError(f"events[{i}].update must be a positive integer")
            if type(down) is not bool:
                raise TypeError(f"events[{i}].down must be bool")
            if type(button) is not int or button not in (1, 2, 3):
                raise ValueError(f"events[{i}].button must be 1..3")
            if type(player) is not int or player not in (1, 2):
                raise ValueError(f"events[{i}].player must be 1 or 2")
            canonical.append({"update": update, "down": down, "button": button, "player": player})
        return self.call("schedule_inputs", {"events": canonical})

    def input_queue_status(self) -> dict[str, Any]:
        """Return observed postUpdate callback count and pending event count."""
        return self.call("input_queue_status")

    def clear_inputs(self) -> dict[str, Any]:
        """Clear all not-yet-dispatched scheduled inputs."""
        return self.call("clear_inputs")

    def snapshot(self, *item_ids: int) -> dict[str, Any]:
        """Get player/progress state and selected Item values in one GD callback.

        This minimizes skew between the Item and player reads; it does not
        promise a particular physics-tick boundary or deterministic replay.
        Empty IDs give the player/progress snapshot without Item values.
        """
        if len(item_ids) > 128 or any(
            type(value) is not int or not (1 <= value <= 9999) for value in item_ids
        ):
            raise ValueError("item IDs must be integers in 1..9999 (up to 128)")
        return self.call("snapshot", {"ids": list(item_ids)})


__all__ = ["GeodeBridge", "GeodeBridgeError", "GeodeUnavailable", "GeodeProtocolError"]
