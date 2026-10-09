# Geode runtime bridge (experimental, Windows-first)

The Python toolkit continues to work without Geometry Dash or Geode. The optional
Windows Geode mod in `geode/gmdtool_bridge/` makes a *running copy* of GD available
for basic runtime inspection. This is **not** a simulator and does not guarantee
identical outcomes across machines, mods, frame pacing, or game versions.

## Requirements and build

- Geometry Dash PC with Geode installed. Match the Geode SDK and GD versions in
  `geode/gmdtool_bridge/mod.json` to your actual installed versions.
- Geode SDK and CLI, CMake, compiler: [official guide](https://docs.geode-sdk.org/getting-started/sdk/).
- Windows target only in the initial native implementation (Winsock2).

From `geode/gmdtool_bridge/`:

```shell
geode build
```

Install the resulting `.geode` package in GD. Enable the mod setting
**Enable local API** and restart GD. The mod listens on **127.0.0.1:18731**,
never an external network interface. Startup creates a new random token and
`bridge-session.json` in the mod's Geode *save directory*. Check the Geode log
for the exact path. Keep this file private and do not expose the port through
network forwarding or a proxy.

## Python

```python
from gmdtool import GeodeBridge

bridge = GeodeBridge.from_session_file(
    r"C:\path\shown\in\geode\log\bridge-session.json"
)
print(bridge.ping())
print(bridge.status())              # returns playing=false if no level
# In the game, open and start a level before querying items:
print(bridge.items(1, 2, 3))        # {1: ..., 2: ..., 3: ...}
bridge.reset_level()                # asks GD to restart the current attempt
bridge.input(down=True, button=1)   # immediate press: P1 jump
bridge.input(down=False, button=1)  # immediate release: P1 jump
print(bridge.input_queue_status())  # observed postUpdate callback count
# Only schedule a short time into the future after inspecting the counter:
current = bridge.input_queue_status()["update_callbacks"]
bridge.schedule_inputs([
    {"update": current + 15, "down": True, "button": 1, "player": 1},
    {"update": current + 25, "down": False, "button": 1, "player": 1},
])
print(bridge.snapshot(1, 2, 3))     # player position/progress + Item values in one callback
```

A separate Python process can use the bridge; it does **not** need to be run
from inside the game. The C++ mod reads game state on Geode's main thread;
the network thread never touches Cocos objects.

## CLI quick connection check

Run the commands from your Python environment after GD/Geode is running and the
mod is enabled. No `.gmd` file or in-game macro is needed for the initial ping.

```shell
gmdtool geode --session "C:\path\to\bridge-session.json" ping
gmdtool geode --session "C:\path\to\bridge-session.json" status
```

Then open a level in the game:

```shell
gmdtool geode --session "C:\path\to\bridge-session.json" items 1 2 3
gmdtool geode --session "C:\path\to\bridge-session.json" snapshot 1 2 3
gmdtool geode --session "C:\path\to\bridge-session.json" input --down --button 1
gmdtool geode --session "C:\path\to\bridge-session.json" input --up --button 1
gmdtool geode --session "C:\path\to\bridge-session.json" reset
gmdtool geode --session "C:\path\to\bridge-session.json" queue-status
gmdtool geode --session "C:\path\to\bridge-session.json" schedule inputs.json
gmdtool geode --session "C:\path\to\bridge-session.json" clear-inputs
```

The output is JSON. For automation, the Python `GeodeBridge` class is recommended.
`--timeout` controls connection/response deadlines; `--compact` emits one-line JSON.
The `--session` option is placed before the operation name.

## Protocol v1

- TCP on loopback, one UTF-8 JSON request and one response per connection,
  each terminated by `\n`.
- Request: `{"id":1,"token":"...","method":"status","params":{}}`.
- Success: `{"id":1,"ok":true,"result":{...}}`.
- Failure: `{"id":1,"ok":false,"error":"..."}`.
- Methods: `ping`, `status`, `input_queue_status`, `clear_inputs`,
  `schedule_inputs` (1..128 button transitions; <=512 pending), `items` with `params.ids` (1..128 IDs,
  ID range 1..9999), `reset_level`, `snapshot` (0..128 Item IDs),
  `input` (`down`: boolean, `button`: 1 jump / 2 left / 3 right,
  `player`: 1 or 2).
- `input` injects **immediately when the main thread executes the request**;
  it is not a frame-scheduled macro. `snapshot` reads the requested state
  together in one main-thread callback but not at an explicitly chosen tick.
- Request limit 16 KiB, response limit 1 MiB on the Python side.
- Server operates one short connection at a time; its main-thread response is
  bounded to three seconds. A timeout does not necessarily cancel an already
  queued main-thread action.

## Known limitations and next work

1. The native mod still needs to be **compiled and launched in an actual Geode
   installation**; Python tests only exercise the wire protocol using a mock.
2. Level load, controlled physics stepping, GDR/GDR2 replay, per-tick trigger
   tracing and screenshots are **not yet implemented**. The new input queue is
   synchronized to **observed PlayLayer::postUpdate callback counts**, not to
   internal physics substeps/TPS or GDR frames. It must not be presented as
   deterministic macro replay. The `input` method is an immediate manual
   transition; both options are experimental until tested inside GD.
   Queue entries are cleared by any level reset, including death-induced resets.
3. State reads currently cover basic PlayLayer/player position/progress and
   requested Item IDs. Never request arbitrary negative or out-of-range IDs.
4. Future input/replay features must distinguish game ticks from render frames.
5. Keep any runtime-specific commands opt-in and avoid adding dependencies to
   gmdtool's core file-editing workflows.

## Callback-scheduled input (experimental)

`status()` and `input_queue_status()` expose `update_callbacks`, a counter of
observed calls to `PlayLayer::postUpdate` in the current attempt. These are **not**
necessarily gameplay physics ticks and their rate may vary with runtime settings.
Use them only for preliminary event scheduling, not for exact GDR/GDR2 conversion.
Inputs for one callback are delivered *before* invoking the original `postUpdate`,
in insertion order, and the original game implementation still runs normally.
The queue is cleared on an attempt reset or leaving the play scene. Observing and
scheduling can change behavior when other mods hook the same function; compare
runs with the bridge disabled. No custom update loop or forced frame pacing is
added by this version.

`inputs.json` for the CLI `schedule` operation is a JSON array:

```json
[
  {"update": 100, "button": 1, "player": 1, "down": true},
  {"update": 110, "button": 1, "player": 1, "down": false}
]
```

Use a future update index; the bridge rejects stale indexes. This mode is
intended to validate the IPC + game-input mechanism before investigating the
true GD physics-step callback and GDR2 synchronization.
