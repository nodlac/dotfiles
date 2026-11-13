-- Ember / Hyprland 0.57 Lua API.
-- Theme generated separately; personal bindings and rules belong in local.lua.
local t = dofile(os.getenv("HOME") .. "/.config/firehawk/current/theme.lua")
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })
hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.config({
  general = {
    gaps_in = 6, gaps_out = 12, border_size = 2, layout = "dwindle",
    col = {
      active_border = { colors = { t.orange, t.ember }, angle = 45 },
      inactive_border = t.panel,
    },
  },
  decoration = {
    rounding = 6, active_opacity = 1.0, inactive_opacity = 1.0,
    shadow = { enabled = true, range = 8, render_power = 3, color = 0x99000000 },
    blur = { enabled = false },
  },
  animations = { enabled = true },
  dwindle = { preserve_split = true },
  input = { kb_layout = "us", follow_mouse = 1 },
  misc = { disable_hyprland_logo = true, force_default_wallpaper = 0 },
})
-- Device-specific keymaps; personal local.lua overrides are loaded last.
dofile(os.getenv("HOME") .. "/.config/firehawk/current/hypr/keyboards.lua")
hl.on("hyprland.start", function()
  hl.exec_cmd("dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP HYPRLAND_INSTANCE_SIGNATURE")
  hl.exec_cmd("waybar")
  hl.exec_cmd("swaync")
  hl.exec_cmd("hyprpaper")
  hl.exec_cmd("hypridle")
  hl.exec_cmd("/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1")
end)
local function exec(keys, command) hl.bind(keys, hl.dsp.exec_cmd(command)) end
exec("SUPER + Return", "ghostty")
exec("SUPER + D", "rofi -show drun -theme ~/.config/firehawk/current/rofi/firehawk.rasi")
exec("SUPER + SHIFT + Escape", "hyprlock")
hl.bind("SUPER + Q", hl.dsp.window.close())
hl.bind("SUPER + SHIFT + F", hl.dsp.window.fullscreen())
hl.bind("SUPER + SHIFT + C", hl.dsp.reload_config())
hl.bind("SUPER + SHIFT + space", hl.dsp.window.float({ action = "toggle" }))
-- Keep i3's session keys free; scratchpad remains available on Ctrl+Super+S.
hl.bind("SUPER + CTRL + S", hl.dsp.workspace.toggle_special("scratch"))
hl.bind("SUPER + CTRL + SHIFT + S", hl.dsp.window.move({ workspace = "special:scratch" }))
-- Ctrl+hjkl belongs to tmux focus, Alt/Super+hjkl to tmux pane swaps.
for key, direction in pairs({H="left", J="down", K="up", L="right"}) do
  hl.bind("CTRL + SHIFT + " .. key, hl.dsp.focus({ direction = direction }))
  hl.bind("ALT + SHIFT + " .. key, hl.dsp.window.move({ direction = direction }))
  hl.bind("SUPER + SHIFT + " .. key, hl.dsp.window.move({ direction = direction }))
end
for key, direction in pairs({left="left", right="right", up="up", down="down"}) do
  hl.bind("SUPER + " .. key, hl.dsp.focus({ direction = direction }))
  hl.bind("SUPER + SHIFT + " .. key, hl.dsp.window.move({ direction = direction }))
end
hl.bind("SUPER + Tab", hl.dsp.focus({ workspace = "e+1" }))
hl.bind("SUPER + SHIFT + Tab", hl.dsp.focus({ workspace = "e-1" }))
-- Match i3's tmux sessions without embedding a machine-specific home directory.
local function session(keys, name, directory)
  local create = "tmux new-session -d -s " .. name
  if directory then create = create .. ' -c "$HOME/' .. directory .. '"' end
  exec(keys, "hyprctl dispatch 'hl.dsp.focus({workspace = 2})'; " ..
    "tmux has-session -t =" .. name .. " 2>/dev/null || " .. create ..
    "; tmux switch-client -t =" .. name)
end
session("SUPER + S", "settings")
session("SUPER + N", "notes")
session("SUPER + A", "agency-admin", "clients/client-dashboard")
session("ALT + A", "agency-admin", "clients/client-dashboard")
session("SUPER + P", "callisto")
session("SUPER + Y", "yerba-mate")
for i = 1, 10 do
  hl.bind("SUPER + " .. (i % 10), hl.dsp.focus({ workspace = i }))
  hl.bind("SUPER + SHIFT + " .. (i % 10), hl.dsp.window.move({ workspace = i }))
end
hl.bind("SUPER + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind("SUPER + mouse:273", hl.dsp.window.resize(), { mouse = true })
exec("XF86AudioRaiseVolume", "wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+")
exec("XF86AudioLowerVolume", "wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-")
exec("XF86AudioMute", "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle")
exec("XF86AudioMicMute", "wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle")
-- No automatic clipboard capture: avoid retaining passwords/business data.
exec("Print", "bash ~/.config/firehawk/current/scripts/screenshot region-copy")
exec("SUPER + Print", "bash ~/.config/firehawk/current/scripts/screenshot full-save")
exec("SHIFT + Print", "bash ~/.config/firehawk/current/scripts/screenshot region-edit")
-- Command+Shift+3/4 on the remapped Apple keyboard, as on i3/macOS.
exec("ALT + SHIFT + 3", "bash ~/.config/firehawk/current/scripts/screenshot full-save")
exec("ALT + SHIFT + 4", "bash ~/.config/firehawk/current/scripts/screenshot region-edit")
exec("ALT + CTRL + SHIFT + 3", "bash ~/.config/firehawk/current/scripts/screenshot full-copy")
exec("ALT + CTRL + SHIFT + 4", "bash ~/.config/firehawk/current/scripts/screenshot region-copy")
exec("SUPER + CTRL + N", "swaync-client -t")
-- User-owned file, never generated or overwritten.
local localfile = os.getenv("HOME") .. "/.config/firehawk/local.lua"
local f = io.open(localfile, "r")
if f then f:close(); dofile(localfile) end
