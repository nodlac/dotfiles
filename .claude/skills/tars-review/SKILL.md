---
name: tars-review
description: Send one or more GitLab MRs to TARS (VidAngel's Slack review agent) for code review, wait for its verdict, return it. Use when the user says "tars review", "have TARS review", "/tars-review <MR url>", or wants a second reviewer on an MR.
argument-hint: <MR url> [more MR urls] [extra notes for TARS]
context: fork
agent: general-purpose
---

# TARS review

TARS is a Slack bot (user `U0BT5JA2E1Y`). The user DMs it at channel `D0BT99K5WSY`. TARS posts its findings as inline GitLab notes on the MR itself, so the job here is to kick it off and relay its verdict.

Input: `$ARGUMENTS`

1. **MR URLs.** Take them from the input. If none were given, find every open, non-draft MR of the user's in the `vidangel` group for the current task. Sibling MRs (backend + frontend) share the `TECH-####` ID but not always the branch name, so the ID is the match key. The exact branch name is the fallback:
   ```
   b=$(git branch --show-current) && [ -n "$b" ] && key=$(grep -oE 'TECH-[0-9]+' <<<"$b" || echo "$b") && \
   glab api --paginate "groups/vidangel/merge_requests?state=opened&scope=created_by_me&per_page=100" \
     | jq -r --arg k "$key" '.[] | select((.draft|not) and (.source_branch|contains($k))) | .web_url'
   ```
   The `[ -n "$b" ]` guard matters: with an empty branch, the filter matches every open MR. If there's no git repo or no match, stop and say so. Don't guess.
2. **Send.** Load the Slack tools via ToolSearch (`select:mcp__claude_ai_Slack__slack_send_message,mcp__claude_ai_Slack__slack_read_thread`). Send to `D0BT99K5WSY` in this shape, which TARS already handles:
   ```
   review these MRs
   • <label> !<iid>: <url>
   ```
   Label each MR by repo (Backend = vidangel-backend, Frontend = www.vidangel.com, otherwise the repo name). Append any extra notes from the input. Keep the returned `ts`; that's the thread.
3. **Wait.** Reviews take about 5–15 min. Loop: `sleep 90` in Bash, then `slack_read_thread` with `response_format: concise` and `oldest` set to the last ts you've seen, so only new replies come back. Ignore progress messages: those starting with `:books:`, `:book:`, `:computer:`, `:mag`, `:snake:`, `:clipboard:`, `:twisted_rightwards_arrows:` or `:hourglass`. TARS is done when a reply contains `Code-ready:` / `Ship-ready:`. After that, do one more read about 60s later, because TARS sometimes adds a follow-up. Give up after 25 min and return the thread permalink.
4. **Return** only:
   - the verdict per MR (Code-ready / Ship-ready plus blocking findings, verbatim)
   - the links to the GitLab notes TARS posted
   - the Slack thread permalink: `https://vidangel.slack.com/archives/D0BT99K5WSY/p<ts without the dot>`

   Drop the progress chatter.

Never edit or resolve TARS's GitLab notes. If TARS asks a question in the thread, return the question instead of answering it.
