-- SprintSync: save → run sprint-sync → reload buffer
vim.api.nvim_create_user_command('SprintSync', function(opts)
  local bufname = vim.api.nvim_buf_get_name(0)
  if not bufname:match('sprint_%d+%.md$') then
    vim.notify('SprintSync: not a sprint file', vim.log.levels.WARN)
    return
  end

  vim.cmd('write')

  local cmd = { vim.fn.expand('~/tools/sprint-sync') }
  for _, arg in ipairs(opts.fargs) do
    if arg ~= 'sync' then
      table.insert(cmd, arg)
    end
  end

  vim.notify('sprint-sync: running...', vim.log.levels.INFO)

  vim.fn.jobstart(cmd, {
    stdout_buffered = true,
    stderr_buffered = true,
    on_stdout = function(_, data)
      if data and #data > 0 then
        local output = table.concat(data, '\n')
        if output:match('%S') then
          vim.schedule(function()
            vim.notify(output, vim.log.levels.INFO)
          end)
        end
      end
    end,
    on_stderr = function(_, data)
      if data and #data > 0 then
        local output = table.concat(data, '\n')
        if output:match('%S') then
          vim.schedule(function()
            vim.notify(output, vim.log.levels.ERROR)
          end)
        end
      end
    end,
    on_exit = function(_, code)
      vim.schedule(function()
        if code == 0 then
          vim.cmd('edit')
          vim.notify('sprint-sync: done', vim.log.levels.INFO)
        else
          vim.notify('sprint-sync: failed (exit ' .. code .. ')', vim.log.levels.ERROR)
        end
      end)
    end,
  })
end, {
  nargs = '*',
  complete = function()
    return { 'sync', 'rollover', 'new', '--dry-run' }
  end,
  desc = 'Run sprint-sync on the current sprint file',
})

-- Auto-reload sprint files when they change on disk (e.g. after CLI sync)
vim.api.nvim_create_autocmd({ 'FocusGained', 'BufEnter', 'CursorHold' }, {
  pattern = '*/sprints/sprint_*.md',
  callback = function()
    vim.cmd('checktime')
  end,
})

return {}
