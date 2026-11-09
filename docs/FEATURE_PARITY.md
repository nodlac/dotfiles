# Feature inventory and deliberate safety changes

This refactor separates **configuration bootstrap** from privileged machine
provisioning. It does not promise byte-for-byte reproduction of every old
installer side effect. Obsolete installers, compatibility loaders and duplicate
snapshots have been removed from the active tree. Their original source is
preserved in Git history at audit commit
`575d0e8292aeb6b0cd920126cc41334eca33ee72`:

- `.dotfiles/.eos-setup.sh`, `.dotfiles/.mac-setup.sh`, `.dotfiles/.server-setup.sh`
- `.dotfiles/.zshrc`, `.dotfiles/.tmux.conf` and the old package inventories

This is historical source for review, not a supported install path. Do not run
whole old installers against a live home. Port individual, reviewed tasks
separately when needed. The current entry points are `setup.sh` and `tests/run.sh`.

| Existing behavior | New location / disposition |
| --- | --- |
| Shared PATH, editor, pyenv, Go PATH, history, completion, vi cursor, word jumps | `config/shared/zshenv`, `zshrc`; PATH deduplication and optional dependency guards |
| Cloudflare tunnel and SQL export functions | Preserved in `config/optional/helpers.zsh`; explicitly source from an approved local override after reviewing external tool dependencies. No function runs just by sourcing it. |
| `dtf`, test and quick-commit helpers | Conventional checkout-scoped `dtf`, `dtf-test`, explicit `dtf-quick-commit`; native `df` untouched |
| Platform installer aliases | Replaced by `dotfiles-setup`; obsolete wrappers and old script paths removed |
| Server helpers, prompt, tmux attach | `machines/callisto.zsh`; duplicate `.zsh/.server.zsh` removed; no environment-file role detection |
| Personal / work-specific shell profiles | Existing tracked files left unchanged and unmanaged; never implicitly sourced. Owner-approved settings belong in `local.zsh`. No private work notes inspected. |
| Shared tmux navigation, restore, theme, mouse, clipboard, pane dimming | `config/shared/tmux.conf`; TPM guarded when missing; zoom moved to prefix-z because prefix-m previously got overwritten by mouse-toggle |
| Callisto yerba-mate shortcut | `machines/callisto.tmux.conf`, explicit machine selection |
| Work todo header / toggle bindings | Original config preserved as `.dotfiles/.tmux.conf` in the audit commit above. Required `tmux-todo.sh` is not tracked in the audited checkout. Do not activate a broken helper or read private notes to reconstruct it. Owner must recover/review it separately, then add an approved local tmux override. |
| Zsh plugins, TPM and tmux plugins | Single shared implementation via `--install-plugins`; no pulls into existing clones |
| Linux CLI, development, media and AI package lists | `platform/packages/arch.txt`; desktop-only packages split out |
| macOS formulae / casks | `platform/packages/macos*.txt`; scrcpy is a desktop formula, not a cask. Existing package availability remains to be verified on target systems. |
| Ubuntu CLI packages / tmux build deps | `platform/packages/ubuntu.txt`; optional `golang-go` can be installed manually. No desktop stack. |
| Neovim config | Existing `.config/nvim` retained, opt-in `--link-nvim`; no automatic launch or plugin execution |
| Homebrew install / yay bootstrap / AUR packages | Manual, approved vendor/AUR installation. Reference recipes remain in Git history; no downloaded installer is executed by bootstrap. |
| npm globals | Old Mac list: `neovim`, `tree-sitter-cli`; old Arch list: `nopt`, `semver`. Install explicitly using a user-owned npm prefix; bootstrap never overwrites `.npmrc`. PATH includes `~/.npm-global/bin`. |
| Python globals | Old `argcomplete`, `glances`, `psutil`, `uv` inventory preserved here and in Git history. Use isolated virtualenvs/pipx/uv as appropriate; no automatic `--break-system-packages`. |
| OpenCode CLI | Existing PATH support retained; install via a separately reviewed vendor method. No `curl | sh`. |
| Source-built tmux / downloaded Neovim upgrades on Ubuntu | Historical recipes remain in Git history for review. Packaged tmux 3.4 is supported; obtain verified versioned tools separately rather than deleting/replacing `~/.local/nvim` or overwriting binaries. |
| Agent dashboard checkout/install | Remains a separate repository/task. Bootstrap never pulls, merges, or executes its installer. Keep existing checkout and local branches. |
| `tools/install.sh` and other work/personal scripts | Retained at existing paths, not automatically executed or linked into home/PATH; review dependencies separately. No blanket `~/tools` symlink. |
| Docker setup / groups / services | Manual, separately approved. Optional distro Docker packages remain in workstation CLI manifests; no daemon/group/firewall changes by setup. |
| Arch editor alternatives, keyd, NetworkManager/Bluetooth services | Reference recipe remains in Git history. No appending to unrelated shell files or writing `/etc/keyd` automatically. |
| macOS key repeat, Spotlight/hotkeys, Karabiner enablement / caps-to-Escape | Reference recipes remain in Git history. Rule asset linked only in desktop mode; activation, live JSON edits, OS defaults and permissions require separate owner review. |
| Login shell changes | Manual `chsh` using the actual installed/approved zsh path; setup does not alter account state |
| Credential/environment file creation or loading | Removed from automatic bootstrap/runtime config. Existing files remain untouched; owner controls any explicit local credential integration. |
| Git bare/worktree/hooks configuration changes | Removed from setup. Safe, reviewed normal-clone migration is documented; hook installation is explicit. |
| Hosting/Infisical deployment | Missing helpers are documented, not silently skipped as available or invented. No hosting deployment is included in dotfiles bootstrap. |

## Optional helper example

After reviewing the preserved helper source and its dependencies, an owner may
add this to their own `~/.config/dotfiles/local.zsh`:

```zsh
source "$DOTFILES_ROOT/config/optional/helpers.zsh"
```

SQL helpers expect approved database values already supplied by the owner's
credential mechanism and the existing `~/tools/ensure-tunnel`; bootstrap neither
reads those values nor installs that tool. The tunnel helper can recreate a
Docker container **only when explicitly invoked by the user**. It is not a setup
action. None of these helpers were executed during this refactor.

## Recovery evidence

The two named hosting helpers are absent at the documented paths in fetched
`main`, `server`, and reachable history for those paths. The old suite asserted
their executable bits unconditionally, producing two real baseline failures.
The replacement tests check managed required scripts and deliberately exercise
missing-source failures; they do not pretend an optional absent feature exists.
Recovery from Callisto or `~/.dotfiles.bak` is a separate permissioned task.
