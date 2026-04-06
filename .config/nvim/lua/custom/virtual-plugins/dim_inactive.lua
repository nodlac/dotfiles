-- Dim Neovim background when tmux pane loses focus
local original_bg = nil
local dimmed = false

-- Capture the original bg after colorscheme loads
vim.api.nvim_create_autocmd('ColorScheme', {
  callback = function()
    local normal = vim.api.nvim_get_hl(0, { name = 'Normal' })
    if normal.bg then
      original_bg = normal.bg
    end
  end,
})

-- Also capture on startup
local normal = vim.api.nvim_get_hl(0, { name = 'Normal' })
if normal.bg then
  original_bg = normal.bg
end

vim.api.nvim_create_autocmd('FocusLost', {
  callback = function()
    if dimmed or not original_bg then return end
    dimmed = true
    local r = math.max(0, math.floor(original_bg / 65536) - 15)
    local g = math.max(0, math.floor((original_bg % 65536) / 256) - 15)
    local b = math.max(0, (original_bg % 256) - 15)
    local cur = vim.api.nvim_get_hl(0, { name = 'Normal' })
    vim.api.nvim_set_hl(0, 'Normal', vim.tbl_extend('force', cur, { bg = r * 65536 + g * 256 + b }))
  end,
})

vim.api.nvim_create_autocmd('FocusGained', {
  callback = function()
    if not dimmed or not original_bg then return end
    dimmed = false
    local cur = vim.api.nvim_get_hl(0, { name = 'Normal' })
    vim.api.nvim_set_hl(0, 'Normal', vim.tbl_extend('force', cur, { bg = original_bg }))
  end,
})

return {}
