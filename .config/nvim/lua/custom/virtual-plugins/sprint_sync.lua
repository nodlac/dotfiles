-- SprintSync: save → run sprint-sync → reload buffer (live floating output)
local M = {}
local last_buf = nil  -- reopenable log buffer

local function open_float(title)
  local buf = vim.api.nvim_create_buf(false, true)
  vim.bo[buf].bufhidden = 'wipe'
  vim.bo[buf].filetype = 'sprintsync'
  local w = math.floor(vim.o.columns * 0.8)
  local h = math.floor(vim.o.lines * 0.7)
  local win = vim.api.nvim_open_win(buf, true, {
    relative = 'editor',
    width = w,
    height = h,
    row = math.floor((vim.o.lines - h) / 2),
    col = math.floor((vim.o.columns - w) / 2),
    style = 'minimal',
    border = 'rounded',
    title = ' ' .. title .. ' ',
    title_pos = 'center',
  })
  vim.wo[win].wrap = false
  vim.wo[win].number = false
  vim.wo[win].signcolumn = 'no'
  -- q closes the float
  vim.keymap.set('n', 'q', '<cmd>close<CR>', { buffer = buf, nowait = true, silent = true })
  return buf, win
end

-- jobstart chunk semantics: data is split on \n. A trailing '' marks
-- "final line was complete (ended with \n)"; no trailing '' means the
-- final element is a partial line to be continued by the next chunk.
local function append(buf, lines)
  if not lines or #lines == 0 then return end
  if not vim.api.nvim_buf_is_valid(buf) then return end
  local ends_with_nl = (lines[#lines] == '')
  local clean = {}
  for _, l in ipairs(lines) do
    table.insert(clean, (l:gsub('\r', '')))
  end
  if ends_with_nl then
    table.remove(clean)  -- drop the trailing empty marker
  end
  if #clean == 0 then return end
  local n = vim.api.nvim_buf_line_count(buf)
  local last = vim.api.nvim_buf_get_lines(buf, n - 1, n, false)[1] or ''
  -- First element continues the previous partial line (if any).
  -- After a chunk that ended with \n we append a trailing empty line,
  -- so `last` is '' and this concat is a no-op.
  clean[1] = last .. clean[1]
  vim.api.nvim_buf_set_lines(buf, n - 1, n, false, clean)
  if ends_with_nl then
    -- Mark buffer "next write starts fresh line" so partial-merge logic
    -- above does not join unrelated chunks.
    vim.api.nvim_buf_set_lines(buf, -1, -1, false, { '' })
  end
  for _, win in ipairs(vim.api.nvim_list_wins()) do
    if vim.api.nvim_win_get_buf(win) == buf then
      vim.api.nvim_win_set_cursor(win, { vim.api.nvim_buf_line_count(buf), 0 })
    end
  end
end

vim.api.nvim_create_user_command('SprintSync', function(opts)
  local sprint_buf = vim.api.nvim_get_current_buf()
  local sprint_win = vim.api.nvim_get_current_win()
  local bufname = vim.api.nvim_buf_get_name(sprint_buf)
  if not bufname:match('sprint_%d+%.md$') then
    vim.notify('SprintSync: not a sprint file', vim.log.levels.WARN)
    return
  end

  -- Save the sprint buffer first so unsaved changes don't get clobbered
  -- when sync writes back to disk. Also save any other modified buffers
  -- pointing at sprint files (in case user edits in splits).
  local save_ok, save_err = pcall(function()
    vim.api.nvim_buf_call(sprint_buf, function() vim.cmd('silent write') end)
  end)
  if not save_ok then
    vim.notify('SprintSync: failed to save buffer — aborting (' .. tostring(save_err) .. ')',
      vim.log.levels.ERROR)
    return
  end
  if vim.bo[sprint_buf].modified then
    vim.notify('SprintSync: buffer still has unsaved changes — aborting', vim.log.levels.ERROR)
    return
  end
  -- Also flush any other modified sprint buffers
  for _, b in ipairs(vim.api.nvim_list_bufs()) do
    if b ~= sprint_buf and vim.api.nvim_buf_is_loaded(b) and vim.bo[b].modified then
      local n = vim.api.nvim_buf_get_name(b)
      if n:match('sprint_%d+%.md$') then
        pcall(vim.api.nvim_buf_call, b, function() vim.cmd('silent write') end)
      end
    end
  end

  local cmd = { vim.fn.expand('~/tools/sprint-sync') }
  for _, arg in ipairs(opts.fargs) do
    if arg ~= 'sync' then table.insert(cmd, arg) end
  end

  -- Save cursor for restore after reload
  local cursor = vim.api.nvim_win_get_cursor(0)
  local view = vim.fn.winsaveview()

  local title = 'sprint-sync ' .. table.concat(opts.fargs, ' ')
  local log_buf, log_win = open_float(title)
  last_buf = log_buf
  append(log_buf, { '$ ' .. table.concat(cmd, ' '), '' })

  vim.fn.jobstart(cmd, {
    stdout_buffered = false,
    stderr_buffered = false,
    -- PYTHONUNBUFFERED forces per-line flushing on pipe stdout so we can
    -- stream output live without pty (which corrupts line breaks).
    env = { PYTHONUNBUFFERED = '1' },
    on_stdout = function(_, data)
      vim.schedule(function() append(log_buf, data) end)
    end,
    on_stderr = function(_, data)
      vim.schedule(function() append(log_buf, data) end)
    end,
    on_exit = function(_, code)
      vim.schedule(function()
        append(log_buf, {
          '',
          code == 0 and '[done — press <Enter> or q to close]'
                     or ('[exit ' .. code .. ' — press <Enter> or q to close]'),
        })
        -- Reload sprint buffer (re-read from disk) + restore cursor in
        -- the original sprint window (not the popup).
        if vim.api.nvim_buf_is_valid(sprint_buf) then
          vim.api.nvim_buf_call(sprint_buf, function() vim.cmd('checktime') end)
          if vim.api.nvim_win_is_valid(sprint_win) then
            pcall(vim.api.nvim_win_call, sprint_win, function()
              vim.fn.winrestview(view)
              pcall(vim.api.nvim_win_set_cursor, sprint_win, cursor)
            end)
          end
        end
        -- Stay open; user closes with <Enter> or q
        if vim.api.nvim_buf_is_valid(log_buf) then
          vim.keymap.set('n', '<CR>', '<cmd>close<CR>',
            { buffer = log_buf, nowait = true, silent = true })
        end
      end)
    end,
  })
end, {
  nargs = '*',
  complete = function() return { 'sync', 'rollover', 'new', '--dry-run' } end,
  desc = 'Run sprint-sync on current sprint file (floating log)',
})

vim.api.nvim_create_user_command('SprintSyncLog', function()
  if last_buf and vim.api.nvim_buf_is_valid(last_buf) then
    local w = math.floor(vim.o.columns * 0.8)
    local h = math.floor(vim.o.lines * 0.7)
    vim.api.nvim_open_win(last_buf, true, {
      relative = 'editor',
      width = w, height = h,
      row = math.floor((vim.o.lines - h) / 2),
      col = math.floor((vim.o.columns - w) / 2),
      style = 'minimal', border = 'rounded',
      title = ' sprint-sync log ', title_pos = 'center',
    })
  else
    vim.notify('no prior sprint-sync log', vim.log.levels.WARN)
  end
end, { desc = 'Reopen last sprint-sync log' })

-- Auto-reload sprint files when they change on disk (e.g. after CLI sync)
vim.api.nvim_create_autocmd({ 'FocusGained', 'BufEnter', 'CursorHold' }, {
  pattern = '*/sprints/sprint_*.md',
  callback = function() vim.cmd('checktime') end,
})

return M
