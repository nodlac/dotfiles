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
import tempfile
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import date


def atomic_write(path, content):
    """Write content (str or list of lines) atomically via tempfile + rename.
    Prevents file truncation if the script crashes mid-write."""
    if isinstance(content, list):
        content = "".join(content)
    target_dir = os.path.dirname(os.path.abspath(path)) or "."
    log(f"atomic_write: start path={path} bytes={len(content)}")
    fd, tmp = tempfile.mkstemp(prefix=".sprint-sync-", suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
        log(f"atomic_write: done path={path}")
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

# Force line-buffered stdout so live streaming (nvim jobstart / pipe) shows
# each print as it happens instead of block-buffering until exit.
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass

import datetime
_LOG_DIR = os.path.expanduser("~/notes/work_notes/sprints/.logs")
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
except Exception:
    pass
_LOG_STAMP = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
LOG_PATH = os.path.join(_LOG_DIR, f"sprint-sync.{_LOG_STAMP}.{os.getpid()}.log")
LOG_LAST = os.path.join(_LOG_DIR, "sprint-sync.last.log")
def log(msg):
    line = f"{datetime.datetime.now().isoformat(timespec='seconds')} [{os.getpid()}] {msg}\n"
    for _p in (LOG_PATH, LOG_LAST):
        try:
            with open(_p, "a") as _lf:
                _lf.write(line)
        except Exception:
            pass
# Truncate .last.log at start of each run so it always reflects newest run only.
try:
    open(LOG_LAST, "w").close()
except Exception:
    pass
log(f"=== run start argv={sys.argv} cwd={os.getcwd()} stdin_tty={sys.stdin.isatty()} ===")
log(f"=== log file: {LOG_PATH} ===")

import traceback as _tb
def _excepthook(exc_type, exc_value, exc_tb):
    log("=== UNCAUGHT EXCEPTION ===")
    for line in _tb.format_exception(exc_type, exc_value, exc_tb):
        for sub in line.rstrip().split("\n"):
            log(sub)
    sys.__excepthook__(exc_type, exc_value, exc_tb)
sys.excepthook = _excepthook

import atexit
atexit.register(lambda: log("=== run end ==="))

# Catch SIGINT (Ctrl+C) so we log where it died.
import signal
def _sigint(_sig, _frm):
    log("=== SIGINT received ===")
    raise KeyboardInterrupt
try:
    signal.signal(signal.SIGINT, _sigint)
except Exception:
    pass
# Prune old per-run logs: keep newest 20.
try:
    _logs = sorted(
        (os.path.join(_LOG_DIR, n) for n in os.listdir(_LOG_DIR)
         if n.startswith("sprint-sync.") and n.endswith(".log") and n != "sprint-sync.last.log"),
        key=os.path.getmtime,
        reverse=True,
    )
    for _old in _logs[20:]:
        os.remove(_old)
except Exception:
    pass

# --- Config ---
TOKEN = os.environ.get("CLICKUP_TOKEN")
USER_ID = os.environ.get("CLICKUP_USER_ID")
TEAM_ID = os.environ.get("CLICKUP_TEAM_ID", "14252037")
SPRINT_FOLDER_ID = "90115890584"
SPRINT_DIR = os.path.expanduser("~/notes/work_notes/sprints")
SPRINT_FILE = os.path.join(SPRINT_DIR, "sprint_tracker.md")
CLICKUP_BASE = f"https://app.clickup.com/t/{TEAM_ID}"
DRY_RUN = "--dry-run" in sys.argv
PULL_ONLY = "--pull-only" in sys.argv or (len(sys.argv) > 1 and sys.argv[1] == "pull")
VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv

# ── User-facing logger ────────────────────────────────────────────────────
# Distinct from the file-only `log()` above. Routes to stdout via stdlib
# logging. Default level = WARNING (errors + warnings + summary only).
# --verbose / -v drops to INFO so per-task updates show.
import logging as _logging

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(tag)s: %(message)s"
_logger = _logging.getLogger("sprintsync")
_logger.setLevel(_logging.INFO if VERBOSE else _logging.WARNING)
_logger.propagate = False
if not _logger.handlers:
    _h = _logging.StreamHandler(sys.stdout)
    _h.setFormatter(_logging.Formatter(_LOG_FORMAT, datefmt="%H:%M:%S"))
    _logger.addHandler(_h)


class _Out:
    """Tag-aware user-facing logger. Tags name the call site, e.g.
    'plan.status', 'execute.update', 'arrange.move'."""
    def info(self, tag, msg):    _logger.info(msg,    extra={"tag": tag})
    def warning(self, tag, msg): _logger.warning(msg, extra={"tag": tag})
    def error(self, tag, msg):   _logger.error(msg,   extra={"tag": tag})
    def summary(self, msg):
        # 1-liner, always visible regardless of level
        print(msg)


out = _Out()

# Marker <-> ClickUp status mapping
MARKER_TO_STATUS = {
    "[ ]": "to do",
    "[/]": "in progress",
    "[>]": "qa",
    "[~]": "blocked",       # stuck — pushes 'blocked' status (must exist in list)
    "[x]": "done",
    "[c]": "Closed",        # closed in ClickUp and moves to Done section locally
    "[d]": "__delete__",    # delete from ClickUp and remove line
}

STATUS_TO_MARKER = {
    "to do": "[ ]",
    "in progress": "[/]",
    "qa": "[>]",
    "blocked": "[~]",
    "done": "[x]",
}

# Sort order for # Current Sprint: urgent first, blocked last.
CURRENT_SPRINT_STATUS_ORDER = {
    "[!]": 0,
    "[>]": 1,
    "[/]": 2,
    "[ ]": 3,
    "[~]": 4,
    "[h]": 5,
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
    "BUG":       "901109915076",
    "B":         "901109915076",
    "CHORE":     "901109915070",
    "C":         "901109915070",
    "FEATURE":   "901109915057",
    "F":         "901109915057",
    "ANALYTICS": "901113670875",
    "A":         "901113670875",
}
# Pretty name for log output
NEW_TYPE_NAME = {
    "BUG": "bug",         "B": "bug",
    "CHORE": "chore",     "C": "chore",
    "FEATURE": "feature", "F": "feature",
    "ANALYTICS": "analytics", "A": "analytics",
}
# NEW_BUG / NEW_B / NEW_CHORE / NEW_C / NEW_FEATURE / NEW_F / NEW_ANALYTICS / NEW_A
# Raw "NEW " without a type is rejected (must pick a type list)
# Long aliases listed before short ones so ANALYTICS matches before A.
# Marker is optional: `- NEW_BUG x` == `- [ ] NEW_BUG x` (group 2 -> None).
NEW_TASK_PATTERN = re.compile(
    r"^(\s*-\s*)(?:\[([^\]]+)\]\s+)?NEW_(ANALYTICS|BUG|CHORE|FEATURE|A|B|C|F)\b\s+(.*)",
    re.IGNORECASE,
)
# Bare NEW (no type) — reported as error so user fixes the line
BARE_NEW_PATTERN = re.compile(
    r"^(\s*-\s*)(?:\[([^\]]+)\]\s+)?NEW(?:_\d+)?\b\s+(.*)"
)
# For tasks created but awaiting custom_id assignment
PENDING_TASK_PATTERN = re.compile(
    r"^(\s*-\s*)\[([^\]]+)\]\s+PENDING:(\w+)\s+(.*)"
)
# Matches child lines explicitly marked NEW (candidate subtasks to create)
CHILD_TASK_PATTERN = re.compile(
    r"^(\s{8,}-\s*)\[([^\]]+)\]\s+NEW\s+(.*)"
)


import time as _time


def api(method, path, body=None):
    """Make a ClickUp API request.
    Logs start + completion + duration at INFO. When --verbose, the user
    sees a live stream of API activity; if the sync hangs, the last
    'api.req start' line names the call that's stuck."""
    url = f"https://api.clickup.com/api/v2{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", TOKEN)
    req.add_header("Content-Type", "application/json")
    log(f"api: {method} {path}")
    out.info("api.req", f"start {method} {path}")
    t0 = _time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            dur_ms = int((_time.monotonic() - t0) * 1000)
            log(f"api: {method} {path} -> {resp.status} ({dur_ms}ms)")
            out.info("api.req", f"done  {method} {path} -> {resp.status} ({dur_ms}ms, {len(body)} bytes)")
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        dur_ms = int((_time.monotonic() - t0) * 1000)
        log(f"api: {method} {path} -> HTTP {e.code} ({dur_ms}ms)")
        out.error("api.http", f"{e.code} on {method} {path} ({dur_ms}ms): {e.read().decode()}")
        return None
    except Exception as e:
        dur_ms = int((_time.monotonic() - t0) * 1000)
        log(f"api: {method} {path} -> EXC {type(e).__name__}: {e} ({dur_ms}ms)")
        out.error("api.exc", f"{method} {path} ({dur_ms}ms): {type(e).__name__}: {e}")
        return None


def find_current_sprint_file():
    """The single sprint tracker file."""
    if not os.path.exists(SPRINT_FILE):
        print(f"Sprint tracker not found: {SPRINT_FILE}")
        sys.exit(1)
    return SPRINT_FILE


def get_sprint_number(filepath):
    """Current sprint number from the `sprint:` frontmatter label.
    Falls back to a sprint_NN filename for legacy files."""
    fm = read_frontmatter(filepath)
    v = fm.get("sprint")
    if v and str(v).isdigit():
        return int(v)
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
    """The single tracker file. sprint_num is ignored — the tracker's
    `sprint:` label defines the active sprint."""
    return find_current_sprint_file()


def set_frontmatter_field(fm_lines, key, value):
    """Set `key: value` inside frontmatter lines (fenced by ---).
    Updates the line in place if present, else inserts before the
    closing fence. Returns new list."""
    out = []
    replaced = False
    key_re = re.compile(rf"\s*{re.escape(key)}\s*:")
    for line in fm_lines:
        if key_re.match(line) and not replaced:
            out.append(f"{key}: {value}\n")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        for i in range(len(out) - 1, -1, -1):
            if out[i].strip() == "---":
                out.insert(i, f"{key}: {value}\n")
                break
    return out


_list_status_cache = {}


def get_list_statuses(list_id):
    """Return list of status name strings available for a ClickUp list.
    Cached per list_id — tasks across lists often share lists, and the
    per-task lookup in sync_push would otherwise re-fetch every iteration."""
    if not list_id:
        return []
    if list_id in _list_status_cache:
        return _list_status_cache[list_id]
    data = api("GET", f"/list/{list_id}")
    statuses = [s["status"] for s in (data or {}).get("statuses", [])] if data else []
    _list_status_cache[list_id] = statuses
    return statuses


def resolve_status(target, available):
    """Map a target status (e.g. 'Closed') to the actual list status string
    (e.g. 'closed (caution!)'). Case-insensitive exact first, then substring.
    Returns None when no list status matches, so the caller can skip rather
    than push an invalid status (ClickUp 400 ITEM_114)."""
    if not available:
        return target
    tl = target.lower()
    for s in available:
        if s.lower() == tl:
            return s
    for s in available:
        if tl in s.lower():
            return s
    return None


_remote_task_cache = {}
_remote_cache_primed = False


def _prime_remote_cache():
    """Seed the per-task cache from the already-fetched team task list. Without
    this the push/drift paths re-GET every TECH task individually (~80 calls,
    5-11s each — the dominant cost of a sync). Tasks not assigned to the user
    won't appear here and still fall back to an individual fetch."""
    global _remote_cache_primed
    if _remote_cache_primed:
        return
    _remote_cache_primed = True
    for t in _get_team_tasks():
        cid = (t.get("custom_id") or "").replace("TECH-", "")
        if cid and cid not in _remote_task_cache:
            _remote_task_cache[cid] = t


def get_task_by_tech_num(tech_num):
    """Look up a single task by its TECH-XXXX custom ID. Returns task dict or None.
    Results are cached per-run so repeat lookups are free."""
    if tech_num in _remote_task_cache:
        return _remote_task_cache[tech_num]
    _prime_remote_cache()
    if tech_num in _remote_task_cache:
        return _remote_task_cache[tech_num]
    data = api("GET", f"/task/TECH-{tech_num}?custom_task_ids=true&team_id={TEAM_ID}")
    result = data if data and data.get("id") else None
    _remote_task_cache[tech_num] = result
    return result


_list_tech_ids_cache = {}


def get_list_task_tech_ids(list_id):
    """Authoritative list membership — all TECH ids returned by the list
    task query (no user filter). Used to detect drift where task.locations
    says the task is in the list but the list view disagrees."""
    if list_id in _list_tech_ids_cache:
        return _list_tech_ids_cache[list_id]
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
    _list_tech_ids_cache[list_id] = ids
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


_team_tasks_cache = None
_team_tasks_lock = threading.Lock()


def _get_team_tasks():
    """All tasks (incl. subtasks, open + closed) assigned to the user across the
    team. The result is the same regardless of which list filters it, so the
    expensive paginated scan runs once per process and is reused by every
    sprint/epic pull (was previously re-fetched per list — ~25s each).
    Lock-guarded so concurrent prewarmers don't double-fetch."""
    global _team_tasks_cache
    with _team_tasks_lock:
        if _team_tasks_cache is not None:
            return _team_tasks_cache
        tasks = []
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
            tasks.extend(data["tasks"])
            if len(data["tasks"]) < 100:
                break
            page += 1
        _team_tasks_cache = tasks
        return tasks


def _fetch_list_assignee_tasks(list_id):
    """Tasks (incl. subtasks, open + closed) assigned to the user whose home
    list is list_id."""
    tasks = []
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
        tasks.extend(data["tasks"])
        if len(data["tasks"]) < 100:
            break
        page += 1
    return tasks


def get_clickup_tasks(list_id):
    """Fetch tasks (and subtasks) assigned to user from a ClickUp list.

    Includes tasks whose home list is the sprint AND tasks that have the
    sprint in their 'locations' (secondary list assignments).
    Subtasks are returned as flat items with a 'parent' field.
    """
    out.info("fetch.tasks", f"begin list={list_id}")
    t0 = _time.monotonic()

    # The home-list pull and the team-wide scan are independent network calls;
    # run them concurrently so this costs max(home, team), not their sum.
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_home = ex.submit(_fetch_list_assignee_tasks, list_id)
        f_team = ex.submit(_get_team_tasks)
        home_tasks = f_home.result()
        team_tasks = f_team.result()

    seen_ids = set()
    tasks = []
    for t in home_tasks:
        if t["id"] not in seen_ids:
            seen_ids.add(t["id"])
            tasks.append(t)
    # Add user's tasks from elsewhere that list this list in their locations.
    for t in team_tasks:
        if t["id"] in seen_ids:
            continue
        if any(loc.get("id") == list_id for loc in t.get("locations", [])):
            seen_ids.add(t["id"])
            tasks.append(t)

    out.info("fetch.tasks", f"done  list={list_id} count={len(tasks)} ({int((_time.monotonic()-t0)*1000)}ms)")
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


def _dropped_lines(before, after):
    """Content lines present in `before` but missing from `after`. Blank-line
    churn is expected from re-spacing, so only non-blank text counts."""
    from collections import Counter
    b = Counter(l.strip() for l in before if l.strip())
    a = Counter(l.strip() for l in after if l.strip())
    missing = b - a
    return [text for text, n in missing.items() for _ in range(n)]


def sort_sections(lines):
    """Sort tasks within each section.

    - # Current Sprint  → status priority: ! > > > / > ' ' > ~ > h (CURRENT_SPRINT_STATUS_ORDER)
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
                blocks.append(["task", m, block])
                i = j
            else:
                # Not a task (notes, NEW_ lines, prose). Ride along with the
                # task above so sorting can never strand it; preamble if none.
                if blocks:
                    blocks[-1][2].append(line)
                else:
                    preamble.append(line)
                i += 1

        if not blocks:
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
        task_blocks = blocks
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

        candidate = lines[:start + 1] + new_body + lines[end:]
        # Reordering must never be lossy. Bail loudly instead of writing a
        # file that quietly ate someone's notes.
        lost = _dropped_lines(lines, candidate)
        if lost:
            out.error("sort.lossy", f"refusing to sort {heading_line.strip()} — would drop {len(lost)} line(s):")
            for l in lost[:10]:
                out.error("sort.lossy", f"    {l}")
            continue

        lines = candidate
        # Recompute indices since we mutated
        heading_idxs = [i for i, l in enumerate(lines) if re.match(r"^#+\s+", l.lstrip())]
        heading_idxs.append(len(lines))

    return lines


def _task_target_sprint(line):
    """Return target sprint NN for a TECH task line, or None.
    [NN] -> int, [FF] -> float('inf') (undecided future), legacy `>> NN`."""
    m = TASK_LINE_PATTERN.match(line)
    if not m:
        return None
    marker_body = m.group(2)
    if marker_body.isdigit():
        return int(marker_body)
    if marker_body == "FF":
        return float("inf")
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
                marker_body = mnew.group(2) or ""
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

            # --- Adopt ClickUp terminal status when local is still open ---
            # Substring match catches custom variants ("closed (caution!)").
            cu_lower = cu_status.lower()
            cu_is_closed = "closed" in cu_lower
            cu_is_done = ("done" in cu_lower) and not cu_is_closed
            if (cu_is_closed or cu_is_done) and local["marker"] in ("[ ]", "[/]"):
                new_marker = "[x]" if cu_is_done else "[c]"
                if DRY_RUN:
                    print(f"  [dry-run] TECH-{tech_num}: local {local['marker']} -> {new_marker} ({cu_status} in ClickUp)")
                else:
                    lines = _update_task_marker(lines, local["line"], new_marker)
                    local["marker"] = new_marker  # keep in-memory state in sync for downstream push
                    print(f"  TECH-{tech_num}: adopted ClickUp status {cu_status} -> {new_marker}")
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
                # ClickUp says no parent, but local is indented. Two cases:
                #   (a) User just indented to express new nesting intent —
                #       push hasn't propagated yet. Leave it; PUSH PARENTS
                #       will pick it up on the same run.
                #   (b) Legacy nesting under a non-TECH or removed parent —
                #       safe to un-nest.
                # Distinguish by checking whether a real local TECH parent
                # sits above at lower indent.
                local_parent_above = None
                for other_tn, other in local_tasks.items():
                    if other["line"] < local["line"] and other["indent"] < local_indent:
                        if (local_parent_above is None
                                or other["line"] > local_tasks[local_parent_above]["line"]):
                            local_parent_above = other_tn
                if local_parent_above:
                    # User intent — defer to PUSH PARENTS.
                    out.info("pull.nest_defer",
                             f"TECH-{tech_num}: indent suggests parent TECH-{local_parent_above}, "
                             "letting PUSH PARENTS propagate")
                else:
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
    # Skip terminal-state locals — no point reconciling closed/deleted tasks
    # against ClickUp, and ClickUp may have deleted them (404 noise).
    _terminal = {"[x]", "[c]", "[d]"}
    off_list = [tn for tn, info in local_tasks.items()
                if tn not in cu_ids and info.get("marker") not in _terminal]
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
        # that PUSH hasn't flushed yet. Substring match catches custom
        # variants like "closed (caution!)" — exact match used to miss.
        cu_lower = cu_status.lower()
        cu_is_closed = "closed" in cu_lower
        cu_is_done = ("done" in cu_lower) and not cu_is_closed
        if (cu_is_closed or cu_is_done) and local["marker"] in ("[ ]", "[/]"):
            new_marker = "[x]" if cu_is_done else "[c]"
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

    # Pre-warm cache: every [NN] / [FF] task needs a remote fetch.
    # Parallelizing this is a big win when many tasks were deferred.
    deferred_tns = [
        tn for tn, info in local_tasks.items()
        if (re.fullmatch(r'\[\d+\]', info["marker"]) or info["marker"] == "[FF]")
        and tn not in cu_lookup
    ]
    if deferred_tns:
        get_tasks_by_tech_nums(deferred_tns)

    for tech_num, local in local_tasks.items():
        local_marker = local["marker"]
        # [h] hold: stays in sprint, local-only — no ClickUp push, and must not
        # fall through to the alpha-topic filing path below.
        if local_marker == "[h]":
            continue
        target_status = MARKER_TO_STATUS.get(local_marker)

        # Detect digit marker [NN] as push-to-sprint-NN, [FF] as park-future
        marker_sprint_override = None
        file_topic = None
        if target_status is None:
            mnum = re.fullmatch(r'\[(\d+)\]', local_marker)
            if mnum:
                marker_sprint_override = int(mnum.group(1))
                target_status = "__push_sprint__"
            elif local_marker == "[FF]":
                target_status = "__park_future__"
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

        if target_status == "__park_future__":
            # [FF] = future, undecided. Best-effort detach from current
            # sprint list (only succeeds if not the home list); record for
            # local relocation to # Future Projects with infinite sort key.
            if not DRY_RUN and list_id:
                if tech_num not in cu_lookup:
                    fetched = get_task_by_tech_num(tech_num)
                    if fetched:
                        cu_lookup[tech_num] = fetched
                if tech_num in cu_lookup:
                    remote_locs = {loc.get("id") for loc in cu_lookup[tech_num].get("locations") or []}
                    if list_id in remote_locs:
                        api("DELETE", f"/list/{list_id}/task/{cu_lookup[tech_num]['id']}")
            push_target_map[tech_num] = float("inf")
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
                # Target sprint's ClickUp list doesn't exist yet, but the
                # local intent is clear: park in # Future Projects.
                print(f"  TECH-{tech_num}: Sprint {target_sprint} list not yet created — parking locally only")
                push_target_map[tech_num] = target_sprint
                pushed += 1
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

            # Idempotency: if the task is already attached to target sprint
            # and not in the current sprint list, skip POST + DELETE.
            remote_locs = {loc.get("id") for loc in cu_lookup[tech_num].get("locations") or []}
            already_in_target = target_list_id in remote_locs
            still_in_current = bool(list_id) and list_id in remote_locs

            if already_in_target and not still_in_current:
                push_target_map[tech_num] = target_sprint
                pushed += 1
                continue

            if DRY_RUN:
                action = []
                if not already_in_target: action.append(f"attach to Sprint {target_sprint}")
                if still_in_current: action.append("detach from current")
                print(f"  [dry-run] TECH-{tech_num}: " + ", ".join(action))
                push_target_map[tech_num] = target_sprint
                pushed += 1
            else:
                attach_ok = already_in_target  # already there counts as success
                if not already_in_target:
                    result = api("POST", f"/list/{target_list_id}/task/{cu_lookup[tech_num]['id']}")
                    attach_ok = result is not None
                if attach_ok:
                    if still_in_current:
                        api("DELETE", f"/list/{list_id}/task/{cu_lookup[tech_num]['id']}")
                    print(f"  TECH-{tech_num}: moved to Sprint {target_sprint} ({target_list_name})")
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

        # Resolve against the task's own list — tasks pushed to other sprints
        # or sitting in type-specific lists may have different status sets
        # than the current sprint list (e.g. "closed" vs "Closed").
        task_list_id = (cu_task.get("list") or {}).get("id") or list_id
        task_statuses = get_list_statuses(task_list_id) or list_statuses
        resolved = resolve_status(target_status, task_statuses)

        if resolved is None:
            print(f"  SKIP TECH-{tech_num}: status '{target_status}' not in list "
                  f"{task_list_id} (have: {', '.join(task_statuses) or 'none'})")
            continue

        if resolved.lower() == cu_status.lower():
            continue

        # Guard: don't reopen a terminal-state task. If ClickUp has the task
        # at any "closed" or "done" variant (e.g. "closed (caution!)") and
        # the local marker would push it back to to-do/in-progress, skip
        # and warn. The user should mark it [c]/[x] locally to match.
        cu_terminal = ("closed" in cu_status.lower()) or ("done" in cu_status.lower())
        local_terminal = ("closed" in resolved.lower()) or ("done" in resolved.lower())
        if cu_terminal and not local_terminal:
            out.warning("push.reopen_guard",
                        f"TECH-{tech_num}: refusing to reopen '{cu_status}' -> '{resolved}'. "
                        f"Mark line [c] locally if you want to keep ClickUp's closed state.")
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
            else:
                print(f"  TECH-{tech_num}: PUT status '{resolved}' failed "
                      f"(list {task_list_id}, available: {', '.join(task_statuses) or 'none'})")

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


def delete_testing_checklist(taskid):
    """Remove a task's testing checklist(s). Matches both the current
    TECH_####_* underscore convention and legacy TECH-####-* hyphen names."""
    if not taskid:
        return []
    d = os.path.expanduser("~/notes/work_notes/testing-checklists")
    removed, seen = [], set()
    for pat in (f"{taskid.replace('-', '_')}*.md", f"{taskid}*.md"):
        for p in glob.glob(os.path.join(d, pat)):
            if p in seen:
                continue
            seen.add(p)
            try:
                os.remove(p)
                removed.append(os.path.basename(p))
            except OSError:
                pass
    return removed


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

        # Task done → its testing checklist is obsolete; remove it.
        removed = delete_testing_checklist(tech)
        if removed:
            print(f"  Deleted testing checklist: {', '.join(removed)}")

        print(f"  Marked '{sess}' done.")


def sync_create(filepath, lines, clickup_tasks=None):
    """Create tasks in ClickUp for NEW_<type> lines. Type selects home list
    (bug/chore/feature).
      [ ] NEW_<type>  → attach to current sprint list; line stays in place
      NEW_<type>      → same as [ ] (marker optional)
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
    future_line_idxs = []   # indices of [NN]/[FF] lines → # Future Projects
    current_line_idxs = []  # indices of PENDING [ ] lines → # Current Sprint
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
        marker_body = m.group(2) or " "  # markerless line == to-do
        marker = f"[{marker_body}]"
        type_key = m.group(3).upper()
        title = m.group(4).strip()

        if not title:
            continue

        type_list_id = NEW_TYPE_LIST[type_key]
        indent_clean = indent.rstrip("- ") or "    "

        # Marker [NN] → digit = target sprint. [FF] → park, no attach.
        # Otherwise marker → status (and attach to current sprint).
        target_sprint = None
        park_future = False
        if marker_body.isdigit():
            target_sprint = int(marker_body)
            if current_sprint is not None and target_sprint <= current_sprint:
                print(f"  ERROR line {i+1}: [{target_sprint}] must be > current sprint {current_sprint}")
                continue
            target_status = "to do"
        elif marker_body == "FF":
            park_future = True
            target_status = "to do"
        else:
            target_status = MARKER_TO_STATUS.get(marker, "to do")

        # Decide which sprint list to attach as secondary
        attach_list_id, attach_list_name = None, None
        if not park_future:
            attach_sprint = target_sprint if target_sprint is not None else current_sprint
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
            if target_sprint is not None or park_future:
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
        elif park_future:
            attached_msg = " (parked, no sprint)"
        elif not park_future and attach_list_id is None:
            # only warn for non-park flows when sprint list lookup failed
            attach_sprint = target_sprint if target_sprint is not None else current_sprint
            if attach_sprint is not None:
                print(f"  WARN: Sprint {attach_sprint} list missing — created but not attached")

        if custom_id:
            tech_num = custom_id.replace("TECH-", "")
            lines[i] = format_task_line(tech_num, marker, title, indent_clean)
            print(f"  Created TECH-{tech_num} ({NEW_TYPE_NAME[type_key]}): {title}{attached_msg}")
            if target_sprint is not None or park_future:
                future_line_idxs.append(i)
            created += 1
        else:
            lines[i] = format_pending_line(task_id, marker, title, indent_clean)
            print(f"  WARNING: created ({NEW_TYPE_NAME[type_key]}) but no custom ID yet: {title}")
            print(f"           Saved as PENDING:{task_id} — will resolve on next sync.")
            if target_sprint is not None or park_future:
                future_line_idxs.append(i)
            else:
                current_line_idxs.append(i)
            created += 1

    # Relocate [NN]/[FF] new creations to # Future Projects (with children)
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
        print(f"  Moved {len(blocks)} new [NN]/[FF] task(s) to # Future Projects.")

    # Relocate plain PENDING creations to # Current Sprint so the user
    # sees newly-created (id-pending) tasks in the active bucket.
    if current_line_idxs and not DRY_RUN:
        blocks = []
        for i in sorted(current_line_idxs, reverse=True):
            block, lines = _remove_task_block(lines, i)
            blocks.append(block)
        blocks.reverse()
        lines, cs_insert = _find_uncategorized_insert(lines)
        for block in blocks:
            for bline in block:
                lines.insert(cs_insert, bline)
                cs_insert += 1
        print(f"  Moved {len(blocks)} PENDING task(s) to # Current Sprint.")

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


def sprint_rollover(to_num=None, to_list_id=None):
    """Roll the single tracker forward to sprint `to_num`, in place.

    - Strips completed [x] tasks + sub-items and empty sections
    - Skips # Done and # Uncategorized Tasks sections
    - Updates the frontmatter `sprint:` label and `clickup_list_id:`
    - Moves uncompleted TECH tasks to the new sprint list in ClickUp

    to_list_id is captured before the frontmatter is rewritten so the
    ClickUp migration knows the source list.
    """
    path = find_current_sprint_file()
    from_num = get_sprint_number(path)
    from_list_id = get_clickup_list_id(path)

    if to_num is None:
        to_num = (from_num or 0) + 1
    if to_list_id is None:
        to_list_id, _ = find_clickup_sprint_list(to_num)
        if not to_list_id:
            print(f"No ClickUp list found for Sprint {to_num}.")
            sys.exit(1)

    print(f"Rolling over: sprint {from_num} -> sprint {to_num} (in {os.path.basename(path)})")

    with open(path, "r") as f:
        lines = f.readlines()

    fm, body = strip_frontmatter(lines)

    filtered = filter_completed(body)
    filtered = remove_empty_sections(filtered)

    while filtered and filtered[0].strip() == "":
        filtered.pop(0)
    while filtered and filtered[-1].strip() == "":
        filtered.pop()

    fm = set_frontmatter_field(fm, "sprint", str(to_num))
    fm = set_frontmatter_field(fm, "clickup_list_id", f'"{to_list_id}"')

    result = fm + ["\n"] + filtered + ["\n"] + ["\n", "# Done\n"]

    if DRY_RUN:
        print("  [dry-run] Would rewrite tracker for the new sprint.")
        sections = [l.strip() for l in filtered if SECTION_HEADER.match(l)]
        print(f"  Sections: {', '.join(sections)}")
        task_count = sum(1 for l in filtered if TASK_MARKER.match(l))
        done_in_source = sum(1 for l in body if DONE_MARKER.match(l))
        print(f"  Tasks carried over: {task_count} (stripped {done_in_source} completed)")
    else:
        atomic_write(path, result)
        task_count = sum(1 for l in filtered if TASK_MARKER.match(l))
        done_in_source = sum(1 for l in body if DONE_MARKER.match(l))
        print(f"  Carried over {task_count} tasks (stripped {done_in_source} completed)")
        sections = [l.strip() for l in filtered if SECTION_HEADER.match(l)]
        for s in sections:
            print(f"    {s}")

    # Move uncompleted tasks from old ClickUp sprint to new one
    if from_list_id and to_list_id and from_list_id != to_list_id:
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


def sprint_new(sprint_num=None):
    """Advance the single sprint tracker to a new ClickUp sprint.

    No new file is created — the tracker's `sprint:` label is updated and
    its body is rolled forward in place.

    1. Pushes pending status changes from the current sprint
    2. Lists available ClickUp sprint lists, picks target (prompt or argv)
    3. Rolls the tracker forward (strip done, reset frontmatter, reset # Done)
    4. Migrates uncompleted ClickUp tasks to the new list
    5. Runs sync to pull in the new sprint's tasks
    """
    path = find_current_sprint_file()
    current_num = get_sprint_number(path)

    # Push any pending status changes from the current sprint first
    current_list_id = get_clickup_list_id(path)
    if current_list_id:
        print(f"Pushing status changes from sprint {current_num}...")
        current_tasks_cu = get_clickup_tasks(current_list_id)
        current_tasks_local, _ = parse_sprint_file(path)
        sync_push(current_tasks_local, current_tasks_cu)
        print()

    data = api("GET", f"/folder/{SPRINT_FOLDER_ID}/list")
    if not data:
        print("Error: Could not fetch sprint lists.")
        sys.exit(1)

    sprint_lists = []
    for lst in data.get("lists", []):
        m_name = re.match(r"Sprint\s+(\d+)", lst["name"])
        if m_name:
            sprint_lists.append((int(m_name.group(1)), lst["id"], lst["name"]))
    sprint_lists.sort()

    print("Available ClickUp sprint lists:")
    for num, lid, name in sprint_lists:
        marker = " (current)" if num == current_num else ""
        print(f"  {num}: {name}{marker}")

    print()
    default_num = current_num + 1 if current_num is not None else None
    if sprint_num is None:
        if default_num is None:
            out.error("sprint_new.default", "Tracker has no current sprint number — "
                      "pass the target on argv: `sprint-sync new <num>`.")
            sys.exit(1)
        if not sys.stdin.isatty():
            log(f"sprint_new: non-tty, defaulting to {default_num}")
            sprint_num = default_num
        else:
            log("sprint_new: prompting for sprint number")
            sys.stdout.write(f"Sprint number to advance to [{default_num}]: ")
            sys.stdout.flush()
            choice = input().strip()
            log(f"sprint_new: got choice={choice!r}")
            if not choice:
                sprint_num = default_num
                log(f"sprint_new: empty input, defaulting to {default_num}")
            elif not choice.isdigit():
                log("sprint_new: choice not digit, exiting")
                print("Invalid sprint number.")
                sys.exit(1)
            else:
                sprint_num = int(choice)
    else:
        log(f"sprint_new: sprint_num passed via argv={sprint_num}")

    if sprint_num == current_num:
        print(f"Tracker is already on sprint {sprint_num}.")
        sys.exit(1)

    list_id = None
    for num, lid, name in sprint_lists:
        if num == sprint_num:
            list_id = lid
            break
    if not list_id:
        print(f"No ClickUp list found for Sprint {sprint_num}.")
        sys.exit(1)

    print()
    log(f"sprint_new: rollover {current_num} -> {sprint_num}")
    sprint_rollover(sprint_num, list_id)
    log("sprint_new: rollover done")

    print()
    print("Running sync...")
    log("sprint_new: calling main()")
    main()
    log("sprint_new: main() returned")


# ── Epic sync (pull-only) ──────────────────────────────────────────────────
# Mirrors selected ClickUp lists ("epics") into standalone markdown files under
# ~/notes/work_notes/epics/. Pull-only: status reflects ClickUp; local edits are
# never pushed back. Only tasks assigned to the user are pulled. Configure the
# lists in ~/.config/sprint-sync/epics.json: {"lists": [{"id": "...", "name": "..."}]}
EPICS_CONFIG = os.path.expanduser("~/.config/sprint-sync/epics.json")
EPICS_DIR = os.path.join(os.path.dirname(SPRINT_DIR), "epics")

EPIC_FILE_TEMPLATE = """---
id: epic_{slug}
aliases: []
tags:
  - epics
clickup_list_id: "{list_id}"
epic: "{name}"
---

<!-- Pull-only mirror of ClickUp list "{name}". Status reflects ClickUp; local edits are NOT pushed back.
Markers:  [ ] todo  [/] in progress  [>] qa  [~] blocked  [x] done  [c] closed -->

# Tasks
"""


def _epic_slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "epic"


def _epic_status_marker(cu_status):
    """Map a ClickUp status to a local marker for the pull-only mirror."""
    s = (cu_status or "").lower()
    if "closed" in s:
        return "[c]"
    if "done" in s:
        return "[x]"
    return STATUS_TO_MARKER.get(s, "[ ]")


def load_epics():
    """Read epic list config. Returns list of {id, name} dicts (possibly empty)."""
    try:
        with open(EPICS_CONFIG) as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        out.error("epics.config", f"could not read {EPICS_CONFIG}: {e}")
        return []
    return [l for l in data.get("lists", []) if l.get("id")]


def _ensure_epic_file(path, list_id, name):
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write(path, EPIC_FILE_TEMPLATE.format(
        slug=_epic_slug(name), list_id=list_id, name=name))
    out.info("epics.create", f"created {os.path.basename(path)}")


def _epic_tasks_insert(lines):
    """Return (lines, insert_idx) for the '# Tasks' section, creating it if absent."""
    for i, line in enumerate(lines):
        if line.strip() == "# Tasks":
            return lines, i + 1
    if lines and lines[-1].strip():
        lines.append("\n")
    lines.append("# Tasks\n")
    return lines, len(lines)


def sync_one_epic(epic):
    """Pull-only mirror of a single epic list into its markdown file.

    New tasks are added under '# Tasks'; existing tasks have their title and
    marker refreshed from ClickUp in place (preserving any local note bullets).
    """
    list_id = epic["id"]
    name = epic.get("name") or list_id
    path = os.path.join(EPICS_DIR, f"{_epic_slug(name)}.md")
    _ensure_epic_file(path, list_id, name)

    tasks = get_clickup_tasks(list_id)  # assignee-filtered (mine only)
    with open(path) as f:
        lines = f.readlines()
    local_tasks, lines = parse_sprint_file_lines(lines)

    new_lines = []
    updated = 0
    for t in tasks:
        cid = t.get("custom_id")
        if not cid:
            continue
        tech = cid.replace("TECH-", "")
        cu_title = t["name"]
        marker = _epic_status_marker((t.get("status") or {}).get("status"))
        if tech in local_tasks:
            local = local_tasks[tech]
            if cu_title and cu_title != local["title"]:
                lines = _update_task_title(lines, local["line"], cu_title)
                updated += 1
            if local["marker"] != marker:
                lines = _update_task_marker(lines, local["line"], marker)
                updated += 1
        else:
            new_lines.append(format_task_line(tech, marker, cu_title))

    if new_lines:
        lines, idx = _epic_tasks_insert(lines)
        for nl in new_lines:
            lines.insert(idx, nl)
            idx += 1

    if DRY_RUN:
        print(f"  [dry-run] {name}: {len(new_lines)} new, {updated} updated")
    else:
        atomic_write(path, lines)
        out.summary(f"  {name}: {len(new_lines)} new, {updated} updated ({os.path.basename(path)})")
    return path, len(new_lines), updated


def _commit_stamp():
    """Local date+time for commit subjects — several syncs a day, date alone collides."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _git_commit_dir(target_dir, label):
    """Stage + commit + push a single directory. Silent if clean / no git."""
    import subprocess
    if not os.path.isdir(target_dir):
        return
    try:
        top = subprocess.check_output(
            ["git", "-C", target_dir, "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return  # not a git repo
    rel = os.path.relpath(target_dir, top)
    subprocess.run(["git", "-C", top, "add", rel], stderr=subprocess.DEVNULL)
    if subprocess.run(["git", "-C", top, "diff", "--cached", "--quiet"]).returncode == 0:
        return  # nothing staged
    msg = f"sprint-sync: {label} ({_commit_stamp()})"
    r = subprocess.run(["git", "-C", top, "commit", "-m", msg],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        print(f"  Commit failed:\n{r.stdout.strip()}")
        return
    print(f"  Committed: {msg}")
    p = subprocess.run(["git", "-C", top, "push"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    print("  Pushed." if p.returncode == 0 else
          f"  Push failed (commit kept locally):\n{p.stdout.strip()}")


def sync_epics():
    """Pull-only sync of all configured epic lists into ~/notes/work_notes/epics/."""
    epics = load_epics()
    if not epics:
        out.info("epics", f"no epics configured (see {EPICS_CONFIG})")
        return
    out.info("epics", f"syncing {len(epics)} epic(s)")
    touched = False
    for epic in epics:
        try:
            sync_one_epic(epic)
            touched = True
        except Exception as e:
            out.error("epics.sync", f"{epic.get('name', epic.get('id'))}: {e}")
    if touched and not DRY_RUN:
        _git_commit_dir(EPICS_DIR, "epics")


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

    # Fetch ClickUp tasks. The no-assignee list scan (used later for drift
    # detection) is independent, so warm its cache concurrently here.
    with ThreadPoolExecutor(max_workers=2) as _ex:
        _f_tasks = _ex.submit(get_clickup_tasks, list_id)
        _ex.submit(get_list_task_tech_ids, list_id)
        clickup_tasks = _f_tasks.result()
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
    out.info("phase.pending", "begin")
    lines = sync_resolve_pending(lines)
    print()
    if not DRY_RUN:
        atomic_write(filepath, lines)

    # Park deferred NEW_XX tasks under # Future Projects
    out.info("phase.organize_future", "begin")
    lines = organize_future_projects(lines, current_sprint=sprint_num)
    print()
    if not DRY_RUN:
        atomic_write(filepath, lines)

    # Create NEW tasks (matured NEW_XX get their TECH line in place, which
    # is inside # Future Projects — the next organize pass promotes them)
    if not PULL_ONLY:
        out.info("phase.create", "begin")
        lines = sync_create(filepath, lines, clickup_tasks)
        print()

    # Promote any matured TECH lines out of # Future Projects
    lines = organize_future_projects(lines, current_sprint=sprint_num)

    # Re-parse after creation (line numbers may have shifted)
    if not DRY_RUN:
        atomic_write(filepath, lines)
    local_tasks, lines = parse_sprint_file(filepath)

    # Pull new tasks
    out.info("phase.pull", "begin")
    lines = sync_pull(filepath, clickup_tasks, local_tasks, lines, placements=placements)
    print()

    # Create subtasks for child lines without IDs
    if not PULL_ONLY:
        out.info("phase.create_subtasks", "begin")
        lines = sync_create_subtasks(lines, clickup_tasks)
        print()

    # Write updated file
    if DRY_RUN:
        print("  [dry-run] Would write changes to sprint file.")
    else:
        atomic_write(filepath, lines)

    # Re-parse after subtask creation
    local_tasks, lines = parse_sprint_file(filepath)

    # Push status changes
    if PULL_ONLY:
        done_tech_ids, deleted_tech_nums, pushed_next_tech_nums = [], [], []
        push_target_map, file_to_section_map, failed_move_tech_nums = {}, {}, set()
    else:
        out.info("phase.push", "begin")
        done_tech_ids, deleted_tech_nums, pushed_next_tech_nums, push_target_map, file_to_section_map, failed_move_tech_nums = sync_push(
            local_tasks, clickup_tasks, current_sprint_num=sprint_num, list_id=list_id
        )
        print()

        # Push parent/nesting changes
        out.info("phase.push_parents", "begin")
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
        atomic_write(filepath, kept)

    # [NN]-marked lines were attached to that sprint's list. Keep the
    # [NN] marker (organize_future_projects sorts by it). If the line
    # currently sits inside # Current Sprint and NN > current sprint,
    # relocate it to # Future Projects.
    if push_target_map and not DRY_RUN:
        with open(filepath) as f:
            current_lines = f.readlines()
        relocated = 0
        # Scope: only sync-managed sections — # Current Sprint, # Drifted,
        # # Failed to Move. Tasks already filed in user topic sections stay
        # there; placement memory will restore them on promotion.
        scope_ranges = []
        for h in ("# Current Sprint", "# Drifted", "# Failed to Move"):
            s, e = _find_section_range(current_lines, h)
            if s is not None:
                scope_ranges.append((s, e))
        def _in_scope(i):
            return any(s <= i < e for s, e in scope_ranges)

        to_move_idxs = []
        for i, line in enumerate(current_lines):
            if not _in_scope(i):
                continue
            m = TASK_LINE_PATTERN.match(line)
            if not m:
                continue
            tech_num = m.group(3) or m.group(4)
            if tech_num not in push_target_map:
                continue
            target_sprint = push_target_map[tech_num]
            if sprint_num is None or target_sprint > sprint_num:
                to_move_idxs.append(i)
        if to_move_idxs:
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
            atomic_write(filepath, current_lines)
            print(f"  Moved {relocated} [NN]-marked task(s) to # Future Projects.")

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
            atomic_write(filepath, current_lines)
            print(f"  Moved {len(blocks)} task(s) to # Failed to Move (home list is current sprint).")

    # File alpha-topic-marker lines into matching section inside sprint file
    if file_to_section_map:
        out.info("phase.file", "begin")
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

            atomic_write(filepath, current_lines)
        elif resolved and DRY_RUN:
            for tech_num, heading in resolved.items():
                print(f"  [dry-run] TECH-{tech_num}: file under {heading.strip()}")
        print()

    # Attach any open local task that is NOT in the current sprint list AND
    # is NOT parked for a future sprint (no `>> NN` suffix). Keeps local
    # invariant: everything present here is either current-sprint or
    # explicitly future-parked.
    out.info("phase.attach_stale", "begin")
    with open(filepath) as f:
        current_lines = f.readlines()
    local_now, _ = parse_sprint_file_lines(current_lines)
    # Skip tasks the user deliberately parked: # Future Projects and
    # # Failed to Move. # Drifted is intentionally NOT skipped — drifted tasks
    # are re-checked each run so they can heal (the partition below trusts the
    # per-task locations record, so a real sprint task won't re-drift).
    in_parked = set()
    for heading in ("# Future Projects", "# Failed to Move"):
        s, e = _find_section_range(current_lines, heading)
        if s is None:
            continue
        for i in range(s + 1, e):
            m = TASK_LINE_PATTERN.match(current_lines[i])
            if m:
                in_parked.add(m.group(3) or m.group(4))

    cu_ids = {(t.get("custom_id") or "").replace("TECH-", "") for t in clickup_tasks if t.get("custom_id")}
    # Authoritative list membership (unfiltered) — source of truth for what
    # the sprint list view actually shows.
    true_list_ids = get_list_task_tech_ids(list_id)
    attached_tech_nums = set()
    drifted_tech_nums = set()

    # Candidates: open local tasks NOT authoritatively in current list,
    # not parked in Future Projects, and NOT explicitly deferred via
    # [NN] / [FF] — those belong to a future sprint, not this one.
    def _is_future_marker(mk):
        return bool(re.fullmatch(r'\[\d+\]', mk)) or mk == "[FF]"
    candidates = [
        tn for tn, info in local_now.items()
        if tn not in true_list_ids
        and tn not in in_parked
        and info["marker"] not in ("[x]", "[c]", "[d]")
        and not _is_future_marker(info["marker"])
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
            # The task's own record places it in this sprint — authoritative.
            # The team scan (cu_ids) and list view are both incomplete (they
            # silently omit some tasks), so trust the per-task locations rather
            # than banishing real work to # Drifted. Warn when the scan missed
            # it so the inconsistency stays visible.
            attached_tech_nums.add(tech_num)
            if tech_num not in cu_ids:
                out.warning("attach.scan_miss",
                            f"TECH-{tech_num}: in sprint per task record but missing "
                            f"from team scan/list view — treating as attached.")
            continue
        to_attach.append((tech_num, remote))

    if to_attach and not PULL_ONLY:
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
    elif to_attach and PULL_ONLY:
        for tn, _ in to_attach:
            print(f"  [pull-only] TECH-{tn}: would attach (skipped)")

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
            atomic_write(filepath, current_lines)
            print(f"  Moved {len(blocks)} drifted task(s) to # Drifted section.")
        print()

    # Promote every task attached to the current sprint list into
    # # Current Sprint. Tasks NOT in the current list stay in their
    # topical section (user-filed home).
    out.info("phase.promote", "begin")
    with open(filepath) as f:
        current_lines = f.readlines()
    current_ids = {(t.get("custom_id") or "").replace("TECH-", "")
                   for t in clickup_tasks if t.get("custom_id")}
    current_ids |= attached_tech_nums  # newly-attached this run
    cs_start, cs_end = _find_section_range(current_lines, "# Current Sprint")
    # Sticky destinations: don't promote tasks back out of these — the user
    # (or sync) put them there deliberately, and promoting them creates a
    # bounce loop with ATTACH STALE on the next run.
    sticky_ranges = []
    for h in ("# Drifted", "# Failed to Move"):
        s, e = _find_section_range(current_lines, h)
        if s is not None:
            sticky_ranges.append((s, e))

    def _in_sticky(idx):
        return any(s <= idx < e for s, e in sticky_ranges)

    # Let # Drifted tasks through to the current_ids gate below: a drifted
    # task that's now back in the assignee-filtered sprint fetch (current_ids)
    # has healed and should promote out. A still-drifting task isn't in
    # current_ids, so the gate leaves it. It won't bounce — once it's in
    # current_ids the attach phase treats it as attached, not drift.
    # (# Failed to Move stays sticky.) Note: true_list_ids is NOT used here —
    # ClickUp's list-view index is unreliable in this workspace.
    drifted_s, drifted_e = _find_section_range(current_lines, "# Drifted")

    def _in_drifted(idx):
        return drifted_s is not None and drifted_s <= idx < drifted_e

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
            if _in_sticky(i) and not _in_drifted(i):
                continue
            # Don't promote closed tasks or tasks deferred via [NN] / [FF]
            # (user explicitly targeted a future sprint — leave marker alone).
            if (tnum in current_ids
                    and marker_body not in ("x", "c", "d", "FF")
                    and not marker_body.isdigit()):
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
            atomic_write(filepath, current_lines)
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
        atomic_write(filepath, current_lines)
    print()

    # Move done items to # Done section
    out.info("phase.move_done", "begin")
    with open(filepath) as f:
        current_lines = f.readlines()
    current_lines = move_done_to_done_section(current_lines)
    if not DRY_RUN:
        atomic_write(filepath, current_lines)
    print()

    # Hold items: surface every sync so parked work gets a deliberate decision.
    cs_s, cs_e = _find_section_range(current_lines, "# Current Sprint")
    if cs_s is not None:
        holds = [current_lines[i].strip()
                 for i in range(cs_s + 1, cs_e)
                 if (m := TASK_LINE_PATTERN.match(current_lines[i])) and m.group(2) == "h"]
        if holds:
            print(f"HOLD ITEMS ({len(holds)}) — decide each: keep [h], reactivate [ ]/[/], or defer [NN]/[FF]:")
            for h in holds:
                print(f"  {h}")
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

    if not DRY_RUN:
        commit_and_push_notes(filepath)

    out.summary("Sync complete.")


def commit_and_push_notes(filepath):
    """Stage the whole notes repo, commit if dirty, push to origin.
    Silent if nothing changed or git isn't reachable."""
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(filepath)))  # ~/notes/work_notes -> ~/notes
    # Find the git toplevel — handle non-standard layouts too
    try:
        top = subprocess.check_output(
            ["git", "-C", repo, "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return  # not a git repo, skip silently

    out.info("phase.git", "begin")
    # Stage the whole repo: sprint files, .placements.json, and any other
    # notes edited alongside the sync (checklists, to-dos, epic notes).
    subprocess.run(["git", "-C", top, "add", "-A", top],
                   stderr=subprocess.DEVNULL)
    # Nothing to commit?
    diff = subprocess.run(["git", "-C", top, "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        print("  Nothing to commit.")
        return

    staged = subprocess.run(["git", "-C", top, "diff", "--cached", "--name-only"],
                            stdout=subprocess.PIPE, text=True).stdout.split()
    for f in staged:
        print(f"    {f}")

    sprint_num = get_sprint_number(filepath)
    label = f"sprint {sprint_num}" if sprint_num else os.path.basename(filepath).removesuffix(".md")
    msg = f"sprint-sync: {label} ({_commit_stamp()})"
    r = subprocess.run(["git", "-C", top, "commit", "-m", msg],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        print(f"  Commit failed:\n{r.stdout.strip()}")
        return
    print(f"  Committed: {msg}")
    p = subprocess.run(["git", "-C", top, "push"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode == 0:
        print("  Pushed.")
    else:
        print(f"  Push failed (commit kept locally):\n{p.stdout.strip()}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a not in ("--dry-run", "--pull-only", "pull", "--verbose", "-v")]

    if not TOKEN:
        print("Error: CLICKUP_TOKEN not set. Add it to ~/.env")
        sys.exit(1)

    if args and args[0] == "epics":
        log("entry: sync_epics")
        sync_epics()
        log("entry: sync_epics done")
    elif args and args[0] == "rollover":
        to_num = int(args[1]) if len(args) > 1 else None
        log(f"entry: rollover to={to_num}")
        sprint_rollover(to_num)
        if not DRY_RUN:
            commit_and_push_notes(find_current_sprint_file())
        log("entry: rollover done")
    elif args and args[0] == "new":
        new_num = None
        if len(args) > 1 and args[1].isdigit():
            new_num = int(args[1])
        log(f"entry: sprint_new num={new_num}")
        sprint_new(new_num)
        log("entry: sprint_new done")
    else:
        # Optional sprint number: sprint-sync [--dry-run] [26]
        target_num = None
        for a in args:
            if a.isdigit():
                target_num = int(a)
                break
        log(f"entry: main target={target_num}")
        main(target_num)
        log("entry: main done")
