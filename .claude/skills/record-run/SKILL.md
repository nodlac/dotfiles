---
name: record-run
description: Record a Playwright video of your own change working so the user can watch it instead of manually testing. Use after finishing a UI change, when asked to "record a video", "prove it works", "show me", or before agent-update review. Works against the app dev server or Storybook.
---

# record-run — video proof of a change

**Scope: web repos only** (`www.vidangel.com`, `investment-site`, and the
Storybook lane). The harness is Playwright/Chromium driving a page: `startApp()`
parses vite's port, the Storybook lane assumes :6006, and auth is a
`.vidangel.com` browser cookie. None of that reaches a native app.

Other repo types need their own lane, and using this one is worse than nothing —
it produces a video of the wrong thing:

| Repo | How to prove a change |
| --- | --- |
| `android` (Kotlin/Compose) | **Built** — Maestro flow + `~/tools/mobile/record-android.sh`. |
| `apple-clients` (Swift, iOS/tvOS) | **Built** — same flow format + `~/tools/mobile/record-apple.sh`. |
| `browser-extension` | Chromium *with the extension loaded* — this harness launches a clean context, so it cannot see extension behavior. |
| `vidangel-backend`, `pier`, `knecht`, `vidangel-hoover`, `vidangel-retention`, analytics work | Do not record video. The deliverable is tests, query output, or the analysis itself. |

Native repos use the mobile lanes — three commands each, one shared Maestro flow
format, and everything below about probing first, one behavior per scenario, and
requirement wording still applies. Full detail in `~/tools/mobile/README.md`.

```sh
test-android --mobile                                  # you boot it; never kill another agent's
~/tools/mobile/probe.sh                                # what's on screen, ~15 lines not 1453
~/tools/mobile/record-android.sh e2e/thing.flow.yaml   # run + record

test-apple --iphone                                    # same shape for iOS/tvOS
~/tools/mobile/record-apple.sh e2e/thing.flow.yaml
```

**Mobile recordings film the real signed-in account.** Maestro has no
request-level mocking, and `clearState: true` does not log you out on iOS (the
session is in the Keychain). Before recording anything you'll share, sign the
device into a dedicated test account or write the flow against a logged-out
screen — do not assume the mocked-identity trick from the app lane is available.

Record a short Chromium video of the change in action. Video lands in
`~/.agents/videos/<tmux-session>/`, newest also symlinked at
`~/.agents/videos/latest.mp4`. User watches with `agent-video` (opens latest)
or `agent-video <session>`.

**The test runs itself.** You write one throwaway scenario script, run it, and
read two lines of output. Never open the video, never screenshot frames, never
dump page HTML into your context to hunt for a selector — the harness prints
what it saw on failure (see *Iterate dry* below). Your job is authoring the
scenario and relaying the verdict + path.

## Probe first, iterate dry, record once

**Never grep app source for selectors, endpoint shapes, or ids.** Ask the
running app once:

```
node ~/tools/pw/probe.mjs https://127.0.0.1:9005/browse [--auth]
```

Prints the route's real URL, visible text, every interactive element's
selector + accessible name, the image CDN hosts, and every XHR/fetch it made
with status and response-shape keys. One read replaces a source expedition.

Then debug off film — that's the expensive part:

```
PW_DRY=1 node scenario.mjs      # seconds, no video, no ffmpeg, same verdict
node scenario.mjs               # once it passes — the real recording
```

`PW_DRY=1` drops slowMo and every viewer-pacing hold. On failure (dry or not)
the harness prints the failing error plus the same app-state dump — read that
instead of re-running blind. `app frame unreachable` means the goto never
landed; check the URL and auth first.

Every requirement must be checked or failed. **A requirement never asserted
fails the run** and is reported as `– … (never asserted)`.

## Shared harness

Playwright lives in `~/tools/pw` (already installed — never `npm i playwright`
in the project repo). Write the scenario in your scratchpad:

```js
import { record, storyUrl, BASE_URL } from '/Users/medina_station/tools/pw/record.mjs'

await record('short-scenario-name', async (app, ui, page) => {
  await app.goto(`${BASE_URL}/some/route`)   // app = iframe Frame; same locator API as page
  await app.getByRole('button', { name: 'Cancel' }).click()
  await app.waitForSelector('.survey')
  await ui.check(0)              // flips requirement 0 to ✅ live on film
  await ui.check('survey')       // or match requirement by substring
  await ui.hold(800)             // let the result sit on screen (skipped when dry)
  // ui.fail(which, 'note') marks ❌ with a note — use when a requirement is
  // observably broken but you want the rest of the run recorded anyway
}, {
  meta: {
    objective: 'One sentence: what this recording proves.',
    requirements: ['acceptance criteria from the task, one per line'],
    pr: '!123', // MR/PR ref if one exists
  },
})
```

The video shows the app (left, 1280px) beside a live checklist panel (right):
scenario name, agent/task/PR/branch, objective, and the requirements — which
check off ✅ or fail ❌ in real time as `ui.check`/`ui.fail` fire. Run ends
with a PASSED/FAILED banner in the panel (uncaught errors print in the panel
too, and freeze the app's broken state on film).

**Always pass `meta`**, and call `ui.check(...)` immediately after each
requirement is visibly proven — a recording with no checkoffs is much less
useful. Every requirement should be checked or failed by the end. **List
`requirements` in the order the scenario proves them** — the panel checks
top-to-bottom as the video plays; out-of-order checkoffs make the viewer hunt.
tmux session, git branch, and the task row from `~/.agents/agents.csv` are
auto-detected; run the scenario from your worktree so branch detection works.

Use `ui.hold(ms)` **only** for viewer pacing — letting a result sit on screen.
A dry run skips it entirely, so any wait the behavior actually depends on must
be `app.waitForTimeout(ms)`. Getting this backwards is subtle and expensive: a
scenario that passes on film fails when dry, and the failure looks like a
product bug rather than a mis-typed wait. If a spec passes recorded but fails
dry, suspect a `ui.hold` that should be a real wait before you suspect the app.

## Don't film what can't be watched

Requirements a viewer cannot see — call counts, ledger state, cache behavior —
are assertions, not footage. Mark them `{ text: '...', visual: false }` so the
panel labels them *asserted* instead of implying the viewer should spot them,
and prove them with plain JS counters plus `ui.check`. Filming invisible logic
is what turns a 40-line scenario into a 190-line one.

## Pick a lane

Default to Storybook. Escalate to the app lane deliberately, when the behavior
genuinely needs it: route guards and redirects, auth or subscription state,
multi-page flows, backend contract, or anything where the integration *is* the
thing under test. When you escalate, go all the way — real staging content plus
mocked identity beats a mock-everything scenario that proves only your fixtures.

1. **Storybook lane** (default for component-level change): no
   backend, no auth, deterministic.
   - Server up? `curl -sf http://localhost:6006/iframe.html -o /dev/null`
   - Else start in background: `npm run storybook -- --no-open` (repo root),
     wait for 6006 to answer.
   - If the component has no story yet, **write one** — that's part of the
     deliverable, commit it separately.
   - Navigate with `storyUrl('path-to-story--variant')`. Story id = lowercased
     title from the `.stories.js` `title:` field + `--` + kebab-case export name.

2. **App lane** (route-level / integration changes): use `startApp()` — it
   spawns a fresh dev server for **your worktree** on whatever port vite
   picks, and never trusts an already-running server that may serve a
   different branch. Do NOT curl for existing servers or start `npm start`
   yourself, and NEVER kill a listener you didn't spawn — other agents' dev
   servers share this machine.

   Don't hand-roll auth, consent, or passthrough plumbing — import it:

   ```js
   import { spec, startApp, authCookie, cookieHost, dismissConsent, unauthed, json }
     from '/Users/medina_station/tools/pw/record.mjs'

   const server = await startApp()          // run from your worktree; or startApp({ dir })
   try {
     await spec('scenario', async (app, ui, page) => {
       await page.context().route('**/api-staging.vidangel.com/**', (route) => {
         const p = new URL(route.request().url()).pathname
         if (p.includes('/users/current')) return route.fulfill(json(USER))
         return unauthed(route)             // real public traffic, fake token stripped
       })
       await app.goto(cookieHost(server.url) + '/route')   // see below — 127.0.0.1 gets no cookie
       await dismissConsent(app)
     }, { cookies: [authCookie()], meta: { /* ... */ } })
   } finally {
     server.stop()
   }
   ```

   - **`cookieHost()` is required for anything logged in.** `authCookie()` is
     scoped to `.vidangel.com`, so a server reached at `127.0.0.1` never
     receives it and the app boots logged out — which looks like a broken
     selector, not an auth problem.

   - Mock only what the requirement depends on — identity and the endpoints
     under test. Let catalog, artwork, and hero content come from real staging
     so the footage is the real design. When a requirement is proven against a
     mock, word it that way ("success state renders given a 200") so the video
     doesn't overclaim.
   - mkcert https is already handled (`ignoreHTTPSErrors` in the harness).

## Scenario rules

- One scenario = one user-visible behavior, 5–30 seconds of footage.
- Pacing is built in: every action is slowed 600ms (`slowMo`, override via
  `record(name, fn, { slowMo: N, meta })`), a visible cursor follows the
  mouse, and clicks flash a ripple. Type with
  `pressSequentially(text, { delay: 90 })`, never `fill`, when the typing
  itself is the thing being shown.
- Record the *change*, not a full regression suite. 1–3 scenarios max.
- Kill any server you started when done.

## Keep the scenario — it's the e2e test

Write scenarios with `spec()`, not `record()`, and save them in the repo's
`e2e/` dir as `<thing>.e2e.mjs` instead of leaving them in scratchpad. Same file,
two modes:

```sh
node ~/tools/pw/e2e.mjs e2e            # whole suite, headless, no video
PW_FILM=1 node e2e/thing.e2e.mjs       # the review recording
```

Before authoring anything, **read `e2e/` and copy the closest existing spec** —
its mocks, auth, and helpers are already correct. Re-deriving them from scratch
is the single most expensive thing you can do here.

A spec for unmerged work goes in as `<thing>.pending.mjs` (the runner globs only
`*.e2e.mjs`), so the suite stays green. Rename it when the feature lands.

## Hand-off

- Put the printed video path(s) in the testing checklist under a
  `## Recordings` heading, one line each: `- [scenario] — /path/to.mp4 — what
  it shows`.
- Mention in your `agent-update review` note that recordings exist.

## Changing the harness

Edited `record.mjs`? Run `node ~/tools/pw/selfcheck.mjs` — covers the dry,
recorded, and failure-diagnostic paths.
