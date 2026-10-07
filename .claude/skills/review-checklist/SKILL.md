---
name: review-checklist
description: Format and rules for the testing checklist an agent writes when moving a task to review (agent-update review). Use right before or after running agent-update review on a non-analytics task.
---

# Review testing checklist

**First: check the `Type` col in `~/.agents/agents.csv`. `Type=analytics` → NO checklist file. The analysis is the deliverable.**

Path: `~/notes/work_notes/testing-checklists/TECH_####_task_description.md` (underscores throughout; no task ID → underscored `<session-name>.md`). `agent-update` prints the right path — follow it exactly.

**Format: an actual checklist.** Every verification step is a `- [ ]` checkbox written as a concrete action a user can perform — click-by-click where it helps (tap target + screen + button label), not a description of the work done. A reader must be able to run each line and mark it off.

Cover what the human verifies, not a replay of the work:
- Golden path (ordered `- [ ]` steps)
- Edge cases / regressions worried about (each its own `- [ ]`)
- Known gaps / caveats
- URLs / test accounts / env flags

One checklist per task — update the existing one, don't create another. `agent-update done` auto-deletes it.
