#!/usr/bin/env python3
"""Give the focused tmux column >=50%, sharing the rest evenly."""
import subprocess
import sys


def tmux(*args):
    return subprocess.check_output(["tmux", *args], text=True).strip()


def balance(window):
    rows = tmux(
        "list-panes", "-t", window, "-F",
        "#{pane_id} #{pane_active} #{pane_width} #{window_width} #{window_height} #{window_zoomed_flag}",
    ).splitlines()
    panes = [row.split() for row in rows]
    if len(panes) < 2 or panes[0][5] == "1":
        return
    active = next(i for i, pane in enumerate(panes) if pane[1] == "1")
    if tmux("show-options", "-wqv", "-t", window, "@pane-minimize") == "on":
        tmux("resize-pane", "-t", panes[active][0], "-x", "100%")
        return

    width, height = map(int, panes[0][3:5])
    available = width - len(panes) + 1  # One border between each column.
    if available < len(panes):
        return  # Terminal too narrow for even one cell per pane.
    focused = min(max(int(panes[active][2]), (width + 1) // 2),
                  available - len(panes) + 1)
    small, remainder = divmod(available - focused, len(panes) - 1)
    widths = []
    for i in range(len(panes)):
        if i == active:
            widths.append(focused)
        else:
            widths.append(small + (remainder > 0))
            remainder = max(0, remainder - 1)

    x = 0
    cells = []
    for pane, column_width in zip(panes, widths):
        cells.append(f"{column_width}x{height},{x},0,{pane[0][1:]}")
        x += column_width + 1
    layout = f"{width}x{height},0,0{{{','.join(cells)}}}"
    checksum = 0
    for byte in layout.encode():
        checksum = (((checksum >> 1) | ((checksum & 1) << 15)) + byte) & 0xffff
    tmux("select-layout", "-t", window, f"{checksum:04x},{layout}")


if __name__ == "__main__":
    try:
        balance(sys.argv[1])
    except subprocess.CalledProcessError:
        pass  # The window may have closed while its hook was queued.
