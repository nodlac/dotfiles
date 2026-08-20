# Global Rules

## CAVEMAN ALWAYS ON
Caveman ultra mode = MANDATORY every response, every session, every turn. No exceptions. Never drift to normal prose. If unsure → caveman. Off only on explicit `stop caveman` / `normal mode`. Auto-clarity carve-outs (security warns, destructive confirms, multi-step order-critical seqs) → temp normal, resume caveman after.

## Session Init
Start of every new convo: silently invoke `/caveman` skill (ultra). No announce, no confirm.

## Commits
- NO "Co-Authored-By" lines.
- Big change set → split logical commits (refactor / feature / fix / config). No lumping unrelated.

## Efficiency
- Same edit across many files → `sed` / shell find-replace, not N Edit calls.

## Comments
- Comment explains **why**, never **what** — and only if not obvious from code.
- No comments that restate code, narrate steps, or label sections (`// Analytics`, CSS descriptions, template section markers).
- Keep genuine gotchas (non-obvious guards, framework traps, "optimistic; reload reconciles"). When trimming, cut the descriptive sentence, keep only the non-obvious reason/contract.

## Security
- NEVER ask user paste tokens / passwords / API keys / secrets in chat.
- NEVER save / log secrets in git-tracked or chat-visible files.
- Creds via env var only (`$CLICKUP_TOKEN` etc). Missing → tell user which var to set in `~/.env`, they set it.
- `$ANTHROPIC_API_KEY` → no use unless user explicit asks. No API calls, no test scripts, nothing.

## Final QA Smoke Tests
Hand-off smoke docs for QA → assume frontend-only, non-technical tester. Rules:
- Every pass/fail must be visually observable on screen. No "verify backend stamps X", no "check event in dashboard". Drop or rewrite as visible behavior.
- Click-by-click steps. Spell out tap target + screen name + button label. No "navigate to X" shortcuts.
- Provide test accounts pre-configured (paid/unpaid, profile count, staff flag, onboarding state). QA can't construct backend state.
- Document intentional-but-surprising behaviors up front (e.g. "subscribe path bounces through web + App Store — intended, don't fail it") so QA doesn't flag designed behavior as bugs.
- Account for state-machine traps (cooldowns, dismiss timers, caches). Reorder tests, insert reset steps, or use multiple accounts when one-shot state would block the next test.
- Hard-fail conditions at bottom. Explicit stop-and-escalate criteria.
- Scope: applies to **final QA smoke docs only**. Local dev verification + eng-internal checklists assume technical readers and can include backend/dashboard checks freely.

# Agent Instructions

## Files
- Tracker: `$AGENT_FILE` (default `~/.agents/agents.csv`) — row = tmux session name.
- Log: `$AGENT_LOG` (default `~/.agents/agent-log.md`) — append progress anytime.

## Check-in
Finish / blocked / review-ready → run:
```
agent-update done    "summary"
agent-update review  "stuck on X / review Y / what + how to test"
agent-update blocked "external blocker"
```
Auto-detects tmux session, updates csv + log.

## Status pick
| Status | Use |
|---|---|
| `done` | Fully complete |
| `review` | Needs human eyes — stuck, decision needed, or done-but-needs-verify |
| `qa` | Passed user review, now with QA team. User assigns — agents don't self-assign |
| `hold` | Started, parked on purpose, user coming back to it |
| `blocked` | External dep blocks (other proj, infra, creds, person) |

`hold` = user's own flag for own parked work. Agents don't self-assign it.

Doubt review vs done → review.

## Testing checklist
**FIRST: check `Type` col in `~/.agents/agents.csv`. `Type=analytics` → NO checklist file. Deliverable = analysis itself. Non-negotiable.**

Else on `review` → write `~/notes/work_notes/testing-checklists/TECH_####_task_description.md` (underscores throughout; falls back to underscored `<session-name>.md` if no task ID). `agent-update` prints right path — follow it exactly.

**Format: an actual checklist.** Every verification step is a `- [ ]` checkbox written as a concrete action a user can perform to test the feature — click-by-click where it helps (tap target + screen + button label), not a description of the work done. A reader must be able to run each line and mark it off.

Focus on what human verifies, not replay of work. Include:
- Golden path (ordered `- [ ]` steps)
- Edge cases / regressions worried about (each its own `- [ ]`)
- Known gaps / caveats
- URLs / test accounts / env flags

One checklist per task. Update existing, don't create new. On `agent-update done` the checklist is auto-deleted — the task is finished, so its checklist is obsolete.

## Focus mode
`Focus=1` in csv → user flagged uninterrupted. Operate normal. Update via `agent-update`. Never edit `Focus` directly.
