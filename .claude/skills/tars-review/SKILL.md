---
name: tars-review
description: Send one or more GitLab MRs to TARS (VidAngel's review agent) for code review, wait for its verdict, return it. Use when the user says "tars review", "have TARS review", "/tars-review <MR url>", or wants a second reviewer on an MR.
argument-hint: <MR url> [more MR urls] [extra notes for TARS]
context: fork
agent: general-purpose
---

# TARS review

TARS is VidAngel's review bot, GitLab user `tars-vidangel-agent`. It posts its findings as inline GitLab notes on the MR. The job here is to start a review and relay the result. Everything goes through `glab`, not Slack: TARS ignores automated Slack posts.

Input: `$ARGUMENTS`

1. **MR URLs.** Take them from the input. If none were given, find every open, non-draft MR of the user's in the `vidangel` group for the current task. Sibling MRs (backend + frontend) share the `TECH-####` ID but not always the branch name, so the ID is the match key. The exact branch name is the fallback:
   ```
   b=$(git branch --show-current) && [ -n "$b" ] && key=$(grep -oE 'TECH-[0-9]+' <<<"$b" || echo "$b") && \
   glab api --paginate "groups/vidangel/merge_requests?state=opened&scope=created_by_me&per_page=100" \
     | jq -r --arg k "$key" '.[] | select((.draft|not) and (.source_branch|contains($k))) | .web_url'
   ```
   The `[ -n "$b" ]` guard matters: with an empty branch, the filter matches every open MR. If there's no git repo or no match, stop and say so. Don't guess.
2. **Trigger.** For each MR, remove then re-add the request: a fresh request is what fires a review, and it also re-fires if TARS was already a reviewer:
   ```
   glab mr update <iid> -R vidangel/<repo> --reviewer -tars-vidangel-agent
   glab mr update <iid> -R vidangel/<repo> --reviewer +tars-vidangel-agent
   ```
   Record the trigger time (`date -u +%Y-%m-%dT%H:%M:%SZ`). Extra notes from the input can't be sent this way, so return them to the user to pass on themselves.
3. **Wait.** Reviews take about 5–15 min. Loop: `sleep 90` in Bash, then for each MR:
   ```
   glab api "projects/<url-encoded path>/merge_requests/<iid>/reviewers" | jq -c '.[]|select(.user.username=="tars-vidangel-agent")|.state'
   glab api "projects/<url-encoded path>/merge_requests/<iid>/notes?sort=desc&per_page=50" \
     | jq --arg t "<trigger time>" '[.[]|select(.author.username=="tars-vidangel-agent" and .created_at>$t)]'
   ```
   An MR is done when TARS's reviewer state leaves `unreviewed`, or when TARS posts a note with `Code-ready:` / `Ship-ready:`. Do one more check about 60s later, because TARS sometimes adds a follow-up. Give up after 25 min and return whatever TARS posted, plus a note that the review never finished.
4. **Prove each finding necessary or not.** Be skeptical: assume a finding is unnecessary until you prove otherwise. Check out the MR's source branch (or read the files at its head SHA) and trace the code: callers, upstream guards, types, tests, framework behavior. Ask two things: does the problem actually happen, and is the fix worth making in this MR (real impact, not style or a hypothetical)? Prove it concretely where you can: a failing input, a test run, a code path that leads to the bad state. Give each finding a verdict:
   - **NECESSARY**: it happens and matters (give the proof: `path:line` trace, input → wrong output, or test output).
   - **UNSURE**: you couldn't prove it either way (say what's missing).
   - **NOT NECESSARY**: already handled, wrong premise, unreachable, or impact too small to justify the change (say why, with `path:line`).
5. **Return** only:
   - the result per MR: TARS's reviewer state, plus any verdict note, verbatim
   - every finding, verbatim, with a link to the GitLab note TARS posted, followed by your verdict and its proof. NECESSARY first, then UNSURE, then NOT NECESSARY.

Never edit or resolve TARS's GitLab notes. If TARS asks a question in a note, return the question instead of answering it.
