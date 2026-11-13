-- Ember: port of the owner's X11 Apple keyboard modifier swap.
-- Wayland-native XKB, not xmodmap. Never change the Glove80/global layout.
-- Physical Option -> Super; Command -> Alt; Caps Lock -> Escape.
local apple = "apple-inc.-magic-keyboard-with-touch-id-and-numeric-keypad"
-- The second suffix covers a duplicate input node exposed by this USB model.
for _, name in ipairs({ apple, apple .. "-1" }) do
  hl.device({
    name = name,
    kb_layout = "us",
    kb_options = "altwin:swap_alt_win,caps:escape",
  })
end
