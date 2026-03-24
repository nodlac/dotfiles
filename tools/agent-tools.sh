#!/usr/bin/env zsh

AGENT_FILE="$HOME/notes/work_notes/sprints/agents.csv"
AGENT_LOG="$HOME/notes/work_notes/sprints/agent-log.md"
CLICKUP_BASE="https://app.clickup.com/t/${CLICKUP_TEAM_ID:-14252037}"
EXCLUDED_SESSIONS="^(aa-|control-center|settings|notes)$"
REPO_DIR="$HOME/vidangel-repo"

# Ensure agents.csv exists with header
if [[ ! -f "$AGENT_FILE" ]]; then
    echo "Status,Task,ClickUp,Session,Notes,Started,Type" > "$AGENT_FILE"
elif ! head -1 "$AGENT_FILE" | grep -q "^Status,"; then
    echo "Status,Task,ClickUp,Session,Notes,Started,Type" | cat - "$AGENT_FILE" > /tmp/_agents_fix.csv && mv /tmp/_agents_fix.csv "$AGENT_FILE"
fi

# Sanitize a session name: spaces to dashes, lowercase, strip non-alphanumeric
_sanitize_session() {
    echo "$1" | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_-]/-/g' | sed 's/--*/-/g' | sed 's/-$//'
}

# Add a TECH task line to # Uncategorized Tasks in a sprint file
# Usage: _sprint_add_task <sprint_file> <tech_id> <marker> <title>
_sprint_add_task() {
    python3 -c "
import sys
sprint_file, tech_id, marker, title = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
team_id = '${CLICKUP_TEAM_ID:-14252037}'
link = f'https://app.clickup.com/t/{team_id}/{tech_id}'
task_line = f'    - {marker} {tech_id} {title} [link]({link})\n'

with open(sprint_file) as f:
    lines = f.readlines()

# Find # Uncategorized Tasks section
uncategorized_idx = None
for i, line in enumerate(lines):
    if line.strip() == '# Uncategorized Tasks':
        uncategorized_idx = i
        break

if uncategorized_idx is not None:
    lines.insert(uncategorized_idx + 1, task_line)
else:
    # Find end of frontmatter
    fence_count = 0
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.strip() == '---':
            fence_count += 1
            if fence_count == 2:
                insert_idx = i + 1
                break
    # Skip legend comment if present
    while insert_idx < len(lines) and lines[insert_idx].strip().startswith('<!--'):
        insert_idx += 1
    lines[insert_idx:insert_idx] = ['\n', '# Uncategorized Tasks\n', task_line, '\n']

with open(sprint_file, 'w') as f:
    f.writelines(lines)
print(f'  Added {tech_id} to {sprint_file}')
" "$1" "$2" "$3" "$4"
}

# Append a row to agents.csv using Python csv module for proper escaping
_agent_append_row() {
    python3 -c "
import csv, sys
row = sys.argv[1:]
path = '$AGENT_FILE'
with open(path, 'a', newline='') as f:
    csv.writer(f).writerow(row)
" "$@"
}

# Read a field from agents.csv by session name
# Usage: _agent_read_field <session> <field_index>
# Fields: 0=Status, 1=Task, 2=ClickUp, 3=Session, 4=Notes, 5=Started
_agent_has_session() {
    python3 -c "
import csv, sys
session = sys.argv[1]
with open('$AGENT_FILE') as f:
    for row in csv.reader(f):
        if len(row) > 3 and row[3] == session:
            sys.exit(0)
sys.exit(1)
" "$1"
}

# Update a field in agents.csv by session name
_agent_update_field() {
    local session="$1" field_idx="$2" new_val="$3"
    python3 -c "
import csv, sys
session, idx, val = sys.argv[1], int(sys.argv[2]), sys.argv[3]
rows = []
with open('$AGENT_FILE') as f:
    rows = list(csv.reader(f))
for row in rows:
    if len(row) > 3 and row[3] == session:
        row[idx] = val
with open('$AGENT_FILE', 'w', newline='') as f:
    csv.writer(f).writerows(rows)
" "$session" "$field_idx" "$new_val"
}

# --- agent-start ---
# Interactive: creates a tmux session, adds a row to agents.csv, launches claude code
# Usage: agent-start [-t repo|analytics]
agent-start() {
    local agent_type=""

    # Parse flags
    while [[ "$1" == -* ]]; do
        case "$1" in
            -t) agent_type="$2"; shift 2 ;;
            *) echo "Unknown flag: $1"; return 1 ;;
        esac
    done

    # Type selection if not provided
    if [[ -z "$agent_type" ]]; then
        printf "Type [r]epo  [a]nalytics  [g]eneral (default): "
        read -r agent_type
        agent_type="${agent_type:-general}"
    fi

    # Resolve single-letter shortcuts
    case "$agent_type" in
        r) agent_type="repo" ;;
        a) agent_type="analytics" ;;
        g) agent_type="general" ;;
    esac

    # Session name (short, first — it's what you'll see in tmux)
    printf "Session name (short, e.g. claude-usage-recap): "
    read -r session_slug
    if [[ -z "$session_slug" ]]; then
        echo "Session name is required."
        return 1
    fi
    session_slug=$(_sanitize_session "$session_slug")
    local session_name="zz-${session_slug}"

    # Task ID — loop until confirmed or skipped
    local _cu_name_for_desc=""
    while true; do
        printf "Task ID (number, TECH-XXXX, 'new' to create, enter to skip): "
        read -r task_id

        # Normalize bare number to TECH-XXXX
        if [[ "$task_id" =~ ^[0-9]+$ ]]; then
            task_id="TECH-${task_id}"
        fi

        # Skip or new — no verification needed
        if [[ -z "$task_id" || "$task_id" == "new" ]]; then
            break
        fi

        # Verify in ClickUp
        if [[ -n "$CLICKUP_TOKEN" ]]; then
            local cu_json=$(curl -s "https://api.clickup.com/api/v2/task/${task_id}?custom_task_ids=true&team_id=${CLICKUP_TEAM_ID}" \
                -H "Authorization: $CLICKUP_TOKEN" 2>/dev/null)
            local cu_name=$(echo "$cu_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('name',''))" 2>/dev/null)
            local cu_status=$(echo "$cu_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',{}).get('status',''))" 2>/dev/null)

            if [[ -z "$cu_name" || "$cu_name" == "None" ]]; then
                echo "  Could not find $task_id in ClickUp. Try again."
                continue
            fi

            printf "  Found: %s [%s]\n" "$cu_name" "$cu_status"
            printf "  Use this task? (y/n): "
            read -r confirm_task
            if [[ "$confirm_task" == "y" || "$confirm_task" == "Y" || "$confirm_task" == "" ]]; then
                _cu_name_for_desc="$cu_name"
                break
            fi
            # rejected — loop back
        else
            break
        fi
    done

    # Agent prompt (what the agent should work on)
    if [[ -n "$_cu_name_for_desc" ]]; then
        printf "Agent prompt [%s]: " "$_cu_name_for_desc"
    else
        printf "Agent prompt: "
    fi
    read -r description
    description="${description:-$_cu_name_for_desc}"
    if [[ -z "$description" ]]; then
        echo "Agent prompt is required."
        return 1
    fi

    # Create ClickUp task if requested
    if [[ "$task_id" == "new" ]]; then
        printf "Task title for ClickUp [${description:0:80}]: "
        read -r cu_title
        cu_title="${cu_title:-${description:0:80}}"

        # Find current sprint list ID from frontmatter
        local sprint_file=$(ls ~/notes/work_notes/sprints/sprint_*.md 2>/dev/null | sort -t_ -k2 -n | tail -1)
        local list_id=$(python3 -c "
import re
with open('$sprint_file') as f:
    content = f.read()
m = re.search(r'clickup_list_id:\s*\"?([^\"\\n]+)', content)
print(m.group(1) if m else '')
" 2>/dev/null)

        if [[ -z "$list_id" ]]; then
            echo "Could not find clickup_list_id in sprint file. Skipping task creation."
            task_id=""
        else
            local result=$(curl -s -X POST "https://api.clickup.com/api/v2/list/${list_id}/task" \
                -H "Authorization: $CLICKUP_TOKEN" \
                -H "Content-Type: application/json" \
                -d "{\"name\": \"${cu_title}\", \"assignees\": [${CLICKUP_USER_ID}], \"status\": \"in progress\"}" 2>/dev/null)

            task_id=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('custom_id',''))" 2>/dev/null)

            if [[ -n "$task_id" && "$task_id" != "None" ]]; then
                echo "Created $task_id: $cu_title"
                # Add to sprint file under Uncategorized Tasks
                [[ -n "$sprint_file" ]] && _sprint_add_task "$sprint_file" "$task_id" "[a]" "$cu_title"
            else
                echo "Failed to create task. Continuing without TECH ID."
                task_id=""
            fi
        fi
    fi

    # Notes file — default to current sprint
    local latest_sprint=$(ls ~/notes/work_notes/sprints/sprint_*.md 2>/dev/null | sort -t_ -k2 -n | tail -1)
    local latest_sprint_rel=$(basename "$latest_sprint")
    local notes_file="sprints/${latest_sprint_rel}"
    local work_dir=""

    case "$agent_type" in
        repo)
            # List available repos
            echo ""
            echo " Available repos:"
            local repos=()
            for d in "$REPO_DIR"/*/; do
                [[ -d "$d/.git" ]] || continue
                repos+=("$(basename "$d")")
            done
            local idx=1
            for r in "${repos[@]}"; do
                printf "  %2d) %s\n" "$idx" "$r"
                ((idx++))
            done
            echo ""
            printf "Pick repo (number or name): "
            read -r repo_pick

            # Resolve pick to repo name
            local repo_name=""
            if [[ "$repo_pick" =~ ^[0-9]+$ ]] && (( repo_pick >= 1 && repo_pick <= ${#repos} )); then
                repo_name="${repos[$repo_pick]}"
            else
                repo_name="$repo_pick"
            fi

            local repo_path="$REPO_DIR/$repo_name"
            if [[ ! -d "$repo_path/.git" ]]; then
                echo "Not a git repo: $repo_path"
                return 1
            fi

            # New branch or existing?
            printf "New branch or existing? [n]ew / [e]xisting (default: new): "
            read -r branch_mode
            branch_mode="${branch_mode:-n}"

            local worktree_path="${repo_path}-${session_slug}"

            if [[ "$branch_mode" == "e" || "$branch_mode" == "existing" ]]; then
                # List local + remote branches with fzf or numbered menu
                echo ""
                echo " Available branches:"
                local branches=()
                while IFS= read -r b; do
                    branches+=("$b")
                done < <(git -C "$repo_path" branch -a --format='%(refname:short)' \
                    | sed 's|^origin/||' \
                    | grep -v '^HEAD$' \
                    | sort -u)

                # Try fzf for fuzzy autocomplete, fall back to numbered list
                local branch_name=""
                if command -v fzf &>/dev/null; then
                    branch_name=$(printf '%s\n' "${branches[@]}" \
                        | fzf --prompt="Branch> " --height=40% --reverse)
                else
                    local idx=1
                    for b in "${branches[@]}"; do
                        printf "  %3d) %s\n" "$idx" "$b"
                        ((idx++))
                    done
                    echo ""
                    printf "Pick branch (number or name): "
                    read -r branch_pick
                    if [[ "$branch_pick" =~ ^[0-9]+$ ]] && (( branch_pick >= 1 && branch_pick <= ${#branches} )); then
                        branch_name="${branches[$branch_pick]}"
                    else
                        branch_name="$branch_pick"
                    fi
                fi

                if [[ -z "$branch_name" ]]; then
                    echo "No branch selected."
                    return 1
                fi

                echo "Fetching ${branch_name}..."
                git -C "$repo_path" fetch origin "$branch_name" 2>/dev/null

                git -C "$repo_path" worktree add "$worktree_path" "$branch_name" 2>/dev/null
                if [[ $? -ne 0 ]]; then
                    # Branch may only exist on remote — create tracking branch
                    git -C "$repo_path" worktree add "$worktree_path" -b "$branch_name" "origin/${branch_name}" 2>/dev/null
                fi
                if [[ $? -ne 0 ]]; then
                    echo "Failed to create worktree for branch '$branch_name'."
                    return 1
                fi

                work_dir="$worktree_path"
                echo "Created worktree: $worktree_path"
                echo "Branch: $branch_name"
            else
                # New branch flow
                local branch_prefix=""
                while true; do
                    printf "Branch type (feature/chore/bug): "
                    read -r branch_type
                    case "$branch_type" in
                        feature|chore|bug) branch_prefix="$branch_type"; break ;;
                        f) branch_prefix="feature"; break ;;
                        c) branch_prefix="chore"; break ;;
                        b) branch_prefix="bug"; break ;;
                        *) echo "  Enter feature, chore, or bug (or f/c/b)" ;;
                    esac
                done

                local branch_name="${branch_prefix}/${session_slug}"
                [[ -n "$task_id" ]] && branch_name="${branch_prefix}/${session_slug}/${task_id}"

                local default_branch=$(git -C "$repo_path" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')
                [[ -z "$default_branch" ]] && default_branch="main"

                echo "Fetching latest ${default_branch}..."
                git -C "$repo_path" fetch origin "$default_branch" 2>/dev/null

                git -C "$repo_path" worktree add "$worktree_path" -b "$branch_name" "origin/${default_branch}" 2>/dev/null
                if [[ $? -ne 0 ]]; then
                    echo "Failed to create worktree at $worktree_path"
                    echo "Branch '$branch_name' may already exist. Try a different description."
                    return 1
                fi

                work_dir="$worktree_path"
                echo "Created worktree: $worktree_path"
                echo "Branch: $branch_name"
            fi
            ;;

        analytics)
            work_dir="$HOME/Reporting"
            ;;

        *)
            # General: prompt for directory
            printf "Working directory [$(pwd)]: "
            read -r work_dir
            work_dir="${work_dir:-$(pwd)}"
            work_dir="${work_dir/#\~/$HOME}"
            ;;
    esac

    if [[ ! -d "$work_dir" ]]; then
        printf "Directory does not exist: $work_dir — create it? (y/n): "
        read -r create_it
        if [[ "$create_it" == "y" ]]; then
            mkdir -p "$work_dir"
            echo "Created: $work_dir"
        else
            return 1
        fi
    fi

    # Check if session already exists
    if tmux has-session -t "$session_name" 2>/dev/null; then
        echo "Session '$session_name' already exists."
        return 1
    fi

    # Clean up task_id
    [[ "$task_id" == "None" ]] && task_id=""

    # Build type label
    local type_label="$agent_type"
    [[ "$agent_type" == "repo" && -n "$repo_name" ]] && type_label="repo:${repo_name}"

    local today=$(date +%Y-%m-%d)

    # Append row to agents.csv
    _agent_append_row "active" "$description" "$task_id" "$session_name" "$notes_file" "$today" "$type_label"

    # Create tmux session in the working directory
    tmux new-session -d -s "$session_name" -c "$work_dir"

    # Build the initial message for claude
    local prompt="You are working on: ${description}"
    [[ -n "$task_id" ]] && prompt="${prompt}\nClickUp: ${CLICKUP_BASE}/${task_id}"
    [[ -n "$notes_file" ]] && prompt="${prompt}\nNotes: ~/notes/work_notes/${notes_file}"
    prompt="${prompt}\n\nWhen you finish or get blocked, update ~/notes/work_notes/sprints/agents.csv per the instructions in ~/.claude/CLAUDE.md"

    # Launch claude code in the session with initial message (interactive mode)
    tmux send-keys -t "$session_name" "claude \"${prompt}\"" Enter

    echo ""
    echo "Session '$session_name' created and tracked."
    [[ -n "$task_id" ]] && echo "ClickUp: ${CLICKUP_BASE}/${task_id}"
    echo "Dir: $work_dir"

    # Switch to the new session
    tmux switch-client -t "$session_name"
}

# --- agent-status ---
# Dashboard: merges agents.csv with live tmux state, opens in csvlens
agent-status() {
    local tmpfile="$HOME/notes/work_notes/sprints/agent-status-view.csv"

    python3 -c '
import csv, subprocess, re, sys, os

agent_file = sys.argv[1]
excluded = sys.argv[2]
tmpfile = sys.argv[3]

# Parse agents.csv
tracked = []
with open(agent_file) as f:
    reader = csv.DictReader(f)
    for row in reader:
        tracked.append(row)

tracked_names = {t["Session"] for t in tracked}

# Get live tmux sessions
live = set()
try:
    out = subprocess.check_output(["tmux", "ls"], stderr=subprocess.DEVNULL, text=True)
    for line in out.splitlines():
        sname = line.split(":")[0]
        if not re.match(excluded, sname):
            live.add(sname)
except Exception:
    pass

# Build display CSV
with open(tmpfile, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Source", "Status", "Task", "ClickUp", "Session", "Branch", "Started"])

    for t in tracked:
        status = t.get("Status", "")
        if status == "active" and t.get("Session", "") not in live:
            status = "STALE"
        w.writerow(["tracked", status, t.get("Task", ""), t.get("ClickUp", ""), t.get("Session", ""), "", t.get("Started", "")])

    for sname in sorted(live):
        if sname in tracked_names:
            continue
        branch = ""
        tech_id = ""
        try:
            pane_path = subprocess.check_output(
                ["tmux", "display-message", "-t", sname, "-p", "#{pane_current_path}"],
                stderr=subprocess.DEVNULL, text=True).strip()
            if pane_path and (os.path.isdir(pane_path + "/.git") or os.path.isfile(pane_path + "/.git")):
                branch = subprocess.check_output(
                    ["git", "-C", pane_path, "branch", "--show-current"],
                    stderr=subprocess.DEVNULL, text=True).strip()
                m = re.search(r"TECH-\d+", branch)
                if m:
                    tech_id = m.group(0)
        except Exception:
            pass
        if tech_id or sname.startswith("zz-"):
            w.writerow(["discovered", "", "", tech_id, sname, branch, ""])
' "$AGENT_FILE" "$EXCLUDED_SESSIONS" "$tmpfile"

    csvlens "$tmpfile"
}

# --- agent-checkin ---
# Loop through active agent sessions, switch to each one so you can interact
# Commands per session: [enter] next  [d] done  [b] blocked  [q] quit
agent-checkin() {
    local sessions=()
    local tasks=()
    local clickups=()

    while IFS=',' read -r status task clickup session rest; do
        [[ "$status" == "Status" ]] && continue  # skip header
        [[ "$status" != "active" ]] && continue
        session=$(echo "$session" | xargs)
        [[ -z "$session" ]] && continue
        # Only include sessions that are live
        tmux has-session -t "$session" 2>/dev/null || continue
        sessions+=("$session")
        tasks+=("$task")
        clickups+=("$clickup")
    done < "$AGENT_FILE"

    if [[ ${#sessions} -eq 0 ]]; then
        echo "No active sessions to check in on."
        return 0
    fi

    echo ""
    echo " Checking in on ${#sessions} active session(s)..."
    echo " Commands: [enter] next  [d] done  [b] blocked  [q] quit"
    echo ""

    local current_session=$(tmux display-message -p '#S' 2>/dev/null)

    for i in {1..${#sessions}}; do
        local sess="${sessions[$i]}"
        local task="${tasks[$i]}"
        local clickup="${clickups[$i]}"

        echo " ─────────────────────────────────────────"
        printf " %s" "$sess"
        [[ -n "$clickup" ]] && printf "  (%s)" "$clickup"
        printf "\n %s\n" "$task"
        echo ""
        printf " Switch to session? [enter=yes/s=skip/q=quit]: "
        read -r action

        case "$action" in
            q|Q) break ;;
            s|S) continue ;;
            *)
                # Switch to the session
                tmux switch-client -t "$sess" 2>/dev/null

                # Wait for user to come back and say what happened
                printf " Back? [enter] next  [d] done  [b] blocked: "
                read -r result

                case "$result" in
                    d|D) agent-done "$sess" ;;
                    b|B)
                        _agent_update_field "$sess" 0 "blocked"
                        echo " [$(date +%Y-%m-%d)] ${sess}: blocked" >> "$AGENT_LOG"
                        echo "Marked '$sess' as blocked."
                        ;;
                esac
                ;;
        esac
    done

    # Switch back to original session
    [[ -n "$current_session" ]] && tmux switch-client -t "$current_session" 2>/dev/null

    echo ""
    echo "Check-in complete."
}

# --- agent-done ---
# Mark a tracked agent as done, optionally kill the tmux session
agent-done() {
    local session_name="$1"

    if [[ -z "$session_name" ]]; then
        echo "Usage: agent-done <session-name>"
        return 1
    fi

    # Update status in agents.csv
    if _agent_has_session "$session_name"; then
        _agent_update_field "$session_name" 0 "done"
        echo "Marked '$session_name' as done"

        # Append to agent log
        echo "- [$(date +%Y-%m-%d)] ${session_name}: marked done" >> "$AGENT_LOG"
    else
        echo "Session '$session_name' not found in agents.csv"
        return 1
    fi

    # Check if session is in a worktree
    if tmux has-session -t "$session_name" 2>/dev/null; then
        local pane_path=$(tmux display-message -t "$session_name" -p '#{pane_current_path}' 2>/dev/null)
        local is_worktree=false
        local worktree_path=""
        if [[ -n "$pane_path" && -f "$pane_path/.git" ]]; then
            is_worktree=true
            worktree_path="$pane_path"
        fi

        printf "Kill tmux session '$session_name'? (y/n): "
        read -r kill_it
        if [[ "$kill_it" == "y" ]]; then
            tmux kill-session -t "$session_name"
            echo "Session killed."

            if $is_worktree && [[ -n "$worktree_path" ]]; then
                printf "Remove worktree at $(basename "$worktree_path")? (y/n): "
                read -r remove_wt
                if [[ "$remove_wt" == "y" ]]; then
                    local main_repo=$(cd "$worktree_path" && git rev-parse --git-common-dir 2>/dev/null | sed 's|/\.git$||')
                    if [[ -n "$main_repo" ]]; then
                        git -C "$main_repo" worktree remove "$worktree_path" 2>/dev/null
                        echo "Worktree removed."
                    else
                        echo "Could not determine main repo. Remove manually: git worktree remove $worktree_path"
                    fi
                fi
            fi
        fi
    fi
}

# --- agent-track ---
# Track an existing tmux session. Use -n <name> to rename it.
agent-track() {
    local rename_to=""

    # Parse flags
    while [[ "$1" == -* ]]; do
        case "$1" in
            -n) rename_to="$2"; shift 2 ;;
            *) echo "Unknown flag: $1"; return 1 ;;
        esac
    done

    local session_name="$1"

    if [[ -z "$session_name" ]]; then
        echo "Usage: agent-track [-n new-name] <session-name>"
        return 1
    fi

    # Verify session exists
    if ! tmux has-session -t "$session_name" 2>/dev/null; then
        echo "Session '$session_name' not found."
        return 1
    fi

    # Check if already tracked
    if _agent_has_session "$session_name"; then
        echo "Session '$session_name' is already tracked."
        return 1
    fi

    # Auto-detect TECH ID from git branch
    local pane_path=$(tmux display-message -t "$session_name" -p '#{pane_current_path}' 2>/dev/null)
    local auto_tech=""
    if [[ -n "$pane_path" && -d "$pane_path/.git" ]]; then
        local branch=$(git -C "$pane_path" branch --show-current 2>/dev/null)
        auto_tech=$(echo "$branch" | grep -oE 'TECH-[0-9]+')
    fi

    # Task ID
    local default_prompt=""
    [[ -n "$auto_tech" ]] && default_prompt=" [$auto_tech]"
    printf "Task ID${default_prompt}: "
    read -r task_id
    task_id="${task_id:-$auto_tech}"
    [[ "$task_id" == "None" ]] && task_id=""

    # Description
    printf "Description: "
    read -r description
    if [[ -z "$description" ]]; then
        echo "Description is required."
        return 1
    fi

    # Notes file — default to latest sprint
    local latest_sprint=$(ls ~/notes/work_notes/sprints/sprint_*.md 2>/dev/null | sort -t_ -k2 -n | tail -1)
    local notes_file=""
    [[ -n "$latest_sprint" ]] && notes_file="sprints/$(basename "$latest_sprint")"

    # Rename session if -n was provided
    local tracked_name="$session_name"
    if [[ -n "$rename_to" ]]; then
        rename_to=$(_sanitize_session "$rename_to")
        tmux rename-session -t "$session_name" "$rename_to"
        tracked_name="$rename_to"
        echo "Renamed session to '$rename_to'"
    fi

    local today=$(date +%Y-%m-%d)
    _agent_append_row "active" "$description" "$task_id" "$tracked_name" "$notes_file" "$today" ""

    echo "Now tracking '$tracked_name'"
    [[ -n "$task_id" ]] && echo "ClickUp: ${CLICKUP_BASE}/${task_id}"
}

# --- agent-triage ---
# Walk through all discovered (untracked) sessions and track, skip, or quit
agent-triage() {
    # Build list of tracked session names
    local tracked_sessions=()
    tracked_sessions=($(python3 -c "
import csv
with open('$AGENT_FILE') as f:
    for row in csv.DictReader(f):
        print(row.get('Session', ''))
"))

    # Collect discovered sessions
    local discovered=()
    local disc_tech=()
    local disc_branch=()

    while IFS= read -r line; do
        local sname=$(echo "$line" | cut -d: -f1)
        echo "$sname" | grep -qE "$EXCLUDED_SESSIONS" && continue

        # Skip if already tracked
        local is_tracked=false
        for ts in "${tracked_sessions[@]}"; do
            [[ "$ts" == "$sname" ]] && is_tracked=true && break
        done
        $is_tracked && continue

        # Get branch info
        local pane_path=$(tmux display-message -t "$sname" -p '#{pane_current_path}' 2>/dev/null)
        local branch="" tech_id=""
        if [[ -n "$pane_path" && -d "$pane_path/.git" ]]; then
            branch=$(git -C "$pane_path" branch --show-current 2>/dev/null)
            tech_id=$(echo "$branch" | grep -oE 'TECH-[0-9]+')
        fi

        # Only show sessions with TECH IDs or zz- prefix
        if [[ -n "$tech_id" || "$sname" == zz-* ]]; then
            discovered+=("$sname")
            disc_tech+=("$tech_id")
            disc_branch+=("$branch")
        fi
    done < <(tmux ls 2>/dev/null)

    # Resolve latest sprint file once for all sessions
    local sprint_file=$(ls ~/notes/work_notes/sprints/sprint_*.md 2>/dev/null | sort -t_ -k2 -n | tail -1)
    local sprint_rel=""
    [[ -n "$sprint_file" ]] && sprint_rel="sprints/$(basename "$sprint_file")"

    if [[ ${#discovered} -eq 0 ]]; then
        echo "No untracked sessions to triage."
        return 0
    fi

    echo ""
    echo " Triaging ${#discovered} untracked session(s)..."
    echo " Commands: [enter] track  [s] skip  [q] quit"
    echo ""

    local i
    for i in {1..${#discovered}}; do
        local sname="${discovered[$i]}"
        local tech_id="${disc_tech[$i]}"
        local branch="${disc_branch[$i]}"

        echo " ─────────────────────────────────────────"
        printf " %s" "$sname"
        [[ -n "$tech_id" ]] && printf "  (%s)" "$tech_id"
        [[ -n "$branch" ]] && printf "  branch: %s" "$branch"

        # If we have a TECH ID, look it up in ClickUp (stored for confirm step)
        local cu_name="" cu_status=""
        if [[ -n "$tech_id" && -n "$CLICKUP_TOKEN" ]]; then
            local cu_json=$(curl -s "https://api.clickup.com/api/v2/task/${tech_id}?custom_task_ids=true&team_id=${CLICKUP_TEAM_ID}" \
                -H "Authorization: $CLICKUP_TOKEN" 2>/dev/null)
            cu_name=$(echo "$cu_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('name',''))" 2>/dev/null)
            cu_status=$(echo "$cu_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',{}).get('status',''))" 2>/dev/null)
        fi

        # Try to match session name to a task line in the sprint file
        # Only when no TECH ID detected — TECH ID match is more reliable
        local sprint_task_match=""
        if [[ -z "$tech_id" && -n "$sprint_file" ]]; then
            local search_name="${sname#zz-}"
            sprint_task_match=$(python3 -c "
import re, sys
name = sys.argv[1]
words = [w.lower() for w in name.split('-') if len(w) >= 3]
if not words:
    sys.exit(0)
best_line, best_score = '', 0
with open(sys.argv[2]) as f:
    for line in f:
        if not re.match(r'\s*-\s*\[.\]', line):
            continue
        lower = line.lower()
        score = sum(1 for w in words if w in lower)
        if score > best_score:
            best_score = score
            best_line = line
if best_score > 0:
    print(re.sub(r'^\s*-\s*\[.\]\s*', '', best_line).strip())
" "$search_name" "$sprint_file" 2>/dev/null)
        fi

        echo ""
        printf " [enter/s/q]: "
        read -r action

        case "$action" in
            q|Q) echo "Done."; return 0 ;;
            s|S) continue ;;
            *)
                # Task ID with auto-detect; confirm match first
                local task_id=""
                if [[ -n "$tech_id" ]]; then
                    echo ""
                    [[ -n "$cu_name" ]] && printf "   ClickUp:      %s [%s]\n" "$cu_name" "$cu_status"
                    [[ -n "$sprint_task_match" ]] && printf "   Sprint match: %s\n" "$sprint_task_match"
                    printf "   Task ID: $tech_id — correct? (y/n/new): "
                    read -r confirm_id
                    case "$confirm_id" in
                        y|Y|"") task_id="$tech_id" ;;
                        new) task_id="new"; cu_name=""; sprint_task_match="" ;;
                        *)
                            cu_name=""; sprint_task_match=""
                            printf "   Task ID (enter to skip, 'new' to create): "
                            read -r task_id
                            ;;
                    esac
                else
                    printf "   Task ID (enter to skip, 'new' to create): "
                    read -r task_id
                fi

                # If a TECH ID was manually entered, look it up in sprint file
                if [[ -n "$task_id" && "$task_id" != "new" && -z "$cu_name" && -n "$sprint_file" ]]; then
                    local manual_match=$(grep -i "$task_id" "$sprint_file" 2>/dev/null | head -1)
                    if [[ -n "$manual_match" ]]; then
                        sprint_task_match=$(echo "$manual_match" | sed 's/^\s*-\s*\[.\]\s*//' | sed 's/\s*\[link\]([^)]*)//g' | sed "s/$task_id//" | xargs)
                        printf "   Found in sprint: %s\n" "$sprint_task_match"
                    fi
                fi

                # Description — pre-fill from ClickUp name, sprint match, or nothing
                local desc_default=""
                if [[ -n "$cu_name" ]]; then
                    desc_default="$cu_name"
                elif [[ -n "$sprint_task_match" ]]; then
                    desc_default="$sprint_task_match"
                fi
                if [[ -n "$desc_default" ]]; then
                    printf "   Task [$desc_default] ('x' to clear): "
                else
                    printf "   Task: "
                fi
                read -r description
                if [[ "$description" == "x" ]]; then
                    description=""
                    printf "   Task: "
                    read -r description
                else
                    description="${description:-$desc_default}"
                fi
                if [[ -z "$description" ]]; then
                    echo "   Skipped (task description required)."
                    continue
                fi

                # Create ClickUp task if requested
                if [[ "$task_id" == "new" ]]; then
                    printf "   Task title for ClickUp [${description:0:80}]: "
                    read -r cu_title
                    cu_title="${cu_title:-${description:0:80}}"

                    local list_id=$(python3 -c "
import re
with open('$sprint_file') as f:
    content = f.read()
m = re.search(r'clickup_list_id:\s*\"?([^\"\\\\n]+)', content)
print(m.group(1) if m else '')
" 2>/dev/null)

                    if [[ -z "$list_id" ]]; then
                        echo "   Could not find clickup_list_id in sprint file. Skipping task creation."
                        task_id=""
                    else
                        local result=$(curl -s -X POST "https://api.clickup.com/api/v2/list/${list_id}/task" \
                            -H "Authorization: $CLICKUP_TOKEN" \
                            -H "Content-Type: application/json" \
                            -d "{\"name\": \"${cu_title}\", \"assignees\": [${CLICKUP_USER_ID}], \"status\": \"in progress\"}" 2>/dev/null)

                        task_id=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('custom_id',''))" 2>/dev/null)

                        if [[ -n "$task_id" && "$task_id" != "None" ]]; then
                            echo "   Created $task_id: $cu_title"
                            # Add to sprint file under Uncategorized Tasks
                            [[ -n "$sprint_file" ]] && _sprint_add_task "$sprint_file" "$task_id" "[a]" "$cu_title"
                        else
                            echo "   Failed to create task. Continuing without TECH ID."
                            task_id=""
                        fi
                    fi
                fi

                # Clean up task_id
                [[ "$task_id" == "None" ]] && task_id=""

                # Rename?
                printf "   Rename session? (enter to keep, or new name): "
                read -r new_name

                local tracked_name="$sname"
                if [[ -n "$new_name" ]]; then
                    new_name=$(_sanitize_session "$new_name")
                    tmux rename-session -t "$sname" "$new_name"
                    tracked_name="$new_name"
                    echo "   Renamed to '$new_name'"
                fi

                # Save to agents.csv
                local today=$(date +%Y-%m-%d)
                _agent_append_row "active" "$description" "$task_id" "$tracked_name" "$sprint_rel" "$today" ""

                echo "   Tracked '$tracked_name'"
                [[ -z "$task_id" ]] && echo "   (use 'agent-link ${tracked_name}' to add a TECH ID later)"
                ;;
        esac
    done

    echo ""
    echo "Triage complete."
}

# --- agent-link ---
# Attach a ClickUp TECH ID to a tracked session, or create a new task
# Usage: agent-link <session-name> [TECH-1234|new]
agent-link() {
    local session_name="$1"
    local task_id="$2"

    if [[ -z "$session_name" ]]; then
        echo "Usage: agent-link <session-name> [TECH-ID|new]"
        return 1
    fi

    # Verify session is tracked
    if ! _agent_has_session "$session_name"; then
        echo "Session '$session_name' not found in agents.csv"
        return 1
    fi

    # Already has a TECH ID?
    local existing=$(python3 -c "
import csv
with open('$AGENT_FILE') as f:
    for row in csv.DictReader(f):
        if row.get('Session') == '$session_name' and row.get('ClickUp'):
            print(row['ClickUp'])
")
    if [[ -n "$existing" ]]; then
        echo "Session already linked to $existing"
        printf "Replace? (y/n): "
        read -r replace_it
        [[ "$replace_it" != "y" ]] && return 0
    fi

    # Prompt for task ID if not provided
    if [[ -z "$task_id" ]]; then
        printf "Task ID (TECH-1234 or 'new'): "
        read -r task_id
    fi

    if [[ -z "$task_id" ]]; then
        echo "No task ID provided."
        return 1
    fi

    # Create ClickUp task if requested
    if [[ "$task_id" == "new" ]]; then
        local row_desc=$(python3 -c "
import csv
with open('$AGENT_FILE') as f:
    for row in csv.DictReader(f):
        if row.get('Session') == '$session_name':
            print(row.get('Task', ''))
")

        printf "Task title for ClickUp [${row_desc:0:80}]: "
        read -r cu_title
        cu_title="${cu_title:-${row_desc:0:80}}"

        local sprint_file=$(ls ~/notes/work_notes/sprints/sprint_*.md 2>/dev/null | sort -t_ -k2 -n | tail -1)
        local list_id=$(python3 -c "
import re
with open('$sprint_file') as f:
    content = f.read()
m = re.search(r'clickup_list_id:\s*\"?([^\"\\\\n]+)', content)
print(m.group(1) if m else '')
" 2>/dev/null)

        if [[ -z "$list_id" ]]; then
            echo "Could not find clickup_list_id in sprint file."
            return 1
        fi

        local result=$(curl -s -X POST "https://api.clickup.com/api/v2/list/${list_id}/task" \
            -H "Authorization: $CLICKUP_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"name\": \"${cu_title}\", \"assignees\": [${CLICKUP_USER_ID}], \"status\": \"in progress\"}" 2>/dev/null)

        task_id=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('custom_id',''))" 2>/dev/null)

        if [[ -n "$task_id" && "$task_id" != "None" ]]; then
            echo "Created $task_id: $cu_title"
            local sprint_file=$(ls ~/notes/work_notes/sprints/sprint_*.md 2>/dev/null | sort -t_ -k2 -n | tail -1)
            [[ -n "$sprint_file" ]] && _sprint_add_task "$sprint_file" "$task_id" "[a]" "$cu_title"
        else
            echo "Failed to create task."
            return 1
        fi
    fi

    # Normalize: accept both TECH-1234 and bare TECH-1234
    [[ "$task_id" == "None" ]] && { echo "No task ID returned."; return 1; }

    # Update ClickUp column (index 2)
    _agent_update_field "$session_name" 2 "$task_id"

    echo "Linked '$session_name' -> $task_id"
}

# --- agent-dashboard ---
# Interactive terminal dashboard: list agents, preview pane output, quick actions
agent-dashboard() {
    python3 ~/work_scripts/agent-dashboard.py "$@"
}

# --- sprint-sync ---
# Two-way sync between sprint markdown and ClickUp
# Usage: sprint-sync [--dry-run] [sprint_num]
sprint-sync() {
    python3 ~/work_scripts/sprint-sync.py "$@"
}

# --- sprint-rollover ---
# Pull uncompleted tasks from previous sprint to current
# Usage: sprint-rollover [--dry-run] [from_num] [to_num]
sprint-rollover() {
    python3 ~/work_scripts/sprint-sync.py rollover "$@"
}

# --- sprint-new ---
# Create a new sprint file linked to ClickUp, rollover + sync
sprint-new() {
    python3 ~/work_scripts/sprint-sync.py new "$@"
}

# --- Zsh completions ---
# Complete session names for agent commands
_agent_tracked_sessions() {
    local sessions=()
    sessions=($(python3 -c "
import csv
with open('$AGENT_FILE') as f:
    for row in csv.DictReader(f):
        s = row.get('Session', '')
        if s:
            print(s)
" 2>/dev/null))
    _describe 'session' sessions && return 0
}

_agent_live_sessions() {
    local sessions=()
    while IFS= read -r line; do
        local sname=$(echo "$line" | cut -d: -f1)
        echo "$sname" | grep -qE "$EXCLUDED_SESSIONS" && continue
        sessions+=("$sname")
    done < <(tmux ls 2>/dev/null)
    _describe 'session' sessions && return 0
}

# Complete agent types for agent-start / agent-new
_agent_types() {
    local -a types=(repo analytics general)
    compadd -a types
}

# agent-new: alias for agent-start
agent-new() { agent-start "$@"; }

if (( $+functions[compdef] )); then
    compdef _agent_tracked_sessions agent-done
    compdef _agent_tracked_sessions agent-link
    compdef _agent_live_sessions agent-track
    compdef '_arguments "-t:type:_agent_types"' agent-start agent-new
fi
