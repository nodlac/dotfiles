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

-- Global find and replace
vim.keymap.set('n', '<leader>x', [[:%s/\<<C-r><C-w>\>/<C-r><C-w>/gI<Left><Left><Left>]])

-- opens file explorer
vim.keymap.set("n", "<leader>pv", "<cmd>Explor<CR>", {
  noremap = true,
  silent = true,
  desc = "Open File Explorer (Netrw) in Current Window"
})

-- remap s
vim.keymap.set('n', 's', 'xi')

-- sprint-sync: save notes, sync with ClickUp, pull changes (floating log)
vim.keymap.set('n', '<leader>ss', '<cmd>SprintSync<CR>', {
    desc = 'Sprint sync (save, sync ClickUp, pull changes)'
})

-- agent-start: extract TECH-XXXX from current line, launch agent in tmux popup
vim.keymap.set('n', '<leader>sa', function()
  local line = vim.api.nvim_get_current_line()
  local task_id = line:match('(TECH%-[0-9]+)')

  -- Collect notes nested under the task: every deeper-indented line until
  -- the next line at or above the task's own indent. Passed to agent-start
  -- so they land in the prompt template (editable before launch).
  local row = vim.api.nvim_win_get_cursor(0)[1]
  local indent = #line:match('^%s*')
  local notes = {}
  for _, l in ipairs(vim.api.nvim_buf_get_lines(0, row, -1, false)) do
    if l:match('^%s*$') or #l:match('^%s*') > indent then
      table.insert(notes, l)
    else
      break
    end
  end
  while #notes > 0 and notes[#notes]:match('^%s*$') do
    table.remove(notes)
  end

  -- Launching an agent means work has started — flip the task marker to [/]
  -- so the next sync pushes "in progress" to ClickUp.
  local in_progress = line:gsub('^(%s*%-%s*)%[[^%]]*%]', '%1[/]', 1)
  if in_progress ~= line then
    vim.api.nvim_set_current_line(in_progress)
  end

  local cmd = 'agent-start'
  if task_id then
    cmd = cmd .. ' --task ' .. task_id
  end
  if #notes > 0 then
    -- /tmp, not tempname(): the popup outlives this function and must still
    -- read the file; agent-start deletes it after use.
    local notes_file = '/tmp/agent-notes-' .. vim.fn.getpid() .. '.md'
    vim.fn.writefile(notes, notes_file)
    cmd = cmd .. ' --notes-file ' .. notes_file
  end
  vim.cmd('w')
  local tmux_cmd = 'tmux display-popup -E -w 80% -h 70% "source ~/repos/agent-tools/agent-tools.sh && ' .. cmd .. '; echo; echo Press enter to close; read"'
  vim.fn.jobstart(tmux_cmd, { detach = true })
end, { desc = 'Start agent from task line (marks in progress)' })

return {}
