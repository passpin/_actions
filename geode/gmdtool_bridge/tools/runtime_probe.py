#!/usr/bin/env python3
"""Standalone, read-mostly gmdtool v0.13.0 diagnostic client (stdlib only).

Does not need the Python gmdtool package. Never sends keys or runs fake ticks.
Use --arm-background only when you have enabled the corresponding Geode setting.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time


def default_session() -> Path:
    root = os.environ.get('LOCALAPPDATA')
    if not root:
        raise RuntimeError('LOCALAPPDATA is missing; pass --session explicitly')
    return Path(root) / 'GeometryDash/geode/mods/gmdtool.runtime-bridge/bridge-session.json'


class Bridge:
    def __init__(self, session: Path):
        descriptor = json.loads(session.read_text(encoding='utf-8'))
        if descriptor.get('host') != '127.0.0.1' or descriptor.get('protocol') != 1:
            raise ValueError('Session descriptor must use protocol 1 and loopback host')
        self.token = descriptor['token']
        self.port = int(descriptor['port'])
        self.sequence = 0

    def call(self, method: str, params: dict | None = None) -> dict:
        self.sequence += 1
        data = json.dumps({
            'id': self.sequence, 'token': self.token,
            'method': method, 'params': params or {}
        }, separators=(',', ':')).encode('utf-8') + b'\n'
        with socket.create_connection(('127.0.0.1', self.port), timeout=5) as sock:
            sock.settimeout(5)
            sock.sendall(data)
            received = bytearray()
            while b'\n' not in received:
                piece = sock.recv(4096)
                if not piece:
                    raise RuntimeError('Geode closed connection without an answer')
                received += piece
                if len(received) > 1_048_576:
                    raise RuntimeError('Response too long')
        payload = json.loads(received.split(b'\n', 1)[0])
        if payload.get('id') != self.sequence or not isinstance(payload.get('ok'), bool):
            raise RuntimeError('Invalid bridge response')
        if not payload['ok']:
            raise RuntimeError(f'{method}: {payload.get("error", "unknown bridge error")}')
        return payload['result']


def diagnose(before: dict, after: dict) -> dict:
    if not before.get('playing') or not after.get('playing'):
        return {'result': 'no_active_level', 'detail': 'Start a level and retry.'}
    delta = (after.get('update_callbacks') or 0) - (before.get('update_callbacks') or 0)
    trace_delta = (after.get('trace', {}).get('observed_updates') or 0) - (before.get('trace', {}).get('observed_updates') or 0)
    item_changed = before.get('values') != after.get('values')
    b1 = before.get('player1') or {}
    b2 = after.get('player1') or {}
    position_changed = b1.get('x') != b2.get('x') or b1.get('y') != b2.get('y')
    percent_changed = before.get('percent') != after.get('percent')
    bg = after.get('background') or {}
    result = {
        'update_callback_delta': delta,
        'trace_sample_delta': trace_delta,
        'position_changed': position_changed,
        'percent_changed': percent_changed,
        'item_values_changed': item_changed,
        'director_paused': bg.get('director_paused'),
        'game_updates_recent': bg.get('game_updates_recent'),
        'window': bg.get('window'),
        'unfocus_pause_suppressed': bg.get('unfocus_pause_suppressed'),
        'last_level_update_ago_ms': bg.get('last_level_update_ago_ms'),
    }
    if delta < 0:
        result['result'] = 'attempt_or_level_changed'
        result['detail'] = 'The counter reset; repeat without restarting/changing level.'
    elif delta == 0:
        result['result'] = 'game_callbacks_stalled'
        result['detail'] = 'Bridge works, but PlayLayer postUpdate did not run during observation.'
    elif position_changed or percent_changed:
        result['result'] = 'game_progress_observed'
        result['detail'] = 'Game callbacks and player/progress changed; gameplay advanced.'
    else:
        result['result'] = 'callbacks_only'
        result['detail'] = 'Callbacks ran; player/progress unchanged (may be paused, dead, stationary, or fixed camera).'
    if delta and trace_delta == 0:
        result['trace_note'] = 'No Item samples observed; tracing may be off or sampling interval > observation.'
    elif trace_delta and not item_changed:
        result['trace_note'] = 'Trace sampled but requested Item values did not change; this can be normal.'
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='Check main-thread/game-loop/Item tracing independently of GD window focus')
    parser.add_argument('--session', type=Path, help='Path to bridge-session.json (default: auto-detect in LOCALAPPDATA)')
    parser.add_argument('--seconds', type=float, default=5.0, help='Observation interval (1 to 30; default 5)')
    parser.add_argument('--ids', type=str, default='', help='Comma-separated Item IDs to read (up to 8), e.g. 1,2')
    parser.add_argument('--trace', action='store_true', help='Start a fresh trace of --ids for the test (replaces any existing trace)')
    parser.add_argument('--arm-background', action='store_true', help='Enable experimental background mode 5 s after launch')
    parser.add_argument('--json', action='store_true', help='Also print full start/end snapshots (contains no auth token)')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30:
        parser.error('--seconds must be 1..30')
    try:
        ids = [] if not args.ids.strip() else [int(x.strip()) for x in args.ids.split(',')]
    except ValueError:
        parser.error('--ids must be comma-separated integers')
    if len(set(ids)) != len(ids) or len(ids) > 8 or any(not 1 <= x <= 9999 for x in ids):
        parser.error('--ids must be 0..8 unique integers in 1..9999')
    if args.trace and not ids:
        parser.error('--trace needs --ids')

    bridge = Bridge(args.session or default_session())
    print('Transport:', bridge.call('ping'))
    if args.arm_background:
        print('Switch to GD, open a level and keep it foreground: arming in 5 seconds...')
        time.sleep(5)
        print('Background control:', bridge.call('background_control', {'enabled': True}))
        if sys.platform == 'win32':
            import winsound
            winsound.Beep(900, 160)
        print('Now switch to another window; measuring in 3 seconds...')
        time.sleep(3)
    if args.trace:
        print('Trace:', bridge.call('trace_start', {'ids': ids, 'every_updates': 1}))
    first = bridge.call('runtime_probe', {'ids': ids})
    print('Observation started; keep the game in the state you want to test.')
    time.sleep(args.seconds)
    second = bridge.call('runtime_probe', {'ids': ids})
    print('\nResult:')
    print(json.dumps(diagnose(first, second), indent=2, ensure_ascii=False))
    if args.trace:
        print('\nTrace summary:', json.dumps(second.get('trace', {}), indent=2, ensure_ascii=False))
        # This test deliberately does not drain/stop an active tracer; user may inspect it.
    if args.json:
        print('\nBefore:', json.dumps(first, indent=2, ensure_ascii=False))
        print('\nAfter:', json.dumps(second, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print('Probe error:', exc, file=sys.stderr)
        raise SystemExit(1) from None
