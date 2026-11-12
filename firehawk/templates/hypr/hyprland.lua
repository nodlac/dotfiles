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
hl.bind("SUPER + F", hl.dsp.window.fullscreen())
hl.bind("SUPER + SHIFT + C", hl.dsp.reload_config())
hl.bind("SUPER + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind("SUPER + S", hl.dsp.workspace.toggle_special("scratch"))
hl.bind("SUPER + SHIFT + S", hl.dsp.window.move({ workspace = "special:scratch" }))
for key, direction in pairs({left="left", right="right", up="up", down="down"}) do
  hl.bind("SUPER + " .. key, hl.dsp.focus({ direction = direction }))
end
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
exec("SUPER + N", "swaync-client -t")
-- User-owned file, never generated or overwritten.
local localfile = os.getenv("HOME") .. "/.config/firehawk/local.lua"
local f = io.open(localfile, "r")
if f then f:close(); dofile(localfile) end
