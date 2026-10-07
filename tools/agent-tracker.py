#!/usr/bin/env python3
"""agent-tracker — sprint_tracker.md side of the agent loop.

  stale [DAYS]              [/] tasks in # Current Sprint added >= DAYS ago (default 7), no open agent
  block TECH-N              print the task line + its notes
  claim TECH-N SESSION      move the block to # Agent Work, tag it with the session
  alert TECH-N MSG          add/replace the 🔔 line under the task
  clear TECH-N              drop the 🔔 line
  release TECH-N            drop agent lines; if in # Agent Work, move back to # Current Sprint

# Agent Work must stay in sprint-sync's sticky list, or sync promotes these
# tasks straight back into # Current Sprint.
"""
import csv, os, re, sys, tempfile
from datetime import date

TRACKER = os.path.expanduser(os.environ.get(
    "SPRINT_TRACKER", "~/notes/work_notes/sprints/sprint_tracker.md"))
AGENT_FILE = os.path.expanduser(os.environ.get("AGENT_FILE", "~/.agents/agents.csv"))
AGENT_WORK, CURRENT = "# Agent Work", "# Current Sprint"
BOT, BELL = "🤖", "🔔"
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*$")


def read():
    with open(TRACKER) as f:
        return f.readlines()


def write(lines):
    # ponytail: no lock vs a concurrent sprint-sync run; add flock if it ever collides
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(TRACKER), prefix=".agent-tracker-")
    with os.fdopen(fd, "w") as f:
        f.writelines(lines)
    os.replace(tmp, TRACKER)


def indent(line):
    return len(line) - len(line.lstrip())


def section(lines, heading):
    for i, l in enumerate(lines):
        if l.rstrip() == heading:
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("# "):
                    return i, j
            return i, len(lines)
    return None, None


def find_task(lines, tech):
    pat = re.compile(rf"^\s*-\s*\[[^\]]+\]\s+\[?{re.escape(tech)}\b")
    return next((i for i, l in enumerate(lines) if pat.match(l)), None)


def block_end(lines, i):
    """End of task i's block: children are deeper-indented; trailing blanks excluded."""
    j, last = i + 1, i + 1
    while j < len(lines) and not lines[j].startswith("#"):
        if lines[j].strip():
            if indent(lines[j]) <= indent(lines[i]):
                break
            last = j + 1
        j += 1
    return last


def need_task(lines, tech):
    i = find_task(lines, tech)
    if i is None:
        sys.exit(f"{tech} not found in {TRACKER}")
    return i


def drop_marked(lines, i, marks):
    end = block_end(lines, i)
    kept = [l for l in lines[i + 1:end]
            if not any(l.lstrip().startswith(f"- {m}") for m in marks)]
    return lines[:i + 1] + kept + lines[end:]


def child(lines, i, text):
    return " " * (indent(lines[i]) + 4) + f"- {text}\n"


def move_block(lines, i, heading, create_before=None):
    end = block_end(lines, i)
    blk = lines[i:end]
    del lines[i:end]
    s, e = section(lines, heading)
    if s is None:
        at = section(lines, create_before)[0] if create_before else len(lines)
        lines[at:at] = [f"{heading}\n", "\n"]
        s, e = section(lines, heading)
    while e > s + 1 and not lines[e - 1].strip():
        e -= 1
    lines[e:e] = blk
    after = e + len(blk)
    if after < len(lines) and lines[after].strip():
        lines.insert(after, "\n")
    return lines


def open_task_ids():
    try:
        with open(AGENT_FILE) as f:
            return {r.get("TaskID", "") for r in csv.DictReader(f) if r.get("Status") != "done"}
    except FileNotFoundError:
        return set()


def stale(days=7):
    lines, busy, today = read(), open_task_ids(), date.today()
    s, e = section(lines, CURRENT)
    if s is None:
        return
    for l in lines[s + 1:e]:
        m = re.match(r"^\s{4}-\s*\[/\]\s+(TECH-\d+)\s+(.*)$", l.rstrip())
        if not m or m.group(1) in busy:
            continue
        tech, rest = m.groups()
        d = DATE_RE.search(rest)
        age = (today - date.fromisoformat(d.group(1))).days if d else 999
        if age >= days:
            title = re.sub(r"\s*\[link\]\([^)]*\)", "", DATE_RE.sub("", rest)).strip()
            print(f"{tech}\t{age}d\t{title}")


def main():
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "stale":
        return stale(int(args[0]) if args else 7)
    if cmd not in ("block", "claim", "alert", "clear", "release") or not args:
        sys.exit(__doc__)
    tech, lines = args[0].upper(), read()
    i = need_task(lines, tech)
    if cmd == "block":
        return print("".join(lines[i:block_end(lines, i)]), end="")
    if cmd == "claim":
        lines = drop_marked(lines, i, (BOT, BELL))
        lines.insert(i + 1, child(lines, i, f"{BOT} auto agent `{args[1]}` started {date.today()}"))
        lines = move_block(lines, i, AGENT_WORK, create_before=CURRENT)
    elif cmd == "alert":
        msg = " ".join(args[1:]).splitlines()[0][:160] if args[1:] else "needs review"
        lines = drop_marked(lines, i, (BELL,))
        lines.insert(i + 1, child(lines, i, f"{BELL} {date.today()} {msg}"))
    elif cmd == "clear":
        lines = drop_marked(lines, i, (BELL,))
    elif cmd == "release":
        lines = drop_marked(lines, i, (BOT, BELL))
        s, e = section(lines, AGENT_WORK)
        if s is not None and s < i < e:
            lines = move_block(lines, i, CURRENT)
    write(lines)


if __name__ == "__main__":
    main()
