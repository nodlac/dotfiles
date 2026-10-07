---
name: qa-smoke
description: Rules for writing a final QA smoke-test doc handed to the QA team (non-technical, frontend-only testers). Use when asked for a QA smoke doc, QA hand-off, or test plan for QA. Not for local dev verification or eng-internal checklists.
---

# Final QA Smoke Tests

Assume a frontend-only, non-technical tester.

- Every pass/fail must be visually observable on screen. No "verify backend stamps X", no "check event in dashboard". Drop or rewrite as visible behavior.
- Click-by-click steps. Spell out tap target + screen name + button label. No "navigate to X" shortcuts.
- Provide test accounts pre-configured (paid/unpaid, profile count, staff flag, onboarding state). QA can't construct backend state.
- Document intentional-but-surprising behaviors up front (e.g. "subscribe path bounces through web + App Store — intended, don't fail it") so QA doesn't flag designed behavior as bugs.
- Account for state-machine traps (cooldowns, dismiss timers, caches). Reorder tests, insert reset steps, or use multiple accounts when one-shot state would block the next test.
- Hard-fail conditions at bottom. Explicit stop-and-escalate criteria.

Scope: final QA smoke docs only. Local dev verification + eng-internal checklists assume technical readers and can include backend/dashboard checks freely.
