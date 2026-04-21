# Global Rules

## Security
- NEVER ask the user to paste tokens, passwords, API keys, or any secrets into the chat.
- NEVER save or log secrets in any file that is tracked by git or visible in conversation history.
- Access credentials only through environment variables (e.g. `$CLICKUP_TOKEN`). If a credential is missing, tell the user which env var to set in `~/.env` and have them do it themselves.

# Agent Instructions

## Files you can read and write

- **Agent tracker**: `~/notes/work_notes/sprints/agents.csv` — your row is identified by your tmux session name
- **Agent log**: `~/notes/work_notes/sprints/agent-log.md` — append progress notes here any time
- **Current sprint**: the highest-numbered file matching `~/notes/work_notes/sprints/sprint_*.md` — read this for task context, acceptance criteria, and related work

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

When moving to `review` or `testing`, write a testing checklist to `~/notes/work_notes/testing-checklists/<TECH-ID>-<short-slug>.md` (or `<session-name>.md` if no task ID). Keep it focused on what a human should verify, not a replay of what you did. Include:

- Golden-path steps (the feature working end-to-end)
- Edge cases and regressions you were worried about
- Any known gaps or caveats
- Relevant URLs, test accounts, or env flags

One checklist per task. Update it (don't create a new one) if the task already has a file.
