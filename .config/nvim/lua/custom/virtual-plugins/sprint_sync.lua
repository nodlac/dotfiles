-- SprintSync: save → run sprint-sync → reload buffer (live floating output)
local M = {}
local last_buf = nil  -- reopenable log buffer

local function open_float(title)
  local buf = vim.api.nvim_create_buf(false, true)
  vim.bo[buf].bufhidden = 'wipe'
  vim.bo[buf].filetype = 'sprintsync'
  local w = math.floor(vim.o.columns * 0.8)
  local h = math.floor(vim.o.lines * 0.7)
  local win = vim.api.nvim_open_win(buf, false, {
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

local function append(buf, lines)
  if not lines or #lines == 0 then return end
  -- Filter trailing empty entry that jobstart emits
  local clean = {}
  for i, l in ipairs(lines) do
    if not (i == #lines and l == '') then
      table.insert(clean, l)
    end
  end
  if #clean == 0 then return end
  if not vim.api.nvim_buf_is_valid(buf) then return end
  local n = vim.api.nvim_buf_line_count(buf)
  local last = vim.api.nvim_buf_get_lines(buf, n - 1, n, false)[1] or ''
  -- First chunk concatenates with last line (partial line support)
  clean[1] = last .. clean[1]
  vim.api.nvim_buf_set_lines(buf, n - 1, n, false, clean)
  -- Scroll windows showing this buffer to bottom
  for _, win in ipairs(vim.api.nvim_list_wins()) do
    if vim.api.nvim_win_get_buf(win) == buf then
      vim.api.nvim_win_set_cursor(win, { vim.api.nvim_buf_line_count(buf), 0 })
    end
  end
end

vim.api.nvim_create_user_command('SprintSync', function(opts)
  local bufname = vim.api.nvim_buf_get_name(0)
  local sprint_buf = 0
  if not bufname:match('sprint_%d+%.md$') then
    vim.notify('SprintSync: not a sprint file', vim.log.levels.WARN)
    return
  end

  vim.cmd('write')

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
    pty = true,  -- preserve line breaks + flushing
    on_stdout = function(_, data)
      vim.schedule(function() append(log_buf, data) end)
    end,
    on_stderr = function(_, data)
      vim.schedule(function() append(log_buf, data) end)
    end,
    on_exit = function(_, code)
      vim.schedule(function()
        append(log_buf, { '', code == 0 and '[done]' or ('[exit ' .. code .. ']') })
        -- Reload sprint buffer (if still current)
        if vim.api.nvim_buf_is_valid(sprint_buf) then
          vim.api.nvim_buf_call(sprint_buf, function() vim.cmd('edit') end)
          if vim.api.nvim_get_current_buf() == sprint_buf then
            pcall(vim.fn.winrestview, view)
            pcall(vim.api.nvim_win_set_cursor, 0, cursor)
          end
        end
        if code == 0 then
          vim.defer_fn(function()
            if vim.api.nvim_win_is_valid(log_win) then
              vim.api.nvim_win_close(log_win, true)
            end
          end, 1500)
        else
          vim.notify('sprint-sync: failed (exit ' .. code .. ') — press q to close log', vim.log.levels.ERROR)
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
