# Global Rules

## Commits
- Do NOT add "Co-Authored-By" lines to commit messages.
- When committing a large set of changes, break them into logical commits — one per concern (e.g., refactor, new feature, bug fix, config change). Do not lump unrelated changes into a single commit.

## Efficiency
- When making the same or similar edit across many files, prefer `sed` or other shell-based find-and-replace over individual Edit tool calls to avoid burning tokens on repetitive changes.

## Security
- NEVER ask the user to paste tokens, passwords, API keys, or any secrets into the chat.
- NEVER save or log secrets in any file that is tracked by git or visible in conversation history.
- Access credentials only through environment variables (e.g. `$CLICKUP_TOKEN`). If a credential is missing, tell the user which env var to set in `~/.env` and have them do it themselves.
- Do NOT use the Anthropic API key (`$ANTHROPIC_API_KEY`) for any purpose unless the user explicitly asks you to. This includes making API calls, building test scripts, or any other use.

## Session Init

At the start of every new conversation, before doing any other work, invoke the `/caveman` skill to activate caveman mode. Do this silently — no need to announce it or wait for user confirmation.

# Agent Instructions

## Files you can read and write

- **Agent tracker**: `$AGENT_FILE` (default `~/.agents/agents.csv`) — your row is identified by your tmux session name
- **Agent log**: `$AGENT_LOG` (default `~/.agents/agent-log.md`) — append progress notes here any time

## Check-in protocol

When you **finish**, get **blocked**, or are **ready for review**, run:

```
agent-update done    "brief summary of what you accomplished"
agent-update review  "stuck on X / ready for review of Y"
agent-update testing "what needs to be tested and how"
agent-update blocked "what external thing is preventing progress"
```

This auto-detects your tmux session name and updates both `agents.csv` and `agent-log.md`.

You can also append notes to `agent-log.md` directly at any time to leave progress updates mid-task.

### Choosing the right status

| Status | When to use |
|--------|-------------|
| `done` | Task is **fully complete**, no further work needed |
| `review` | You're stuck, need a human decision, or need input to proceed — also use when work is ready for human review |
| `testing` | Work is done but needs to be tested before it's considered complete |
| `blocked` | An **external dependency** is preventing progress — another project isn't done, infra is down, missing credentials, waiting on someone else |

When in doubt between `review` and `done`, use `review`.

### Testing checklist

When moving to `review` or `testing`, write a testing checklist to `~/notes/work_notes/testing-checklists/<TECH-ID>-<short-slug>.md` (or `<session-name>.md` if no task ID). Skip this for analytics tasks (Type=`analytics` in agents.csv) — their deliverable is the analysis itself, not something a reviewer re-runs.

Keep it focused on what a human should verify, not a replay of what you did. Include:

- Golden-path steps (the feature working end-to-end)
- Edge cases and regressions you were worried about
- Any known gaps or caveats
- Relevant URLs, test accounts, or env flags

One checklist per task. Update it (don't create a new one) if the task already has a file.

### Focus mode

If the `Focus` column for your session in `agents.csv` is `1`, the user has flagged this session for uninterrupted work. Operate normally — update status via `agent-update` as usual. Just don't alter the `Focus` flag itself by editing `agents.csv` directly.
