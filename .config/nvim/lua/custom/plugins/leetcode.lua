return {
  'kawre/leetcode.nvim',
  event = "VeryLazy",
  dependencies = {
    'nvim-lua/plenary.nvim',
    'MunifTanjim/nui.nvim',
    'nvim-treesitter/nvim-treesitter',
  },
  opts = {
    lang = 'go',
    cn = { enabled = false },
    picker = 'telescope',
  },
}
