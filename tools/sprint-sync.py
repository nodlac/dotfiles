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
from concurrent.futures import ThreadPoolExecutor
from datetime import date

# Force line-buffered stdout so live streaming (nvim jobstart / pipe) shows
# each print as it happens instead of block-buffering until exit.
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

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
    "[x]": "done",
    "[c]": "Closed",        # closed in ClickUp and moves to Done section locally
    "[d]": "__delete__",    # delete from ClickUp and remove line
}

STATUS_TO_MARKER = {
    "to do": "[ ]",
    "in progress": "[/]",
    "qa": "[>]",
    "done": "[x]",
}

# Sort order for # Current Sprint: urgent first, blocked last.
CURRENT_SPRINT_STATUS_ORDER = {
    "[!]": 0,
    "[>]": 1,
    "[/]": 2,
    "[ ]": 3,
    "[~]": 4,
}

# Patterns
TECH_PATTERN = re.compile(r"TECH-(\d+)")
# Matches task lines:
#   - [x] TECH-1234 title [link](url)
#   - [x] [TECH-1234](url) title        (legacy prepended link)
#   - [x] TECH-1234 title               (plain, no link)
TASK_LINE_PATTERN = re.compile(
    r"^(\s*-\s*)\[([^\]]+)\]\s+"  # prefix + marker (1+ non-bracket chars)
    r"(?:\[TECH-(\d+)\]\([^)]*\)|TECH-(\d+))"  # linked or plain TECH ID
    r"\s*(.*?)(?:\s*\[link\]\([^)]*\))?(?:\s*\d{4}-\d{2}-\d{2})?\s*$"  # title, stripping trailing [link](url) and date
)
# Creation lists (one per task type — task type = folder/list membership)
NEW_TYPE_LIST = {
    "BUG":     "901109915076",
    "B":       "901109915076",
    "CHORE":   "901109915070",
    "C":       "901109915070",
    "FEATURE": "901109915057",
    "F":       "901109915057",
}
# Pretty name for log output
NEW_TYPE_NAME = {
    "BUG": "bug", "B": "bug",
    "CHORE": "chore", "C": "chore",
    "FEATURE": "feature", "F": "feature",
}
# NEW_BUG / NEW_B / NEW_CHORE / NEW_C / NEW_FEATURE / NEW_F
# Raw "NEW " without a type is rejected (must pick a type list)
NEW_TASK_PATTERN = re.compile(
    r"^(\s*-\s*)\[([^\]]+)\]\s+NEW_(BUG|B|CHORE|C|FEATURE|F)\b\s+(.*)",
    re.IGNORECASE,
)
# Bare NEW (no type) — reported as error so user fixes the line
BARE_NEW_PATTERN = re.compile(
    r"^(\s*-\s*)\[([^\]]+)\]\s+NEW(?:_\d+)?\b\s+(.*)"
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


def get_list_statuses(list_id):
    """Return list of status name strings available for a ClickUp list."""
    data = api("GET", f"/list/{list_id}")
    if not data:
        return []
    return [s["status"] for s in data.get("statuses", [])]


def resolve_status(target, available):
    """Map a target status (e.g. 'Closed') to the actual list status string
    (e.g. 'closed (caution!)'). Case-insensitive exact first, then substring."""
    if not available:
        return target
    tl = target.lower()
    for s in available:
        if s.lower() == tl:
            return s
    for s in available:
        if tl in s.lower():
            return s
    return target


_remote_task_cache = {}


def get_task_by_tech_num(tech_num):
    """Look up a single task by its TECH-XXXX custom ID. Returns task dict or None.
    Results are cached per-run so repeat lookups are free."""
    if tech_num in _remote_task_cache:
        return _remote_task_cache[tech_num]
    data = api("GET", f"/task/TECH-{tech_num}?custom_task_ids=true&team_id={TEAM_ID}")
    result = data if data and data.get("id") else None
    _remote_task_cache[tech_num] = result
    return result


def get_list_task_tech_ids(list_id):
    """Authoritative list membership — all TECH ids returned by the list
    task query (no user filter). Used to detect drift where task.locations
    says the task is in the list but the list view disagrees."""
    page = 0
    ids = set()
    while True:
        data = api("GET", f"/list/{list_id}/task?include_closed=true&subtasks=true&page={page}")
        tasks = (data or {}).get("tasks") or []
        for t in tasks:
            cid = (t.get("custom_id") or "").replace("TECH-", "")
            if cid:
                ids.add(cid)
        if len(tasks) < 100:
            break
        page += 1
    return ids


def get_tasks_by_tech_nums(tech_nums, max_workers=10):
    """Parallel fetch for a batch of TECH numbers. Returns {tech_num: task_or_None}."""
    tech_nums = list(tech_nums)
    if not tech_nums:
        return {}
    # Filter out cached ones
    to_fetch = [tn for tn in tech_nums if tn not in _remote_task_cache]
    if to_fetch:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            list(ex.map(get_task_by_tech_num, to_fetch))
    return {tn: _remote_task_cache.get(tn) for tn in tech_nums}


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


SPRINT_OVERRIDE_RE = re.compile(r'\s*>>\s*(\d+)\s*$')


def parse_sprint_file_lines(lines):
    """Parse in-memory lines and return dict of TECH ID -> (line_num, marker, title, indent, target_sprint)."""
    tasks = {}
    for i, line in enumerate(lines):
        m = TASK_LINE_PATTERN.match(line)
        if m:
            tech_id = m.group(3) or m.group(4)
            marker = f"[{m.group(2)}]"
            title = m.group(5).strip()
            target_sprint = None
            om = SPRINT_OVERRIDE_RE.search(title)
            if om:
                target_sprint = int(om.group(1))
                title = SPRINT_OVERRIDE_RE.sub('', title).strip()
            indent = len(line) - len(line.lstrip())
            tasks[tech_id] = {"line": i, "marker": marker, "title": title,
                              "indent": indent, "target_sprint": target_sprint}
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


CURRENT_SPRINT_HEADING = "# Current Sprint"
LEGACY_CURRENT_HEADINGS = ("# Current Sprint", "# Uncategorized Tasks")


def _find_uncategorized_insert(lines):
    """Return the line index to insert into the current sprint section.
    Prefers '# Current Sprint', falls back to legacy '# Uncategorized Tasks'.
    Creates the section if missing. Returns (lines, insert_idx)."""
    for i, line in enumerate(lines):
        if line.strip() in LEGACY_CURRENT_HEADINGS:
            return lines, i + 1

    # Section missing — create '# Current Sprint' after frontmatter / legend
    insert_idx = 0
    fence_count = 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            fence_count += 1
            if fence_count == 2:
                insert_idx = i + 1
                break
    for i in range(insert_idx, len(lines)):
        if lines[i].startswith("# Legend") or lines[i].lstrip().startswith("<!--"):
            insert_idx = i + 1
            while insert_idx < len(lines) and lines[insert_idx].strip().startswith("<!--"):
                insert_idx += 1
            break

    lines[insert_idx:insert_idx] = ["\n", CURRENT_SPRINT_HEADING + "\n"]
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


def _find_section_range(lines, heading):
    """Return (start_idx, end_idx) bounding lines of a top-level section.
    start_idx = line of heading, end_idx = first line of the next top-level
    heading (or len(lines) if this is the last section). (None, None) if
    section missing."""
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == heading:
            start = i
            break
    if start is None:
        return None, None
    for j in range(start + 1, len(lines)):
        stripped = lines[j].lstrip()
        # Top-level heading only — "# " but not "## "
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return start, j
    return start, len(lines)


def _find_future_projects_insert(lines):
    """Return (lines, insert_idx) for new items in # Future Projects.
    Creates the section just above # Done if missing, else at end of file."""
    return _ensure_section_above_done(lines, "# Future Projects")


def _find_failed_move_insert(lines):
    """Return (lines, insert_idx) for tasks that can't be sprint-deferred
    via secondary-attach (their ClickUp home list IS the current sprint).
    Placed ABOVE # Current Sprint so the failure is visible at the top."""
    start, _ = _find_section_range(lines, "# Failed to Move")
    if start is not None:
        return lines, start + 1
    cs_start, _ = _find_section_range(lines, "# Current Sprint")
    insert_idx = cs_start if cs_start is not None else len(lines)
    if insert_idx > 0 and lines[insert_idx - 1].strip() != "":
        lines[insert_idx:insert_idx] = ["\n"]
        insert_idx += 1
    lines[insert_idx:insert_idx] = ["# Failed to Move\n", "\n"]
    after = insert_idx + 2
    if after < len(lines) and lines[after].strip() != "":
        lines[after:after] = ["\n"]
    return lines, insert_idx + 1


def _find_drifted_insert(lines):
    """Return (lines, insert_idx) for tasks whose ClickUp record claims the
    current sprint in `locations` but which the sprint list view does NOT
    include. Placed ABOVE # Current Sprint so drift is visible at the top."""
    start, _ = _find_section_range(lines, "# Drifted")
    if start is not None:
        return lines, start + 1
    cs_start, _ = _find_section_range(lines, "# Current Sprint")
    insert_idx = cs_start if cs_start is not None else len(lines)
    if insert_idx > 0 and lines[insert_idx - 1].strip() != "":
        lines[insert_idx:insert_idx] = ["\n"]
        insert_idx += 1
    lines[insert_idx:insert_idx] = ["# Drifted\n", "\n"]
    after = insert_idx + 2
    if after < len(lines) and lines[after].strip() != "":
        lines[after:after] = ["\n"]
    return lines, insert_idx + 1


def _ensure_section_above_done(lines, heading):
    start, _ = _find_section_range(lines, heading)
    if start is not None:
        return lines, start + 1
    dstart, _ = _find_section_range(lines, "# Done")
    insert_idx = dstart if dstart is not None else len(lines)
    if insert_idx > 0 and lines[insert_idx - 1].strip() != "":
        lines[insert_idx:insert_idx] = ["\n"]
        insert_idx += 1
    lines[insert_idx:insert_idx] = [f"{heading}\n", "\n"]
    after = insert_idx + 2
    if after < len(lines) and lines[after].strip() != "":
        lines[after:after] = ["\n"]
    return lines, insert_idx + 1


# ── Placement memory: remember which section each TECH lives in ──────────
PLACEMENTS_FILE = os.path.join(SPRINT_DIR, ".placements.json")
# Sections we never file *into* (pull destinations, done-pile, cruft).
EXCLUDED_PLACEMENT_HEADINGS = {
    "# Current Sprint",
    "# Uncategorized Tasks",  # legacy
    "# Done",
    "# Future Projects",
}


def snapshot_placements(lines):
    """Return {tech_id: nearest_top_or_H2_heading} for every TECH in `lines`.
    Skips tasks filed in sections we explicitly ignore."""
    placements = {}
    current_heading = None
    for line in lines:
        stripped = line.lstrip()
        # Track headings — prefer deeper (## / ###) over top-level
        if stripped.startswith("#"):
            current_heading = line.rstrip()
            continue
        m = TASK_LINE_PATTERN.match(line)
        if m and current_heading:
            if current_heading in EXCLUDED_PLACEMENT_HEADINGS:
                continue
            tech = m.group(3) or m.group(4)
            placements[tech] = current_heading
    return placements


def load_placements():
    try:
        with open(PLACEMENTS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_placements(mem):
    os.makedirs(os.path.dirname(PLACEMENTS_FILE), exist_ok=True)
    with open(PLACEMENTS_FILE, "w") as f:
        json.dump(mem, f, indent=2, sort_keys=True)


def _find_heading_end(lines, heading_text):
    """Return (heading_idx, end_idx) where end_idx is the line of the next
    heading at the same-or-higher level. (None, None) if not found."""
    # Determine heading level
    level = 0
    for ch in heading_text.lstrip():
        if ch == "#":
            level += 1
        else:
            break
    for i, line in enumerate(lines):
        if line.rstrip() == heading_text.rstrip():
            for j in range(i + 1, len(lines)):
                s = lines[j].lstrip()
                # Count leading # in candidate heading
                if s.startswith("#"):
                    lvl = 0
                    for ch in s:
                        if ch == "#": lvl += 1
                        else: break
                    if lvl <= level:
                        return i, j
            return i, len(lines)
    return None, None


def insert_into_remembered_section(lines, heading_text, task_line):
    """Insert task_line (str or list[str]) at the end of the section whose
    heading matches `heading_text`. Returns (lines, inserted_idx) or
    (lines, None) if the section isn't present in this file."""
    start, end = _find_heading_end(lines, heading_text)
    if start is None:
        return lines, None
    # Skip trailing blank lines to keep the insertion tight
    insert_idx = end
    while insert_idx > start + 1 and lines[insert_idx - 1].strip() == "":
        insert_idx -= 1
    block = [task_line] if isinstance(task_line, str) else list(task_line)
    for offset, bline in enumerate(block):
        lines.insert(insert_idx + offset, bline)
    return lines, insert_idx


def sort_sections(lines):
    """Sort tasks within each section.

    - # Current Sprint  → status priority: ! > > > / > ' ' > ~ (CURRENT_SPRINT_STATUS_ORDER)
    - other ## sections → TECH ID asc
    - # Future Projects, # Done              → leave alone (others handle them)
    """
    if not lines:
        return lines
    # Identify section spans at any heading level
    heading_idxs = [i for i, l in enumerate(lines) if re.match(r"^#+\s+", l.lstrip())]
    heading_idxs.append(len(lines))

    for h_i in range(len(heading_idxs) - 1):
        start = heading_idxs[h_i]
        end = heading_idxs[h_i + 1]
        heading_line = lines[start].rstrip()
        heading_text = heading_line.lstrip("# ").strip()
        if heading_text in ("Future Projects", "Done", "Failed to Move", "Drifted"):
            continue

        is_current = heading_text == "Current Sprint"

        # Group task "blocks" (task line + deeper-indented children)
        body = lines[start + 1:end]
        blocks = []
        i = 0
        preamble = []
        # Skip leading blank/comment lines as preamble
        while i < len(body) and body[i].strip() == "":
            preamble.append(body[i])
            i += 1
        while i < len(body):
            line = body[i]
            m = TASK_LINE_PATTERN.match(line)
            if m:
                task_indent = len(line) - len(line.lstrip())
                block = [line]
                j = i + 1
                # Absorb blank + deeper-indented successors
                while j < len(body):
                    nxt = body[j]
                    if nxt.strip() == "":
                        block.append(nxt)
                        j += 1
                        continue
                    nxt_indent = len(nxt) - len(nxt.lstrip())
                    if nxt_indent > task_indent:
                        block.append(nxt)
                        j += 1
                    else:
                        break
                # Trim trailing blank
                while block and block[-1].strip() == "":
                    block.pop()
                blocks.append(("task", m, block))
                i = j
            else:
                # Not a task — keep as loose line (e.g. notes between tasks)
                blocks.append(("loose", None, [line]))
                i += 1

        if not blocks or not any(t == "task" for t, _, _ in blocks):
            continue

        def sort_key(entry):
            t, m, block = entry
            if t != "task":
                return (99, 0, 0)
            marker = f"[{m.group(2)}]"
            tech_id = int(m.group(3) or m.group(4))
            if is_current:
                rank = CURRENT_SPRINT_STATUS_ORDER.get(marker, 10)
                return (rank, tech_id, 0)
            return (0, tech_id, 0)

        # Only sort if section has 2+ task blocks
        task_blocks = [b for b in blocks if b[0] == "task"]
        if len(task_blocks) < 2:
            continue
        task_blocks.sort(key=sort_key)

        # Rebuild: preamble + sorted task blocks. In # Current Sprint,
        # insert one blank line between status-marker groups. Other
        # sections stay contiguous.
        new_body = list(preamble)
        last_rank = None
        for t, m, blk in task_blocks:
            if is_current:
                marker = f"[{m.group(2)}]"
                rank = CURRENT_SPRINT_STATUS_ORDER.get(marker, 10)
                if last_rank is not None and rank != last_rank:
                    new_body.append("\n")
                last_rank = rank
            new_body.extend(blk)
        # Ensure exactly one trailing blank before next heading
        if new_body and new_body[-1].strip() != "":
            new_body.append("\n")

        lines = lines[:start + 1] + new_body + lines[end:]
        # Recompute indices since we mutated
        heading_idxs = [i for i, l in enumerate(lines) if re.match(r"^#+\s+", l.lstrip())]
        heading_idxs.append(len(lines))

    return lines


def _task_target_sprint(line):
    """Return target sprint NN for a TECH task line, or None.
    Prefers [NN] marker; falls back to legacy `>> NN` suffix."""
    m = TASK_LINE_PATTERN.match(line)
    if not m:
        return None
    marker_body = m.group(2)
    if marker_body.isdigit():
        return int(marker_body)
    override = SPRINT_OVERRIDE_RE.search(line.rstrip("\n"))
    if override:
        return int(override.group(1))
    return None


def organize_future_projects(lines, current_sprint=None):
    """Promote matured TECH-XXXX lines inside # Future Projects back to
    # Current Sprint. A TECH line counts as matured when its [NN] marker
    (or legacy `>> NN` suffix) is <= current_sprint. NEW_XX lines left
    wherever author put them."""
    moved_to_future = 0
    moved_out = 0

    # Pass 2: matured TECH lines inside # Future Projects → back to Uncategorized
    fstart, fend = _find_section_range(lines, "# Future Projects")
    if fstart is not None:
        matured = []
        for i in range(fstart + 1, fend):
            target = _task_target_sprint(lines[i])
            if target is None:
                continue
            # Only mature when we know the current sprint AND target has
            # arrived. Unknown sprint → never strip [NN] (fail safe).
            if current_sprint is None or target > current_sprint:
                continue
            matured.append(i)
        matured_blocks = []
        for i in sorted(matured, reverse=True):
            block, lines = _remove_task_block(lines, i)
            # Reset [NN] marker to [ ] and strip legacy `>> NN` on head
            head = block[0]
            head = re.sub(r'\[\d+\]', '[ ]', head, count=1)
            head = SPRINT_OVERRIDE_RE.sub('', head.rstrip("\n")) + "\n"
            block[0] = head
            matured_blocks.append(block)
        matured_blocks.reverse()

        if matured_blocks:
            lines, insert_idx = _find_uncategorized_insert(lines)
            for block in matured_blocks:
                for bline in block:
                    lines.insert(insert_idx, bline)
                    insert_idx += 1
            moved_out = len(matured_blocks)

    # Pass 3: sort parked task blocks (task + nested children) by target
    # sprint, blank line between cohorts.
    fstart, fend = _find_section_range(lines, "# Future Projects")
    if fstart is not None:
        # Find head lines in section, top-down
        head_entries = []  # (line_idx, sprint_n)
        for i in range(fstart + 1, fend):
            line = lines[i]
            mnew = NEW_TASK_PATTERN.match(line)
            if mnew:
                # NEW_<type> with [NN] marker has digit sprint
                marker_body = mnew.group(2)
                if marker_body.isdigit():
                    head_entries.append((i, int(marker_body)))
                continue
            target = _task_target_sprint(line)
            if target is not None:
                head_entries.append((i, target))

        if head_entries:
            # Pop blocks bottom-up
            blocks = []  # (sprint_n, block_lines)
            for i, sprint_n in sorted(head_entries, key=lambda x: -x[0]):
                block, lines = _remove_task_block(lines, i)
                blocks.append((sprint_n, block))
            blocks.reverse()
            blocks.sort(key=lambda x: x[0])

            # Rebuild the section: heading + blocks with blank between cohorts
            new_body = []
            last_sprint = None
            for sprint_n, block in blocks:
                if last_sprint is not None and sprint_n != last_sprint:
                    new_body.append("\n")
                new_body.extend(block)
                last_sprint = sprint_n
            # Trailing blank before next heading
            if new_body and new_body[-1].strip() != "":
                new_body.append("\n")

            # Recompute section range after pops and replace body
            fstart, fend = _find_section_range(lines, "# Future Projects")
            lines = lines[:fstart + 1] + ["\n"] + new_body + lines[fend:]

    tag = "[dry-run] " if DRY_RUN else ""
    if moved_out:
        print(f"  {tag}Promoted {moved_out} matured task(s) from # Future Projects.")
    else:
        print("  No changes.")
    return lines


def _update_task_marker(lines, line_idx, new_marker):
    """Replace the [X] marker of a task line, preserving everything else."""
    line = lines[line_idx]
    m = TASK_LINE_PATTERN.match(line)
    if not m:
        return lines
    # new_marker is like "[x]" or "[30]" — preserve brackets as given
    bracketed = new_marker if new_marker.startswith("[") else f"[{new_marker}]"
    lines[line_idx] = re.sub(r'\[[^\]]+\]', bracketed, line, count=1)
    return lines


def _get_task_indent(lines, line_idx):
    """Return the indentation of a task line (number of leading spaces)."""
    return len(lines[line_idx]) - len(lines[line_idx].lstrip())


def _remove_task_block(lines, line_idx):
    """Remove a task line and all its deeper-indented children (including
    blank lines between them). Returns (removed_lines, remaining_lines)."""
    task_indent = _get_task_indent(lines, line_idx)
    block = [lines[line_idx]]
    j = line_idx + 1
    while j < len(lines):
        if lines[j].strip() == "":
            # Look ahead: only absorb blank if deeper content follows
            k = j + 1
            while k < len(lines) and lines[k].strip() == "":
                k += 1
            if k < len(lines) and (len(lines[k]) - len(lines[k].lstrip())) > task_indent:
                block.extend(lines[j:k])
                j = k
                continue
            break
        if (len(lines[j]) - len(lines[j].lstrip())) > task_indent:
            block.append(lines[j])
            j += 1
        else:
            break
    remaining = lines[:line_idx] + lines[j:]
    return block, remaining


def sync_pull(filepath, clickup_tasks, local_tasks, lines, placements=None):
    """Pull new tasks and subtasks from ClickUp into the sprint file.

    Also updates task names and re-nests/un-nests tasks when parent changes.
    If `placements` is provided ({tech_id: heading_text}), new tasks that
    match a remembered heading are inserted there instead of Uncategorized.
    """
    placements = placements or {}

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

    # Insert top-level tasks — prefer remembered section, else Uncategorized
    new_top_for_uncat = []
    for tech_num, marker, title in new_top:
        remembered = placements.get(tech_num)
        if remembered:
            task_line = format_task_line(tech_num, marker, title)
            lines, inserted_idx = insert_into_remembered_section(lines, remembered, task_line)
            if inserted_idx is not None:
                section_label = remembered.lstrip("# ").rstrip()
                print(f"    {marker} TECH-{tech_num} {title}  → {section_label}")
                pulled += 1
                continue
        # Section missing in this file — fall through to Uncategorized
        new_top_for_uncat.append((tech_num, marker, title))

    if new_top_for_uncat:
        lines, insert_idx = _find_uncategorized_insert(lines)
        for tech_num, marker, title in new_top_for_uncat:
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
    off_remotes = get_tasks_by_tech_nums(off_list)
    for tech_num in off_list:
        remote = off_remotes.get(tech_num)
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


def sync_push(local_tasks, clickup_tasks, current_sprint_num=None, list_id=None):
    """Push local status changes to ClickUp.
    Returns (done_tech_ids, deleted_tech_nums, pushed_next_tech_nums).
    """
    cu_lookup = {}
    for task in clickup_tasks:
        custom_id = task.get("custom_id")
        if custom_id:
            cu_lookup[custom_id.replace("TECH-", "")] = task

    # Fetch actual list statuses so targets like "Closed" map to the list's
    # real status string (e.g. "closed (caution!)").
    list_statuses = get_list_statuses(list_id) if list_id else []

    pushed = 0
    done_tech_ids = []
    deleted_tech_nums = []
    pushed_next_tech_nums = []
    sprint_list_cache = {}  # sprint_num -> (id, name)

    # push_target_map: tech_num -> target_sprint (for lines to MOVE into Future Projects)
    # pushed_next_tech_nums: tech_num for lines to REMOVE from file (target list missing)
    # file_to_section_map: tech_num -> section_heading_text (for alpha topic markers)
    # failed_move_tech_nums: task's home list IS current sprint — can't be deferred
    #                       via secondary-attach, line goes to # Failed to Move
    push_target_map = {}
    file_to_section_map = {}
    failed_move_tech_nums = set()

    for tech_num, local in local_tasks.items():
        local_marker = local["marker"]
        target_status = MARKER_TO_STATUS.get(local_marker)

        # Detect digit marker [NN] as push-to-sprint-NN
        marker_sprint_override = None
        file_topic = None
        if target_status is None:
            mnum = re.fullmatch(r'\[(\d+)\]', local_marker)
            if mnum:
                marker_sprint_override = int(mnum.group(1))
                target_status = "__push_sprint__"
            else:
                # Multi-char alpha marker → file to matching section
                mtopic = re.fullmatch(r'\[([A-Za-z][A-Za-z0-9 _\-]*)\]', local_marker)
                if mtopic and mtopic.group(1) not in (k.strip('[]') for k in MARKER_TO_STATUS):
                    file_topic = mtopic.group(1).strip()
                    target_status = "__file_to_section__"

        if not target_status:
            continue

        if target_status == "__file_to_section__":
            # Defer: main() will find the heading, move the line, reset marker.
            file_to_section_map[tech_num] = file_topic
            pushed += 1
            continue

        if target_status == "__push_sprint__":
            target_sprint = marker_sprint_override
            if current_sprint_num is not None and target_sprint <= current_sprint_num:
                print(f"  ERROR TECH-{tech_num}: [{target_sprint}] must be > current sprint {current_sprint_num}")
                continue

            if target_sprint not in sprint_list_cache:
                nl_id, nl_name = find_clickup_sprint_list(target_sprint)
                sprint_list_cache[target_sprint] = (nl_id, nl_name)
            target_list_id, target_list_name = sprint_list_cache[target_sprint]

            if target_list_id is None:
                print(f"  SKIP TECH-{tech_num}: Sprint {target_sprint} has no ClickUp list yet")
                continue

            if tech_num not in cu_lookup:
                fetched = get_task_by_tech_num(tech_num)
                if fetched:
                    cu_lookup[tech_num] = fetched
            if tech_num not in cu_lookup:
                print(f"  SKIP TECH-{tech_num}: not in ClickUp (cannot attach to Sprint {target_sprint})")
                continue

            # If the task's HOME list is the current sprint, we can't truly
            # defer via secondary-attach (home keeps it visible here).
            # Flag for manual cleanup instead.
            remote_home = (cu_lookup[tech_num].get("list") or {}).get("id")
            if list_id and remote_home == list_id:
                print(f"  FAIL TECH-{tech_num}: home list is current sprint — routed to # Failed to Move")
                failed_move_tech_nums.add(tech_num)
                pushed += 1
                continue

            if DRY_RUN:
                print(f"  [dry-run] TECH-{tech_num}: attach to Sprint {target_sprint}, reset marker")
                push_target_map[tech_num] = target_sprint
                pushed += 1
            else:
                result = api("POST", f"/list/{target_list_id}/task/{cu_lookup[tech_num]['id']}")
                if result is not None:
                    print(f"  TECH-{tech_num}: attached to Sprint {target_sprint} ({target_list_name})")
                    push_target_map[tech_num] = target_sprint
                    pushed += 1
                else:
                    print(f"  TECH-{tech_num}: attach failed")
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

        resolved = resolve_status(target_status, list_statuses)

        if resolved.lower() == cu_status.lower():
            continue

        if DRY_RUN:
            print(f"  [dry-run] TECH-{tech_num}: {cu_status} -> {resolved}")
            pushed += 1
        else:
            result = api("PUT", f"/task/{cu_task['id']}", {"status": resolved})
            if result:
                print(f"  TECH-{tech_num}: {cu_status} -> {resolved}")
                pushed += 1
                if resolved.lower() in ("done", "closed") or "closed" in resolved.lower():
                    done_tech_ids.append(f"TECH-{tech_num}")

    if pushed == 0:
        print("  No status changes to push.")
    else:
        print(f"  Pushed {pushed} status updates.")

    return done_tech_ids, deleted_tech_nums, pushed_next_tech_nums, push_target_map, file_to_section_map, failed_move_tech_nums


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
    """Create tasks in ClickUp for NEW_<type> lines. Type selects home list
    (bug/chore/feature).
      [ ] NEW_<type>  → attach to current sprint list; line stays in place
      [NN] NEW_<type> → attach to sprint NN list; line relocated to # Future Projects
    Bare NEW (no type) is flagged as an error."""
    current_sprint = get_sprint_number(filepath)
    sprint_list_id = get_clickup_list_id(filepath)

    # Build title -> custom_id lookup from existing ClickUp tasks for dedup
    existing_by_title = {}
    for t in (clickup_tasks or []):
        cid = t.get("custom_id")
        if cid:
            existing_by_title[t["name"].strip()] = cid

    created = 0
    future_line_idxs = []  # indices of [NN] lines to relocate to Future Projects
    sprint_cache = {}  # target_sprint -> (list_id, list_name)
    for i, line in enumerate(lines):
        # Flag bare NEW (no type) and skip
        if BARE_NEW_PATTERN.match(line) and not NEW_TASK_PATTERN.match(line):
            print(f"  ERROR line {i+1}: bare NEW — use NEW_BUG | NEW_CHORE | NEW_FEATURE (or NEW_B / NEW_C / NEW_F)")
            continue

        m = NEW_TASK_PATTERN.match(line)
        if not m:
            continue

        indent = m.group(1)
        marker_body = m.group(2)
        marker = f"[{marker_body}]"
        type_key = m.group(3).upper()
        title = m.group(4).strip()

        if not title:
            continue

        type_list_id = NEW_TYPE_LIST[type_key]
        indent_clean = indent.rstrip("- ") or "    "

        # Marker [NN] → digit = target sprint. Otherwise marker → status.
        target_sprint = None
        if marker_body.isdigit():
            target_sprint = int(marker_body)
            if current_sprint is not None and target_sprint <= current_sprint:
                print(f"  ERROR line {i+1}: [{target_sprint}] must be > current sprint {current_sprint}")
                continue
            target_status = "to do"
        else:
            target_status = MARKER_TO_STATUS.get(marker, "to do")

        # Decide which sprint list to attach as secondary
        attach_sprint = target_sprint if target_sprint is not None else current_sprint
        attach_list_id, attach_list_name = None, None
        if attach_sprint is not None:
            if attach_sprint == current_sprint and sprint_list_id:
                attach_list_id, attach_list_name = sprint_list_id, f"Sprint {current_sprint}"
            else:
                if attach_sprint not in sprint_cache:
                    sprint_cache[attach_sprint] = find_clickup_sprint_list(attach_sprint)
                attach_list_id, attach_list_name = sprint_cache[attach_sprint]

        if DRY_RUN:
            extra = f" → {attach_list_name}" if attach_list_id else ""
            print(f"  [dry-run] Would create ({NEW_TYPE_NAME[type_key]}): {title}{extra}")
            created += 1
            continue

        # Dedup: reuse if title already exists
        if title in existing_by_title:
            existing_id = existing_by_title[title]
            tech_num = existing_id.replace("TECH-", "")
            lines[i] = format_task_line(tech_num, marker, title, indent_clean)
            print(f"  Reused existing TECH-{tech_num}: {title}")
            if target_sprint is not None:
                future_line_idxs.append(i)
            created += 1
            continue

        result = api("POST", f"/list/{type_list_id}/task", {
            "name": title,
            "assignees": [int(USER_ID)],
            "status": target_status,
        })

        if not (result and result.get("id")):
            continue

        task_id = result["id"]
        custom_id = result.get("custom_id", "")
        if not custom_id:
            fetched = api("GET", f"/task/{task_id}")
            custom_id = fetched.get("custom_id", "") if fetched else ""

        attached_msg = ""
        if attach_list_id:
            res = api("POST", f"/list/{attach_list_id}/task/{task_id}")
            if res is not None:
                attached_msg = f" → {attach_list_name}"
        elif attach_sprint is not None:
            print(f"  WARN: Sprint {attach_sprint} list missing — created but not attached")

        if custom_id:
            tech_num = custom_id.replace("TECH-", "")
            lines[i] = format_task_line(tech_num, marker, title, indent_clean)
            print(f"  Created TECH-{tech_num} ({NEW_TYPE_NAME[type_key]}): {title}{attached_msg}")
            if target_sprint is not None:
                future_line_idxs.append(i)
            created += 1
        else:
            lines[i] = format_pending_line(task_id, marker, title, indent_clean)
            print(f"  WARNING: created ({NEW_TYPE_NAME[type_key]}) but no custom ID yet: {title}")
            print(f"           Saved as PENDING:{task_id} — will resolve on next sync.")
            created += 1

    # Relocate [NN] NEW_* creations to # Future Projects (with children)
    if future_line_idxs and not DRY_RUN:
        blocks = []
        for i in sorted(future_line_idxs, reverse=True):
            block, lines = _remove_task_block(lines, i)
            blocks.append(block)
        blocks.reverse()
        lines, fp_insert = _find_future_projects_insert(lines)
        for block in blocks:
            for bline in block:
                lines.insert(fp_insert, bline)
                fp_insert += 1
        print(f"  Moved {len(blocks)} new [NN] task(s) to # Future Projects.")

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
<!-- Markers:  [ ] todo  [/] in progress  [>] qa  [~] blocked  [!] urgent  [x] done  [c] closed  [d] delete
Sprint / filing:  [NN] attach to sprint NN (drops to [ ] when promoted)  [topic] file under ## topic heading
Create:  NEW_BUG | NEW_CHORE | NEW_FEATURE  (short: NEW_B | NEW_C | NEW_F)  creates in that type's list
Combo:  [NN] NEW_BUG <title>  creates + attaches to sprint NN (line parked in # Future Projects)
Pending:  PENDING:<id> awaiting custom ID
Sections:  # Failed to Move  # Drifted  # Current Sprint  # <topic>  # Future Projects  # Done -->

# Current Sprint

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

    # Placement memory: snapshot where each TECH currently lives, merge
    # with saved state so newly-filed tasks are remembered for future pulls.
    placements = load_placements()
    placements.update(snapshot_placements(lines))

    # Resolve any PENDING tasks from prior syncs
    print("RESOLVE PENDING:")
    lines = sync_resolve_pending(lines)
    print()
    if not DRY_RUN:
        with open(filepath, "w") as f:
            f.writelines(lines)

    # Park deferred NEW_XX tasks under # Future Projects
    print("ORGANIZE FUTURE:")
    lines = organize_future_projects(lines, current_sprint=sprint_num)
    print()
    if not DRY_RUN:
        with open(filepath, "w") as f:
            f.writelines(lines)

    # Create NEW tasks (matured NEW_XX get their TECH line in place, which
    # is inside # Future Projects — the next organize pass promotes them)
    print("CREATE:")
    lines = sync_create(filepath, lines, clickup_tasks)
    print()

    # Promote any matured TECH lines out of # Future Projects
    lines = organize_future_projects(lines, current_sprint=sprint_num)

    # Re-parse after creation (line numbers may have shifted)
    if not DRY_RUN:
        with open(filepath, "w") as f:
            f.writelines(lines)
    local_tasks, lines = parse_sprint_file(filepath)

    # Pull new tasks
    print("PULL:")
    lines = sync_pull(filepath, clickup_tasks, local_tasks, lines, placements=placements)
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
    done_tech_ids, deleted_tech_nums, pushed_next_tech_nums, push_target_map, file_to_section_map, failed_move_tech_nums = sync_push(
        local_tasks, clickup_tasks, current_sprint_num=sprint_num, list_id=list_id
    )
    print()

    # Push parent/nesting changes
    print("PUSH PARENTS:")
    sync_push_parents(local_tasks, clickup_tasks)
    print()

    # Remove [d] lines and lines whose push target sprint has no ClickUp list yet.
    purge_nums = set(deleted_tech_nums) | set(pushed_next_tech_nums)
    if purge_nums and not DRY_RUN:
        with open(filepath) as f:
            current_lines = f.readlines()
        kept = []
        for line in current_lines:
            m = TASK_LINE_PATTERN.match(line)
            if m:
                tech_num = m.group(3) or m.group(4)
                if tech_num in purge_nums:
                    tag = "deleted" if tech_num in deleted_tech_nums else "pushed (no target list yet)"
                    print(f"  Removed TECH-{tech_num} from sprint file ({tag}).")
                    continue
            kept.append(line)
        with open(filepath, "w") as f:
            f.writelines(kept)

    # [NN]-marked lines were attached to that sprint's list. Keep the
    # [NN] marker (organize_future_projects sorts by it). If the line
    # currently sits inside # Current Sprint and NN > current sprint,
    # relocate it to # Future Projects.
    if push_target_map and not DRY_RUN:
        with open(filepath) as f:
            current_lines = f.readlines()
        relocated = 0
        cstart, cend = _find_section_range(current_lines, "# Current Sprint")

        if cstart is not None:
            to_move_idxs = []
            for i in range(cstart + 1, cend):
                m = TASK_LINE_PATTERN.match(current_lines[i])
                if not m:
                    continue
                tech_num = m.group(3) or m.group(4)
                if tech_num not in push_target_map:
                    continue
                target_sprint = push_target_map[tech_num]
                if sprint_num is None or target_sprint > sprint_num:
                    to_move_idxs.append(i)
            if to_move_idxs:
                # Pop blocks (task + children) bottom-up to preserve indices
                blocks = []
                for i in sorted(to_move_idxs, reverse=True):
                    block, current_lines = _remove_task_block(current_lines, i)
                    blocks.append(block)
                blocks.reverse()
                current_lines, fp_insert = _find_future_projects_insert(current_lines)
                for block in blocks:
                    for bline in block:
                        current_lines.insert(fp_insert, bline)
                        fp_insert += 1
                relocated = len(blocks)

        if relocated:
            with open(filepath, "w") as f:
                f.writelines(current_lines)
            print(f"  Moved {relocated} [NN]-marked task(s) from # Current Sprint to # Future Projects.")

    # Failed-to-move: [NN] applied to a task whose ClickUp home IS the
    # current sprint list. Secondary-attach can't truly defer it, so route
    # the line to # Failed to Move for manual cleanup.
    if failed_move_tech_nums and not DRY_RUN:
        with open(filepath) as f:
            current_lines = f.readlines()
        head_idxs = []
        for i, line in enumerate(current_lines):
            m = TASK_LINE_PATTERN.match(line)
            if not m:
                continue
            tech_num = m.group(3) or m.group(4)
            if tech_num in failed_move_tech_nums:
                head_idxs.append(i)
        if head_idxs:
            blocks = []
            for i in sorted(head_idxs, reverse=True):
                block, current_lines = _remove_task_block(current_lines, i)
                blocks.append(block)
            blocks.reverse()
            current_lines, fm_insert = _find_failed_move_insert(current_lines)
            for block in blocks:
                for bline in block:
                    current_lines.insert(fm_insert, bline)
                    fm_insert += 1
            with open(filepath, "w") as f:
                f.writelines(current_lines)
            print(f"  Moved {len(blocks)} task(s) to # Failed to Move (home list is current sprint).")

    # File alpha-topic-marker lines into matching section inside sprint file
    if file_to_section_map:
        print("FILE:")
        with open(filepath) as f:
            current_lines = f.readlines()

        # Build a normalized heading map: key = lowercase-trimmed text, val = full heading line
        heading_map = {}
        for line in current_lines:
            stripped = line.lstrip()
            if stripped.startswith("#"):
                text = stripped.lstrip("#").strip().lower()
                heading_map[text] = line.rstrip()

        resolved = {}  # tech_num -> heading_text
        for tech_num, topic in file_to_section_map.items():
            heading = heading_map.get(topic.lower().strip())
            if heading is None:
                print(f"  ERROR TECH-{tech_num}: no heading matching '{topic}' in sprint file — leaving marker as-is")
                continue
            resolved[tech_num] = heading

        if resolved and not DRY_RUN:
            # Reset markers on resolved head lines to [ ]
            for i, line in enumerate(current_lines):
                m = TASK_LINE_PATTERN.match(line)
                if not m:
                    continue
                tech_num = m.group(3) or m.group(4)
                if tech_num in resolved:
                    current_lines[i] = re.sub(r'\[[^\]]+\]', '[ ]', line, count=1)

            # Find head-line indices, pop blocks bottom-up, then insert
            head_idxs = []
            for i, line in enumerate(current_lines):
                m = TASK_LINE_PATTERN.match(line)
                if not m:
                    continue
                tech_num = m.group(3) or m.group(4)
                if tech_num in resolved:
                    head_idxs.append((i, tech_num))
            move_map = {}  # heading_text -> [blocks]
            for i, tech_num in sorted(head_idxs, key=lambda x: -x[0]):
                block, current_lines = _remove_task_block(current_lines, i)
                move_map.setdefault(resolved[tech_num], []).insert(0, block)

            # Insert under each target heading
            for heading, blocks in move_map.items():
                for block in blocks:
                    current_lines, _ = insert_into_remembered_section(current_lines, heading, block)
                print(f"  Filed {len(blocks)} task(s) under {heading.strip()}")

            with open(filepath, "w") as f:
                f.writelines(current_lines)
        elif resolved and DRY_RUN:
            for tech_num, heading in resolved.items():
                print(f"  [dry-run] TECH-{tech_num}: file under {heading.strip()}")
        print()

    # Attach any open local task that is NOT in the current sprint list AND
    # is NOT parked for a future sprint (no `>> NN` suffix). Keeps local
    # invariant: everything present here is either current-sprint or
    # explicitly future-parked.
    print("ATTACH STALE:")
    with open(filepath) as f:
        current_lines = f.readlines()
    local_now, _ = parse_sprint_file_lines(current_lines)
    # Find Future Projects range so we skip parked tasks
    fstart, fend = _find_section_range(current_lines, "# Future Projects")
    in_future = set()
    if fstart is not None:
        for i in range(fstart + 1, fend):
            m = TASK_LINE_PATTERN.match(current_lines[i])
            if m:
                in_future.add(m.group(3) or m.group(4))

    cu_ids = {(t.get("custom_id") or "").replace("TECH-", "") for t in clickup_tasks if t.get("custom_id")}
    # Authoritative list membership (unfiltered) — source of truth for what
    # the sprint list view actually shows.
    true_list_ids = get_list_task_tech_ids(list_id)
    attached_tech_nums = set()
    drifted_tech_nums = set()

    # Candidates: open local tasks NOT authoritatively in current list, not parked
    candidates = [
        tn for tn, info in local_now.items()
        if tn not in true_list_ids
        and tn not in in_future
        and info["marker"] not in ("[x]", "[c]", "[d]")
    ]
    # Everything genuinely in the list counts as attached
    for tn in true_list_ids:
        if tn in local_now:
            attached_tech_nums.add(tn)

    remotes = get_tasks_by_tech_nums(candidates)

    # Partition: drifted (locations lies) vs needs-attach
    to_attach = []
    for tech_num in candidates:
        remote = remotes.get(tech_num)
        if not remote:
            print(f"  SKIP TECH-{tech_num}: not in ClickUp")
            continue
        remote_locs = {loc.get("id") for loc in remote.get("locations") or []}
        if list_id in remote_locs:
            # ClickUp record claims sprint membership but list view disagrees
            print(f"  DRIFT TECH-{tech_num}: secondary to Sprint {sprint_num} is stale — routing to # Drifted")
            drifted_tech_nums.add(tech_num)
            continue
        to_attach.append((tech_num, remote))

    if to_attach:
        def _attach(entry):
            tn, remote = entry
            if DRY_RUN:
                return (tn, True, None)
            res = api("POST", f"/list/{list_id}/task/{remote['id']}")
            return (tn, res is not None, None)
        with ThreadPoolExecutor(max_workers=10) as ex:
            for tn, ok, _ in ex.map(_attach, to_attach):
                if ok:
                    tag = "[dry-run] " if DRY_RUN else ""
                    print(f"  {tag}TECH-{tn}: attached to Sprint {sprint_num} list")
                    attached_tech_nums.add(tn)
                else:
                    print(f"  TECH-{tn}: attach failed")

    if not attached_tech_nums and not drifted_tech_nums:
        print("  Nothing to attach.")
    print()

    # Move drifted tasks (with children) to # Drifted section
    if drifted_tech_nums and not DRY_RUN:
        with open(filepath) as f:
            current_lines = f.readlines()
        head_idxs = []
        for i, line in enumerate(current_lines):
            m = TASK_LINE_PATTERN.match(line)
            if not m:
                continue
            tech_num = m.group(3) or m.group(4)
            if tech_num in drifted_tech_nums:
                head_idxs.append(i)
        if head_idxs:
            blocks = []
            for i in sorted(head_idxs, reverse=True):
                block, current_lines = _remove_task_block(current_lines, i)
                blocks.append(block)
            blocks.reverse()
            current_lines, d_insert = _find_drifted_insert(current_lines)
            for block in blocks:
                for bline in block:
                    current_lines.insert(d_insert, bline)
                    d_insert += 1
            with open(filepath, "w") as f:
                f.writelines(current_lines)
            print(f"  Moved {len(blocks)} drifted task(s) to # Drifted section.")
        print()

    # Promote every task attached to the current sprint list into
    # # Current Sprint. Tasks NOT in the current list stay in their
    # topical section (user-filed home).
    print("PROMOTE TO CURRENT:")
    with open(filepath) as f:
        current_lines = f.readlines()
    current_ids = {(t.get("custom_id") or "").replace("TECH-", "")
                   for t in clickup_tasks if t.get("custom_id")}
    current_ids |= attached_tech_nums  # newly-attached this run
    cs_start, cs_end = _find_section_range(current_lines, "# Current Sprint")
    moved = 0
    if cs_start is not None and current_ids:
        to_promote = []
        for i, line in enumerate(current_lines):
            if cs_start <= i < cs_end:
                continue
            m = TASK_LINE_PATTERN.match(line)
            if not m:
                continue
            tnum = m.group(3) or m.group(4)
            marker_body = m.group(2).strip()
            # Don't promote closed tasks or tasks deferred via [NN]
            # (user explicitly targeted a future sprint — leave marker alone).
            if tnum in current_ids and marker_body not in ("x", "c", "d") and not marker_body.isdigit():
                to_promote.append(i)
        if to_promote and not DRY_RUN:
            blocks = []
            for i in sorted(to_promote, reverse=True):
                block, current_lines = _remove_task_block(current_lines, i)
                blocks.append(block)
            blocks.reverse()
            current_lines, insert_idx = _find_uncategorized_insert(current_lines)
            for block in blocks:
                # Strip any stale '>> NN' suffix + reset [NN] marker on head line
                head = block[0]
                head = re.sub(r'\[\d+\]', '[ ]', head, count=1)
                head = SPRINT_OVERRIDE_RE.sub('', head.rstrip("\n")) + "\n"
                block[0] = head
                for bline in block:
                    current_lines.insert(insert_idx, bline)
                    insert_idx += 1
            with open(filepath, "w") as f:
                f.writelines(current_lines)
            moved = len(blocks)
        elif to_promote:
            for i in to_promote:
                print(f"  [dry-run] Would promote: {current_lines[i].strip()}")
            moved = len(to_promote)
    print(f"  Promoted {moved} task(s) to # Current Sprint.")
    print()

    # Sort pass: # Current Sprint by status priority; other ## sections
    # by TECH ID asc; # Future Projects by target sprint (existing logic
    # in organize_future_projects).
    print("SORT SECTIONS:")
    with open(filepath) as f:
        current_lines = f.readlines()
    current_lines = sort_sections(current_lines)
    if not DRY_RUN:
        with open(filepath, "w") as f:
            f.writelines(current_lines)
    print()

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

    # Refresh placement memory from the final file state
    if not DRY_RUN:
        with open(filepath) as f:
            final_lines = f.readlines()
        placements.update(snapshot_placements(final_lines))
        save_placements(placements)

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
