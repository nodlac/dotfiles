#!/bin/bash
jq -r '.context_window // empty
  | (.context_window_size // 200000) as $size
  | (if .current_usage then (.current_usage.input_tokens // 0) + (.current_usage.cache_creation_input_tokens // 0) + (.current_usage.cache_read_input_tokens // 0)
     else (.used_percentage // 0) * $size / 100 end) as $t
  | "ctx \($t / 1000 | floor)K"
  | if $t > 150000 then "\u001b[31m\(.)\u001b[0m" else . end' 2>/dev/null
