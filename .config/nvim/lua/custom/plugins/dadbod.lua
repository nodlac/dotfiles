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
        if not t then return end
        -- Check if port is already listening
        local check = vim.fn.system('lsof -iTCP:' .. t.port .. ' -sTCP:LISTEN -t 2>/dev/null')
        if check ~= '' then return end
        -- Ensure the tunnels session exists
        local has_session = vim.fn.system('tmux has-session -t ' .. tunnel_session .. ' 2>/dev/null; echo $?'):gsub('%s+', '')
        if has_session ~= '0' then
          vim.fn.system(string.format(
            "tmux new-session -d -s %s -n '%s' 'evaql %s %s'",
            tunnel_session, db_name, t.domain, t.env
          ))
        else
          vim.fn.system(string.format(
            "tmux new-window -t %s -n '%s' 'evaql %s %s'",
            tunnel_session, db_name, t.domain, t.env
          ))
        end
        vim.notify('Opening SSH tunnel for ' .. db_name .. '...', vim.log.levels.INFO)
        vim.fn.system('sleep 3')
      end

      local function run_query_with_tunnel(keys)
        local db_name = vim.b.dbui_db_key_name or vim.b.db_key_name
        if db_name then
          ensure_tunnel(db_name)
        end
        return vim.api.nvim_feedkeys(vim.api.nvim_replace_termcodes(keys, true, false, true), 'n', false)
      end

      vim.keymap.set('n', '<leader>r', '<cmd>DBUIToggle<cr>', { desc = 'Toggle DB Sidebar' })
      vim.keymap.set('n', '<leader><CR>', function() run_query_with_tunnel('vip:DB<cr>') end, { desc = 'Run SQL block' })
      vim.keymap.set('n', '<S-CR>', function() run_query_with_tunnel('vip:DB<cr>') end, { desc = 'Run SQL block' })
      vim.keymap.set('i', '<S-CR>', function() run_query_with_tunnel('<Esc>vip:DB<cr>') end, { desc = 'Run SQL block' })

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
