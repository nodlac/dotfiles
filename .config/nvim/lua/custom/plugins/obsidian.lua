local workspaces = {}
for _, workspace in ipairs({
  { name = 'personal', path = '~/notes/nodlac_notes/' },
  { name = 'work', path = '~/notes/work_notes/' },
}) do
  if vim.fn.isdirectory(vim.fn.expand(workspace.path)) == 1 then
    table.insert(workspaces, workspace)
  end
end

return {
  'epwalsh/obsidian.nvim',
  version = '*', -- recommended, use latest release instead of latest commit
  enabled = #workspaces > 0,
  lazy = false,
  ft = 'markdown',
  -- Replace the above line with this if you only want to load obsidian.nvim for markdown files in your vault:
  -- event = {
  --   -- If you want to use the home shortcut '~' here you need to call 'vim.fn.expand'.
  --   -- E.g. "BufReadPre " .. vim.fn.expand "~" .. "/my-vault/*.md"
  --   -- refer to `:h file-pattern` for more examples
  --   "BufReadPre path/to/my-vault/*.md",
  --   "BufNewFile path/to/my-vault/*.md",
  -- },
  dependencies = {
    -- Required.
    'nvim-lua/plenary.nvim',
  },
  opts = {
    follow_url_func = function(url)
      vim.fn.jobstart({ 'open', '-a', 'Google Chrome', url })
    end,
    ui = {
      enable = false,
    },
    workspaces = workspaces,
  },
}
