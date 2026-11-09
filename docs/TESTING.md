# Testing and audit record

## Pre-change baseline

Audit base: `575d0e8292aeb6b0cd920126cc41334eca33ee72` (`main`). A separate
conventional checkout and feature branch were created; the live home-worktree and
Callisto were not modified.

The original `.dotfiles/test.sh` assumes `$HOME` is the Git worktree, reads an
environment template, scans all tracked content for secrets, and invokes installed
applications against home paths. Running it on the real home would violate this
task's restricted-file policy. Instead, its **unchanged** contents were run in an
isolated temporary home with a minimal Git index containing explicitly allowlisted
installer scripts, shell/tmux/desktop config, and `tools/ensure-tunnel`. Restricted
files, personal/work profiles and unrelated tools were not copied or scanned.

Recorded result: **exit 1; 35 passed, 2 failed, 1 skipped**. Failures:

- `tools/server-hosting-setup.sh is executable`
- `tools/infisical-first-admin.sh is executable`

Both scripts are genuinely absent from the audited `main`, not merely omitted
from an otherwise available baseline. Aerospace was skipped because not installed.
The missing environment-template grep printed an error but the old suite counted
it as a pass: this is an invalid success condition, not evidence of a clean secret
scan. No unrestricted original-suite pass is claimed.

Other original-test problems:

- Hardcoded `$HOME/.dotfiles`, validators using live application paths.
- Syntax dispatch based partly on the first 200 bytes of file content/path;
  missing files silently skipped.
- Python bytecode compiled beside working files; tests could dirty a checkout.
- GNU/BSD Lua compiler options conflated; no actual supported-platform CI.
- String matches for specific old setup implementations substituted for behavioral
  tests (e.g. looking for `core.hooksPath` even though setup should not change it).
- tmux plugin startup and credential-file sourcing were possible while testing.
- Working-tree tests were not staged-index tests, despite being a commit hook.

The new runner replaces those checks for documented reasons, not just to obtain
green CI. The independent Ghostty/Aerospace/keyboard regression checks remain.
There is no live secret scan in this suite: restricted files require a separately
authorized security review and must never be printed in CI logs.

## Current suite

Local implementation result: **54 tests passed, no skips**, on Behemoth Linux
using disposable homes (zsh and tmux loading checks included). Workflow YAML
also parsed with Ruby's YAML library, and `git diff --check` passed. These are
not claims of actual machine migration or package-manager installation testing.

```sh
bash tests/run.sh
```

Requires Python 3, Bash, and Git. Setup is exercised with `/bin/bash`, including
Apple's system Bash 3.2 on macOS (not accidentally a newer Homebrew Bash).
zsh and tmux runtime tests explicitly skip if
unavailable; CI installs both so those checks must run there. The production
bootstrap itself requires only Bash, Git checkout metadata, and standard Unix
utilities. It does not depend on Python.

Tests use temporary homes and copies of an explicit set of managed source files.
They never copy the whole repository or follow the actual user's home files.
External command environments do not inherit credentials or user Git config.
Runtime shell tests disable global rc loading where zsh supports it; tmux uses a
private socket and a plugin-free fixture home, then kills only that test server.

Coverage includes detection fixtures (Arch, EndeavourOS, Ubuntu, macOS, WSL1/2,
unknown/unsupported OS, non-executable os-release), entry point and syntax,
required-source failures, profile validation, work-OS confirmation, links, broken
links/files/directories as conflicts, explicit unique backups, unsafe parent
symlinks, idempotency, side-effect-free dry-run, checkout/home-worktree safeguards,
package/plugin plans, missing manifests, native `df`, checkout-scoped `dtf`,
missing optional plugins, local overrides, and isolated tmux configuration loading.
Package/network commands are not actually run by tests. Paths with spaces are
included in fixtures.

## HOME-dependent tmux launchers

Some machines have a `tmux` shell launcher that executes a versioned binary under
`$HOME/.local/share`. The test deliberately changes HOME, so that launcher cannot
find its payload. This is a validator-launch failure, not evidence that the tmux
config parsed successfully or failed. Never restore the live HOME to make the test
pass: that could activate real plugins and local configuration.

Provide the absolute path to the actual executable instead. For Callisto's
reported tmux 3.5a installation, **if this executable exists**:

```sh
test -x "$HOME/.local/share/tmux-3.5a/bin/tmux"
DOTFILES_TEST_TMUX="$HOME/.local/share/tmux-3.5a/bin/tmux" bash tests/run.sh
```

If that binary needs bundled shared libraries (Callisto's launcher supplies
`runtime/libjemalloc.so.2`), provide its known runtime directory explicitly:

```sh
DOTFILES_TEST_TMUX="$HOME/.local/share/tmux-3.5a/bin/tmux" \
DOTFILES_TEST_TMUX_LIBRARY_PATH="$HOME/.local/share/tmux-3.5a/runtime" \
  bash tests/run.sh
```

The library option is a colon-separated list of absolute, existing directories;
empty or relative entries fail. It supplies `LD_LIBRARY_PATH` only to the test's
tmux commands, including version probing and private-server cleanup. It does not
inherit the user's loader environment, enable `LD_PRELOAD`, or restore the live
HOME. Point it only at trusted libraries you intend to load.

These overrides are used only by the tests, not by setup or your shell. They do
not change HOME, PATH, installed programs, or the active tmux server. If testing a
different binary (such as `/usr/bin/tmux`), record which version was tested; that
does not also verify a separate local build. An invalid override or broken
launcher **fails** with instructions rather than silently skipping or falling
back to a different tmux. The selected executable/version is printed in the test
output. Regression fixtures reproduce the HOME-dependent launcher failure and
verify a direct payload can be probed without changing the isolated HOME. Further
fixtures reproduce a missing bundled-runtime failure and verify the explicit
library environment is passed without mutating the base fixture environment.

## CI and actual machine validation

GitHub Actions runs Ubuntu 24.04/latest and macOS runner tests plus an Arch Linux
container check. Initial CI caught insecure preinstalled completion paths causing
`compinit` to prompt without a terminal on Ubuntu. Startup now uses `compinit -i`
to ignore insecure paths, not `-u` to trust them. A writable-completion-path
regression verifies it stays unloaded and startup emits no error.

CI does not run setup against a runner's real home, install the dotfiles
package manifests, provision servers, or validate desktop input integration.
Actual machine migration remains gated on owner review and the PLATFORMS.md
checklist. Linux-host fixtures for WSL/macOS are not actual WSL/macOS deployment
verification. Inspect the PR's CI results rather than assuming a workflow passed
merely because it was added.

## Optional commit hook

`dtf config core.hooksPath tools/git-hooks` explicitly enables the tracked hook in
a normal checkout. Setup does not set it. It tests the **working tree**, not the
staged index; review partially staged changes before committing. The hook unsets
Git's exported directory/index variables before discovering the checkout.
