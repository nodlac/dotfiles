# Global Rules

## Commits / MRs
- Always open PRs/MRs as drafts (`gh pr create --draft`, `glab mr create --draft`).
- Big change set → split logical commits (refactor / feature / fix / config). No lumping unrelated.
- MR/PR descriptions and MR/PR comments (incl. review comments, replies, inline notes) are written by the user, never drafted by Claude. Goal: the user only posts what they understand — writing it themselves is how that's ensured.
  - Before opening an MR or posting a comment: stop and ask the user to write it in their own words. Don't offer a draft, outline, or fill-in template — not even if asked "just give me a start"; offer facts instead (diff summary, findings, links) for them to write from.
  - Then check their text against the diff: flag anything inaccurate, missing (the why, a risky change they skipped), or over the format below. Point out the gaps and suggested tweaks; change nothing on your own. When they ask, apply it — small tweaks directly, bigger gaps they rewrite unless they say to apply those too.
  - Post their final text verbatim. Applies to subagents/skills too (`glab mr create`, `glab mr note`, `gh pr comment`, `/code-review --comment`, API calls) — none post on their own.
  - Format for descriptions: max 2 paragraphs — what changed and why it's needed. Terse, clear. No filler, no file-by-file tours. Include screenshots / recordings where possible.

## Efficiency
- Same edit across many files → `sed` / shell find-replace, not N Edit calls.

## Subagents
Every main-context turn re-reads the whole history, so a loop of trial-and-error calls costs far more there than in a subagent. Delegate when only the conclusion matters:
- Finding code: likely >3 grep/read calls, or across repos → `Explore` agent. Ask for file:line + a short excerpt, not whole files.
- Data lookups / SQL iteration (BIM, FINNEGAN) → `data-explorer` agent.

## DB tunnels
- BIM / FINN connection fails → run `~/tools/ensure-tunnel <bim|finn|bim_stag|finn_stag>` first (it reopens via evaql). Only ask me to open the tunnel if it exits non-zero; include its output.
- Test suites, builds, e2e runs → `verifier` agent.
- Independent lookups → launch them in parallel in one message.
- Keep in main: edits, a single known file read, anything that needs back-and-forth with the user.
- Brief subagents fully (paths, task ID, what's known) — they don't see this conversation.

## Comments
- Comment explains **why**, never **what** — and only if not obvious from code.
- No comments that restate code, narrate steps, or label sections (`// Analytics`, CSS descriptions, template section markers).
- Keep genuine gotchas (non-obvious guards, framework traps, "optimistic; reload reconciles"). When trimming, cut the descriptive sentence, keep only the non-obvious reason/contract.

## Scripts
- Any script that runs longer than a few seconds (migrations, data fixes, batch jobs, analyses) prints progress while it runs: what phase it's in, `i/total` every N items (`flush=True`), and a summary at the end (counts, skips, failures). Note any slow silent phase up front (e.g. "selecting subs...").

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
- `cr` / `qa` / `deploy` / `hold` are the user's flags — never self-assign.
- On `review` (non-analytics task) → load the `review-checklist` skill and write the checklist it describes.
- `Focus=1` in csv → operate normally; never edit `Focus`.

## Focus / Done
- Hours Mon–Fri 5am–6pm MT (`hooks/work-hours.sh` injects the reminder). Outside them: tell me to stop, offer to log it for tomorrow.
- Override (extend a day, weekend P1 push): when I ask, write an MT expiry like `2026-11-08 18:00` to `~/.claude/work-hours-override`; guard stays silent until then. Always set an expiry — ask me for one if I didn't give it. Never open-ended.
- Done = the ask is met + verified once → say "Done." and stop. No unrequested polish, extra dashboard tabs, reruns, or follow-up analyses; offer extras in ≤1 line.
- Before a report/dashboard/analysis: name the decision it changes and who reads it. None → say so, suggest skipping or a 3-line Slack answer.
- Analytics: one refinement pass max unless the new result would flip the decision.
- Drift from the task's stated goal → flag it in one line, suggest parking it as `[FF]` in the tracker. Don't silently expand scope.
- Starting new work while the tracker has >10 `[/]` items → remind me to finish or park one first.
- Parking work → `[FF]` in the tracker with 3 sub-lines: `↻ revisit:` (trigger/date), `Value:` (estimate + source), `State:` (where code/artifacts/branch live). Then stop its agent session.
- Priority: first sub-line `⚑ P1|P2|P3 — reason` under a tracker task (never in the title; sprint-sync renames titles from ClickUp). Claude guesses P from impact (revenue/retention/legal/deadline = P1); my edits win. P1 work before P2; no new P3 while a P1 is open.
- Ship list: `🚢` after the P on the `⚑` line = near-done, finish this sprint. `grep 🚢 sprint_tracker.md` lists them; ship-list items come before starting anything new.
