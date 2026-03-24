#!/usr/bin/env zsh
# Opens a ClickUp task in the browser
# Usage: clickup-open TECH-3684
TEAM_ID="${CLICKUP_TEAM_ID:-14252037}"
open "https://app.clickup.com/t/${TEAM_ID}/$1"
