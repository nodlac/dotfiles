# Dotfiles

Portable zsh/tmux configuration with a conservative, offline-first bootstrap.
New installs use a **conventional Git checkout**, not a Git directory inside the
home worktree. Existing installations are not automatically migrated.

## Fresh machine

Install Git and Bash using your OS's package manager. Clone into a separate,
permanent directory (not `$HOME` itself, `~/.dotfiles`, or a managed link target):

```sh
git clone https://github.com/nodlac/dotfiles.git ~/projects/dotfiles
cd ~/projects/dotfiles
./setup.sh
```

**`./setup.sh` is the one setup entry point.** By default it links shared zsh/tmux
configuration and selects the generic **headless** profile. It does not install
anything or change your login shell. Install zsh/tmux first or explicitly request
packages; start `zsh` to use the environment. Desktop tools are opt-in even on a
laptop. See [platform commands](docs/PLATFORMS.md) for machine-specific options.

### Preview, conflicts, and reruns

```sh
./setup.sh --dry-run
./setup.sh --machine behemoth --profile desktop --dry-run
```

Dry-run performs no writes, downloads, package installation, service operations,
or Git configuration changes. It reports detection, selected profile, links,
conflicts, planned backups and requested package/plugin actions. Conflicts exit
with status 2 and remain untouched. Invalid options or missing sources exit 1.

Existing files, directories, and even broken symlinks are **never silently
replaced**. Review conflicts first. Only if you explicitly approve moving them:

```sh
./setup.sh --machine behemoth --profile desktop --replace --dry-run
./setup.sh --machine behemoth --profile desktop --replace
```

`--replace` moves each conflicting object intact to a unique directory under
`~/.local/state/dotfiles/backups/<UTC timestamp>-<PID>/`, retaining its relative
path, then creates the new link. It never overwrites an existing backup. Correct
links are left unchanged, including their timestamps. Symlinked parent directories
are rejected rather than traversed. **Do not run concurrent setup processes.**
The preview's timestamp/PID will differ from a later real invocation.

Setup validates all sources and conflicts before changes. It is not a transaction
across disk failures or package-manager errors; completed links and backups remain
available if a later operation fails. Rerun after resolving the error.

### Optional installation

```sh
./setup.sh --install-packages --install-plugins --dry-run
./setup.sh --install-packages --install-plugins
```

Packages use apt-get, pacman or an already-installed Homebrew. Linux package
commands request sudo normally; do **not** invoke setup itself with sudo. Package
manifests are data, not sourced shell code. Existing plugin checkouts are kept
without pulling. Plugin code is third-party code; review before opting in.
There is no `curl | sh`, AUR-helper bootstrap, system upgrade, or automatic
execution of this repository's unrelated tool installers.

Use `--profile desktop` explicitly for supported desktop config/packages.
`--link-nvim` separately opts into the existing Neovim configuration; it requires
Neovim >= 0.10 and may install its own plugins when first opened. Ubuntu's packaged
Neovim may be too old: see [feature inventory](docs/FEATURE_PARITY.md).

## Configuration layers

```text
setup.sh                   Single entry point (Bash 3.2-compatible)
lib/setup.sh               Link, conflict, backup, package and plugin primitives
config/shared/             Portable zshenv, zshrc, tmux
config/optional/            Reviewed, explicitly sourced helpers only
platform/detect.sh         Linux/macOS, distribution, WSL1/2 detection
platform/*.zsh             OS-specific shell behavior
platform/packages/         CLI and separate desktop package manifests
machines/                  Public, non-secret machine overrides
~/.config/dotfiles/         User-owned local overrides; never replaced by setup
tests/                     Isolated regression checks
```

Desktop application configs stay in their existing repository paths to preserve
history. They are linked from an explicit allowlist, never by globbing every
hidden file. No SSH, credential, personal/work profile, or environment file is
installed or read by bootstrap. Unrelated `tools/` files stay in the checkout and
are not automatically installed into your home or added to PATH. Unreviewed
personal assets and private profiles from the old layout remain untouched;
they are not bootstrap modules.

Setup links the selected public machine files into `~/.config/dotfiles/`. It does
not infer machine identity from hostname. After shared/platform/machine settings,
zsh loads `~/.config/dotfiles/local.zsh` if present. tmux similarly loads
`~/.config/dotfiles/tmux.local.conf`. Keep private settings there, outside Git;
bootstrap and tests never inspect those files in your real home.

The root checkout is linked as `~/.local/share/dotfiles`. Keep the checkout at a
stable path; after moving it, rerun setup with the new path and review link
replacements. This version uses `~/.config`, `~/.local/share`, and `~/.local/state`
explicitly; it does not modify an existing `XDG_CONFIG_HOME` or other shell files.

## Git: `dtf`, never `df`

In a newly started configured zsh:

```sh
dtf status
dtf diff
dtf add config/shared/zshrc
dtf commit -m 'Update shell configuration'
dtf push
dtf-test
```

`dtf` is `git -C "$DOTFILES_ROOT"`, so operations are scoped to the checkout.
Native `df` remains the disk-space command. `dtf-quick-commit` is an explicit
user-invoked helper that stages tracked changes, opens a commit, then pushes;
setup never invokes it. `dotfiles-setup` reruns the unified entry point.
Obsolete platform installers, root config symlinks, and compatibility loaders
have been removed. Use `setup.sh` or `dotfiles-setup`, not the old script paths.
Historical recipes remain in Git history; see the feature inventory below.

Hooks are **not changed by setup**. If desired, explicitly enable the working-tree
checks with `dtf config core.hooksPath tools/git-hooks`; see [testing](docs/TESTING.md).

## Existing machines: review before migration

Follow [the migration guide](docs/MIGRATION.md), one machine at a time **after PR
review**. It preserves the old Git directory, branches, backup and local config.
Do not pull this refactor into a legacy home worktree as a migration shortcut.

Behemoth's canonical links were verified locally, and the owner confirmed
Callisto's new shell link and checkout-scoped `dtf`. Their old repositories/backups
remain separate; this cleanup does not retire them. See the migration guide for the original Callisto risk and subsequent
owner-reported checks. Medina Station's macOS migration is recorded in
[platform verification](docs/PLATFORMS.md); the personal MacBook and WSL2 machine
still need their own checks.

## Tests and verification

```sh
bash tests/run.sh
```

Tests require Python 3 and Git; install zsh/tmux for runtime loading checks. They
use disposable homes and allowlisted sources, not your live configuration.
[Testing notes](docs/TESTING.md) record the constrained pre-change baseline and
which checks are automated versus actual machine validation. GitHub Actions runs
the suite on Linux and macOS; a green fixture test is not a WSL/Callisto deployment.

See [feature preservation and deliberate safety changes](docs/FEATURE_PARITY.md)
before relying on an old installer behavior. Removed installers and the completed
refactor brief are available in Git history, not duplicated in the active tree.
