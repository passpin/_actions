# gmdtool Runtime Bridge — passpin (v0.1.4)

A Windows-first **experimental source project**, not a compiled `.geode` file.
Designed for Geometry Dash **2.2081** and Geode SDK **5.9.0**.

## What changed from v0.1.2

- Added GitHub Releases auto-update (`src/auto_update.cpp`): at the GD main
  menu it checks `passpin/for_build` latest release, downloads the exact asset
  `gmdtool.runtime-bridge.geode`, verifies the GitHub-provided SHA-256 digest
  and package metadata, stages it in the mod save directory, and shows an
  English **Later / Restart** prompt. Only on **Restart** does it back up the
  current package and atomically swap the `.geode` file.
- No DLL hot-reload, no in-memory patching, no background HTTP server. The
  opt-in localhost runtime bridge (settings `enabled`) is unchanged.
- `mod.json` version bumped to `v0.1.4`; new `auto-update` setting (default
  on).

## Compile with GitHub Actions (no additional local toolchain)

The repository layout for CI (this checkout root) is:

```text
geode/gmdtool_bridge/
  CMakeLists.txt
  mod.json
  build-windows.ps1
  src/main.cpp
  src/bridge_transport.hpp
  src/bridge_transport.cpp
  src/auto_update.cpp
.github/workflows/
  build-geode.yml   (Windows build, every push)
  release-geode.yml (tag-triggered build + GitHub Release publish)
```

Go to **Actions > Build gmdtool Geode Bridge (Windows) > Run workflow** (or
push a commit). After a successful build, download the
`passpin-gmdtool-runtime-bridge-win64` artifact and extract the `.geode`.

Publishing is automatic: pushing a tag `vX.Y.Z` (matching
`geode/gmdtool_bridge/mod.json` `version`) runs the release workflow, builds
the Windows mod and attaches the compiled `.geode` as a public Release asset
named `gmdtool.runtime-bridge.geode`.

## Safety and status

- The local API is **OFF by default**; `enabled` must be switched on in the
  mod settings and GD restarted.
- Binding is **127.0.0.1:18731 only**, with a per-launch token in
  `bridge-session.json` inside the mod's save directory.
- Auto-update requires a **public** GitHub Release with the exact asset name
  and a `sha256:` digest; it fails closed otherwise. See `AUTO_UPDATE.md`.
- Make backups, test offline on a disposable level, and disable other
  interfering mods when investigating execution-order anomalies.
- Scheduled input timing is counted in `PlayLayer::postUpdate` calls,
  **not physics ticks**. GDR2-accurate macro replay, screenshot capture,
  pause/step and detailed trigger traces are **not implemented**.
- This environment cannot run the official **Windows Geode SDK compiler** or
  Geometry Dash, so C++ cross-environment tests are not proof of a successful
  Windows build or in-game operation.

## Local build

Requires Geode CLI + Geode SDK 5.9.0, GD Win64 bindings, Clang, CMake, Ninja
and Windows SDK/Visual Studio Build Tools. From the mod root:

```powershell
.\build-windows.ps1
```

## Python client

From the full gmdtool package:

```python
from gmdtool import GeodeBridge
bridge = GeodeBridge.from_session_file(r"C:\path\to\bridge-session.json")
print(bridge.ping())
print(bridge.status())
```

## v0.1.2 connectivity diagnostics

`ping` validates the local transport and token *without* requiring GD's main
thread to advance. It does **not** prove runtime access. `bridge_health` is
also network-only, reporting counters and recent main-thread service
timestamps. `status`, `items`, `snapshot`, and input commands **still** use
main-thread dispatch. Test with GD visible/foreground and running, not
minimized.

```python
print(bridge.ping())
print(bridge.call("bridge_health"))
print(bridge.status())  # requires main thread to process work
```

If `status` times out, inspect `bridge_health` before and after. If the
`completed` counter does not increase, the queued main-thread callback has not
been serviced. Do not retry mutation commands repeatedly on timeouts.

A queued command is cancelled if it has not started when its timeout fires.
If it was already running, the outcome remains uncertain.
