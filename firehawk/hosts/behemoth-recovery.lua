-- Temporary, opt-in Behemoth session troubleshooting; not a fleet-wide default.
-- Loaded by ~/.config/firehawk/local.lua only on this machine.
-- A software cursor is a diagnostic workaround, not a proven input-failure fix.
hl.config({
  cursor = { no_hardware_cursors = 1 },
  debug = { disable_logs = false, enable_stdout_logs = true },
})

-- Recovery keys do not depend on the Apple device-specific Alt/Super swap.
hl.bind("CTRL + ALT + Return", hl.dsp.exec_cmd("ghostty"))
-- This immediately logs out of Hyprland; unsaved application work can be lost.
hl.bind("CTRL + ALT + BackSpace", hl.dsp.exit())

hl.on("hyprland.start", function()
  hl.exec_cmd("bash ~/.config/firehawk/current/scripts/session-diagnostics")
  -- A visible terminal lets us test ordinary typing without a launcher binding.
  hl.exec_cmd("ghostty")
end)
