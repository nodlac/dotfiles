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

## Security
- NEVER ask user paste tokens / passwords / API keys / secrets in chat.
- NEVER save / log secrets in git-tracked or chat-visible files.
- Creds via env var only (`$CLICKUP_TOKEN` etc). Missing → tell user which var to set in `~/.env`, they set it.
- `$ANTHROPIC_API_KEY` → no use unless user explicit asks. No API calls, no test scripts, nothing.

# Agent Instructions

## Files
- Tracker: `$AGENT_FILE` (default `~/.agents/agents.csv`) — row = tmux session name.
- Log: `$AGENT_LOG` (default `~/.agents/agent-log.md`) — append progress anytime.

## Check-in
Finish / blocked / review-ready → run:
```
agent-update done    "summary"
agent-update review  "stuck on X / review Y"
agent-update testing "what + how to test"
agent-update blocked "external blocker"
```
Auto-detects tmux session, updates csv + log.

## Status pick
| Status | Use |
|---|---|
| `done` | Fully complete |
| `review` | Stuck / need human decision / ready for human review |
| `testing` | Done but needs verify |
| `blocked` | External dep blocks (other proj, infra, creds, person) |

Doubt review vs done → review.

## Testing checklist
**FIRST: check `Type` col in `~/.agents/agents.csv`. `Type=analytics` → NO checklist file. Deliverable = analysis itself. Non-negotiable.**

Else on `review`/`testing` → write `~/notes/work_notes/testing-checklists/<TECH-ID>-<slug>.md` (or `<session-name>.md` if no task ID). `agent-update` prints right path — follow it.

Focus on what human verifies, not replay of work. Include:
- Golden path
- Edge cases / regressions worried about
- Known gaps / caveats
- URLs / test accounts / env flags

One checklist per task. Update existing, don't create new.

## Focus mode
`Focus=1` in csv → user flagged uninterrupted. Operate normal. Update via `agent-update`. Never edit `Focus` directly.
