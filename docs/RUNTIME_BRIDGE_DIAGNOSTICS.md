# Geode bridge v0.1.2 — connectivity diagnostics

The mod's TCP server runs on 127.0.0.1:18731 only and authenticates every request
with a per-start token from `bridge-session.json`.

- `ping` tests authenticated transport only and does **not** wait for GD's main thread.
- `bridge_health` reports counts of queued, started, completed, timed-out
  requests plus last-main-callback completion and last PlayLayer postUpdate ages.
- `status`, `items`, `snapshot`, `input`, `reset_level`, etc. access GD/Cocos
  only through Geode's main-thread dispatcher.
- If GD is minimized/unfocused/blocked and not processing its main-thread task
  queue, these commands can time out even though `ping` works.
- A timeout before dispatch begins cancels the command; if already started its
  side effects can have occurred. Do not indiscriminately retry mutations.

Test sequence (keep the game visible and preferably in windowed mode):

```bash
py -m gmdtool geode --session "C:\path\to\bridge-session.json" ping
py -m gmdtool geode --session "C:\path\to\bridge-session.json" bridge-health
py -m gmdtool geode --session "C:\path\to\bridge-session.json" status
```

Transport ping success is not a test of gameplay state handling.
Scheduled input update counters are still NOT physical ticks or GDR2 playback.
