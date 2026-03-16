return {
    'kawre/leetcode.nvim',
    build = function()
      local ok, ts_update = pcall(require, 'nvim-treesitter.install').update
      if ok then
        ts_update { with_sync = true }
      end
    end,
    dependencies = {
      'nvim-lua/plenary.nvim',
      'MunifTanjim/nui.nvim',
      'nvim-treesitter/nvim-treesitter',
    },
    opts = {
      lang = 'go',
          cn = {
        enabled = false,
    },
      picker = 'telescope',
    },
}  
