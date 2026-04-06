#!/usr/bin/env python3
"""
agent-dashboard — terminal dashboard for reviewing AI agents
"""
import curses
import csv
import subprocess
import re
import os
import time
import tempfile
from datetime import datetime

AGENT_FILE = os.path.expanduser("~/notes/work_notes/sprints/agents.csv")
AGENT_LOG  = os.path.expanduser("~/notes/work_notes/sprints/agent-log.md")
EXCLUDED   = re.compile(r'^(aa-|control-center|settings|notes)$')
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[mGKHFABCDsuJh]|\x1b\(B|\x1b=|\r')
REFRESH_INTERVAL = 30  # seconds

# Layout
HEADER_LINES = 2
FOOTER_LINES = 1
DIVIDER_LINE = 1

# Column widths
W_STATUS  = 8
W_TYPE    = 16
W_SESSION = 28
W_CLICKUP = 11

# Color pair indices
C_ACTIVE   = 1
C_BLOCKED  = 2
C_STALE    = 3
C_DONE     = 4
C_HEADER   = 5
C_SELECTED = 6
C_BAR      = 7
C_PREVIEW  = 8
C_REVIEW   = 9
C_TESTING  = 10

STATUS_ORDER  = {'active': 0, 'review': 1, 'testing': 2, 'blocked': 3, 'stale': 4, 'done': 5}
STATUS_MARKER = {'active': '*', 'review': 'R', 'testing': 'T', 'blocked': '!', 'stale': '?', 'done': 'd'}
COLOR_MAP = None  # initialized after curses.start_color()


# ── CSV helpers ──────────────────────────────────────────────────────────────

def _rewrite_csv(transform):
    """Read agents.csv, apply transform(rows) -> rows, write back."""
    with open(AGENT_FILE) as f:
        rows = list(csv.reader(f))
    rows = transform(rows)
    with open(AGENT_FILE, 'w', newline='') as f:
        csv.writer(f).writerows(rows)


def load_agents():
    try:
        with open(AGENT_FILE) as f:
            return [dict(r) for r in csv.DictReader(f)]
    except FileNotFoundError:
        return []


def update_agent_status(session, new_status):
    def transform(rows):
        for row in rows:
            if len(row) > 3 and row[3] == session:
                row[0] = new_status
        return rows
    _rewrite_csv(transform)


def remove_agent(session):
    _rewrite_csv(lambda rows: [r for r in rows if not (len(r) > 3 and r[3] == session)])


def append_log(session, message):
    today = datetime.now().strftime('%Y-%m-%d')
    with open(AGENT_LOG, 'a') as f:
        f.write(f"- [{today}] {session}: {message}\n")


# ── tmux helpers ─────────────────────────────────────────────────────────────

def get_live_sessions():
    try:
        out = subprocess.check_output(["tmux", "ls"], stderr=subprocess.DEVNULL, text=True)
        return {line.split(":")[0] for line in out.splitlines()
                if not EXCLUDED.match(line.split(":")[0])}
    except Exception:
        return set()


def get_pane_output(session, lines=50):
    try:
        out = subprocess.check_output(
            ["tmux", "capture-pane", "-t", session, "-p", "-e"],
            stderr=subprocess.DEVNULL, text=True
        )
        out = ANSI_ESCAPE.sub('', out)
        content = out.splitlines()
        return content[-lines:] if content else []
    except Exception:
        return []


def age_str(started):
    if not started:
        return ''
    try:
        delta = datetime.now() - datetime.strptime(started.strip(), '%Y-%m-%d')
        return f"{delta.days}d" if delta.days > 0 else f"{delta.seconds // 3600}h"
    except Exception:
        return ''


# ── Dashboard ────────────────────────────────────────────────────────────────

class Dashboard:
    def __init__(self, stdscr):
        self.stdscr      = stdscr
        self.agents      = []
        self.live        = set()
        self.selected    = 0
        self.scroll      = 0
        self.pscroll     = 0
        self.last_refresh = 0
        self.hide_done   = False
        self.search      = ''
        self._pending_g  = False
        # sort_mode: 'status' | 'alpha' | 'age'
        self.sort_mode   = 'status'
        # pane_cache: {session: (lines, timestamp)}
        self.pane_cache  = {}
        self._init_curses()

    def _init_curses(self):
        global COLOR_MAP
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(C_ACTIVE,   curses.COLOR_GREEN,   -1)
        curses.init_pair(C_BLOCKED,  curses.COLOR_RED,     -1)
        curses.init_pair(C_STALE,    curses.COLOR_YELLOW,  -1)
        curses.init_pair(C_DONE,     curses.COLOR_WHITE,   -1)
        curses.init_pair(C_HEADER,   curses.COLOR_CYAN,    -1)
        curses.init_pair(C_SELECTED, curses.COLOR_BLACK,   curses.COLOR_CYAN)
        curses.init_pair(C_BAR,      curses.COLOR_BLACK,   curses.COLOR_WHITE)
        curses.init_pair(C_PREVIEW,  curses.COLOR_WHITE,   -1)
        curses.init_pair(C_REVIEW,   curses.COLOR_MAGENTA, -1)
        curses.init_pair(C_TESTING,  curses.COLOR_YELLOW,  -1)
        COLOR_MAP = {
            'active':  curses.color_pair(C_ACTIVE),
            'review':  curses.color_pair(C_REVIEW)  | curses.A_BOLD,
            'testing': curses.color_pair(C_TESTING) | curses.A_BOLD,
            'blocked': curses.color_pair(C_BLOCKED) | curses.A_BOLD,
            'stale':   curses.color_pair(C_STALE),
            'done':    curses.color_pair(C_DONE)    | curses.A_DIM,
        }
        self.stdscr.nodelay(True)
        self.stdscr.timeout(500)

    def refresh_data(self):
        self.agents = load_agents()
        self.live   = get_live_sessions()
        self.last_refresh = time.time()

    def _enrich(self):
        enriched = []
        for a in self.agents:
            status  = a.get('Status', '')
            session = a.get('Session', '')
            ds = 'stale' if status == 'active' and session not in self.live else status
            enriched.append({**a, '_ds': ds})
        if self.sort_mode == 'alpha':
            enriched.sort(key=lambda a: a.get('Session', '').lower())
        elif self.sort_mode == 'age':
            enriched.sort(key=lambda a: a.get('Started', '') or '', reverse=True)
        else:  # status (default)
            enriched.sort(key=lambda a: (STATUS_ORDER.get(a['_ds'], 9), a.get('Session', '').lower()))
        if self.hide_done:
            enriched = [a for a in enriched if a['_ds'] != 'done']
        if self.search:
            q = self.search.lower()
            enriched = [a for a in enriched if q in a.get('Session', '').lower()
                        or q in a.get('Task', '').lower()]
        return enriched

    def _selected_agent(self, enriched):
        """Return the currently selected agent dict, or None."""
        if enriched and 0 <= self.selected < len(enriched):
            return enriched[self.selected]
        return None

    def _pin_selection(self, enriched):
        """Remember the session name of the currently selected agent."""
        agent = self._selected_agent(enriched)
        return agent.get('Session', '') if agent else ''

    def _restore_selection(self, enriched, session):
        """Move self.selected to the row matching session, if found."""
        if not session:
            return
        for i, a in enumerate(enriched):
            if a.get('Session') == session:
                self.selected = i
                return

    def _refresh_pinned(self, enriched):
        """Refresh data while keeping the cursor on the same session."""
        pinned = self._pin_selection(enriched)
        self.refresh_data()
        new_enriched = self._enrich()
        self._restore_selection(new_enriched, pinned)
        return new_enriched

    def _get_pane(self, session, lines=50):
        now = time.time()
        cached = self.pane_cache.get(session)
        if cached and now - cached[1] < 10:
            return cached[0]
        output = get_pane_output(session, max(lines, 50))
        self.pane_cache[session] = (output, now)
        return output

    def _invalidate_pane(self, session):
        self.pane_cache.pop(session, None)
        self.pscroll = 0

    # ── drawing ──────────────────────────────────────────────────────────────

    def draw(self, enriched):
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()

        # clamp selection
        self.selected = max(0, min(self.selected, len(enriched) - 1)) if enriched else 0

        available    = h - HEADER_LINES - FOOTER_LINES - DIVIDER_LINE
        list_rows    = max(1, min(len(enriched), available - 3))
        preview_rows = max(0, available - list_rows)
        W_TASK       = max(w - W_STATUS - W_TYPE - W_SESSION - W_CLICKUP - 6, 10)

        # title bar
        ago    = int(time.time() - self.last_refresh)
        hide   = "  [h: show done]" if self.hide_done else "  [h: hide done]"
        search = f"  [/{self.search}]" if self.search else ""
        sort   = f"  sort:{self.sort_mode}"
        self._bar(0, f" Agent Dashboard  {datetime.now():%Y-%m-%d %H:%M}  {ago}s ago{hide}{sort}{search}", w)

        # column header
        col_hdr = (f" {'ST':<{W_STATUS}} {'SESSION':<{W_SESSION}} "
                   f"{'TASK':<{W_TASK}} {'CLICKUP':<{W_CLICKUP}} {'TYPE/AGE':<{W_TYPE}}")
        self._write(1, 0, col_hdr[:w], curses.color_pair(C_HEADER) | curses.A_BOLD)

        # list rows
        if self.selected >= self.scroll + list_rows:
            self.scroll = self.selected - list_rows + 1
        elif self.selected < self.scroll:
            self.scroll = self.selected

        for i in range(list_rows):
            idx = i + self.scroll
            if idx >= len(enriched):
                break
            a      = enriched[idx]
            ds     = a['_ds']
            status = f"{STATUS_MARKER.get(ds, ' ')} {ds}"
            type_age = (a.get('Type','') or age_str(a.get('Started','')))[:W_TYPE]
            line   = (f" {status:<{W_STATUS}} {a.get('Session','')[:W_SESSION]:<{W_SESSION}} "
                      f"{a.get('Task','')[:W_TASK]:<{W_TASK}} "
                      f"{a.get('ClickUp','')[:W_CLICKUP]:<{W_CLICKUP}} "
                      f"{type_age:<{W_TYPE}}")
            row_y = HEADER_LINES + i
            if row_y >= h - FOOTER_LINES - 1:
                break
            attr = (curses.color_pair(C_SELECTED) | curses.A_BOLD) if idx == self.selected \
                   else COLOR_MAP.get(ds, 0)
            self._write(row_y, 0, line[:w].ljust(min(w, len(line) + 1)), attr)

        # divider
        div_y = HEADER_LINES + list_rows
        if div_y < h - FOOTER_LINES:
            sel = self._selected_agent(enriched)
            label   = f" Preview: {sel['Session']} " if sel else " Preview "
            divider = ("─" * 3 + label + "─" * max(0, w - 3 - len(label)))[:w]
            self._write(div_y, 0, divider, curses.color_pair(C_HEADER))

        # preview
        if enriched and preview_rows > 0:
            sel     = self._selected_agent(enriched)
            session = sel.get('Session', '') if sel else ''
            py0     = div_y + 1

            if session in self.live:
                lines = self._get_pane(session, preview_rows)
                max_ps = max(0, len(lines) - preview_rows)
                self.pscroll = max(0, min(self.pscroll, max_ps))
                start = max(0, len(lines) - preview_rows - self.pscroll)
                for i, pline in enumerate(lines[start: start + preview_rows]):
                    if py0 + i >= h - FOOTER_LINES:
                        break
                    self._write(py0 + i, 0, pline[:w - 1], curses.color_pair(C_PREVIEW))
                if not lines:
                    self._write(py0, 0, " (no output captured)", curses.color_pair(C_STALE))
            else:
                self._write(py0, 0, " (session not running)", curses.color_pair(C_BLOCKED))

        # footer
        self._bar(h - 1,
                  " [↑↓/jk/gg/G] navigate  [enter] switch  [c] command  [K] ctrl+c  "
                  "[n] new  [a] active  [r] review  [t] testing  [b] blocked  [d] done  [x] done+kill  "
                  "[/?] search  [o] sort  [h] hide done  [PgUp/PgDn] preview  [v] refresh  [q] quit", w)

        self.stdscr.noutrefresh()
        curses.doupdate()

    def _bar(self, y, text, w):
        try:
            self.stdscr.attron(curses.color_pair(C_BAR) | curses.A_BOLD)
            self.stdscr.addstr(y, 0, text[:w].ljust(w))
            self.stdscr.attroff(curses.color_pair(C_BAR) | curses.A_BOLD)
        except curses.error:
            pass

    def _write(self, y, x, text, attr=0):
        try:
            self.stdscr.attron(attr)
            self.stdscr.addstr(y, x, text)
            self.stdscr.attroff(attr)
        except curses.error:
            pass

    # ── event loop ───────────────────────────────────────────────────────────

    def run(self):
        self.refresh_data()

        while True:
            if time.time() - self.last_refresh > REFRESH_INTERVAL:
                self._refresh_pinned(self._enrich())

            enriched = self._enrich()
            self.draw(enriched)

            try:
                key = self.stdscr.getch()
            except (curses.error, KeyboardInterrupt):
                break

            if key == -1:
                continue

            agent = self._selected_agent(enriched)

            # reset pending-g on any key that isn't 'g'
            if key != ord('g'):
                self._pending_g = False

            if key in (ord('q'), ord('Q')):
                break

            elif key == ord('K'):
                if agent:
                    subprocess.run(["tmux", "send-keys", "-t", agent['Session'], "C-c"],
                                   stderr=subprocess.DEVNULL)
                    self._invalidate_pane(agent['Session'])

            elif key in (curses.KEY_UP, ord('k')):
                self.selected = max(0, self.selected - 1)
                self.pscroll = 0

            elif key in (curses.KEY_DOWN, ord('j')):
                self.selected = min(len(enriched) - 1, self.selected + 1) if enriched else 0
                self.pscroll = 0

            elif key == ord('G'):
                self.selected = max(0, len(enriched) - 1)
                self.pscroll = 0

            elif key == ord('g'):
                if self._pending_g:
                    self.selected = 0
                    self.scroll = 0
                    self.pscroll = 0
                    self._pending_g = False
                else:
                    self._pending_g = True

            elif key in (ord('/'), ord('?')):
                query = self._prompt(f" /search [{self.search}]: " if self.search else " /search: ")
                if query.strip() or not self.search:
                    self.search = query.strip()
                self.selected = 0
                self.scroll = 0

            elif key == 27:  # ESC clears search
                self.search = ''
                self.selected = 0
                self.scroll = 0

            elif key in (ord('v'), ord('V')):
                self._refresh_pinned(enriched)

            elif key in (ord('h'), ord('H')):
                self.hide_done = not self.hide_done
                self.selected = 0
                self.scroll = 0

            elif key in (ord('o'), ord('O')):
                modes = ['status', 'alpha', 'age']
                self.sort_mode = modes[(modes.index(self.sort_mode) + 1) % len(modes)]
                self.selected = 0
                self.scroll = 0

            elif key == curses.KEY_RESIZE:
                self.stdscr.clear()

            elif key == curses.KEY_PPAGE:
                self.pscroll += 5

            elif key == curses.KEY_NPAGE:
                self.pscroll = max(0, self.pscroll - 5)

            elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                if agent and agent['Session'] in self.live:
                    subprocess.run(["tmux", "switch-client", "-t", agent['Session']],
                                   stderr=subprocess.DEVNULL)

            elif key in (ord('d'), ord('D')):
                if agent:
                    update_agent_status(agent['Session'], 'done')
                    append_log(agent['Session'], 'marked done from dashboard')
                    self._refresh_pinned(enriched)

            elif key in (ord('t'), ord('T')):
                if agent:
                    update_agent_status(agent['Session'], 'testing')
                    append_log(agent['Session'], 'marked testing from dashboard')
                    self._refresh_pinned(enriched)

            elif key in (ord('b'), ord('B')):
                if agent:
                    update_agent_status(agent['Session'], 'blocked')
                    append_log(agent['Session'], 'marked blocked from dashboard')
                    self._refresh_pinned(enriched)

            elif key in (ord('x'), ord('X')):
                if agent:
                    session = agent['Session']
                    choice = self._prompt(f" '{session}': [k]ill  [u]ntrack  [c]ancel: ")
                    choice = choice.strip().lower()
                    if choice in ('k', 'kill'):
                        append_log(session, 'session killed from dashboard')
                        subprocess.run(["tmux", "kill-session", "-t", session],
                                       stderr=subprocess.DEVNULL)
                        remove_agent(session)
                        self._refresh_pinned(enriched)
                    elif choice in ('u', 'untrack'):
                        append_log(session, 'untracked from dashboard')
                        remove_agent(session)
                        self._refresh_pinned(enriched)

            elif key in (ord('a'), ord('A')):
                if agent:
                    update_agent_status(agent['Session'], 'active')
                    append_log(agent['Session'], 'marked active from dashboard')
                    self._refresh_pinned(enriched)

            elif key in (ord('n'), ord('N')):
                curses.endwin()
                os.system("zsh -c 'bindkey -e; source ~/tools/agent-tools.sh && agent-start'")
                os.system("stty sane")
                self.stdscr = curses.initscr()
                self._init_curses()
                self._refresh_pinned(enriched)

            elif key in (ord('r'), ord('R')):
                if agent:
                    update_agent_status(agent['Session'], 'review')
                    append_log(agent['Session'], 'marked needs review from dashboard')
                    self._refresh_pinned(enriched)

            elif ord('0') <= key <= ord('9'):
                if agent:
                    session = agent['Session']
                    subprocess.run(["tmux", "send-keys", "-t", session, chr(key)],
                                   stderr=subprocess.DEVNULL)
                    self._invalidate_pane(session)
                    time.sleep(0.05)  # let tmux process the keystroke
                    self._get_pane(session)  # force re-capture into cache
                    if agent.get('Status') != 'active':
                        update_agent_status(session, 'active')
                        append_log(session, 'reset to active after receiving input from dashboard')
                    self.last_refresh = 0  # mark stale, refresh on next cycle

            elif key in (ord('c'), ord('C')):
                if agent:
                    session = agent['Session']
                    msg = self._popup_edit(f"Message for {session}")
                    if msg:
                        subprocess.run(["tmux", "send-keys", "-t", session, msg, "Enter"],
                                       stderr=subprocess.DEVNULL)
                        self._invalidate_pane(session)
                        if agent.get('Status') != 'active':
                            update_agent_status(session, 'active')
                            append_log(session, 'reset to active after receiving input from dashboard')
                        self.last_refresh = 0  # mark stale, refresh on next cycle

    def _prompt(self, label):
        """Inline input at the footer bar. Returns text or '' if cancelled."""
        h, w = self.stdscr.getmaxyx()
        buf  = []
        curses.flushinp()  # discard any stale keypresses before opening prompt
        curses.curs_set(1)
        self.stdscr.nodelay(False)
        self.stdscr.timeout(-1)
        try:
            while True:
                display  = (label + ''.join(buf))[:w - 1]
                cursor_x = min(len(display), w - 1)
                self._bar(h - 1, display.ljust(w), w)
                try:
                    self.stdscr.move(h - 1, cursor_x)
                except curses.error:
                    pass
                self.stdscr.noutrefresh()
                curses.doupdate()
                try:
                    ch = self.stdscr.getch()
                except (curses.error, KeyboardInterrupt):
                    return ''
                if ch in (curses.KEY_ENTER, ord('\n'), ord('\r')):
                    if buf:  # ignore Enter on empty buffer — keep prompt open
                        return ''.join(buf)
                elif ch == 27:
                    return ''
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if buf:
                        buf.pop()
                elif 32 <= ch < 127:
                    buf.append(chr(ch))
        finally:
            curses.flushinp()
            curses.curs_set(0)
            self.stdscr.nodelay(True)
            self.stdscr.timeout(500)

    def _popup_edit(self, title=""):
        """Open nvim in a tmux popup for multiline editing. Returns text or ''."""
        tmp = tempfile.NamedTemporaryFile(suffix='.md', prefix='agent-msg-', delete=False)
        tmp.close()
        try:
            curses.endwin()
            subprocess.run(
                ["tmux", "display-popup", "-E", "-w", "80%", "-h", "60%",
                 "-T", title, "nvim", tmp.name],
            )
            os.system("stty sane")
            self.stdscr = curses.initscr()
            self._init_curses()
            with open(tmp.name) as f:
                return f.read().strip()
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


def main():
    os.system("stty sane")
    curses.wrapper(lambda s: Dashboard(s).run())


if __name__ == '__main__':
    main()
