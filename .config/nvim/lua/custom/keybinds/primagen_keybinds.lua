-- fix tabs to reasonable lengths.
vim.opt.tabstop = 4
vim.opt.softtabstop = 4
vim.opt.shiftwidth = 4
vim.opt.expandtab = true
-- Don't show the mode, since it's already in the status line
vim.opt.showmode = false

vim.opt.wrap = false

vim.opt.swapfile = false
vim.opt.backup = false
vim.opt.undodir = os.getenv 'HOME' .. '/.vim/undodir'
vim.opt.undofile = true

vim.opt.hlsearch = false
vim.opt.incsearch = true

vim.opt.termguicolors = true

vim.opt.signcolumn = 'yes'
vim.opt.isfname:append '@-@'

vim.opt.colorcolumn = '80'

-- [[ Prime Keymaps ]]

-- move when in visual mode
vim.keymap.set('v', 'J', ":m '>+1<CR>gv=gv")
vim.keymap.set('v', 'K', ":m '<-2<CR>gv=gv")

-- key cursor steady when using J
vim.keymap.set('n', 'J', 'mzJ`z')

-- keep cursor in middle when page up / down
vim.keymap.set('n', '<C-d>', '<C-d>zz')
vim.keymap.set('n', '<C-u>', '<C-u>zz')

--keep cursor in middle when searching
vim.keymap.set('n', 'n', 'nzzzv')
vim.keymap.set('n', 'N', 'Nzzzv')

-- allows keeping yank when pasting
vim.keymap.set('x', '<leader>p', '"_dP')

-- yank to clipboard
vim.keymap.set({ 'n', 'v' }, '<leader>y', [["+y]])
vim.keymap.set('n', '<leader>Y', [["+Y]])

-- delete to void register
vim.keymap.set('n', '<leader>d', '"_d')
vim.keymap.set('v', '<leader>d', '"_d')

vim.keymap.set('n', 'Q', '<nop>') -- prime says it's the worst place in the universe...

vim.keymap.set('n', '<C-f>', '<cmd>silent !tmux neww tmux-sessionizer<CR>')

vim.keymap.set('n', '<leader>x', [[:%s/\<<C-r><C-w>\>/<C-r><C-w>/gI<Left><Left><Left>]])

vim.keymap.set("n", "<leader>pv", "<cmd>Explor<CR>", {
  noremap = true,
  silent = true,
  desc = "Open File Explorer (Netrw) in Current Window"
})

-- remap s
vim.keymap.set('n', 's', 'xi')


-- remap rename
vim.keymap.set('n', '<leader>rn', 'grn')

-- sprint-sync: save notes, sync with ClickUp, pull changes
vim.keymap.set('n', '<leader>ss', '<cmd>w | botright split | terminal sprint-sync<CR>', {
    desc = 'Sprint sync (save, sync ClickUp, pull changes)'
})

-- agent-start: extract TECH-XXXX from current line, launch agent in tmux popup
vim.keymap.set('n', '<leader>sa', function()
  local line = vim.api.nvim_get_current_line()
  local task_id = line:match('(TECH%-[0-9]+)')
  local cmd = 'agent-start'
  if task_id then
    cmd = cmd .. ' --task ' .. task_id
  end
  vim.cmd('w')
  local tmux_cmd = 'tmux display-popup -E -w 80% -h 70% "source ~/tools/agent-tools.sh && ' .. cmd .. '; echo; echo Press enter to close; read"'
  vim.fn.jobstart(tmux_cmd, { detach = true })
end, { desc = 'Start agent from task line' })

return {}
