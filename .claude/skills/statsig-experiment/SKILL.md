---
name: statsig-experiment
description: >
  Verify a Statsig experiment against its definition in code, and diagnose one that reads back
  empty or whose events never arrive. Reads the test module in the repo as the source of truth,
  then checks Statsig config, the codebase, and per-account evaluation for drift. Read-only —
  it reports what to change in the console, it does not provision anything.
  Use when the user is standing up a new A/B test, says a variant comes back "" or empty,
  says Statsig events aren't showing up, asks to check or verify Statsig config, or invokes
  /statsig-experiment.
---

# Statsig experiment setup, driven from code

The point of this skill: a test used to be one line — `ABTest.expose(TEST_NAME, VARIATIONS,
'account')` — reviewable in a diff with no out-of-band state. Statsig splits that into code
plus console config, and the console half **fails silently**. This restores the original
ergonomics: the test module in the repo is the source of truth, and this skill makes Statsig
match it.

## The three silent failures this exists to prevent

1. **Parameter missing or experiment not started** → the read returns the store's fallback,
   everyone gets control, nothing errors. Indistinguishable from "test is off".
2. **Event not in the allowlist** → `log-event/` returns 204 and the backend drops the event.
   Nothing errors, and Statsig shows no data.
3. **Shared parameter store clobbered** → the update endpoint takes the *whole* `parameters`
   array. A write that omits existing entries silently deletes live flags
   (`markwatched_enabled`, `content_guide_position`, …). Worse for `event_pipeline`: drop
   `event_allowlist` and every Statsig event stops flowing, app-wide.

## Current state: read-only

**Only `verify.py` exists, and it issues nothing but GETs.** There is no write path yet, by
decision — the param-store endpoint replaces the *whole* `parameters` array, and untested code
doing that against a store holding live flags is not a risk worth taking. Setup itself is
still done in the Statsig console; this skill tells you precisely what's wrong when it doesn't
work.

Before a write path is added, all three must hold:

1. Exercised against a **throwaway Statsig project** first, so payload shapes are confirmed
   against the real API with nothing live at stake.
2. A **dry-run** that prints the exact POST body and a diff against current state.
3. **`event_pipeline` is never written by tooling.** Its failure is app-wide and invisible: if
   the backend can't read `event_allowlist`, it drops every event. Two entries a week is not
   worth that exposure.

## Hard rules

- **The client refuses non-GET.** `statsig_api.request()` raises on POST/PATCH/PUT/DELETE
  unless the caller passes `allow_write=True`, and nothing here does. The available Console
  keys are read_write at project level, so Statsig will not stop a mutation — this does.
  Adding a write means opting in at the call site, visible in a diff.
- **Never blind-write.** Any future mutation is read → splice → diff → confirm. Do not
  substitute ad-hoc curl for it.
- **Never delete.** Reconciling only adds or updates keys in the spec; everything else in a
  store is echoed back untouched. Retiring a test is manual on purpose.
- **Code wins.** When the module and Statsig disagree, the module is right — that's the point.
  Show the diff and confirm before changing anything.
- **The key is `$STATSIG_CONSOLE_API_KEY`**, a Console API key (console.statsig.com/api_keys)
  — a *different* key type from the server SDK secret in Django's `STATSIG_API_KEY`. Never
  print it, never write it to a file, never pass it as a CLI argument.

## What this can never own

Code can declare the test's mechanics — name, variants, parameter, event names. It cannot
declare what winning means. Metric definitions live in Statsig, and experiment creation
requires naming primary and secondary metrics. So the durable split is: assignment plumbing
from code, measurement in Statsig. This is less than the old `ABTest.expose` one-liner gave;
don't pretend otherwise to the user.

## Workflow

1. **Derive the spec from code.** Read the test module (e.g.
   `src/services/ab_test/serviceWarningTest.js`) and extract: test name, parameter store,
   parameter key, the variant strings the code matches on, and every event name passed to
   `ABTest.logEvent`. Grep the call sites for the `logEvent` names — they're usually not all
   in the module.
2. **Show the spec and confirm it.** Print it as JSON and have the user check it. A wrong
   variant string here means a test that reads back a value the code ignores.
   Write it to the scratchpad, not the repo — it's a transient hand-off to the scripts, and a
   committed copy would become the second source of truth this skill exists to avoid.
3. **Verify.** `scripts/verify.py spec.json` — reports what exists, what's missing, what
   mismatches. Exit 0 means Statsig already matches the code; exit 1 lists the drift.
4. **Report the findings and what to click.** Each finding names the specific console change.
   There is no write path — see "Current state" above.
5. **Verify again** after they've made the changes, then have them load an affected page and
   confirm the parameter returns a real variant rather than the fallback.

## Verifying the parts that aren't automated

Setup is manual, so verification has to reach further than the Console API does. Four layers,
cheapest first. All read-only.

**1. Code vs spec — no API key needed, so run it first.**

```
python3 scripts/check_code.py spec.json --module src/services/ab_test/<test>.js --web-root .
```

Catches what Statsig cannot see: from Statsig's side, a test wired to variant strings the code
never matches looks perfectly healthy. It checks that every variant appears as a literal in the
module, that the test name / store / key in the spec are really in the code, that every spec
event has an `ABTest.logEvent` call firing it (and flags related events fired but *not*
allowlisted, which get dropped), that the QA pin survives, and that the backend still names the
allowlist store `event_pipeline`/`event_allowlist` — if that were renamed, the allowlist checks
would pass while checking nothing.

**2. Statsig config — needs the Console API key.**

```
python3 scripts/verify.py spec.json
```

Beyond assignment wiring this also reports the manual-only parts: missing primary metrics (an
experiment with none cannot be read out), a targeting gate (accounts it excludes read the
fallback, indistinguishable from a broken setup), and leftover QA overrides.

**3. Does it evaluate for a specific account?** Neither of the above can answer this — the
Console API reports config, not per-user evaluation. In the backend repo:

```
python manage.py shell < scripts/evaluate_for_user.py
```

Edit `EMAIL` first. It prints whether the store resolves, what the parameter returns with a
sentinel default versus an empty one, a known-good key in the same store as a control, and the
account's Statsig `user_id` plus its `staff` / `beta_user` flags — the usual reasons a targeting
rule excludes someone.

**4. In the browser, signed in as a real account.** `POST feature-flags/parameter-store/<store>/`
returns a real variant rather than the fallback; the console carries no
`<test>: … resolved empty` warning; `POST feature-flags/log-event/` fires and the events appear
in Statsig.

Timing and gotchas that make step 4 lie:

- The allowlist is cached **60s** in the backend. After editing it, wait a minute.
- `log-event/` is `IsAuthenticated`; signed-out sessions log nothing.
- Event metadata is stringified server-side (`{str(k): str(v)}`, nulls dropped), so booleans
  arrive as `"True"`/`"False"` in Python casing. Metric filters that expect `true` match nothing.

## Spec format

```json
{
  "test": "web_service_link_warning",
  "hypothesis": "Warning + relink CTA on the title page recovers more blocked plays.",
  "id_type": "userID",
  "variants": { "control": 34, "show_warning": 33, "link_to_play": 33 },
  "param_store": "content_features",
  "param_key": "service_link_warning_variant",
  "experiment_param": "web_service_link_warning_params",
  "param_type": "string",
  "events": ["service_warning", "service_warning_play_clicked"]
}
```

**`param_key` and `experiment_param` are different strings and both matter.** `param_key` is
the key in the parameter store, which is what the app asks for. `experiment_param` is the
parameter *inside the experiment*, which is what each group sets a value for. The store links
them via its `param_name` field. Conflating the two produces a confident, wrong report that
the groups are missing their values — check the raw payload before telling anyone to change
config.

`variants` maps variant name → allocation percent, and must sum to 100. The variant name is
also the value returned for that group, because the code string-matches on it.

`id_type` must match the unit the backend sends. In vidangel-backend that's
`str(request.user.id)` (`apps/common/services/statsig.py`, `user_from_request`), which Statsig
reports as **`userID`** — note the casing. The Console API docs example says `user_id`; the
live API returns `userID`, and a spec using the doc value produces a bogus mismatch finding.

## Notes and limits

- Written against the documented Console API (`https://statsigapi.net/console/v1`, version
  `20240601`). It has **not** been exercised against a live project — on first use run
  `verify.py` only, and expect to adjust response-shape handling if Statsig's payloads differ
  from the docs. Fix the script rather than working around it.
- The parameter's *static fallback* (the empty string this repo relies on to tell "no
  assignment" apart from "assigned to control") may not be settable through the param-store
  endpoint, which documents only `ref_type: experiment`. If `verify.py` reports the parameter
  as experiment-backed but reads still come back empty, check the fallback in the console.
- Analysis and results stay in the Statsig UI. This covers launching, not reading outcomes.
