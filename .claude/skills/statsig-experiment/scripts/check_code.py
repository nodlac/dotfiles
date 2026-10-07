#!/usr/bin/env python3
"""Static checks: does the code agree with the spec, and is this skill still current?

Touches no network and needs no API key — it reads the repos. These catch the drift
that Statsig-side checks cannot see, because from Statsig's view a test wired to
strings the code never matches looks perfectly healthy.

    python3 check_code.py spec.json --module src/services/ab_test/serviceWarningTest.js \\
        [--web-root .] [--backend-root ~/vidangel-repo/vidangel-backend]

Exit 0 = code agrees with spec. Exit 1 = drift.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

from statsig_api import ALLOWLIST_KEY, ALLOWLIST_STORE, StatsigError, die, load_spec

FAIL = 'FAIL'
WARN = 'WARN'


def _read(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def check_module(spec: dict, module_path: str, findings: list) -> None:
    """The module is the source of truth; the spec must be a faithful reading of it."""
    if not os.path.exists(module_path):
        findings.append((FAIL, f'test module not found: {module_path}'))
        return
    src = _read(module_path)

    for label, want in (
        ('test name', spec['test']),
        ('param store', spec['param_store']),
        ('param key', spec['param_key']),
    ):
        if f"'{want}'" not in src and f'"{want}"' not in src:
            findings.append(
                (FAIL, f'{label} {want!r} from the spec does not appear in {os.path.basename(module_path)}')
            )

    # Every variant must be a literal the code matches on, or that arm is dead code
    # in the app while Statsig happily serves it.
    for variant in spec['variants']:
        if f"'{variant}'" not in src and f'"{variant}"' not in src:
            findings.append(
                (
                    FAIL,
                    f'variant {variant!r} never appears as a literal in the module — Statsig would '
                    f'serve it and the code would ignore it',
                )
            )

    # The QA pin is how tests get verified without waiting on allocation; it keys off
    # the test name, so a rename that misses it silently disables the pin.
    if 'location.search' not in src:
        findings.append((WARN, 'no ?<test>=<variant> QA pin found in the module'))


def _grep_events(web_root: str) -> dict[str, list[str]]:
    """Event names passed to ABTest.logEvent, mapped to the files that fire them."""
    try:
        out = subprocess.run(
            ['grep', '-rn', '--include=*.vue', '--include=*.js', r"logEvent(\s*['\"]", os.path.join(web_root, 'src')],
            capture_output=True,
            text=True,
        ).stdout
    except FileNotFoundError:
        return {}
    found: dict[str, list[str]] = {}
    for line in out.splitlines():
        m = re.search(r"logEvent\(\s*['\"]([^'\"]+)['\"]", line)
        if not m:
            continue
        where = line.split(':', 1)[0]
        found.setdefault(m.group(1), []).append(os.path.relpath(where, web_root))
    return found


def check_events(spec: dict, web_root: str, findings: list) -> None:
    """Both directions matter. An event fired but not allowlisted is dropped silently;
    an allowlisted event nobody fires is a metric that will never populate."""
    fired = _grep_events(web_root)
    spec_events = set(spec.get('events') or [])

    for ev in sorted(spec_events - set(fired)):
        findings.append(
            (FAIL, f'spec lists event {ev!r} but no ABTest.logEvent call fires it — any metric on it stays empty')
        )

    # Only flag unlisted events from files that also touch this test, so unrelated
    # tests' events don't show up as noise.
    key_hint = spec['param_key'].replace('_variant', '')
    for ev, files in sorted(fired.items()):
        if ev in spec_events:
            continue
        if key_hint in ev or spec['test'] in ev or any(key_hint in f for f in files):
            findings.append(
                (
                    WARN,
                    f'event {ev!r} is fired ({files[0]}) but not in the spec — if it is part of this '
                    f'test it needs an allowlist entry, or it is dropped',
                )
            )


def check_backend_constants(backend_root: str, findings: list) -> None:
    """This skill hardcodes the allowlist store/key. If the backend renames them,
    verify.py would check the wrong store and cheerfully report success."""
    path = os.path.join(os.path.expanduser(backend_root), 'apps/common/services/statsig.py')
    if not os.path.exists(path):
        findings.append((WARN, f'backend not found at {path}; cannot confirm allowlist store/key are current'))
        return
    src = _read(path)
    for const, expected in (('PM_STORE_NAME', ALLOWLIST_STORE), ('PM_STORE_KEY', ALLOWLIST_KEY)):
        m = re.search(rf"^{const}\s*=\s*['\"]([^'\"]+)['\"]", src, re.M)
        if not m:
            findings.append((WARN, f'could not find {const} in the backend; allowlist checks may be stale'))
        elif m.group(1) != expected:
            findings.append(
                (
                    FAIL,
                    f'backend {const} is {m.group(1)!r} but this skill assumes {expected!r} — update '
                    f'ALLOWLIST_STORE/ALLOWLIST_KEY in statsig_api.py or every allowlist check is wrong',
                )
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('spec')
    ap.add_argument('--module', required=True, help='path to the test module')
    ap.add_argument('--web-root', default='.')
    ap.add_argument('--backend-root', default='~/vidangel-repo/vidangel-backend')
    args = ap.parse_args()

    spec = load_spec(args.spec)
    findings: list[tuple[str, str]] = []
    check_module(spec, args.module, findings)
    check_events(spec, args.web_root, findings)
    check_backend_constants(args.backend_root, findings)

    if not findings:
        print('ok: code agrees with the spec')
        return 0
    for level, msg in findings:
        print(f'{level}: {msg}')
    fails = [f for f in findings if f[0] == FAIL]
    print()
    print(f'{len(fails)} blocking, {len(findings) - len(fails)} advisory')
    return 1 if fails else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except StatsigError as e:
        die(str(e))
