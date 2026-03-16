 return {
  "avifenesh/claucode.nvim",
  config = function()
    require("claucode").setup()
  end,
}
-- return{
--   "wtfox/claude-chat.nvim",
--   config = true,
-- }
-- return {
--   "coder/claudecode.nvim",
--   dependencies = { "folke/snacks.nvim" },
--   config = true,
--   event = "VimEnter",  -- Add this line to load when Neovim starts
--   keys = {
--     { "<leader>e", nil, desc = "AI/Claude Code" },
--     { "<leader>ec", "<cmd>ClaudeCode<cr>", desc = "Toggle Claude" },
--     { "<leader>ef", "<cmd>ClaudeCodeFocus<cr>", desc = "Focus Claude" },
--     { "<leader>er", "<cmd>ClaudeCode --resume<cr>", desc = "Resume Claude" },
--     { "<leader>eC", "<cmd>ClaudeCode --continue<cr>", desc = "Continue Claude" },
--     { "<leader>em", "<cmd>ClaudeCodeSelectModel<cr>", desc = "Select Claude model" },
--     { "<leader>eb", "<cmd>ClaudeCodeAdd %<cr>", desc = "Add current buffer" },
--     { "<leader>es", "<cmd>ClaudeCodeSend<cr>", mode = "v", desc = "Send to Claude" },
--     {
--       "<leader>as",
--       "<cmd>ClaudeCodeTreeAdd<cr>",
--       desc = "Add file",
--       ft = { "NvimTree", "neo-tree", "oil", "minifiles", "netrw" },
--     },
--     -- Diff management
--     { "<leader>aa", "<cmd>ClaudeCodeDiffAccept<cr>", desc = "Accept diff" },
--     { "<leader>ad", "<cmd>ClaudeCodeDiffDeny<cr>", desc = "Deny diff" },
--   },
-- }
