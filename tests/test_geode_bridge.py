"""Transport tests with a mock; do not imply the native Geode mod is tested."""

from __future__ import annotations

import json
import socketserver
import threading

import pytest

from gmdtool.geode_bridge import (
    GeodeBridge, GeodeBridgeError, GeodeProtocolError, GeodeUnavailable
)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(16385)
        request = json.loads(raw)
        response = {"id": request["id"], "ok": True, "result": {}}
        if request["token"] != "secret":
            response = {"id": request["id"], "ok": False, "error": "authentication failed"}
        elif request["method"] == "ping":
            response["result"] = {"protocol": 1, "online": True}
        elif request["method"] == "bridge_health":
            response["result"] = {"transport_ok": True, "queued": 3, "completed": 1,
                                  "timed_out": 2, "main_thread_checked": False}
        elif request["method"] == "status":
            response["result"] = {"playing": True, "player1": {"x": 100, "y": 30}}
        elif request["method"] == "items":
            response["result"] = {"values": {str(k): k + 10 for k in request["params"]["ids"]}}
        elif request["method"] == "reset_level":
            response["result"] = {"requested": True}
        elif request["method"] == "input":
            response["result"] = {"accepted": True, "echo": request["params"]}
        elif request["method"] == "snapshot":
            response["result"] = {"playing": True, "player1": {"x": 100, "y": 30},
                                  "values": {str(k): k + 10 for k in request["params"]["ids"]}}
        elif request["method"] == "schedule_inputs":
            response["result"] = {"accepted": len(request["params"]["events"]), "echo": request["params"]["events"]}
        elif request["method"] == "input_queue_status":
            response["result"] = {"update_callbacks": 20, "queued_inputs": 0}
        elif request["method"] == "clear_inputs":
            response["result"] = {"cleared": 0}
        elif request["method"] == "bad_response":
            response["id"] = -99
        else:
            response = {"id": request["id"], "ok": False, "error": "unknown method"}
        self.wfile.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")


@pytest.fixture
def mock_geode():
    with _Server(("127.0.0.1", 0), _Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1]
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_ping_and_status(mock_geode):
    client = GeodeBridge(token="secret", port=mock_geode)
    assert client.ping() == {"protocol": 1, "online": True}
    assert client.status()["player1"]["x"] == 100


def test_item_read_and_reset(mock_geode):
    client = GeodeBridge(token="secret", port=mock_geode)
    assert client.items(1, 3, 99) == {1: 11, 3: 13, 99: 109}
    assert client.reset_level() == {"requested": True}


def test_immediate_input_and_snapshot(mock_geode):
    client = GeodeBridge(token="secret", port=mock_geode)
    assert client.input(down=True)["echo"] == {"down": True, "button": 1, "player": 1}
    assert client.input(down=False, button=3, player=2)["echo"]["down"] is False
    assert client.snapshot()["values"] == {}
    snapshot = client.snapshot(1, 2, 4)
    assert snapshot["player1"]["x"] == 100
    assert snapshot["values"] == {"1": 11, "2": 12, "4": 14}


def test_invalid_input_and_snapshot(mock_geode):
    client = GeodeBridge(token="secret", port=mock_geode)
    for kwargs in ({"down": 1}, {"down": "true"}):
        with pytest.raises(TypeError):
            client.input(**kwargs)
    for kwargs in ({"down": True, "button": 0}, {"down": True, "button": True},
                   {"down": True, "player": 0}, {"down": False, "player": True}):
        with pytest.raises(ValueError):
            client.input(**kwargs)
    for ids in ((0,), (True,), (10000,), (1.5,), tuple(range(1, 130))):
        with pytest.raises(ValueError):
            client.snapshot(*ids)


def test_auth_and_remote_error(mock_geode):
    client = GeodeBridge(token="bad", port=mock_geode)
    with pytest.raises(GeodeBridgeError, match="authentication failed"):
        client.ping()
    with pytest.raises(GeodeBridgeError, match="unknown method"):
        GeodeBridge(token="secret", port=mock_geode).call("not_supported")


def test_response_id_must_match(mock_geode):
    with pytest.raises(GeodeProtocolError, match="envelope"):
        GeodeBridge(token="secret", port=mock_geode).call("bad_response")


def test_invalid_items_and_constructor():
    client = GeodeBridge(token="secret")
    for ids in [(), (0,), (-1,), (10000,), (True,), (1.5,), tuple(range(1, 130))]:
        with pytest.raises(ValueError):
            client.items(*ids)
    with pytest.raises(ValueError):
        GeodeBridge(token="")
    with pytest.raises(ValueError):
        GeodeBridge(token="abc", port=0)
    with pytest.raises(ValueError):
        GeodeBridge(token="abc", timeout=0)


def test_session_descriptor(tmp_path, mock_geode):
    file = tmp_path / "bridge-session.json"
    file.write_text(json.dumps({"protocol": 1, "host": "127.0.0.1", "port": mock_geode,
                                "token": "secret"}), encoding="utf-8")
    assert GeodeBridge.from_session_file(file).ping()["online"]
    file.write_text(json.dumps({"protocol": 1, "host": "example.com", "port": mock_geode,
                                "token": "secret"}), encoding="utf-8")
    with pytest.raises(GeodeProtocolError, match="127.0.0.1"):
        GeodeBridge.from_session_file(file)


def test_unreachable_port():
    # Listen on an ephemeral port, then close it to test refusal.
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(GeodeUnavailable):
        GeodeBridge(token="secret", port=port, timeout=0.3).ping()


def test_runtime_cli_roundtrip(mock_geode, tmp_path, capsys):
    from gmdtool.cli import main

    session = tmp_path / "bridge-session.json"
    session.write_text(json.dumps({"protocol": 1, "host": "127.0.0.1", "port": mock_geode,
                                   "token": "secret"}), encoding="utf-8")

    def cli(*args):
        return main(["geode", "--session", str(session), "--compact", *args])

    assert cli("ping") == 0
    assert json.loads(capsys.readouterr().out)["online"] is True
    assert cli("status") == 0
    assert json.loads(capsys.readouterr().out)["playing"] is True
    assert cli("items", "2", "3") == 0
    assert json.loads(capsys.readouterr().out)["values"] == {"2": 12, "3": 13}
    assert cli("snapshot", "1") == 0
    assert json.loads(capsys.readouterr().out)["values"] == {"1": 11}
    assert cli("input", "--down", "--button", "1") == 0
    assert json.loads(capsys.readouterr().out)["echo"]["down"] is True
    assert cli("input", "--up") == 0
    assert json.loads(capsys.readouterr().out)["echo"]["down"] is False
    assert cli("reset") == 0
    assert json.loads(capsys.readouterr().out)["requested"] is True


def test_runtime_cli_unavailable(tmp_path, capsys):
    from gmdtool.cli import main
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    session = tmp_path / "bridge-session.json"
    session.write_text(json.dumps({"protocol": 1, "host": "127.0.0.1", "port": port,
                                   "token": "secret"}), encoding="utf-8")
    code = main(["geode", "--session", str(session), "--timeout", "0.3", "ping"])
    assert code == 2
    assert "unable to reach Geode" in capsys.readouterr().err


def test_scheduled_update_callback_input(mock_geode):
    client = GeodeBridge(token="secret", port=mock_geode)
    assert client.input_queue_status() == {"update_callbacks": 20, "queued_inputs": 0}
    events = [{"update": 21, "down": True},
              {"update": 31, "down": False, "button": 3, "player": 2}]
    result = client.schedule_inputs(events)
    assert result["accepted"] == 2
    assert result["echo"] == [
        {"update": 21, "down": True, "button": 1, "player": 1},
        {"update": 31, "down": False, "button": 3, "player": 2}]
    assert client.clear_inputs() == {"cleared": 0}


@pytest.mark.parametrize("events,exc", [
    ([], ValueError), ([{"update": 0, "down": True}], ValueError),
    ([{"update": True, "down": True}], ValueError),
    ([{"update": 1, "down": 1}], TypeError),
    ([{"update": 1, "down": True, "button": 4}], ValueError),
    ([{"update": 1, "down": True, "player": 0}], ValueError),
    (["not dict"], TypeError),
])
def test_schedule_validation(events, exc):
    with pytest.raises(exc):
        GeodeBridge(token="secret").schedule_inputs(events)


def test_schedule_cli(mock_geode, tmp_path, capsys):
    from gmdtool.cli import main
    session = tmp_path / "session.json"
    session.write_text(json.dumps({"protocol": 1, "host": "127.0.0.1",
        "port": mock_geode, "token": "secret"}), encoding="utf-8")
    events = tmp_path / "events.json"
    events.write_text(json.dumps([{"update": 55, "down": True}]), encoding="utf-8")
    prefix = ["geode", "--session", str(session), "--compact"]
    assert main(prefix + ["schedule", str(events)]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"] == 1
    assert main(prefix + ["queue-status"]) == 0
    assert json.loads(capsys.readouterr().out)["update_callbacks"] == 20
    assert main(prefix + ["clear-inputs"]) == 0
    assert json.loads(capsys.readouterr().out)["cleared"] == 0


def test_bridge_health(mock_geode):
    client = GeodeBridge(token="secret", port=mock_geode)
    health = client.bridge_health()
    assert health["transport_ok"] is True
    assert health["main_thread_checked"] is False
    assert health["timed_out"] == 2


def test_bridge_health_cli(mock_geode, tmp_path, capsys):
    from gmdtool.cli import main
    session = tmp_path / "session.json"
    session.write_text(json.dumps({"protocol": 1, "host": "127.0.0.1",
        "port": mock_geode, "token": "secret"}), encoding="utf-8")
    assert main(["geode", "--session", str(session), "bridge-health"]) == 0
    assert json.loads(capsys.readouterr().out)["transport_ok"] is True
