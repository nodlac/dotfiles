return {
  {
    'kristijanhusak/vim-dadbod-ui',
    dependencies = {
      'tpope/vim-dadbod',
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

      vim.g.db_ui_save_location = vim.fn.expand '~/scripts'
      vim.g.db_ui_tmp_query_location = vim.fn.expand '~/scripts/queries'
      vim.g.db_ui_default_query = 'SELECT * from "{table}" LIMIT 500;'
      vim.g.db_ui_show_help = 0
      vim.g.db_ui_use_nerd_fonts = 1
      vim.g.db_adapter_postgres_params = '--set statement_timeout=300000'  -- 5min timeout

    end,
    config = function()
      -- DB names used in DBUI drawer (maps to ensure-tunnel script names)
      local db_names = { 'bim_prod', 'bim_stag', 'finn_prod', 'finn_stag' }

      local function ensure_tunnel(db_name)
        vim.notify('Checking SSH tunnel for ' .. db_name .. '...', vim.log.levels.INFO)
        local result = vim.fn.system(vim.fn.expand('~/tools/ensure-tunnel') .. ' ' .. db_name)
        if vim.v.shell_error ~= 0 then
          vim.notify('Tunnel failed for ' .. db_name .. ': ' .. result, vim.log.levels.ERROR)
        end
      end

      -- DBUI drawer keybindings
      vim.api.nvim_create_autocmd('FileType', {
        pattern = 'dbui',
        callback = function()
          vim.keymap.set('n', 't', '<Plug>(DBUI_SelectLine)', { buffer = true, desc = 'DBUI toggle' })
          vim.keymap.set('n', 'r', function()
            local line = vim.fn.getline('.')
            for _, name in ipairs(db_names) do
              if line:find(name, 1, true) then
                ensure_tunnel(name)
                break
              end
            end
          end, { buffer = true, desc = 'DBUI reconnect tunnel' })
          vim.keymap.set('n', '<CR>', function()
            local line = vim.fn.getline('.')
            for _, name in ipairs(db_names) do
              if line:find(name, 1, true) then
                ensure_tunnel(name)
                break
              end
            end
            vim.cmd('execute "normal \\<Plug>(DBUI_SelectLine)"')
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
              '*',
              'FROM ',
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
