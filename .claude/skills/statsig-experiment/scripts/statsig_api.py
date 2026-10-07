"""Thin Statsig Console API client. Stdlib only.

The key comes from $STATSIG_CONSOLE_API_KEY and is never logged, echoed, or written
anywhere. This is a Console API key (console.statsig.com/api_keys), not the server
SDK secret.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = 'https://statsigapi.net/console/v1'
API_VERSION = '20240601'

# The store the backend reads to decide which client events it will forward.
ALLOWLIST_STORE = 'event_pipeline'
ALLOWLIST_KEY = 'event_allowlist'


class StatsigError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get('STATSIG_CONSOLE_API_KEY', '').strip()
    if not key:
        raise StatsigError(
            'STATSIG_CONSOLE_API_KEY is not set. Create a Console API key at '
            'console.statsig.com/api_keys and export it from ~/.env. It is not the '
            'same key as the server SDK secret.'
        )
    return key


def request(method: str, path: str, body: dict | None = None, *, allow_write: bool = False) -> dict:
    """Every call funnels through here, which is where read-only is enforced.

    The available Console API keys are read_write at the project level — Statsig
    won't stop a mutation for us, so this does. Anything other than GET raises
    unless the caller passes allow_write=True explicitly, and nothing in this skill
    does. A future write path has to opt in at the call site, in a diff someone
    reads, rather than a stray verb slipping through unnoticed.
    """
    if method.upper() != 'GET' and not allow_write:
        raise StatsigError(
            f'refusing {method} {path}: this client is read-only. Mutations must pass '
            f'allow_write=True and go through a read -> diff -> confirm flow.'
        )
    url = f'{BASE}{path}'
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('STATSIG-API-KEY', _key())
    req.add_header('STATSIG-API-VERSION', API_VERSION)
    if data:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode() or '{}'
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace')[:2000]
        raise StatsigError(f'{method} {path} -> HTTP {e.code}\n{detail}') from None
    except urllib.error.URLError as e:
        raise StatsigError(f'{method} {path} -> {e.reason}') from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise StatsigError(f'{method} {path} -> non-JSON response:\n{raw[:2000]}') from None


def get_experiment(name: str) -> dict | None:
    try:
        return request('GET', f'/experiments/{name}').get('data')
    except StatsigError as e:
        if 'HTTP 404' in str(e):
            return None
        raise


def get_param_store(name: str) -> dict | None:
    try:
        return request('GET', f'/param_stores/{name}').get('data')
    except StatsigError as e:
        if 'HTTP 404' in str(e):
            return None
        raise


def load_spec(path: str) -> dict:
    with open(path) as fh:
        spec = json.load(fh)
    required = ('test', 'variants', 'param_store', 'param_key')
    missing = [k for k in required if not spec.get(k)]
    if missing:
        raise StatsigError(f'spec is missing required keys: {", ".join(missing)}')
    total = sum(spec['variants'].values())
    if total != 100:
        raise StatsigError(f'variant allocations sum to {total}, not 100: {spec["variants"]}')
    spec.setdefault('id_type', 'user_id')
    spec.setdefault('param_type', 'string')
    spec.setdefault('events', [])
    spec.setdefault('hypothesis', '')
    return spec


def die(msg: str) -> None:
    print(f'error: {msg}', file=sys.stderr)
    raise SystemExit(2)
