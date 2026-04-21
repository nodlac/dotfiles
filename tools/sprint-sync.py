#!/usr/bin/env python3
"""
sprint-sync: two-way sync between local sprint markdown files and ClickUp.

Pull: fetches tasks assigned to you from the ClickUp sprint list,
      adds new ones to # Uncategorized Tasks in your sprint file.
Push: reads task markers in your sprint file and updates ClickUp status.
Create: lines with NEW get created in ClickUp and replaced with the real ID.
"""

import os
import re
import sys
import glob
import json
import urllib.request
import urllib.error
from datetime import date

# --- Config ---
TOKEN = os.environ.get("CLICKUP_TOKEN")
USER_ID = os.environ.get("CLICKUP_USER_ID")
TEAM_ID = os.environ.get("CLICKUP_TEAM_ID", "14252037")
SPRINT_FOLDER_ID = "90115890584"
SPRINT_DIR = os.path.expanduser("~/notes/work_notes/sprints")
CLICKUP_BASE = f"https://app.clickup.com/t/{TEAM_ID}"
DRY_RUN = "--dry-run" in sys.argv

# Marker <-> ClickUp status mapping
MARKER_TO_STATUS = {
    "[ ]": "to do",
    "[/]": "in progress",
    "[>]": "qa",
    "[T]": "qa",           # testing required — maps to qa in ClickUp
    "[x]": "done",
    "[c]": "Closed",  # closed in ClickUp and moves to Done section locally
    "[a]": "in progress",  # agent running counts as in progress in ClickUp
    "[d]": "__delete__",   # delete from ClickUp and remove line
}

STATUS_TO_MARKER = {
    "to do": "[ ]",
    "in progress": "[/]",
    "qa": "[>]",
    "done": "[x]",
    "testing": "[T]",
}

# Patterns
TECH_PATTERN = re.compile(r"TECH-(\d+)")
# Matches task lines:
#   - [x] TECH-1234 title [link](url)
#   - [x] [TECH-1234](url) title        (legacy prepended link)
#   - [x] TECH-1234 title               (plain, no link)
TASK_LINE_PATTERN = re.compile(
    r"^(\s*-\s*)\[(.)\]\s+"  # prefix + marker
    r"(?:\[TECH-(\d+)\]\([^)]*\)|TECH-(\d+))"  # linked or plain TECH ID
    r"\s*(.*?)(?:\s*\[link\]\([^)]*\))?(?:\s*\d{4}-\d{2}-\d{2})?\s*$"  # title, stripping trailing [link](url) and date
)
# For NEW creation (immediate) and NEW_XX (deferred until sprint >= XX)
NEW_TASK_PATTERN = re.compile(
    r"^(\s*-\s*)\[(.)\]\s+NEW(?:_(\d+))?\s+(.*)"
)
# For tasks created but awaiting custom_id assignment
PENDING_TASK_PATTERN = re.compile(
    r"^(\s*-\s*)\[(.)\]\s+PENDING:(\w+)\s+(.*)"
)
# Matches child lines explicitly marked NEW (candidate subtasks to create)
CHILD_TASK_PATTERN = re.compile(
    r"^(\s{8,}-\s*)\[(.)\]\s+NEW\s+(.*)"
)


def api(method, path, body=None):
    """Make a ClickUp API request."""
    url = f"https://api.clickup.com/api/v2{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", TOKEN)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        print(f"  API error {e.code}: {e.read().decode()}")
        return None


def find_current_sprint_file():
    """Find the sprint file with the highest number."""
    files = glob.glob(os.path.join(SPRINT_DIR, "sprint_*.md"))
    if not files:
        print("No sprint files found.")
        sys.exit(1)

    def sprint_num(f):
        m = re.search(r"sprint_(\d+)", f)
        return int(m.group(1)) if m else 0

    return max(files, key=sprint_num)


def get_sprint_number(filepath):
    """Extract sprint number from filename."""
    m = re.search(r"sprint_(\d+)", filepath)
    return int(m.group(1)) if m else None


def read_frontmatter(filepath):
    """Read YAML frontmatter from a markdown file."""
    with open(filepath, "r") as f:
        content = f.read()

    m = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return {}

    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            val = val.strip().strip('"').strip("'")
            fm[key.strip()] = val
    return fm


def get_clickup_list_id(filepath):
    """Get ClickUp list ID from frontmatter, or fall back to name matching."""
    fm = read_frontmatter(filepath)
    list_id = fm.get("clickup_list_id")
    if list_id:
        return list_id

    # Fallback: match by sprint number
    sprint_num = get_sprint_number(filepath)
    data = api("GET", f"/folder/{SPRINT_FOLDER_ID}/list")
    if not data:
        return None

    for lst in data.get("lists", []):
        m_name = re.match(r"Sprint\s+(\d+)", lst["name"])
        if m_name and int(m_name.group(1)) == sprint_num:
            return lst["id"]

    return None


def find_clickup_sprint_list(sprint_num):
    """Find the ClickUp list ID and name for a given sprint number."""
    data = api("GET", f"/folder/{SPRINT_FOLDER_ID}/list")
    if not data:
        return None, None

    for lst in data.get("lists", []):
        m = re.match(r"Sprint\s+(\d+)", lst["name"])
        if m and int(m.group(1)) == sprint_num:
            return lst["id"], lst["name"]

    return None, None


def get_sprint_file(sprint_num=None):
    """Get sprint file path. If sprint_num given, use that; otherwise highest."""
    if sprint_num:
        path = os.path.join(SPRINT_DIR, f"sprint_{sprint_num}.md")
        if os.path.exists(path):
            return path
        print(f"Sprint file not found: sprint_{sprint_num}.md")
        sys.exit(1)
    return find_current_sprint_file()


def get_task_by_tech_num(tech_num):
    """Look up a single task by its TECH-XXXX custom ID. Returns task dict or None."""
    data = api("GET", f"/task/TECH-{tech_num}?custom_task_ids=true&team_id={TEAM_ID}")
    if data and data.get("id"):
        return data
    return None


def get_clickup_tasks(list_id):
    """Fetch tasks (and subtasks) assigned to user from a ClickUp list.

    Includes tasks whose home list is the sprint AND tasks that have the
    sprint in their 'locations' (secondary list assignments).
    Subtasks are returned as flat items with a 'parent' field.
    """
    seen_ids = set()
    tasks = []

    # 1. Get tasks whose home list is the sprint (including subtasks)
    page = 0
    while True:
        data = api(
            "GET",
            f"/list/{list_id}/task"
            f"?assignees[]={USER_ID}"
            f"&include_closed=true"
            f"&subtasks=true"
            f"&page={page}",
        )
        if not data or not data.get("tasks"):
            break
        for t in data["tasks"]:
            if t["id"] not in seen_ids:
                seen_ids.add(t["id"])
                tasks.append(t)
        if len(data["tasks"]) < 100:
            break
        page += 1

    # 2. Get all tasks assigned to user, filter by sprint in locations
    page = 0
    while True:
        data = api(
            "GET",
            f"/team/{TEAM_ID}/task"
            f"?assignees[]={USER_ID}"
            f"&include_closed=true"
            f"&subtasks=true"
            f"&page={page}",
        )
        if not data or not data.get("tasks"):
            break
        for t in data["tasks"]:
            if t["id"] in seen_ids:
                continue
            locations = t.get("locations", [])
            if any(loc.get("id") == list_id for loc in locations):
                seen_ids.add(t["id"])
                tasks.append(t)
        if len(data["tasks"]) < 100:
            break
        page += 1

    return tasks


def parse_sprint_file(filepath):
    """Parse sprint file and return dict of TECH ID -> (line_num, marker, title)."""
    with open(filepath, "r") as f:
        lines = f.readlines()
    return parse_sprint_file_lines(lines)


def parse_sprint_file_lines(lines):
    """Parse in-memory lines and return dict of TECH ID -> (line_num, marker, title, indent)."""
    tasks = {}
    for i, line in enumerate(lines):
        m = TASK_LINE_PATTERN.match(line)
        if m:
            tech_id = m.group(3) or m.group(4)
            marker = f"[{m.group(2)}]"
            title = m.group(5).strip()
            indent = len(line) - len(line.lstrip())
            tasks[tech_id] = {"line": i, "marker": marker, "title": title, "indent": indent}
    return tasks, lines


def format_task_line(tech_id, marker, title, indent="    "):
    """Format a task line with TECH ID, appended link, and date added."""
    today = date.today().isoformat()
    return f"{indent}- {marker} TECH-{tech_id} {title} [link]({CLICKUP_BASE}/TECH-{tech_id}) {today}\n"


def format_pending_line(internal_id, marker, title, indent="    "):
    """Format a task line for a created task still awaiting its custom ID."""
    return f"{indent}- {marker} PENDING:{internal_id} {title}\n"


def format_subtask_line(tech_id, marker, title, indent="        "):
    """Format a subtask line (deeper indent, TECH ID, no link needed)."""
    return f"{indent}- {marker} TECH-{tech_id} {title}\n"


def _find_uncategorized_insert(lines):
    """Return the line index to insert into # Uncategorized Tasks.
    Creates the section if missing. Returns (lines, insert_idx)."""
    for i, line in enumerate(lines):
        if line.strip() == "# Uncategorized Tasks":
            return lines, i

    # Section missing — create it after frontmatter / legend
    insert_idx = 0
    fence_count = 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            fence_count += 1
            if fence_count == 2:
                insert_idx = i + 1
                break
    for i in range(insert_idx, len(lines)):
        if lines[i].startswith("# Legend"):
            insert_idx = i + 1
            while insert_idx < len(lines) and lines[insert_idx].strip().startswith("<!--"):
                insert_idx += 1
            break

    lines[insert_idx:insert_idx] = ["\n", "# Uncategorized Tasks\n"]
    return lines, insert_idx + 2  # after the new header


def _subtask_insert_idx(lines, parent_line_idx):
    """Return the index to insert a subtask after the parent and any existing subtasks."""
    parent_indent = len(lines[parent_line_idx]) - len(lines[parent_line_idx].lstrip())
    insert_after = parent_line_idx
    j = parent_line_idx + 1
    while j < len(lines):
        line = lines[j]
        if line.strip() == "":
            j += 1
            continue
        if len(line) - len(line.lstrip()) > parent_indent:
            insert_after = j
            j += 1
        else:
            break
    return insert_after + 1


def _update_task_title(lines, line_idx, new_title):
    """Update the title portion of a task line, preserving indent, marker, TECH ID, link, and date."""
    line = lines[line_idx]
    m = TASK_LINE_PATTERN.match(line)
    if not m:
        return lines
    prefix = m.group(1)       # indent + "- "
    marker_char = m.group(2)  # single char inside []
    tech_num = m.group(3) or m.group(4)

    # Preserve trailing date if present
    date_match = re.search(r'\s+(\d{4}-\d{2}-\d{2})\s*$', line)
    date_str = f" {date_match.group(1)}" if date_match else ""

    lines[line_idx] = (
        f"{prefix}[{marker_char}] TECH-{tech_num} {new_title} "
        f"[link]({CLICKUP_BASE}/TECH-{tech_num}){date_str}\n"
    )
    return lines


def _update_task_marker(lines, line_idx, new_marker):
    """Replace the [X] marker of a task line, preserving everything else."""
    line = lines[line_idx]
    m = TASK_LINE_PATTERN.match(line)
    if not m:
        return lines
    # new_marker is like "[x]"; strip the brackets, keep just the char
    mchar = new_marker.strip("[]")
    lines[line_idx] = re.sub(r'\[.\]', f'[{mchar}]', line, count=1)
    return lines


def _get_task_indent(lines, line_idx):
    """Return the indentation of a task line (number of leading spaces)."""
    return len(lines[line_idx]) - len(lines[line_idx].lstrip())


def _remove_task_block(lines, line_idx):
    """Remove a task line and all its deeper-indented children. Returns (removed_lines, remaining_lines)."""
    task_indent = _get_task_indent(lines, line_idx)
    block = [lines[line_idx]]
    j = line_idx + 1
    while j < len(lines):
        if lines[j].strip() == "":
            j += 1
            continue
        if (len(lines[j]) - len(lines[j].lstrip())) > task_indent:
            block.append(lines[j])
            j += 1
        else:
            break
    # Remove block from lines
    remaining = lines[:line_idx] + lines[j:]
    return block, remaining


def sync_pull(filepath, clickup_tasks, local_tasks, lines):
    """Pull new tasks and subtasks from ClickUp into the sprint file.

    Also updates task names and re-nests/un-nests tasks when parent changes.
    """

    # Build internal_id -> tech_num map for parent resolution
    id_to_tech = {}
    for task in clickup_tasks:
        cid = task.get("custom_id")
        if cid:
            id_to_tech[task["id"]] = cid.replace("TECH-", "")

    new_top = []       # (tech_num, marker, title) — top-level or orphan subtasks
    # subtask insertions: (parent_line_idx, formatted_line, label)
    subtask_insertions = []
    updated = 0
    renested = 0

    for task in clickup_tasks:
        cid = task.get("custom_id")
        if not cid:
            continue
        tech_num = cid.replace("TECH-", "")
        cu_status = task["status"]["status"]
        cu_title = task["name"]
        parent_id = task.get("parent")

        if tech_num in local_tasks:
            local = local_tasks[tech_num]

            # --- Update title if changed or missing (bare TECH-XXXX) ---
            if cu_title and (not local["title"] or cu_title != local["title"]):
                if DRY_RUN:
                    print(f"  [dry-run] TECH-{tech_num}: rename '{local['title']}' -> '{cu_title}'")
                else:
                    lines = _update_task_title(lines, local["line"], cu_title)
                    print(f"  TECH-{tech_num}: renamed -> {cu_title}")
                updated += 1

            # --- Check nesting changes ---
            local_indent = _get_task_indent(lines, local["line"])
            cu_parent_tech = id_to_tech.get(parent_id) if parent_id else None

            if cu_parent_tech and cu_parent_tech in local_tasks:
                # Should be nested under parent
                parent_indent = _get_task_indent(lines, local_tasks[cu_parent_tech]["line"])
                expected_indent = parent_indent + 4
                if local_indent != expected_indent:
                    if DRY_RUN:
                        print(f"  [dry-run] TECH-{tech_num}: would re-nest under TECH-{cu_parent_tech}")
                    else:
                        # Remove task block from current position
                        block, lines = _remove_task_block(lines, local["line"])
                        # Re-parse to get updated line numbers
                        local_tasks, lines = parse_sprint_file_lines(lines)
                        if cu_parent_tech in local_tasks:
                            parent_line = local_tasks[cu_parent_tech]["line"]
                            insert_idx = _subtask_insert_idx(lines, parent_line)
                            # Re-indent block
                            old_indent = len(block[0]) - len(block[0].lstrip())
                            indent_diff = expected_indent - old_indent
                            for bi, bline in enumerate(block):
                                if bline.strip():
                                    cur = len(bline) - len(bline.lstrip())
                                    new_indent = max(0, cur + indent_diff)
                                    block[bi] = " " * new_indent + bline.lstrip()
                            for bi, bline in enumerate(block):
                                lines.insert(insert_idx + bi, bline)
                            print(f"  TECH-{tech_num}: re-nested under TECH-{cu_parent_tech}")
                            # Re-parse again after insertion
                            local_tasks, lines = parse_sprint_file_lines(lines)
                    renested += 1
            elif not parent_id and local_indent > 4:
                # Was nested, now top-level in ClickUp — un-nest
                if DRY_RUN:
                    print(f"  [dry-run] TECH-{tech_num}: would un-nest to top level")
                else:
                    block, lines = _remove_task_block(lines, local["line"])
                    # Re-indent to top level (4 spaces)
                    old_indent = len(block[0]) - len(block[0].lstrip())
                    indent_diff = 4 - old_indent
                    for bi, bline in enumerate(block):
                        if bline.strip():
                            cur = len(bline) - len(bline.lstrip())
                            new_indent = max(0, cur + indent_diff)
                            block[bi] = " " * new_indent + bline.lstrip()
                    # Insert into Uncategorized
                    lines, insert_idx = _find_uncategorized_insert(lines)
                    for bi, bline in enumerate(block):
                        lines.insert(insert_idx + bi, bline)
                    print(f"  TECH-{tech_num}: un-nested to top level")
                    local_tasks, lines = parse_sprint_file_lines(lines)
                renested += 1

            continue

        # New task — skip done
        if cu_status == "done":
            continue

        cu_marker = STATUS_TO_MARKER.get(cu_status, "[ ]")

        if parent_id:
            parent_tech = id_to_tech.get(parent_id)
            if parent_tech and parent_tech in local_tasks:
                parent_line = local_tasks[parent_tech]["line"]
                subtask_line = format_task_line(tech_num, cu_marker, cu_title, "        ")
                subtask_insertions.append((parent_line, subtask_line, tech_num, cu_title))
                continue
        # No parent, or parent not in local file — goes to Uncategorized
        new_top.append((tech_num, cu_marker, cu_title))

    pulled = 0

    # Apply subtask insertions from bottom to top to preserve line indices
    subtask_insertions.sort(key=lambda x: x[0], reverse=True)
    for parent_line_idx, subtask_line, tech_num, title in subtask_insertions:
        idx = _subtask_insert_idx(lines, parent_line_idx)
        lines.insert(idx, subtask_line)
        print(f"    [ ] TECH-{tech_num} {title}  (subtask)")
        pulled += 1

    # Insert top-level tasks into # Uncategorized Tasks
    if new_top:
        lines, insert_idx = _find_uncategorized_insert(lines)
        for tech_num, marker, title in new_top:
            lines.insert(insert_idx, format_task_line(tech_num, marker, title))
            insert_idx += 1
            print(f"    {marker} TECH-{tech_num} {title}")
            pulled += 1

    # ── Off-list drift: fetch tasks not in the sprint's list and
    # reconcile title + (conservative) status. This covers tasks that
    # were rolled over in markdown but never attached to the sprint
    # list in ClickUp.
    cu_ids = {
        (task.get("custom_id") or "").replace("TECH-", "")
        for task in clickup_tasks if task.get("custom_id")
    }
    off_list = [tn for tn in local_tasks if tn not in cu_ids]
    off_list_updates = 0
    for tech_num in off_list:
        remote = get_task_by_tech_num(tech_num)
        if not remote:
            continue
        local = local_tasks[tech_num]
        cu_title = remote.get("name") or ""
        cu_status = remote.get("status", {}).get("status", "")

        # Title drift
        if cu_title and cu_title != local["title"]:
            if DRY_RUN:
                print(f"  [dry-run] TECH-{tech_num}: rename '{local['title']}' -> '{cu_title}' (off-list)")
            else:
                lines = _update_task_title(lines, local["line"], cu_title)
                print(f"  TECH-{tech_num}: renamed (off-list) -> {cu_title}")
            off_list_updates += 1

        # Status drift — only adopt ClickUp terminal states when local
        # is still open, to avoid clobbering in-flight local changes
        # that PUSH hasn't flushed yet.
        if cu_status in ("done", "Closed") and local["marker"] in ("[ ]", "[/]"):
            new_marker = "[x]" if cu_status == "done" else "[c]"
            if DRY_RUN:
                print(f"  [dry-run] TECH-{tech_num}: local {local['marker']} -> {new_marker} (closed in ClickUp)")
            else:
                lines = _update_task_marker(lines, local["line"], new_marker)
                print(f"  TECH-{tech_num}: adopted ClickUp status {cu_status} -> {new_marker}")
            off_list_updates += 1

    if pulled:
        print(f"  Pulled {pulled} tasks/subtasks.")
    if updated:
        print(f"  Updated {updated} task name(s).")
    if renested:
        print(f"  Re-nested {renested} task(s).")
    if off_list_updates:
        print(f"  Off-list drift: {off_list_updates} update(s).")
    if not pulled and not updated and not renested and not off_list_updates:
        print("  No changes to pull.")

    return lines


def sync_push(local_tasks, clickup_tasks):
    """Push local status changes to ClickUp.
    Returns (done_tech_ids, deleted_tech_nums).
    """
    cu_lookup = {}
    for task in clickup_tasks:
        custom_id = task.get("custom_id")
        if custom_id:
            cu_lookup[custom_id.replace("TECH-", "")] = task

    pushed = 0
    done_tech_ids = []
    deleted_tech_nums = []

    for tech_num, local in local_tasks.items():
        local_marker = local["marker"]
        target_status = MARKER_TO_STATUS.get(local_marker)
        if not target_status:
            continue

        if target_status == "__delete__":
            if DRY_RUN:
                print(f"  [dry-run] TECH-{tech_num}: would delete from ClickUp")
                pushed += 1
            else:
                if tech_num not in cu_lookup:
                    fetched = get_task_by_tech_num(tech_num)
                    if fetched:
                        cu_lookup[tech_num] = fetched
                if tech_num in cu_lookup:
                    result = api("DELETE", f"/task/{cu_lookup[tech_num]['id']}")
                    if result is not None:
                        print(f"  TECH-{tech_num}: deleted from ClickUp")
                        deleted_tech_nums.append(tech_num)
                        pushed += 1
                    else:
                        print(f"  TECH-{tech_num}: delete failed")
                else:
                    # Not in ClickUp at all — just remove from file
                    deleted_tech_nums.append(tech_num)
            continue

        if tech_num not in cu_lookup:
            fetched = get_task_by_tech_num(tech_num)
            if not fetched:
                if target_status in ("done", "Closed"):
                    # Task removed from ClickUp but marked done/closed locally — just count it
                    print(f"  TECH-{tech_num}: not in ClickUp, treating as done")
                    done_tech_ids.append(f"TECH-{tech_num}")
                else:
                    print(f"  SKIP TECH-{tech_num}: not found in ClickUp")
                continue
            cu_lookup[tech_num] = fetched

        cu_task = cu_lookup[tech_num]
        cu_status = cu_task["status"]["status"]

        if target_status == cu_status:
            continue

        if DRY_RUN:
            print(f"  [dry-run] TECH-{tech_num}: {cu_status} -> {target_status}")
            pushed += 1
        else:
            result = api("PUT", f"/task/{cu_task['id']}", {"status": target_status})
            if result:
                print(f"  TECH-{tech_num}: {cu_status} -> {target_status}")
                pushed += 1
                if target_status in ("done", "Closed"):
                    done_tech_ids.append(f"TECH-{tech_num}")

    if pushed == 0:
        print("  No status changes to push.")
    else:
        print(f"  Pushed {pushed} status updates.")

    return done_tech_ids, deleted_tech_nums


def _derive_local_parents(local_tasks):
    """Derive parent relationships from indentation in local sprint file.

    Returns dict of tech_num -> parent_tech_num (or None for top-level tasks).
    A task's parent is the nearest preceding task with strictly lower indent.
    """
    # Sort tasks by line number to walk in file order
    sorted_tasks = sorted(local_tasks.items(), key=lambda x: x[1]["line"])
    parents = {}
    # Stack of (tech_num, indent) — ancestors in current nesting
    stack = []

    for tech_num, info in sorted_tasks:
        indent = info["indent"]
        # Pop stack until we find a task with strictly less indent
        while stack and stack[-1][1] >= indent:
            stack.pop()
        parents[tech_num] = stack[-1][0] if stack else None
        stack.append((tech_num, indent))

    return parents


def sync_push_parents(local_tasks, clickup_tasks):
    """Push local nesting changes to ClickUp.

    Compares parent relationships derived from local indentation against
    ClickUp's parent field. Updates ClickUp when they differ.
    """
    # Build lookups
    cu_lookup = {}
    id_to_tech = {}
    tech_to_id = {}
    for task in clickup_tasks:
        custom_id = task.get("custom_id")
        if custom_id:
            tech_num = custom_id.replace("TECH-", "")
            cu_lookup[tech_num] = task
            id_to_tech[task["id"]] = tech_num
            tech_to_id[tech_num] = task["id"]

    local_parents = _derive_local_parents(local_tasks)
    pushed = 0

    for tech_num, local_parent_tech in local_parents.items():
        # Skip tasks marked for deletion
        local_marker = local_tasks[tech_num]["marker"]
        if MARKER_TO_STATUS.get(local_marker) == "__delete__":
            continue

        # Need ClickUp task to compare
        if tech_num not in cu_lookup:
            continue

        cu_task = cu_lookup[tech_num]
        cu_parent_id = cu_task.get("parent")
        cu_parent_tech = id_to_tech.get(cu_parent_id) if cu_parent_id else None

        if local_parent_tech == cu_parent_tech:
            continue

        # Local parent must exist in ClickUp to set it
        if local_parent_tech and local_parent_tech not in tech_to_id:
            print(f"  SKIP TECH-{tech_num}: local parent TECH-{local_parent_tech} not in ClickUp")
            continue

        new_parent_id = tech_to_id[local_parent_tech] if local_parent_tech else None
        direction = (
            f"nest under TECH-{local_parent_tech}" if local_parent_tech
            else "un-nest to top level"
        )

        if DRY_RUN:
            print(f"  [dry-run] TECH-{tech_num}: would {direction}")
            pushed += 1
        else:
            result = api("PUT", f"/task/{cu_task['id']}", {"parent": new_parent_id})
            if result:
                print(f"  TECH-{tech_num}: {direction}")
                pushed += 1
            else:
                print(f"  TECH-{tech_num}: failed to {direction}")

    if pushed == 0:
        print("  No parent changes to push.")
    else:
        print(f"  Pushed {pushed} parent update(s).")


def check_agent_closeout(done_tech_ids):
    """For any done tasks, check if there are active agents and prompt to close."""
    if not done_tech_ids:
        return

    agent_file = os.path.expanduser("~/notes/work_notes/sprints/agents.csv")
    if not os.path.exists(agent_file):
        return

    import csv, subprocess
    matches = []
    with open(agent_file) as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        if row.get("Status") == "active" and row.get("ClickUp") in done_tech_ids:
            matches.append(row)

    if not matches:
        return

    print("\nAGENT CLOSEOUT:")
    for row in matches:
        sess = row["Session"]
        tech = row["ClickUp"]
        task = row["Task"]
        print(f"  {tech} is done — agent session '{sess}' ({task})")
        ans = input(f"  Close session '{sess}'? (y/n): ").strip().lower()
        if ans != "y":
            continue

        # Mark done in CSV
        updated = []
        with open(agent_file) as f:
            for r in csv.DictReader(f):
                if r["Session"] == sess:
                    r["Status"] = "done"
                updated.append(r)
        with open(agent_file, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["Status", "Task", "ClickUp", "Session", "Notes", "Started"])
            w.writeheader()
            w.writerows(updated)

        # Kill tmux session if alive
        result = subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True)
        if result.returncode == 0:
            kill = input(f"  Kill tmux session '{sess}'? (y/n): ").strip().lower()
            if kill == "y":
                subprocess.run(["tmux", "kill-session", "-t", sess])
                print(f"  Killed '{sess}'.")

        # Append to agent log
        log_file = os.path.expanduser("~/notes/work_notes/sprints/agent-log.md")
        today = __import__("datetime").date.today().isoformat()
        with open(log_file, "a") as f:
            f.write(f"- [{today}] {sess}: closed — {tech} marked done\n")

        print(f"  Marked '{sess}' done.")


def sync_create(filepath, lines, clickup_tasks=None):
    """Create tasks in ClickUp for NEW lines. NEW_XX deferred until sprint >= XX."""
    current_sprint = get_sprint_number(filepath)
    list_id = get_clickup_list_id(filepath)

    if not list_id:
        print("  Could not find ClickUp sprint list for creation.")
        return lines

    # Build title -> custom_id lookup from existing ClickUp tasks for dedup
    existing_by_title = {}
    for t in (clickup_tasks or []):
        cid = t.get("custom_id")
        if cid:
            existing_by_title[t["name"].strip()] = cid

    created = 0
    for i, line in enumerate(lines):
        m = NEW_TASK_PATTERN.match(line)
        if not m:
            continue

        indent = m.group(1)
        marker = f"[{m.group(2)}]"
        gate_sprint = m.group(3)  # None for NEW, "30" for NEW_30
        title = m.group(4).strip()

        if not title:
            continue

        # Deferred: NEW_30 waits until current sprint >= 30
        if gate_sprint is not None:
            gate_num = int(gate_sprint)
            if current_sprint is None or current_sprint < gate_num:
                continue  # not yet — leave line as-is

        target_status = MARKER_TO_STATUS.get(marker, "to do")
        indent_clean = indent.rstrip("- ") or "    "

        if DRY_RUN:
            print(f"  [dry-run] Would create: {title} (status: {target_status})")
            created += 1
            continue

        # Dedup: if a task with this title already exists in ClickUp, reuse it
        if title in existing_by_title:
            existing_id = existing_by_title[title]
            tech_num = existing_id.replace("TECH-", "")
            lines[i] = format_task_line(tech_num, marker, title, indent_clean)
            print(f"  Reused existing TECH-{tech_num}: {title}")
            created += 1
            continue

        result = api("POST", f"/list/{list_id}/task", {
            "name": title,
            "assignees": [int(USER_ID)],
            "status": target_status,
        })

        if result and result.get("id"):
            task_id = result["id"]
            custom_id = result.get("custom_id", "")

            if not custom_id:
                # Retry once — custom_id assignment can lag
                fetched = api("GET", f"/task/{task_id}")
                custom_id = fetched.get("custom_id", "") if fetched else ""

            if custom_id:
                tech_num = custom_id.replace("TECH-", "")
                lines[i] = format_task_line(tech_num, marker, title, indent_clean)
                print(f"  Created TECH-{tech_num}: {title}")
                created += 1
            else:
                lines[i] = format_pending_line(task_id, marker, title, indent_clean)
                print(f"  WARNING: created task but no custom ID yet: {title}")
                print(f"           Saved as PENDING:{task_id} — will resolve on next sync.")
                created += 1

    if created == 0:
        print("  No NEW tasks to create.")

    return lines


def sync_resolve_pending(lines):
    """Resolve PENDING:<id> lines by fetching the internal task and checking for custom_id."""
    resolved = 0
    for i, line in enumerate(lines):
        m = PENDING_TASK_PATTERN.match(line)
        if not m:
            continue
        indent  = m.group(1)
        marker  = f"[{m.group(2)}]"
        task_id = m.group(3)
        title   = m.group(4).strip()
        indent_clean = indent.rstrip("- ") or "    "

        if DRY_RUN:
            print(f"  [dry-run] Would resolve PENDING:{task_id}: {title}")
            continue

        fetched    = api("GET", f"/task/{task_id}")
        custom_id  = fetched.get("custom_id", "") if fetched else ""
        if custom_id:
            tech_num  = custom_id.replace("TECH-", "")
            lines[i]  = format_task_line(tech_num, marker, title, indent_clean)
            print(f"  Resolved PENDING:{task_id} → TECH-{tech_num}: {title}")
            resolved += 1
        else:
            print(f"  Still pending: {title} ({task_id}) — custom ID not assigned yet")

    if resolved == 0:
        print("  No pending tasks to resolve.")
    return lines


def get_line_indent(line):
    """Return the indentation level of a line (number of leading spaces)."""
    return len(line) - len(line.lstrip())


DONE_MARKER = re.compile(r"^\s*-\s*\[[xc]\]")
TASK_MARKER = re.compile(r"^\s*-\s*\[.\]")
SECTION_HEADER = re.compile(r"^(#{1,6})\s+(.+)")
SKIP_SECTIONS = {"Done", "Uncategorized Tasks"}


def sync_create_subtasks(lines, clickup_tasks):
    """Create ClickUp subtasks for child lines that have markers but no TECH ID."""
    # Build custom_id -> task object lookup (need both internal id and list id)
    tech_to_task = {}
    for t in clickup_tasks:
        cid = t.get("custom_id", "")
        if cid:
            tech_to_task[cid.replace("TECH-", "")] = t

    created = 0
    current_parent = None   # full task object
    current_parent_indent = -1

    for i, line in enumerate(lines):
        # Track current parent task
        pm = TASK_LINE_PATTERN.match(line)
        if pm:
            tech_num = pm.group(3) or pm.group(4)
            current_parent = tech_to_task.get(tech_num)
            current_parent_indent = get_line_indent(line)
            continue

        # Check for child candidate
        cm = CHILD_TASK_PATTERN.match(line)
        if not cm:
            # Non-task line — if it's not indented deeper than parent, reset parent
            if line.strip() and get_line_indent(line) <= current_parent_indent:
                current_parent = None
            continue

        if not current_parent:
            continue

        indent = cm.group(1)
        marker = f"[{cm.group(2)}]"
        title  = cm.group(3).strip()
        target_status = MARKER_TO_STATUS.get(marker, "to do")
        indent_clean = indent.rstrip("- ") or "        "

        parent_internal_id = current_parent["id"]
        list_id = current_parent.get("list", {}).get("id")
        if not list_id:
            print(f"  Cannot create subtask (no list id for parent): {title}")
            continue

        if DRY_RUN:
            print(f"  [dry-run] Would create subtask under {parent_internal_id}: {title}")
            created += 1
            continue

        result = api("POST", f"/list/{list_id}/task", {
            "name": title,
            "assignees": [int(USER_ID)],
            "status": target_status,
            "parent": parent_internal_id,
        })

        if result and result.get("id"):
            task_id   = result["id"]
            custom_id = result.get("custom_id", "")
            if not custom_id:
                fetched   = api("GET", f"/task/{task_id}")
                custom_id = fetched.get("custom_id", "") if fetched else ""

            if custom_id:
                tech_num   = custom_id.replace("TECH-", "")
                lines[i]   = format_subtask_line(tech_num, marker, title, indent_clean)
                print(f"  Created subtask TECH-{tech_num}: {title}")
            else:
                lines[i] = f"{indent_clean}- {marker} PENDING:{task_id} {title}\n"
                print(f"  Created subtask (pending ID): {title}")
            created += 1
        else:
            print(f"  Failed to create subtask: {title}")

    if created == 0:
        print("  No subtasks to create.")
    return lines


def move_done_to_done_section(lines):
    """Move [x] task lines (and their children) to a # Done section at the bottom.
    Lines already inside an existing # Done section are left in place.
    """
    done_groups  = []  # list of line-lists to move
    kept         = []
    skip_indent  = -1
    current_group = []
    in_done_section = False

    for line in lines:
        # Track whether we're inside the existing Done section — don't touch those lines
        hm = SECTION_HEADER.match(line)
        if hm:
            if hm.group(2).strip() == "Done" and len(hm.group(1)) == 1:
                in_done_section = True
            elif len(hm.group(1)) <= 1:
                in_done_section = False

        if in_done_section:
            kept.append(line)
            continue
        # If collecting a done group's children
        if skip_indent >= 0:
            line_indent = get_line_indent(line)
            if line.strip() == "" or line_indent > skip_indent:
                current_group.append(line)
                continue
            else:
                # Done group ended
                # Trim trailing blank lines from group
                while current_group and current_group[-1].strip() == "":
                    current_group.pop()
                done_groups.append(current_group)
                current_group = []
                skip_indent = -1

        if DONE_MARKER.match(line):
            skip_indent = get_line_indent(line)
            current_group = [line]
        else:
            kept.append(line)

    # Flush last group
    if current_group:
        while current_group and current_group[-1].strip() == "":
            current_group.pop()
        done_groups.append(current_group)

    if not done_groups:
        return lines

    # Find existing # Done section in kept lines
    done_section_idx = None
    for i, line in enumerate(kept):
        if re.match(r"^#\s+Done\s*$", line):
            done_section_idx = i
            break

    if done_section_idx is None:
        # Append Done section at end
        while kept and kept[-1].strip() == "":
            kept.pop()
        kept.append("\n")
        kept.append("# Done\n")
        done_section_idx = len(kept) - 1

    # Find insert point: after the # Done header, before next same-level header
    insert_idx = done_section_idx + 1
    while insert_idx < len(kept):
        hm = SECTION_HEADER.match(kept[insert_idx])
        if hm and len(hm.group(1)) <= 1:
            break
        insert_idx += 1

    # Insert done groups at insert_idx (in reverse to preserve order)
    flat = []
    for group in done_groups:
        flat.extend(group)

    kept[insert_idx:insert_idx] = flat

    moved = len(done_groups)
    print(f"  Moved {moved} done task(s) to # Done section.")
    return kept


def filter_completed(lines):
    """Remove completed tasks and their sub-items from lines.

    Preserves section structure. Strips:
    - [x] lines and all deeper-indented sub-items beneath them
    - Entire # Done and # Uncategorized Tasks sections
    - Frontmatter (handled separately)
    - Empty sections (headers with no remaining content)
    """
    filtered = []
    skip_indent = -1       # indent level of a [x] task we're skipping under
    skip_section = False   # True when inside a section to skip entirely
    skip_section_level = 0 # heading level of skipped section

    for line in lines:
        # Check for section headers
        hm = SECTION_HEADER.match(line)
        if hm:
            level = len(hm.group(1))
            title = hm.group(2).strip()

            # If we were skipping a section, check if this header ends it
            if skip_section:
                if level <= skip_section_level:
                    skip_section = False
                else:
                    continue  # sub-header within skipped section

            # Check if this new section should be skipped
            if title in SKIP_SECTIONS:
                skip_section = True
                skip_section_level = level
                skip_indent = -1
                continue

            skip_indent = -1
            filtered.append(line)
            continue

        # If inside a skipped section, skip everything
        if skip_section:
            continue

        # Check if this is a completed task
        if DONE_MARKER.match(line):
            skip_indent = get_line_indent(line)
            continue

        # If we're skipping sub-items of a completed task
        if skip_indent >= 0:
            line_indent = get_line_indent(line)
            # Blank lines don't break the skip — but non-indented content does
            if line.strip() == "":
                # Keep blank lines tentatively (might be between sub-items)
                continue
            if line_indent > skip_indent:
                continue  # sub-item of completed task
            else:
                skip_indent = -1  # back to normal

        filtered.append(line)

    return filtered


def strip_frontmatter(lines):
    """Remove YAML frontmatter, return (frontmatter_lines, body_lines)."""
    if not lines or lines[0].strip() != "---":
        return [], lines

    fence_count = 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            fence_count += 1
            if fence_count == 2:
                return lines[:i + 1], lines[i + 1:]

    return [], lines


def remove_empty_sections(lines):
    """Remove section headers that have no content beneath them."""
    result = []
    i = 0
    while i < len(lines):
        hm = SECTION_HEADER.match(lines[i])
        if hm:
            level = len(hm.group(1))
            # Look ahead: is there any non-blank, non-header content before
            # the next same-or-higher-level header?
            has_content = False
            j = i + 1
            while j < len(lines):
                next_hm = SECTION_HEADER.match(lines[j])
                if next_hm and len(next_hm.group(1)) <= level:
                    break
                if lines[j].strip():
                    # Non-blank, non-header line — or a sub-header
                    if next_hm:
                        # It's a sub-header; check if IT has content
                        pass
                    else:
                        has_content = True
                        break
                j += 1

            if not has_content:
                # Skip this empty header and any blank lines after it
                i += 1
                while i < len(lines) and lines[i].strip() == "":
                    i += 1
                continue

        result.append(lines[i])
        i += 1

    return result


def sprint_rollover(from_num=None, to_num=None):
    """Roll over uncompleted work from one sprint to another.

    - Copies entire sprint structure, stripping [x] tasks + sub-items
    - Skips # Done and # Uncategorized Tasks sections
    - Removes empty sections
    - Moves uncompleted TECH tasks to the new sprint list in ClickUp
    """
    files = glob.glob(os.path.join(SPRINT_DIR, "sprint_*.md"))

    def sprint_num_from_file(f):
        m_f = re.search(r"sprint_(\d+)", f)
        return int(m_f.group(1)) if m_f else 0

    nums = sorted(set(sprint_num_from_file(f) for f in files))

    if from_num is None:
        if len(nums) < 2:
            print("Need at least two sprint files for rollover.")
            sys.exit(1)
        from_num = nums[-2]
    if to_num is None:
        to_num = nums[-1]

    from_path = os.path.join(SPRINT_DIR, f"sprint_{from_num}.md")
    to_path = os.path.join(SPRINT_DIR, f"sprint_{to_num}.md")

    if not os.path.exists(from_path):
        print(f"Source file not found: sprint_{from_num}.md")
        sys.exit(1)
    if not os.path.exists(to_path):
        print(f"Target file not found: sprint_{to_num}.md")
        sys.exit(1)

    print(f"Rolling over: sprint_{from_num}.md -> sprint_{to_num}.md")

    # Read source file
    with open(from_path, "r") as f:
        from_lines = f.readlines()

    # Separate frontmatter from body
    _, body = strip_frontmatter(from_lines)

    # Filter out completed tasks and skipped sections
    filtered = filter_completed(body)

    # Remove empty sections
    filtered = remove_empty_sections(filtered)

    # Strip leading/trailing blank lines
    while filtered and filtered[0].strip() == "":
        filtered.pop(0)
    while filtered and filtered[-1].strip() == "":
        filtered.pop()

    if not any(line.strip() for line in filtered):
        print("  No uncompleted content to roll over.")
        return

    # Read target file and find where to append
    with open(to_path, "r") as f:
        to_lines = f.readlines()

    to_fm, to_body = strip_frontmatter(to_lines)

    # Append rolled-over content after frontmatter and any existing content
    # If target already has body content, append after it
    # If target is fresh (from sprint-new), append after frontmatter
    result = to_fm + ["\n"] + filtered + ["\n"] + ["\n", "# Done\n"]

    if DRY_RUN:
        print("  [dry-run] Would write rolled-over content to target.")
        # Show summary
        sections = [l.strip() for l in filtered if SECTION_HEADER.match(l)]
        print(f"  Sections: {', '.join(sections)}")
        task_count = sum(1 for l in filtered if TASK_MARKER.match(l))
        done_in_source = sum(1 for l in body if DONE_MARKER.match(l))
        print(f"  Tasks carried over: {task_count} (stripped {done_in_source} completed)")
    else:
        with open(to_path, "w") as f:
            f.writelines(result)
        task_count = sum(1 for l in filtered if TASK_MARKER.match(l))
        done_in_source = sum(1 for l in body if DONE_MARKER.match(l))
        print(f"  Carried over {task_count} tasks (stripped {done_in_source} completed)")
        sections = [l.strip() for l in filtered if SECTION_HEADER.match(l)]
        for s in sections:
            print(f"    {s}")

    # Move uncompleted tasks from old ClickUp sprint to new one
    from_list_id = get_clickup_list_id(from_path)
    to_list_id = get_clickup_list_id(to_path)
    if from_list_id and to_list_id:
        print("\nClickUp sprint migration:")
        # Fetch all non-done tasks assigned to user from old sprint
        old_tasks = get_clickup_tasks(from_list_id)
        moved = 0
        for cu_task in old_tasks:
            if cu_task["status"]["status"] == "done":
                continue
            task_id = cu_task["id"]
            custom_id = cu_task.get("custom_id", "unknown")
            name = cu_task["name"]

            if DRY_RUN:
                print(f"  [dry-run] Would add {custom_id} to new sprint: {name}")
                moved += 1
            else:
                res = api("POST", f"/list/{to_list_id}/task/{task_id}")
                if res:
                    print(f"  Added {custom_id} to new sprint: {name}")
                    moved += 1

        if moved:
            print(f"  Migrated {moved} tasks to new sprint in ClickUp.")
        else:
            print("  No tasks to migrate in ClickUp.")


def sprint_new():
    """Create a new sprint file linked to a ClickUp sprint list.

    1. Lists available sprint lists from ClickUp
    2. Lets user pick one
    3. Creates sprint file with clickup_list_id in frontmatter
    4. Runs rollover from previous sprint
    5. Runs sync to pull in ClickUp tasks
    """
    # Push any pending status changes from current sprint first
    existing_files = glob.glob(os.path.join(SPRINT_DIR, "sprint_*.md"))
    if existing_files:
        def _snum(f):
            m_f = re.search(r"sprint_(\d+)", f)
            return int(m_f.group(1)) if m_f else 0
        current_file = max(existing_files, key=_snum)
        current_list_id = get_clickup_list_id(current_file)
        if current_list_id:
            print(f"Pushing status changes from {os.path.basename(current_file)}...")
            current_tasks_cu = get_clickup_tasks(current_list_id)
            current_tasks_local, _ = parse_sprint_file(current_file)
            sync_push(current_tasks_local, current_tasks_cu)
            print()

    data = api("GET", f"/folder/{SPRINT_FOLDER_ID}/list")
    if not data:
        print("Error: Could not fetch sprint lists.")
        sys.exit(1)

    lists = data.get("lists", [])
    # Sort by sprint number
    sprint_lists = []
    for lst in lists:
        m_name = re.match(r"Sprint\s+(\d+)", lst["name"])
        if m_name:
            sprint_lists.append((int(m_name.group(1)), lst["id"], lst["name"]))
    sprint_lists.sort()

    # Show available lists
    existing_files = glob.glob(os.path.join(SPRINT_DIR, "sprint_*.md"))
    existing_nums = set()
    for f in existing_files:
        m_file = re.search(r"sprint_(\d+)", f)
        if m_file:
            existing_nums.add(int(m_file.group(1)))

    print("Available ClickUp sprint lists:")
    for num, lid, name in sprint_lists:
        linked = " (already has file)" if num in existing_nums else ""
        print(f"  {num}: {name}{linked}")

    print()
    choice = input("Sprint number to create: ").strip()
    if not choice.isdigit():
        print("Invalid sprint number.")
        sys.exit(1)

    sprint_num = int(choice)
    target_path = os.path.join(SPRINT_DIR, f"sprint_{sprint_num}.md")

    if os.path.exists(target_path):
        print(f"sprint_{sprint_num}.md already exists.")
        sys.exit(1)

    # Find the ClickUp list
    list_id = None
    for num, lid, name in sprint_lists:
        if num == sprint_num:
            list_id = lid
            break

    if not list_id:
        print(f"No ClickUp list found for Sprint {sprint_num}.")
        sys.exit(1)

    # Create the file with frontmatter
    content = f"""---
id: sprint_{sprint_num}
aliases: []
tags:
  - sprints
clickup_list_id: "{list_id}"
---
<!-- [ ] todo  [/] in progress  [a] agent  [~] blocked/waiting  [>] qa  [!] urgent  [x] done  [d] delete
NEW create  NEW_XX deferred until sprint >= XX  PENDING:<id> awaiting custom ID -->

# Uncategorized Tasks

# Prioritized by Core Responsibilities

# Done
"""
    with open(target_path, "w") as f:
        f.write(content)

    print(f"Created sprint_{sprint_num}.md (list: {list_id})")

    # Rollover from previous sprint
    prev_nums = sorted(n for n in existing_nums if n < sprint_num)
    if prev_nums:
        print()
        sprint_rollover(prev_nums[-1], sprint_num)

    # Sync to pull in ClickUp tasks
    print()
    print("Running sync...")
    main(sprint_num)


def main(target_sprint_num=None):
    if not TOKEN:
        print("Error: CLICKUP_TOKEN not set. Add it to ~/.env")
        sys.exit(1)
    if not USER_ID:
        print("Error: CLICKUP_USER_ID not set. Add it to ~/.env")
        sys.exit(1)

    filepath = get_sprint_file(target_sprint_num)
    sprint_num = get_sprint_number(filepath)
    print(f"Sprint file: {os.path.basename(filepath)}")

    # Get list ID from frontmatter first, then fallback
    list_id = get_clickup_list_id(filepath)
    if not list_id:
        print(f"Error: No ClickUp list ID found for Sprint {sprint_num}")
        print(f"  Add 'clickup_list_id: \"LIST_ID\"' to the frontmatter.")
        sys.exit(1)
    print(f"ClickUp list: {list_id}")

    # Fetch ClickUp tasks
    clickup_tasks = get_clickup_tasks(list_id)
    print(f"ClickUp tasks assigned to you: {len(clickup_tasks)}")

    # Parse local file
    local_tasks, lines = parse_sprint_file(filepath)
    print(f"Local TECH tasks found: {len(local_tasks)}")
    print()

    # Resolve any PENDING tasks from prior syncs
    print("RESOLVE PENDING:")
    lines = sync_resolve_pending(lines)
    print()
    if not DRY_RUN:
        with open(filepath, "w") as f:
            f.writelines(lines)

    # Create NEW tasks
    print("CREATE:")
    lines = sync_create(filepath, lines, clickup_tasks)
    print()

    # Re-parse after creation (line numbers may have shifted)
    if not DRY_RUN:
        with open(filepath, "w") as f:
            f.writelines(lines)
    local_tasks, lines = parse_sprint_file(filepath)

    # Pull new tasks
    print("PULL:")
    lines = sync_pull(filepath, clickup_tasks, local_tasks, lines)
    print()

    # Create subtasks for child lines without IDs
    print("CREATE SUBTASKS:")
    lines = sync_create_subtasks(lines, clickup_tasks)
    print()

    # Write updated file
    if DRY_RUN:
        print("  [dry-run] Would write changes to sprint file.")
    else:
        with open(filepath, "w") as f:
            f.writelines(lines)

    # Re-parse after subtask creation
    local_tasks, lines = parse_sprint_file(filepath)

    # Push status changes
    print("PUSH:")
    done_tech_ids, deleted_tech_nums = sync_push(local_tasks, clickup_tasks)
    print()

    # Push parent/nesting changes
    print("PUSH PARENTS:")
    sync_push_parents(local_tasks, clickup_tasks)
    print()

    # Remove [d] lines from the sprint file
    if deleted_tech_nums and not DRY_RUN:
        with open(filepath) as f:
            current_lines = f.readlines()
        kept = []
        for line in current_lines:
            m = TASK_LINE_PATTERN.match(line)
            if m:
                tech_num = m.group(3) or m.group(4)
                if tech_num in deleted_tech_nums:
                    print(f"  Removed TECH-{tech_num} from sprint file.")
                    continue
            kept.append(line)
        with open(filepath, "w") as f:
            f.writelines(kept)

    # Move done items to # Done section
    print("MOVE DONE:")
    with open(filepath) as f:
        current_lines = f.readlines()
    current_lines = move_done_to_done_section(current_lines)
    if not DRY_RUN:
        with open(filepath, "w") as f:
            f.writelines(current_lines)
    print()

    # Prompt to close any agent sessions tied to done tasks
    if not DRY_RUN:
        check_agent_closeout(done_tech_ids)

    print("Sync complete.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    if not TOKEN:
        print("Error: CLICKUP_TOKEN not set. Add it to ~/.env")
        sys.exit(1)

    if args and args[0] == "rollover":
        from_num = int(args[1]) if len(args) > 1 else None
        to_num = int(args[2]) if len(args) > 2 else None
        sprint_rollover(from_num, to_num)
    elif args and args[0] == "new":
        sprint_new()
    else:
        # Optional sprint number: sprint-sync [--dry-run] [26]
        target_num = None
        for a in args:
            if a.isdigit():
                target_num = int(a)
                break
        main(target_num)
