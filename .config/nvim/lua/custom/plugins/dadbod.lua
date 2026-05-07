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
          -- < closes an expanded node, > opens a collapsed one. dadbod-ui
          -- only exposes a toggle plug, so check expansion state on the
          -- current line and only act in the requested direction.
          local function dbui_dir(open)
            local line = vim.fn.getline('.')
            -- Expanded nodes render with a "down" glyph (▾, ▼, ↓ depending
            -- on font); collapsed with a "right" glyph (▸, ▶, →). Use the
            -- nerd-font icons dadbod-ui ships with by default.
            local is_expanded = line:match('[▾▼↓]') ~= nil
            if open and not is_expanded then
              vim.cmd('execute "normal \\<Plug>(DBUI_SelectLine)"')
            elseif (not open) and is_expanded then
              vim.cmd('execute "normal \\<Plug>(DBUI_SelectLine)"')
            end
          end
          vim.keymap.set('n', '<', function() dbui_dir(false) end,
            { buffer = true, desc = 'DBUI close expanded node' })
          vim.keymap.set('n', '>', function() dbui_dir(true) end,
            { buffer = true, desc = 'DBUI open collapsed node' })
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

      -- ── Fuzzy table search across all configured DBs ────────────────────
      -- Telescope picker over `db / table` — type freely, results match
      -- via subsequence ("contentuser" → "content_request_user").
      -- :DBFindTable          uses cache (fast)
      -- :DBFindTable!         force refresh (re-queries each DB)
      local table_cache = {}  -- db_name -> { "schema.table", ... }

      local function fetch_tables(db)
        ensure_tunnel(db.name)
        local ok, result = pcall(vim.fn['db#adapter#call'], db.url, 'tables', {}, {})
        if ok and type(result) == 'table' then
          return result
        end
        return {}
      end

      local function load_all_tables(force)
        for _, db in ipairs(vim.g.dbs or {}) do
          if force or not table_cache[db.name] then
            vim.notify('Loading tables for ' .. db.name .. '…', vim.log.levels.INFO)
            table_cache[db.name] = fetch_tables(db)
          end
        end
      end

      local function pick_table(force)
        load_all_tables(force)
        local items = {}
        for db_name, tables in pairs(table_cache) do
          for _, t in ipairs(tables) do
            table.insert(items, db_name .. '  /  ' .. t)
          end
        end
        if #items == 0 then
          vim.notify('No tables loaded — check tunnels and credentials', vim.log.levels.WARN)
          return
        end
        local has_telescope, _ = pcall(require, 'telescope.pickers')
        if not has_telescope then
          vim.notify('Telescope not available', vim.log.levels.ERROR)
          return
        end
        local pickers = require('telescope.pickers')
        local finders = require('telescope.finders')
        local conf = require('telescope.config').values
        local actions = require('telescope.actions')
        local action_state = require('telescope.actions.state')
        pickers.new({}, {
          prompt_title = 'DB Tables',
          finder = finders.new_table { results = items },
          sorter = conf.generic_sorter({}),
          attach_mappings = function(prompt_bufnr)
            actions.select_default:replace(function()
              local sel = action_state.get_selected_entry()
              actions.close(prompt_bufnr)
              if not sel then return end
              local db_name, tbl = sel[1]:match('^(.-)%s+/%s+(.+)$')
              if not db_name or not tbl then return end
              local url
              for _, db in ipairs(vim.g.dbs or {}) do
                if db.name == db_name then url = db.url; break end
              end
              if not url then return end
              if not url or url == '' then
                vim.notify('No URL for ' .. db_name .. ' (env var empty?)',
                  vim.log.levels.ERROR)
                return
              end
              ensure_tunnel(db_name)
              -- Open new buffer with explicit syntax so b:db lives in the
              -- right buffer. vim.cmd('let') is the most direct way to
              -- set a buffer-local var that dadbod will see.
              vim.cmd('new')
              local newbuf = vim.api.nvim_get_current_buf()
              vim.bo[newbuf].filetype = 'sql'
              vim.api.nvim_buf_set_lines(newbuf, 0, -1, false, {
                '-- ' .. db_name .. ' / ' .. tbl,
                '-- Date: ' .. os.date('%Y-%m-%d'),
                '',
                'SELECT *',
                'FROM ' .. tbl,
                'LIMIT 500;',
              })
              -- Use vim's `let` directly — survives any plugin that
              -- inspects b:db during buffer init.
              vim.cmd(string.format('let b:db = %s', vim.fn.string(url)))
              pcall(vim.api.nvim_win_set_cursor, 0, { 4, 7 })
            end)
            return true
          end,
        }):find()
      end

      vim.api.nvim_create_user_command('DBFindTable', function(opts)
        pick_table(opts.bang)
      end, { bang = true, desc = 'Fuzzy-find table across all DBs (! refreshes cache)' })

      vim.keymap.set('n', '<leader>rt', '<cmd>DBFindTable<cr>',
        { desc = 'DB find table (fuzzy)' })

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
