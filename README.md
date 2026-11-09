# Dotfiles

Portable shell configuration and machine setup for my personal computers and servers.

> **Status:** This repository is being prepared for a cross-platform refactor. The one-command bootstrap described below is the **target design**, not a claim that it works today. Existing setup scripts and the bare-Git workflow may still require machine-specific steps. Do not run an unfamiliar setup script without reviewing it.

## Supported environments (target)

| Machine | Environment | Intended role |
| --- | --- | --- |
| Behemoth | Arch / EndeavourOS | Linux workstation |
| Callisto | Ubuntu Server | Headless homelab server |
| Somnambulist | Ubuntu on WSL2 | Windows-hosted shell environment |
| MacBook | macOS | Laptop |
| Medina Station | Verify OS | Work machine with separate settings |

## Planned setup experience

The goal is a fresh checkout followed by **one documented bootstrap command**, for example:

```bash
git clone git@github.com:nodlac/dotfiles.git ~/dotfiles
cd ~/dotfiles
./setup.sh
```

**These commands illustrate the intended future workflow.** The refactor has not yet established that `setup.sh` exists or that this procedure is safe on current machines. Until implementation and testing are complete, follow the existing platform-specific scripts only after reviewing their behavior.

The future bootstrap should:

1. Detect Linux, macOS, or WSL2 and select appropriate steps.
2. Install or link shared shell configuration, with platform and machine overrides.
3. Avoid desktop dependencies on servers.
4. Preserve existing files through non-destructive backups and safe symlink handling.
5. Be idempotent: rerunning setup should not duplicate, corrupt, or silently replace configuration.
6. Keep credentials and local environment values outside the tracked portable configuration.

## Proposed organization

The refactor should aim for a simple layout along these lines, adapting to the existing repository rather than moving files blindly:

```text
setup.sh                # Future single entry point
config/                 # Shared shell and tool configuration
platform/               # OS-specific setup logic
machines/               # Non-secret, machine-specific overrides
tests/                  # Automated regression checks
docs/                   # Setup, migration, and design notes
```

This tree is **proposed**, not the current file layout.

## Git and aliases

Use `dtf` for dotfiles Git operations across machines. **Never alias `df`**, which is the native disk-space command. The refactor must update dependent helpers and tests consistently.

The existing repository uses a bare Git directory at `~/.dotfiles` with the home directory as its working tree. The refactor should assess whether to keep that model or migrate to a conventional checkout. Do not assume the two models can be mixed safely, and do not automatically commit, merge, push, or delete local files during setup.

## Machine migration

Do not migrate all machines at once. Start with a clean checkout and a test baseline, then review the implementation pull request. After approval, migrate and validate each machine separately.

**Callisto needs special care:** it previously used a `server` branch, with differences from `main` and checkout/pull conflicts involving `.zshrc` and `.mac-setup.sh`. A backup was made at `~/.dotfiles.bak`, but the final local Git state has not been independently verified. Preserve local settings and reconcile branches before migrating.

## Testing expectations

Tests should cover platform detection, WSL2 handling, script presence, symlink conflicts, safe reruns, configuration loading, and preservation of native `df`. Run the existing suite before changes, correct flawed tests only for sound reasons, and use CI where practical. Machine-specific testing must be reported separately from CI results.

## Security and change policy

Do not access or modify `.env` files, secrets, credentials, or private work notes. Do not overwrite or remove user configuration without approval. Make implementation changes on a feature branch and submit a pull request instead of pushing directly to `main`.

## Refactor specification

See [Cross-platform refactor agent brief](docs/CROSS_PLATFORM_REFACTOR_PROMPT.md) for the detailed requirements, execution plan, safety constraints, and definition of done.
