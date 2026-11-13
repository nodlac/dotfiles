import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { type OverlayHandle, truncateToWidth, visibleWidth } from "@earendil-works/pi-tui";

let overlay: OverlayHandle | undefined;
function clearOverlay() {
  overlay?.hide();
  overlay = undefined;
}

// Five-pixel lettering packed into three terminal rows with half blocks.
// Keep lettering fixed-size on narrow terminals; clip at the right edge.
// Fall back to bold text only for unsupported characters.
const alphabet: Record<string, string> = {
  A: "01110/10001/11111/10001/10001", B: "11110/10001/11110/10001/11110",
  C: "01111/10000/10000/10000/01111", D: "11110/10001/10001/10001/11110",
  E: "11111/10000/11110/10000/11111", F: "11111/10000/11110/10000/10000",
  G: "01111/10000/10111/10001/01110", H: "10001/10001/11111/10001/10001",
  I: "111/010/010/010/111", J: "00111/00010/00010/10010/01100",
  K: "10001/10010/11100/10010/10001", L: "10000/10000/10000/10000/11111",
  M: "10001/11011/10101/10001/10001", N: "10001/11001/10101/10011/10001",
  O: "01110/10001/10001/10001/01110", P: "11110/10001/11110/10000/10000",
  Q: "01110/10001/10001/10011/01111", R: "11110/10001/11110/10010/10001",
  S: "01111/10000/01110/00001/11110", T: "11111/00100/00100/00100/00100",
  U: "10001/10001/10001/10001/01110", V: "10001/10001/10001/01010/00100",
  W: "10001/10001/10101/11011/10001", X: "10001/01010/00100/01010/10001",
  Y: "10001/01010/00100/00100/00100", Z: "11111/00010/00100/01000/11111",
  "0": "01110/10011/10101/11001/01110", "1": "010/110/010/010/111",
  "2": "11110/00001/01110/10000/11111", "3": "11110/00001/01110/00001/11110",
  "4": "10010/10010/11111/00010/00010", "5": "11111/10000/11110/00001/11110",
  "6": "01111/10000/11110/10001/01110", "7": "11111/00010/00100/01000/01000",
  "8": "01110/10001/01110/10001/01110", "9": "01110/10001/01111/00001/11110",
  " ": "00/00/00/00/00", "-": "000/000/111/000/000",
};

function showName(ctx: ExtensionContext, rawName?: string) {
  if (ctx.mode !== "tui") return;
  // Session names are data, never terminal control sequences.
  const name = rawName?.replace(/[\x00-\x1f\x7f-\x9f]/g, "").trim();
  clearOverlay();
  ctx.ui.setWidget("agent-name", undefined);
  ctx.ui.setHeader(undefined);
  if (!name) return;
  // An invisible widget provides the host TUI; the banner itself is a
  // non-capturing overlay anchored to the visible terminal, not scrollback.
  ctx.ui.setWidget("agent-name", (tui, _theme) => {
    const component = {
    render(width: number) {
      const theme = ctx.ui.theme;
      const glyphs = [...name.toUpperCase()].map((char) => alphabet[char]?.split("/"));
      let content: string[];
      if (glyphs.every(Boolean)) {
        content = Array.from({ length: 3 }, (_, row) => glyphs
          .map((glyph) => [...glyph![row * 2]].map((top, col) => {
            const bottom = glyph![row * 2 + 1]?.[col] ?? "0";
            return top === "1" ? (bottom === "1" ? "█" : "▀") : (bottom === "1" ? "▄" : " ");
          }).join(""))
          .join(" "));
      } else {
        content = [name];
      }
      return content.map((line) => truncateToWidth(line, Math.max(0, width), ""))
        .map((line) => theme.bg("userMessageBg", theme.fg("accent",
        theme.bold(line + " ".repeat(Math.max(0, width - visibleWidth(line)))),
      )));
    },
    invalidate() {},
    };
    overlay = tui.showOverlay(component, {
      anchor: "top-left", row: 0, col: 0, width: "100%", maxHeight: 3,
      nonCapturing: true,
      visible: (_width, height) => height >= 10,
    });
    return { render: () => [], invalidate() {} };
  });
}

export default function agentName(pi: ExtensionAPI) {
  // Reuse built-in /name rather than shadowing it. Pi persists the name.
  pi.on("session_start", (_event, ctx) => showName(ctx, ctx.sessionManager.getSessionName()));
  pi.on("session_info_changed", (event, ctx) => showName(ctx, event.name));
  pi.on("session_shutdown", clearOverlay);
}
