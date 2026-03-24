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
    end,
    config = function()
      vim.keymap.set('n', '<leader>r', '<cmd>DBUIToggle<cr>', { desc = 'Toggle DB Sidebar' })
      vim.keymap.set('n', '<leader><CR>', 'vip:DB<cr>', { desc = 'Run SQL block' })

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
              '',
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
