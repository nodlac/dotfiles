-- Enable treesitter highlighting (nvim 0.11+ with new nvim-treesitter needs this)
vim.treesitter.start(0, 'markdown')

-- Keep conceallevel at 0 so delimiters stay visible
vim.opt_local.conceallevel = 0

-- Checkbox highlight groups — distinct, high-contrast palette
vim.api.nvim_set_hl(0, 'CbDone',    { fg = '#ff007c' })  -- party pink
vim.api.nvim_set_hl(0, 'CbProgress',{ fg = '#7aa2f7' })  -- blue (in progress)
vim.api.nvim_set_hl(0, 'CbUrgent',  { fg = '#ff9e64' })  -- orange
vim.api.nvim_set_hl(0, 'CbReview',  { fg = '#bb9af7' })  -- purple (QA)
vim.api.nvim_set_hl(0, 'CbBlocked', { fg = '#f7768e' })  -- red
vim.api.nvim_set_hl(0, 'CbAlt',     { fg = '#0db9d7' })  -- cyan
vim.api.nvim_set_hl(0, 'CbCode',    { fg = '#73daca' })  -- teal
vim.api.nvim_set_hl(0, 'CbDefer',   { fg = '#565f89' })  -- muted slate (delete)

-- Checkboxes (higher priority so they override treesitter)
vim.fn.matchadd('CbDone',     '\\[x\\]', 20)   -- done
vim.fn.matchadd('CbProgress', '\\[/\\]', 20)   -- in progress
vim.fn.matchadd('CbUrgent',   '\\[!\\]', 20)   -- urgent
vim.fn.matchadd('CbReview',   '\\[>\\]', 20)   -- in review
vim.fn.matchadd('CbBlocked',  '\\[\\~\\]', 20) -- blocked/dependent
vim.fn.matchadd('CbAlt',      '\\[a\\]', 20)   -- alternative
vim.fn.matchadd('CbCode',     '\\[c\\]', 20)   -- in code
vim.fn.matchadd('CbDefer',    '\\[d\\]', 20)   -- delegated/deferred

-- TECH ticket references — inherit color from checkbox on same line
vim.api.nvim_set_hl(0, 'TechId', { fg = '#c0caf5' })  -- fallback: text white
vim.fn.matchadd('TechId',      '\\%(^\\|\\s\\)\\zsTECH-\\d\\+\\ze\\%($\\|\\s\\)', 20)
vim.fn.matchadd('CbDone',      '\\[x\\].\\{-}\\zsTECH-\\d\\+', 21)
vim.fn.matchadd('CbProgress',  '\\[/\\].\\{-}\\zsTECH-\\d\\+', 21)
vim.fn.matchadd('CbUrgent',    '\\[!\\].\\{-}\\zsTECH-\\d\\+', 21)
vim.fn.matchadd('CbReview',    '\\[>\\].\\{-}\\zsTECH-\\d\\+', 21)
vim.fn.matchadd('CbBlocked',   '\\[\\~\\].\\{-}\\zsTECH-\\d\\+', 21)
vim.fn.matchadd('CbAlt',       '\\[a\\].\\{-}\\zsTECH-\\d\\+', 21)
vim.fn.matchadd('CbCode',      '\\[c\\].\\{-}\\zsTECH-\\d\\+', 21)
vim.fn.matchadd('CbDefer',     '\\[d\\].\\{-}\\zsTECH-\\d\\+', 21)

-- Purple markdown links [text](https://...)
vim.api.nvim_set_hl(0, 'MdLink', { fg = '#c792ea' })
vim.fn.matchadd('MdLink', '\\[[^]]*\\]([^)]*)', 20)

-- Date stamps YYYY-MM-DD
vim.fn.matchadd('Number', '\\d\\{4}-\\d\\{2}-\\d\\{2}', 20)

