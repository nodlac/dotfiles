-- blink.cmp source: complete sprint task markers and heading names
-- inside "[...]" at the start of a markdown task line.
--
-- Triggered when: current line matches `^%s*-%s*%[` and no `]` yet,
-- i.e. cursor is between the opening bracket and the close of a
-- task-line marker. Suggestions cover:
--   * single-char status markers: ' ', '/', '>', 'x', 'c', 'a', 'd', 'p'
--   * digit prefix (NN) reminder for push-to-sprint
--   * any # / ## / ### heading from the current buffer (for [<topic>]
--     filing) — inserted as the raw heading text, matched by sprint-sync.

local M = {}

function M.new(opts)
  return setmetatable({ opts = opts or {} }, { __index = M })
end

local STATUS_ITEMS = {
  { label = " ",  detail = "todo"           },
  { label = "/",  detail = "in progress"    },
  { label = ">",  detail = "qa"             },
  { label = "x",  detail = "done"           },
  { label = "c",  detail = "closed"         },
  { label = "d",  detail = "delete"         },
  { label = "~",  detail = "blocked / waiting" },
  { label = "!",  detail = "urgent"         },
  { label = "NN", detail = "attach to sprint NN — replace NN with digits" },
  { label = "FF", detail = "park for future (undecided sprint)" },
}

local function in_bracket_context()
  local line = vim.api.nvim_get_current_line()
  local col = vim.api.nvim_win_get_cursor(0)[2]
  local before = line:sub(1, col)
  -- Must look like "- [<stuff-no-close-bracket>"
  if not before:match("^%s*%-%s*%[") then return false end
  local open = before:find("%[[^%]]*$")
  return open ~= nil
end

function M:enabled()
  return vim.bo.filetype == "markdown" and in_bracket_context()
end

function M:get_completions(ctx, callback)
  if not in_bracket_context() then
    callback({ items = {}, is_incomplete_forward = false, is_incomplete_backward = false })
    return function() end
  end

  local items = {}

  for _, s in ipairs(STATUS_ITEMS) do
    table.insert(items, {
      label = s.label,
      kind = vim.lsp.protocol.CompletionItemKind.Keyword,
      detail = s.detail,
      insertText = s.label,
      sortText = "0_" .. s.label,
    })
  end

  -- Headings from current buffer
  local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  local seen = {}
  for _, line in ipairs(lines) do
    local txt = line:match("^%s*#+%s+(.+)$")
    if txt and not seen[txt] then
      seen[txt] = true
      table.insert(items, {
        label = txt,
        kind = vim.lsp.protocol.CompletionItemKind.Folder,
        detail = "heading",
        insertText = txt,
        sortText = "1_" .. txt:lower(),
      })
    end
  end

  callback({
    items = items,
    is_incomplete_forward = false,
    is_incomplete_backward = false,
  })
  return function() end
end

function M:get_trigger_characters()
  return { "[" }
end

return M
