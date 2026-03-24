return {
  {
    'tpope/vim-dadbod',
    dependencies = {
      'kristijanhusak/vim-dadbod-ui',
      'kristijanhusak/vim-dadbod-completion',
    },
    init = function()
      -- These must be set BEFORE dadbod-ui plugin/db_ui.vim sources
      vim.g.dbs = {
        { name = 'bim_prod', url = os.getenv 'BIM_URL' },
        { name = 'finn_prod', url = os.getenv 'FINN_URL' },
        { name = 'bim_stag', url = os.getenv 'BIM_STAGING_URL' },
        { name = 'finn_stag', url = os.getenv 'FINN_STAGING_URL' },
      }

      vim.g.db_ui_save_location = vim.fn.expand '~/Scripts'
      vim.g.db_ui_tmp_query_location = vim.fn.expand '~/Scripts/queries'
      vim.g.db_ui_default_query = 'SELECT * from "{table}" LIMIT 500;'
      vim.g.db_ui_show_help = 0
      vim.g.db_ui_use_nerd_fonts = 1
      vim.g.db_adapter_postgres_params = { '--set', 'statement_timeout=300000' }  -- 5min timeout
    end,
    config = function()
      local log_path = vim.fn.expand '~/dadbod-debug.log'
      local function dblog(msg)
        local f = io.open(log_path, 'a')
        if f then
          f:write(os.date '%Y-%m-%d %H:%M:%S' .. ' | ' .. msg .. '\n')
          f:close()
        end
      end

      -- SSH tunnel config: db name -> { port, evaql_domain, evaql_env }
      local tunnels = {
        bim_prod  = { port = 24601, domain = 'bim',      env = 'production' },
        bim_stag  = { port = 24602, domain = 'bim',      env = 'staging' },
        finn_prod = { port = 24603, domain = 'finnegan',  env = 'production' },
        finn_stag = { port = 24604, domain = 'finnegan',  env = 'staging' },
      }

      local tunnel_session = 'tunnels'

      local function ensure_tunnel(db_name)
        local t = tunnels[db_name]
        if not t then
          dblog('no tunnel config for: ' .. tostring(db_name))
          return
        end
        -- Check if port is already listening
        local check = vim.fn.system('lsof -iTCP:' .. t.port .. ' -sTCP:LISTEN -t 2>/dev/null')
        if check ~= '' then
          dblog('tunnel already open for ' .. db_name .. ' on port ' .. t.port)
          return
        end
        -- Kill any dead pane for this db before opening a new one
        local has_session = vim.fn.system('tmux has-session -t ' .. tunnel_session .. ' 2>/dev/null; echo $?'):gsub('%s+', '')
        if has_session == '0' then
          -- Find and kill panes whose title or command contains this db's evaql args
          local panes = vim.fn.system(string.format(
            "tmux list-panes -t %s -F '#{pane_id} #{pane_current_command}' 2>/dev/null",
            tunnel_session
          ))
          for pane_id, cmd_name in panes:gmatch('(%%%d+) (%S+)') do
            -- Kill panes that are sitting at a shell (tunnel died) or waiting on read
            if cmd_name == 'zsh' or cmd_name == 'bash' or cmd_name == 'read' then
              vim.fn.system('tmux kill-pane -t ' .. pane_id .. ' 2>/dev/null')
            end
          end
          -- Re-check if session still exists after cleanup
          has_session = vim.fn.system('tmux has-session -t ' .. tunnel_session .. ' 2>/dev/null; echo $?'):gsub('%s+', '')
        end

        local cmd = string.format('evaql %s %s; echo "Tunnel closed. Press enter to exit."; read', t.domain, t.env)
        if has_session ~= '0' then
          vim.fn.system(string.format(
            "tmux new-session -d -s %s -n tunnels '%s'",
            tunnel_session, cmd
          ))
        else
          vim.fn.system(string.format(
            "tmux split-window -t %s -h '%s'",
            tunnel_session, cmd
          ))
        end
        vim.notify('Opening SSH tunnel for ' .. db_name .. '...', vim.log.levels.INFO)
        dblog('opening tunnel for ' .. db_name)
        -- Poll until port is listening (up to 30s)
        for _ = 1, 30 do
          vim.fn.system('sleep 1')
          local up = vim.fn.system('lsof -iTCP:' .. t.port .. ' -sTCP:LISTEN -t 2>/dev/null')
          if up ~= '' then
            dblog('tunnel open for ' .. db_name)
            return
          end
        end
        dblog('tunnel timeout for ' .. db_name)
        vim.notify('Tunnel for ' .. db_name .. ' failed to open after 30s', vim.log.levels.ERROR)
      end

      -- Remap <CR> in DBUI drawer to check tunnel before expanding
      vim.api.nvim_create_autocmd('FileType', {
        pattern = 'dbui',
        callback = function()
          vim.keymap.set('n', '<CR>', function()
            local line = vim.fn.getline('.')
            dblog('drawer CR pressed, line: ' .. line)
            -- Extract db name from drawer line (strip icons/whitespace)
            for name, _ in pairs(tunnels) do
              if line:find(name, 1, true) then
                dblog('matched db: ' .. name)
                ensure_tunnel(name)
                break
              end
            end
            -- Pass through to DBUI's original handler
            local keys = vim.api.nvim_replace_termcodes('<Plug>(DBUI_SelectLine)', true, false, true)
            vim.api.nvim_feedkeys(keys, 'm', false)
          end, { buffer = true, desc = 'DBUI select with tunnel' })
        end,
      })

      vim.keymap.set('n', '<leader>r', '<cmd>DBUIToggle<cr>', { desc = 'Toggle DB Sidebar' })
      vim.keymap.set('n', '<leader><CR>', 'vip:DB<cr>', { desc = 'Run SQL block' })
      vim.keymap.set('n', '<S-CR>', 'vip:DB<cr>', { desc = 'Run SQL block' })
      vim.keymap.set('i', '<S-CR>', '<Esc>vip:DB<cr>', { desc = 'Run SQL block' })

      -- Insert template into new DBUI query buffers
      -- DBUI buffers have no .sql extension, so match on FileType instead
      vim.api.nvim_create_autocmd('FileType', {
        pattern = { 'sql' },
        callback = function()
          if vim.b.dbui_db_key_name and vim.api.nvim_buf_line_count(0) <= 1 and vim.api.nvim_buf_get_lines(0, 0, 1, false)[1] == '' then
            local template = {
              '-- Date: ' .. os.date '%Y-%m-%d',
              '',
              'SELECT ',
              'LIMIT 500;',
            }
            vim.api.nvim_buf_set_lines(0, 0, -1, false, template)
            vim.api.nvim_win_set_cursor(0, { 3, 7 }) -- cursor after "SELECT "
          end
        end,
      })
    end,
  },
}
