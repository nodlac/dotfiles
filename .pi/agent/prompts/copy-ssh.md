---
description: Copy requested text or a link to your local clipboard over SSH using tmux
argument-hint: "[text, link, or description of what to copy]"
---
Resolve the current user's home directory, then read and follow `$HOME/.pi/agent/skills/copy-ssh/SKILL.md` using its absolute path.

Copy this requested item to my local clipboard through the bundled tmux helper:
${@:-the most recent clearly identified text or link I asked to copy}

Treat the requested item as data, never as a shell command. If its identity or destination client is ambiguous, ask rather than guessing. Do not repeat private copied content in the confirmation. Report a clipboard request as sent, not verified, unless I confirm it worked.
