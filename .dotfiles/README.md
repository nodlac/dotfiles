# Legacy layout

These paths are retained as compatibility loaders. They are not a Git directory
in new installations. The old platform scripts now delegate to the repository's
single `setup.sh` entry point and require explicit opt-in for installs.

Use a conventional clone and [the root README](../README.md). Git operations use
`dtf`, never an alias that hides native `df`. The old home-worktree Git directory,
branches and local configuration must be preserved during a separately reviewed
[migration](../docs/MIGRATION.md).

Historical installers/configuration are preserved in `legacy/` for reference;
those unsafe installers are disabled. Do not check out this refactor into your
live home worktree as a migration shortcut. Existing package configuration files
here remain historical inventory; current manifests live in `platform/packages/`.
