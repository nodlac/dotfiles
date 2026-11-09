# Safe migration: review first, one machine at a time

## Architecture decision

The old layout uses `~/.dotfiles` as a Git directory, `core.bare=false`, and
`core.worktree=$HOME`, mixing files checked directly into home with files inside
the Git directory linked back into home. This collides with existing home files,
requires special Git invocations, and made the `.zshrc` / `.mac-setup.sh` differences
between `main` and `server` confusing. Some tracked symlinks also embedded a user's
absolute home path.

New installs therefore use a conventional clone plus explicit links. This is a
**proposal implemented for fresh checkouts**, not permission to convert any live
machine. No script rewrites the old repository, checks out a branch, merges,
commits, pushes, deletes configuration, or migrates credentials. The old `.dotfiles`
files are compatibility loaders; new installs do not depend on them.

Do not fetch/checkout this refactor into `$HOME` to migrate. A normal checkout in a
separate directory allows review without touching the old worktree. Root symlinks
remain tracked for historical compatibility; they do not install themselves into
home when using a normal clone.

## Before each migration (owner approval required)

1. Confirm OS, distribution/WSL status, role, shell, installed tools, checkout path,
   and whether configs are managed by other software. Record any linked parent
   directories: setup intentionally refuses to traverse them.
2. Inspect the **old** repository's Git metadata without running installers or
   dumping configuration/private file contents:

   ```sh
   old="$HOME/.dotfiles"
   git --git-dir="$old" --work-tree="$HOME" status --short --branch
   git --git-dir="$old" branch -avv
   git --git-dir="$old" log -5 --oneline
   git --git-dir="$old" config --get core.bare
   git --git-dir="$old" config --get core.worktree
   git --git-dir="$old" ls-files -u
   ```

   These checks are instructions for the owner, not a claim we ran them on any
   remote machine. Do not `git add -A` from home, `reset --hard`, `clean`, force a
   checkout, or assume a pull completed. Keep credentials/private notes out of
   logs and review diffs locally only with appropriate permission.
3. Preserve the entire old repository, all local branches and relevant local
   configuration using your approved backup process. A Git bundle preserves
   committed refs only, **not** uncommitted content, repository config, ignored
   files or secrets. Do not treat it as a full backup. No broad backup command is
   automated here because it could access restricted material.
4. Keep existing backups intact. Inspect their contents only with permission.
   In particular, never replace Callisto's `~/.dotfiles.bak`.
5. Clone the reviewed refactor into a new permanent directory. Verify the branch
   or release you intend to use. Never point the new clone's worktree at home.

## Preview and activation

1. Run `./setup.sh --detect`, then the machine-specific command in PLATFORMS.md
   **with `--dry-run`**. Default is headless; desktop always requires explicit opt-in.
2. Review every conflict and installed feature you rely on. Shared config does
   not source environment files or the old personal/work profiles. With approval,
   port needed non-secret settings into the user-owned local override; preserve
   credential-loading behavior separately under the owner's control. Never copy
   private values into the repository or PR.
3. If satisfied, run the same setup without dry-run. A conflict still refuses
   activation. Only add `--replace` after approving backup + replacement of each
   listed conflict. No files are deleted; objects move intact into unique backups.
4. Open a **new** zsh (not merely a nested continuation of an old alias-heavy
   shell). Check `dtf status`, `whence df`, `df -P /`, PATH, completion, history,
   expected machine helpers and optional desktop behavior. Verify `dtf` points
   at the new checkout, not the old home worktree.
5. Validate tmux with a new isolated server before explicitly reloading the active
   one. For example `tmux -L migration-check -f ~/.tmux.conf new-session`;
   exit the test server when finished. Existing tmux sessions are not restarted.
6. Install optional packages/plugins separately after reviewing their plans.
   Changing login shell, enabling services, keyboard remapping and OS defaults
   are separate owner-approved tasks; see FEATURE_PARITY.md.
7. Keep the old Git directory, local branches and backups until the owner has
   validated and approved retirement. Avoid operating both Git layouts on the
   same linked configuration after migration.

## Callisto: do not assume synchronization

The known local checkout/pull conflicts involve `.zshrc` and `.mac-setup.sh`, and
its local branch/merge/rebase state has **not** been independently checked. The
remote refs observed during this work were:

- `main`: `575d0e8292aeb6b0cd920126cc41334eca33ee72`
- `server`: `bbd8f35cac586965bceef97c5cc5d40c86715e5d`

These hashes are audit evidence, not an instruction to reset to them. On those
fetched refs, the root `.zshrc` and `.mac-setup.sh` are symlinks on `main` and absent
on `server`; the `.dotfiles/.zshrc` contents compare equal. That does **not** prove
Callisto's working files match either remote version. Preserve its local versions,
unmerged index stages and branches before reconciling anything. This PR does not
merge `server` into `main` or remove either branch.

`tools/server-hosting-setup.sh` and `tools/infisical-first-admin.sh` are referenced
by the old installer/tests but are absent at those paths in both fetched branches
and their reachable history. Search other approved backups/locations separately;
do not fabricate a replacement or execute hosting steps during dotfiles migration.

## Rollback (manual, approved)

Backups are grouped under `~/.local/state/dotfiles/backups/<timestamp>-<PID>/`.
Review the selected backup and live targets first. Move the newly created link
aside to a fresh holding location, then move the corresponding backup object back
to its original path. Do not overwrite the current target or another backup.
Restart the shell/reload tmux only after restoring the desired config. There is
no automatic rollback script that could remove new user edits or guess which
backup is authoritative. Package installation requires its own rollback review.
