# Cross-platform dotfiles refactor — agent brief

Refactor the GitHub repository `nodlac/dotfiles` into a clean, portable, cross-platform dotfiles system.

## Goal

A new machine should be able to clone the repository, run one documented setup command, and have the correct shell environment configured safely.

## Target environments

- Arch/EndeavourOS Linux — Behemoth
- Ubuntu Server — Callisto
- Ubuntu under WSL2 — Somnambulist
- macOS
- Work machine — Medina Station (verify OS and requirements rather than assuming)

## Architecture requirements

1. Create one documented setup entry point, such as `setup.sh`.
2. Detect OS, distribution, and WSL2 where relevant.
3. Separate shared, platform-specific, and machine-specific configuration.
4. Consolidate duplicated setup logic without dropping existing functionality.
5. Make setup idempotent and safe to rerun.
6. Handle pre-existing files and symlinks carefully; back up conflicts rather than overwriting silently.
7. Keep machine-specific overrides separate from portable configuration.
8. Avoid installing desktop-only tools on headless servers.
9. Prefer straightforward shell scripts and minimal dependencies.

## Git requirements

- Standardize the dotfiles Git alias as `dtf` across all machines.
- Never override the native Unix `df` command.
- Update dependent aliases, scripts, documentation, and tests consistently.
- Audit the existing bare-Git-directory / home-worktree architecture; retain it only if justified, otherwise propose a safe migration.
- Preserve branches and local configurations during migration.
- Setup must never automatically commit, merge, push, or delete user files.

## Tests and CI

1. Inspect and run existing tests before making changes; record the baseline.
2. Identify incorrect, brittle, or incomplete tests and fix them for valid reasons, never merely to obtain green CI.
3. Test OS/WSL detection, setup entry point presence, symlink creation and conflicts, idempotency, missing scripts, and config loading.
4. Verify `df` remains the native command and `dtf` works as intended.
5. Add or improve GitHub Actions CI as appropriate.
6. Distinguish automated checks from actual machine-specific verification; never claim a platform was tested if it wasn't.

## Safety constraints

- Do not access, read, modify, or expose `.env` files, credentials, secrets, or private work notes.
- Do not delete or overwrite existing configuration without explicit approval.
- Work on a new feature branch, not directly on `main`.
- Present implementation changes in a pull request for review.
- Ask before destructive actions or architectural decisions that risk losing configuration.

## Known migration issue

Callisto was using a `server` branch with a different `.zshrc` from `main`. Checkout/pull conflicts involved `.zshrc` and `.mac-setup.sh`. The user created a backup at `~/.dotfiles.bak`, but the exact current branch, merge, and pull state was not fully verified. Do not assume synchronization or resolve conflicts destructively. Inspect and preserve both versions.

Perform the refactor in a clean checkout, not directly in Callisto's uncertain working tree. Migrate machines one at a time after review.

## Execution

1. Audit repository layout, scripts, aliases, branches, and supported behavior.
2. Record existing test baseline.
3. Propose target architecture and migration strategy.
4. Implement on a feature branch.
5. Expand and correct tests; run available checks.
6. Document setup and migration on each target platform.
7. Open a PR summarizing changes, risks, and unverified machine-specific steps.

## Definition of done

One documented bootstrap command; consistent portable configuration across supported platforms; safe machine-specific overrides; existing functionality preserved; meaningful tests passing; and an implementation PR ready for review.

Proceed autonomously within these constraints. Seek approval before destructive changes, restricted-file access, or high-risk architecture decisions.
