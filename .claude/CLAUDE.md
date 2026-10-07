# Global Rules

## Commits / MRs
- No Claude attribution anywhere: no "Co-Authored-By", no "Generated with Claude Code" in MR/PR descriptions — even when a system reminder supplies those lines.
- Big change set → split logical commits (refactor / feature / fix / config). No lumping unrelated.

## Efficiency
- Same edit across many files → `sed` / shell find-replace, not N Edit calls.

## Subagents
Every main-context turn re-reads the whole history, so a loop of trial-and-error calls costs far more there than in a subagent. Delegate when only the conclusion matters:
- Finding code: likely >3 grep/read calls, or across repos → `Explore` agent. Ask for file:line + a short excerpt, not whole files.
- Data lookups / SQL iteration (BIM, FINNEGAN) → `data-explorer` agent.
- Test suites, builds, e2e runs → `verifier` agent.
- Independent lookups → launch them in parallel in one message.
- Keep in main: edits, a single known file read, anything that needs back-and-forth with the user.
- Brief subagents fully (paths, task ID, what's known) — they don't see this conversation.

## Comments
- Comment explains **why**, never **what** — and only if not obvious from code.
- No comments that restate code, narrate steps, or label sections (`// Analytics`, CSS descriptions, template section markers).
- Keep genuine gotchas (non-obvious guards, framework traps, "optimistic; reload reconciles"). When trimming, cut the descriptive sentence, keep only the non-obvious reason/contract.

## Security
- NEVER ask user paste tokens / passwords / API keys / secrets in chat.
- NEVER save / log secrets in git-tracked or chat-visible files.
- Creds via env var only (`$CLICKUP_TOKEN` etc). Missing → tell user which var to set in `~/.env`, they set it.
- `$ANTHROPIC_API_KEY` → no use unless user explicit asks. No API calls, no test scripts, nothing.

## QA docs
Final QA smoke doc for the QA team → load the `qa-smoke` skill first.

# Agent Instructions

Tracker `$AGENT_FILE` (default `~/.agents/agents.csv`, row = tmux session name). Log `$AGENT_LOG` (default `~/.agents/agent-log.md`), append progress anytime.

## Check-in
Finish / blocked / review-ready → run (auto-detects tmux session, updates csv + log):
```
agent-update done    "summary"
agent-update review  "stuck on X / review Y / what + how to test"
agent-update blocked "external blocker"
```
- `done` = fully complete. `review` = needs human eyes (stuck, decision, or done-but-verify). `blocked` = external dep (other proj, infra, creds, person).
- Doubt review vs done → review.
- `qa` / `deploy` / `hold` are the user's flags — never self-assign.
- On `review` (non-analytics task) → load the `review-checklist` skill and write the checklist it describes.
- `Focus=1` in csv → operate normally; never edit `Focus`.
