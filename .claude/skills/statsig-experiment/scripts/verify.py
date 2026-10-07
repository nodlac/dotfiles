#!/usr/bin/env python3
"""Read-only: does Statsig match what the code expects?

Issues nothing but GETs. It cannot modify Statsig, so the worst case for a wrong
assumption in here is a wrong answer, not a broken store.

    python3 verify.py spec.json

Exit 0 = Statsig matches the spec. Exit 1 = drift, reported as findings.
"""

from __future__ import annotations

import sys

from statsig_api import (
    ALLOWLIST_KEY,
    ALLOWLIST_STORE,
    StatsigError,
    die,
    get_experiment,
    get_param_store,
    load_spec,
)

FAIL = 'FAIL'
WARN = 'WARN'
OK = 'ok'


def check_experiment(spec: dict, findings: list) -> None:
    name = spec['test']
    exp = get_experiment(name)
    if exp is None:
        findings.append((FAIL, f'experiment {name!r} does not exist'))
        return

    status = exp.get('status')
    non_prod = exp.get('enabledNonProdEnvironments') or []
    if status != 'active':
        if non_prod:
            findings.append(
                (
                    WARN,
                    f'experiment {name!r} status is {status!r} but is enabled for '
                    f'{", ".join(non_prod)} — it serves there and not in production. Start it '
                    f'when you want production traffic',
                )
            )
        else:
            findings.append(
                (
                    FAIL,
                    f'experiment {name!r} status is {status!r} with no non-prod environments '
                    f'enabled — it allocates nowhere, so every read falls through to the fallback',
                )
            )

    got_id = exp.get('idType')
    want_id = spec['id_type']
    if got_id != want_id:
        findings.append(
            (
                FAIL,
                f'experiment idType is {got_id!r}, spec wants {want_id!r} — a mismatch '
                f'buckets on a different unit than the backend sends',
            )
        )

    groups = exp.get('groups') or []
    got_names = sorted(g.get('name', '') for g in groups)
    want_names = sorted(spec['variants'])
    if got_names != want_names:
        findings.append(
            (FAIL, f'variant names are {got_names}, spec wants {want_names} — the code string-matches these')
        )

    total = sum(g.get('size', 0) for g in groups)
    if total != 100:
        findings.append((WARN, f'group sizes sum to {total}, not 100'))

    # The store key and the experiment's own parameter name are different strings by
    # design; the store maps one to the other via param_name. Groups carry the latter.
    key = spec.get('experiment_param') or spec['param_key']
    for g in groups:
        gname = g.get('name', '?')
        values = g.get('parameterValues') or {}
        if key not in values:
            findings.append(
                (FAIL, f'group {gname!r} has no parameterValues[{key!r}] — reads fall through to the fallback')
            )
        elif values[key] != gname:
            findings.append(
                (
                    FAIL,
                    f'group {gname!r} returns {values[key]!r} for {key!r}; the code matches on '
                    f'the variant name, so it should return {gname!r}',
                )
            )

    alloc = exp.get('allocation')
    if isinstance(alloc, (int, float)) and alloc < 100:
        findings.append((WARN, f'layer allocation is {alloc}% — some accounts get no assignment by design'))

    # Not automatable, but checkable: an experiment with no primary metric cannot be
    # read out, which you only discover when you go looking for results.
    if not (exp.get('primaryMetrics') or []):
        findings.append((FAIL, f'experiment {name!r} has no primary metrics — there is nothing to read out'))
    if not (exp.get('secondaryMetrics') or []):
        findings.append((WARN, f'experiment {name!r} has no secondary metrics'))

    gate = exp.get('targetingGateID') or exp.get('targetingGateName')
    if gate:
        findings.append(
            (
                WARN,
                f'targeting gate {gate!r} is set — accounts it excludes get no assignment and read the '
                f'fallback, which looks identical to a broken setup',
            )
        )

    # No override check here on purpose. The experiment payload carries no `overrides` or
    # `userIDOverrides` field (confirmed against the live API), so the check that used to
    # live here could never fire — worse than no check, because it implied coverage. A
    # forgotten QA override does skew results; detecting it needs the overrides endpoint,
    # which is not implemented yet.


def check_param_store(spec: dict, findings: list) -> None:
    store_name = spec['param_store']
    store = get_param_store(store_name)
    if store is None:
        findings.append((FAIL, f'parameter store {store_name!r} does not exist or is unreadable'))
        return

    params = store.get('parameters') or []
    key = spec['param_key']
    match = next((p for p in params if p.get('name') == key), None)
    if match is None:
        have = ', '.join(sorted(p.get('name', '?') for p in params)) or '(none)'
        findings.append(
            (FAIL, f'{store_name} has no parameter {key!r}. Present: {have}')
        )
        return

    ref = match.get('ref_type')
    if ref != 'experiment':
        findings.append(
            (FAIL, f'{store_name}.{key} ref_type is {ref!r}, not "experiment" — it is not wired to the test')
        )
    exp_name = match.get('experiment_name')
    if exp_name and exp_name != spec['test']:
        findings.append((FAIL, f'{store_name}.{key} points at experiment {exp_name!r}, spec wants {spec["test"]!r}'))

    want_param = spec.get('experiment_param')
    got_param = match.get('param_name')
    if want_param and got_param != want_param:
        findings.append(
            (
                FAIL,
                f'{store_name}.{key} maps to experiment parameter {got_param!r}, spec wants '
                f'{want_param!r} — the store would read a parameter the groups do not set',
            )
        )

    ptype = match.get('param_type')
    if ptype != spec['param_type']:
        findings.append(
            (
                FAIL,
                f'{store_name}.{key} param_type is {ptype!r}, spec wants {spec["param_type"]!r} — the '
                f'backend picks its typed getter from the default the client sends',
            )
        )

    # Not fatal: the client sends a sentinel, so it can tell this case apart itself.
    if match.get('value') not in (None, ''):
        findings.append((WARN, f'{store_name}.{key} static fallback is {match.get("value")!r}; expected empty'))


def check_allowlist(spec: dict, findings: list) -> None:
    events = spec.get('events') or []
    if not events:
        return
    store = get_param_store(ALLOWLIST_STORE)
    if store is None:
        findings.append((FAIL, f'{ALLOWLIST_STORE!r} is unreadable — when the backend cannot fetch it, it drops ALL events'))
        return
    entry = next((p for p in (store.get('parameters') or []) if p.get('name') == ALLOWLIST_KEY), None)
    if entry is None:
        findings.append((FAIL, f'{ALLOWLIST_STORE} has no {ALLOWLIST_KEY!r} parameter — every Statsig event is being dropped'))
        return
    allowed = ((entry.get('value') or {}).get('allowed_events')) or {}
    for ev in events:
        if ev not in allowed:
            findings.append(
                (FAIL, f'event {ev!r} is not in {ALLOWLIST_KEY} — log-event returns 204 and the backend drops it silently')
            )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        die('usage: verify.py spec.json')
    spec = load_spec(argv[1])

    print(f'test          : {spec["test"]}')
    print(f'param         : {spec["param_store"]}.{spec["param_key"]} ({spec["param_type"]})')
    print(f'variants      : {spec["variants"]}')
    print(f'id type       : {spec["id_type"]}')
    print(f'events        : {", ".join(spec["events"]) or "(none)"}')
    print()

    findings: list[tuple[str, str]] = []
    check_experiment(spec, findings)
    check_param_store(spec, findings)
    check_allowlist(spec, findings)

    if not findings:
        print(f'{OK}: Statsig matches the spec')
        return 0

    fails = [f for f in findings if f[0] == FAIL]
    for level, msg in findings:
        print(f'{level}: {msg}')
    print()
    print(f'{len(fails)} blocking, {len(findings) - len(fails)} advisory')
    return 1 if fails else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv))
    except StatsigError as e:
        die(str(e))
