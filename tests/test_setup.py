#!/usr/bin/env python3
"""Portable regression suite. Explicit allowlists; no live-home or secret scans."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Explicitly exercise Apple's system Bash 3.2 on macOS, even if brew has Bash 5.
BASH = '/bin/bash' if Path('/bin/bash').is_file() else shutil.which('bash')
ZSH = shutil.which('zsh')
# HOME-dependent launchers cannot locate their payload in an isolated test home.
# Allow an explicit real executable; never "fix" that by restoring the live HOME.
TMUX = os.environ.get('DOTFILES_TEST_TMUX') or shutil.which('tmux')
TMUX_LIBRARY_PATH = os.environ.get('DOTFILES_TEST_TMUX_LIBRARY_PATH')
GIT = shutil.which('git')
BASE_ENV = {
    'PATH': os.pathsep.join(dict.fromkeys([str(Path(BASH).parent), '/usr/local/bin', '/usr/bin', '/bin'])),
    'LC_ALL': 'C', 'TERM': 'xterm-256color',
    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
}


def run(args, env, **kwargs):
    return subprocess.run(args, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=60, **kwargs)


def tmux_runtime_env(env, library_path=None):
    result = dict(env)
    if library_path is not None:
        directories = library_path.split(os.pathsep)
        if any(not p or not Path(p).is_absolute() or not Path(p).is_dir()
               for p in directories):
            raise AssertionError('DOTFILES_TEST_TMUX_LIBRARY_PATH must contain only '
                                 'absolute, existing library directories (no empty entries).')
        # Explicit allowlist, not inheritance of the user's loader environment.
        # Use only for tmux commands; retain the fixture HOME and private socket.
        result['LD_LIBRARY_PATH'] = library_path
    return result


def probe_tmux(binary, env):
    guidance = ('Set DOTFILES_TEST_TMUX to the absolute path of the real tmux binary, '
                'not a HOME-dependent launcher. For a bundled runtime, also set '
                'DOTFILES_TEST_TMUX_LIBRARY_PATH. Tests must retain their isolated HOME.')
    if not Path(binary).is_absolute():
        raise AssertionError(guidance)
    try:
        result = run([binary, '-V'], env)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AssertionError(f'Cannot launch tmux validator {binary}: {error}\n{guidance}') from error
    if result.returncode != 0 or not result.stdout.startswith('tmux '):
        raise AssertionError(f'tmux validator {binary} failed before config loading:\n'
                             f'{result.stdout}{result.stderr}\n{guidance}')
    return result.stdout.strip()


def snapshot(home):
    # Called only on homes created by these tests; never the actual user home.
    result = {}
    for p in sorted(home.rglob('*')):
        name = str(p.relative_to(home))
        if p.is_symlink():
            result[name] = ('link', os.readlink(p), p.lstat().st_mtime_ns)
        elif p.is_file():
            result[name] = ('file', p.read_bytes(), p.stat().st_mtime_ns)
        else:
            result[name] = ('dir',)
    return result


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dotfiles-tests-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home with spaces'
        self.home.mkdir()
        self.repo = self.base / 'repo with spaces'
        self.repo.mkdir()
        # Never copy arbitrary tracked files, credentials or private work configs.
        for name in ['setup.sh', 'lib/setup.sh', 'platform/detect.sh',
                     'platform/linux.zsh', 'platform/macos.zsh']:
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        for name in ['config/shared', 'machines', 'platform/packages']:
            shutil.copytree(ROOT / name, self.repo / name)
        self.env = dict(BASE_ENV, HOME=str(self.home), ZDOTDIR=str(self.home))
        result = run([GIT, 'init', '-q', str(self.repo)], self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Setup flow uses a stub; actual detection has its own fixture tests below.
        self.fake_platform()

    def fake_platform(self, os_name='linux', distro='ubuntu', wsl='none'):
        (self.repo / 'platform/detect.sh').write_text(
            'detect_platform() { DF_OS=%s; DF_DISTRO=%s; DF_WSL=%s; }\n'
            % (os_name, distro, wsl))

    def setup(self, *args, ok=True):
        result = run([BASH, str(self.repo / 'setup.sh'), *args], self.env)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def shell(self, code):
        return run([ZSH, '-d', '-i', '-c', code], self.env)

    def prepare_firehawk(self):
        self.fake_platform('linux', 'endeavouros')
        shutil.copy2(ROOT / 'lib/firehawk.sh', self.repo / 'lib/firehawk.sh')
        for name in ['firehawk/theme', 'firehawk/profiles', 'firehawk/templates', 'firehawk/assets/brand']:
            shutil.copytree(ROOT / name, self.repo / name)
        shutil.copy2(ROOT / 'firehawk/firehawk-theme', self.repo / 'firehawk/firehawk-theme')
        (self.repo / '.config/ghostty').mkdir(parents=True)
        (self.repo / '.config/ghostty/config').write_text('# fixture\n')

    def test_firehawk_dry_run_has_no_writes(self):
        self.prepare_firehawk()
        before = snapshot(self.home)
        result = self.setup('--profile', 'desktop', '--desktop', 'firehawk', '--theme-profile', 'behemoth', '--dry-run')
        self.assertIn('THEME', result.stdout)
        self.assertIn('/.config/hypr', result.stdout)
        self.assertNotIn('/.config/i3', result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_firehawk_conflict_prevents_generation(self):
        self.prepare_firehawk()
        (self.home / '.config/waybar').mkdir(parents=True)
        (self.home / '.config/waybar/custom').write_text('keep')
        before = snapshot(self.home)
        result = self.setup('--profile', 'desktop', '--desktop', 'firehawk', ok=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(snapshot(self.home), before)

    def test_firehawk_package_plan_is_separate(self):
        self.prepare_firehawk()
        bindir = self.base / 'bin'
        bindir.mkdir()
        pacman = bindir / 'pacman'
        pacman.write_text('#!/bin/sh\nexit 99\n')
        pacman.chmod(0o755)
        self.env['PATH'] = str(bindir) + os.pathsep + self.env['PATH']
        result = self.setup('--profile', 'desktop', '--desktop', 'firehawk', '--install-packages', '--dry-run')
        self.assertIn('hyprland', result.stdout)
        self.assertIn('python-pillow', result.stdout)
        self.assertNotIn('i3-wm', result.stdout)
        self.assertEqual(snapshot(self.home), {})

    def test_firehawk_requires_supported_opt_in(self):
        for args in [('--desktop', 'firehawk'), ('--profile', 'desktop', '--desktop', 'firehawk'),
                     ('--profile', 'desktop', '--theme-profile', 'behemoth')]:
            self.setup(*args, ok=False)
        self.prepare_firehawk()
        self.setup('--profile', 'desktop', '--desktop', 'firehawk', '--theme-profile', '../../bad', ok=False)
        self.setup('--profile', 'desktop', '--desktop', 'firehawk', '--theme-profile', 'missing', ok=False)
        self.assertEqual(snapshot(self.home), {})

    def test_firehawk_missing_source_prevents_writes(self):
        self.prepare_firehawk()
        (self.repo / 'firehawk/templates/hypr/hyprland.lua').unlink()
        self.setup('--profile', 'desktop', '--desktop', 'firehawk', ok=False)
        self.assertEqual(snapshot(self.home), {})

    def test_firehawk_unsafe_state_parent_rejected(self):
        self.prepare_firehawk()
        outside = self.base / 'outside'
        outside.mkdir()
        (self.home / '.local').mkdir()
        (self.home / '.local/state').symlink_to(outside)
        self.setup('--profile', 'desktop', '--desktop', 'firehawk', '--replace', ok=False)
        self.assertEqual(list(outside.iterdir()), [])

    def test_entrypoint_is_executable(self):
        self.assertTrue(os.access(ROOT / 'setup.sh', os.X_OK))

    def test_help(self):
        self.assertIn('--dry-run', self.setup('--help').stdout)
        self.assertEqual(snapshot(self.home), {})

    def test_retired_entrypoints_are_not_shipped(self):
        for name in ['.mac-setup.sh', '.zshrc', '.tmux.conf', 'legacy',
                     '.dotfiles/.eos-setup.sh', '.dotfiles/.mac-setup.sh',
                     '.dotfiles/.server-setup.sh', '.dotfiles/.zshrc',
                     '.dotfiles/.zshenv', '.dotfiles/.tmux.conf', '.dotfiles/test.sh']:
            self.assertFalse(os.path.lexists(ROOT / name), name)
        self.assertTrue((ROOT / 'setup.sh').is_file())

    @unittest.skipUnless(ZSH, 'zsh unavailable')
    def test_canonical_shell_loads_without_legacy_tree(self):
        self.assertFalse((self.repo / '.dotfiles').exists())
        self.setup()
        for name, source in [('.zshrc', 'zshrc'), ('.zshenv', 'zshenv')]:
            self.assertEqual((self.home / name).resolve(), self.repo / 'config/shared' / source)
        result = self.shell('[[ $(dtf rev-parse --show-toplevel) = "$DOTFILES_ROOT" ]] '
                            '&& (( $+functions[dtf-test] ))')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    def test_detect_only(self):
        self.assertIn('distro=ubuntu', self.setup('--detect').stdout)
        self.assertEqual(snapshot(self.home), {})

    def test_dry_run_has_no_side_effects(self):
        before = snapshot(self.home)
        result = self.setup('--dry-run')
        self.assertIn('LINK', result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_links_and_idempotency(self):
        self.setup()
        self.assertEqual((self.home / '.zshrc').resolve(), self.repo / 'config/shared/zshrc')
        self.assertEqual((self.home / '.local/share/dotfiles').resolve(), self.repo)
        self.assertFalse((self.home / '.config/ghostty').exists())
        before = snapshot(self.home)
        self.setup()
        self.setup('--dry-run')
        self.assertEqual(snapshot(self.home), before)

    def test_conflict_is_atomic_and_unchanged(self):
        (self.home / '.zshrc').write_text('old config\n')
        before = snapshot(self.home)
        for options in [[], ['--dry-run']]:
            self.assertIn('CONFLICT', self.setup(*options, ok=False).stdout)
            self.assertEqual(snapshot(self.home), before)
        self.assertFalse((self.home / '.local').exists())

    def test_explicit_backup_and_replace(self):
        (self.home / '.zshrc').write_text('my old shell\n')
        (self.home / '.tmux.conf').symlink_to('missing-target')
        before = snapshot(self.home)
        result = self.setup('--replace', '--dry-run')
        self.assertIn('BACKUP', result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.setup('--replace')
        backups = self.home / '.local/state/dotfiles/backups'
        first = list(backups.iterdir())
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].stat().st_mode & 0o077, 0)
        self.assertEqual((first[0] / '.zshrc').read_text(), 'my old shell\n')
        self.assertEqual(os.readlink(first[0] / '.tmux.conf'), 'missing-target')
        before = snapshot(self.home)
        self.setup('--replace')
        self.assertEqual(snapshot(self.home), before)

    def test_distinct_runs_preserve_prior_backups(self):
        (self.home / '.zshrc').write_text('first')
        self.setup('--replace')
        (self.home / '.zshrc').unlink()
        (self.home / '.zshrc').write_text('second')
        self.setup('--replace')
        backups = list((self.home / '.local/state/dotfiles/backups').iterdir())
        self.assertEqual(len(backups), 2)
        self.assertEqual({(p / '.zshrc').read_text() for p in backups}, {'first', 'second'})

    def test_directory_conflict_is_preserved(self):
        (self.home / '.zshrc').mkdir()
        (self.home / '.zshrc/custom').write_text('keep')
        self.setup('--replace')
        backups = list((self.home / '.local/state/dotfiles/backups').iterdir())
        self.assertEqual((backups[0] / '.zshrc/custom').read_text(), 'keep')

    def test_parent_symlink_is_not_traversed(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (self.home / '.config').symlink_to(outside, target_is_directory=True)
        self.setup('--replace', ok=False)
        self.assertEqual(list(outside.iterdir()), [])

    def test_backup_parent_symlink_is_not_traversed(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (self.home / '.local').mkdir()
        (self.home / '.local/state').symlink_to(outside, target_is_directory=True)
        self.setup('--replace', ok=False)
        self.assertEqual(list(outside.iterdir()), [])

    def test_regular_parent_is_not_overwritten(self):
        (self.home / '.config').write_text('keep')
        self.setup('--replace', ok=False)
        self.assertEqual((self.home / '.config').read_text(), 'keep')

    def test_missing_sources_fail_before_changes(self):
        for path in ['config/shared/zshrc', 'platform/linux.zsh', 'machines/generic.zsh']:
            p = self.repo / path
            data = p.read_text()
            p.unlink()  # Only this test-owned copy is removed.
            self.assertIn('Missing', self.setup(ok=False).stderr)
            self.assertEqual(snapshot(self.home), {})
            p.write_text(data)

    def test_missing_library_fails(self):
        (self.repo / 'lib/setup.sh').unlink()
        self.assertIn('Missing lib/setup.sh', self.setup(ok=False).stderr)
        self.assertEqual(snapshot(self.home), {})

    def test_checkout_inside_managed_target_is_rejected(self):
        destination = self.home / '.local/share/dotfiles'
        destination.parent.mkdir(parents=True)
        shutil.move(str(self.repo), destination)
        self.repo = destination
        before = snapshot(self.home)
        self.assertIn('inside managed target', self.setup('--replace', ok=False).stderr)
        self.assertEqual(snapshot(self.home), before)

    def test_missing_detection_script_fails(self):
        (self.repo / 'platform/detect.sh').unlink()
        self.assertIn('Missing platform/detect.sh', self.setup(ok=False).stderr)
        self.assertEqual(snapshot(self.home), {})

    def test_legacy_home_worktree_is_rejected(self):
        shutil.rmtree(self.repo / '.git')  # Only our temporary empty Git repository.
        self.assertIn('conventional clone', self.setup(ok=False).stderr)
        self.assertEqual(snapshot(self.home), {})

    def test_invalid_arguments(self):
        for args in [('--machine',), ('--oops',), ('--machine', '../../bad'),
                     ('--profile', 'bad'), ('--machine', 'macos')]:
            self.setup(*args, ok=False)
        self.assertEqual(snapshot(self.home), {})

    def test_callisto_is_headless(self):
        self.setup('--machine', 'callisto', '--dry-run')
        self.setup('--machine', 'callisto', '--profile', 'desktop', ok=False)
        self.fake_platform(wsl='2')
        self.setup('--machine', 'callisto', ok=False)

    def test_somnambulist_requires_wsl2(self):
        self.setup('--machine', 'somnambulist', ok=False)
        self.fake_platform(wsl='1')
        self.setup('--machine', 'somnambulist', ok=False)
        self.fake_platform(wsl='2')
        self.setup('--machine', 'somnambulist')
        self.assertTrue((self.home / '.config/dotfiles/machine.zsh').is_symlink())
        self.setup('--profile', 'desktop', ok=False)

    def test_work_requires_confirmation(self):
        self.setup('--machine', 'medina-station', ok=False)
        self.setup('--machine', 'medina-station', '--confirm-work-os', 'macos', '--profile', 'headless', ok=False)
        self.setup('--machine', 'medina-station', '--confirm-work-os', 'linux', '--profile', 'headless', '--dry-run')

    def test_local_overrides_are_never_replaced(self):
        local = self.home / '.config/dotfiles'
        local.mkdir(parents=True)
        (local / 'local.zsh').write_text('export DOTFILES_LOCAL_MARKER=yes\n')
        (local / 'tmux.local.conf').write_text('set -g status-left local\n')
        self.setup('--replace')
        self.assertEqual((local / 'local.zsh').read_text(), 'export DOTFILES_LOCAL_MARKER=yes\n')
        self.assertEqual((local / 'tmux.local.conf').read_text(), 'set -g status-left local\n')
        if ZSH:
            result = self.shell('test "$DOTFILES_LOCAL_MARKER" = yes')
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(ZSH, 'zsh unavailable; config loading not verified')
    def test_shell_loads_without_plugins_and_native_df_survives(self):
        self.setup()
        result = self.shell('''
            (( ! $+aliases[df] && ! $+functions[df] )) || exit 2
            [[ $(whence -p df) = /* ]] || exit 3
            df -P / >/dev/null || exit 4
            [[ $(dtf rev-parse --show-toplevel) = "$DOTFILES_ROOT" ]] || exit 5
            [[ $EDITOR = nvim ]] || exit 6
            source "$HOME/.zshrc"
            [[ ":$PATH:" != *":$HOME/.local/bin:$HOME/.local/bin:"* ]] || exit 7
        ''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')

    @unittest.skipUnless(ZSH, 'zsh unavailable')
    def test_insecure_completion_paths_are_ignored_without_prompting(self):
        self.setup()
        insecure = self.base / 'insecure-completions'
        insecure.mkdir(mode=0o777)
        insecure.chmod(0o777)
        (insecure / '_unsafe').write_text('#compdef unsafecommand\n_arguments "*::args:->args"\n')
        self.env['INSECURE_FPATH'] = str(insecure)
        result = self.shell('fpath=("$INSECURE_FPATH" $fpath); source "$HOME/.zshrc"; '
                            '[[ -z ${_comps[unsafecommand]-} ]]')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    @unittest.skipUnless(ZSH, 'zsh unavailable')
    def test_callisto_helpers_load(self):
        self.setup('--machine', 'callisto')
        result = self.shell('[[ $DOTFILES_MACHINE = callisto ]] && (( $+functions[serve] && $+functions[jlog] ))')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(ZSH, 'zsh unavailable')
    def test_legacy_helper_aliases_do_not_break_reload(self):
        self.setup()
        result = self.shell('alias dtf-test=false; alias dtf-quick-commit=false; '
                            'source "$HOME/.zshrc"; '
                            '(( $+functions[dtf-test] && $+functions[dtf-quick-commit] ))')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')

    @unittest.skipUnless(ZSH, 'zsh unavailable')
    def test_macos_shell_layer_loads(self):
        self.fake_platform('macos', 'macos')
        self.setup('--machine', 'macos')
        result = self.shell('[[ $aliases[ls] = "ls -G" && $DOTFILES_MACHINE = macos ]]')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_never_invokes_network_or_privilege_commands(self):
        bin_dir = self.base / 'bin'
        bin_dir.mkdir()
        for name in ['sudo', 'curl', 'brew', 'apt-get', 'pacman', 'git', 'systemctl', 'chsh']:
            script = bin_dir / name
            script.write_text('#!/bin/sh\nprintf "unexpected command\\n" >&2\nexit 99\n')
            script.chmod(0o755)
        self.env['PATH'] = str(bin_dir) + os.pathsep + self.env['PATH']
        self.setup()
        self.setup('--dry-run')

    def test_plugin_dry_run_never_clones(self):
        before = snapshot(self.home)
        result = self.setup('--install-plugins', '--dry-run')
        self.assertIn('CLONE', result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_plugin_install_is_opt_in_and_never_pulls(self):
        bin_dir = self.base / 'bin'
        bin_dir.mkdir()
        script = bin_dir / 'git'
        script.write_text('#!/bin/sh\n[ "$1" = clone ] || exit 99\n'
                          'for arg do destination=$arg; done\nmkdir -p "$destination/.git"\n')
        script.chmod(0o755)
        self.env['PATH'] = str(bin_dir) + os.pathsep + self.env['PATH']
        self.setup('--install-plugins')
        self.assertTrue((self.home / '.tmux/plugins/tpm/.git').is_dir())
        self.assertTrue((self.home / '.zsh/fzf-tab/.git').is_dir())
        before = snapshot(self.home)
        self.setup('--install-plugins')
        self.assertEqual(snapshot(self.home), before)

    def test_plugin_conflict_blocks_all_changes(self):
        path = self.home / '.zsh/zsh-autosuggestions'
        path.mkdir(parents=True)
        before = snapshot(self.home)
        self.setup('--install-plugins', ok=False)
        self.assertEqual(snapshot(self.home), before)

    def test_headless_packages_have_no_desktop_packages(self):
        bin_dir = self.base / 'bin'
        bin_dir.mkdir()
        for name in ['apt-get', 'pacman', 'brew']:
            script = bin_dir / name
            script.write_text('#!/bin/sh\nexit 99\n')
            script.chmod(0o755)
        self.env['PATH'] = str(bin_dir) + os.pathsep + self.env['PATH']
        for os_name, distro in [('linux', 'ubuntu'), ('linux', 'arch'), ('macos', 'macos')]:
            self.fake_platform(os_name, distro)
            result = self.setup('--install-packages', '--dry-run')
            for name in ['ghostty', 'i3-wm', 'karabiner-elements', 'scrcpy', 'slack']:
                self.assertNotIn(name, result.stdout)
        self.assertEqual(snapshot(self.home), {})

    def test_requested_package_commands_use_reviewed_arguments(self):
        bin_dir = self.base / 'bin'
        bin_dir.mkdir()
        log = self.base / 'commands.log'
        self.env['COMMAND_LOG'] = str(log)
        for name in ['apt-get', 'sudo']:
            script = bin_dir / name
            script.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n')
            script.chmod(0o755)
        self.env['PATH'] = str(bin_dir) + os.pathsep + self.env['PATH']
        self.setup('--install-packages', '--dry-run')
        self.assertFalse(log.exists())
        self.setup('--install-packages')
        commands = log.read_text()
        self.assertIn('apt-get update', commands)
        self.assertIn('apt-get install git curl zsh tmux', commands)
        self.assertNotIn('ghostty', commands)

    def test_infisical_dry_run_has_no_side_effects(self):
        for os_name, distro in [('linux', 'ubuntu'), ('macos', 'macos')]:
            self.fake_platform(os_name, distro)
            before = snapshot(self.home)
            result = self.setup('--install-infisical', '--dry-run')
            self.assertIn('INFISICAL 0.45.4', result.stdout)
            self.assertEqual(snapshot(self.home), before)

    def test_infisical_existing_binary_is_kept(self):
        target = self.home / '.local/bin/infisical'
        target.parent.mkdir(parents=True)
        target.write_text('user-managed binary')
        self.setup('--install-infisical')
        self.assertEqual(target.read_text(), 'user-managed binary')

    def test_infisical_install_and_checksum_failure(self):
        bindir = self.base / 'bin'
        bindir.mkdir()
        self.env['PATH'] = str(bindir) + os.pathsep + self.env['PATH']
        scripts = {
            'curl': '#!/bin/sh\nexit 0\n',
            'sha256sum': '#!/bin/sh\ncat >/dev/null\nexit 1\n',
            'tar': '#!/bin/sh\nprintf "#!/bin/sh\\nexit 0\\n" > "$4/infisical"\n',
        }
        for name, content in scripts.items():
            path = bindir / name
            path.write_text(content)
            path.chmod(0o755)
        target = self.home / '.local/bin/infisical'
        self.setup('--install-infisical', ok=False)
        self.assertFalse(target.exists())
        (bindir / 'sha256sum').write_text('#!/bin/sh\ncat >/dev/null\nexit 0\n')
        self.setup('--install-infisical')
        self.assertTrue(os.access(target, os.X_OK))
        self.assertIn('#!/bin/sh', target.read_text())

    def test_infisical_unsafe_parent_blocks_changes(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (self.home / '.local').mkdir()
        (self.home / '.local/bin').symlink_to(outside)
        before = snapshot(self.home)
        self.setup('--install-infisical', ok=False)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(list(outside.iterdir()), [])

    def test_missing_package_manifest_blocks_all_changes(self):
        (self.repo / 'platform/packages/ubuntu.txt').unlink()
        self.setup('--install-packages', ok=False)
        self.assertEqual(snapshot(self.home), {})

    def test_unknown_distro_config_only(self):
        self.fake_platform(distro='unknown')
        self.setup('--dry-run')
        self.setup('--install-packages', '--dry-run', ok=False)
        self.assertEqual(snapshot(self.home), {})

    def test_desktop_links_are_explicit(self):
        self.fake_platform(distro='arch')
        for path in ['.config/i3', '.config/ghostty']:
            p = self.repo / path
            p.mkdir(parents=True)
            (p / 'config').write_text('# fixture\n')
        self.setup('--machine', 'behemoth', '--profile', 'desktop')
        self.assertTrue((self.home / '.config/i3').is_symlink())
        self.assertTrue((self.home / '.config/ghostty').is_symlink())

    def test_tmux_probe_handles_home_dependent_launchers(self):
        payload = self.base / 'real home/.local/share/tmux-3.5a/bin/tmux'
        payload.parent.mkdir(parents=True)
        payload.write_text('#!/bin/sh\nprintf "tmux 3.5a\\n"\n')
        payload.chmod(0o755)
        launcher = self.base / 'tmux-launcher'
        launcher.write_text('#!/bin/sh\nexec env "$HOME/.local/share/tmux-3.5a/bin/tmux" "$@"\n')
        launcher.chmod(0o755)
        before = snapshot(self.home)
        with self.assertRaisesRegex(AssertionError, 'DOTFILES_TEST_TMUX'):
            probe_tmux(str(launcher), self.env)
        self.assertEqual(probe_tmux(str(payload), self.env), 'tmux 3.5a')
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.env['HOME'], str(self.home))

    def test_invalid_tmux_override_fails_instead_of_skipping(self):
        for binary in ['relative/tmux', str(self.base / 'missing-tmux')]:
            with self.assertRaisesRegex(AssertionError, 'DOTFILES_TEST_TMUX'):
                probe_tmux(binary, self.env)

    def test_bundled_tmux_runtime_keeps_home_isolated(self):
        runtime = self.base / 'runtime with spaces'
        runtime.mkdir()
        payload = self.base / 'bundled-tmux'
        payload.write_text('#!/bin/sh\n'
                           '[ "$LD_LIBRARY_PATH" = "$EXPECTED_RUNTIME" ] || exit 127\n'
                           'printf "tmux 3.5a\\n"\n')
        payload.chmod(0o755)
        base_env = dict(self.env, EXPECTED_RUNTIME=str(runtime))
        before = dict(base_env)
        with self.assertRaisesRegex(AssertionError, 'DOTFILES_TEST_TMUX_LIBRARY_PATH'):
            probe_tmux(str(payload), base_env)
        runtime_env = tmux_runtime_env(base_env, str(runtime))
        self.assertEqual(probe_tmux(str(payload), runtime_env), 'tmux 3.5a')
        self.assertEqual(base_env, before)
        self.assertEqual(runtime_env['HOME'], str(self.home))
        self.assertNotIn('LD_PRELOAD', runtime_env)

    def test_invalid_tmux_library_paths_fail(self):
        for path in ['', '.', 'relative/lib', str(self.base / 'missing'),
                     str(self.base) + os.pathsep, os.pathsep + str(self.base)]:
            with self.assertRaisesRegex(AssertionError, 'DOTFILES_TEST_TMUX_LIBRARY_PATH'):
                tmux_runtime_env(self.env, path)
        self.assertEqual(tmux_runtime_env(self.env), self.env)

    @unittest.skipUnless(TMUX, 'tmux unavailable; loading not verified')
    def test_tmux_loads_in_isolated_server(self):
        tmux_env = tmux_runtime_env(self.env, TMUX_LIBRARY_PATH)
        version = probe_tmux(TMUX, tmux_env)
        print(f'\nValidating {TMUX} ({version}) with isolated HOME', file=sys.stderr)
        self.setup()
        # -S isolates the socket; no active user's server or plugins are touched.
        sock = str(self.base / 'tmux.sock')
        command = [TMUX, '-S', sock, '-f', str(self.home / '.tmux.conf')]
        try:
            result = run(command + ['new-session', '-d', '-s', 'check', 'sleep 30'], tmux_env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stderr, '')
            errors = run([TMUX, '-S', sock, 'show-messages'], tmux_env)
            self.assertNotIn('invalid', errors.stdout.lower())
            result = run([TMUX, '-S', sock, 'show-options', '-gv', 'prefix'], tmux_env)
            self.assertEqual(result.stdout.strip(), 'C-Space')
        finally:
            run([TMUX, '-S', sock, 'kill-server'], tmux_env)


class DetectionTests(unittest.TestCase):
    def detect(self, system, release, data):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'os-release'
            p.write_text(data)
            env = dict(BASE_ENV, HOME=tmp)
            return run([BASH, '-c', '. "$1"; detect_platform "$2" "$3" "$4" || exit; '
                        'printf "%s:%s:%s" "$DF_OS" "$DF_DISTRO" "$DF_WSL"',
                        'test', str(ROOT / 'platform/detect.sh'), system, release, str(p)], env)

    def test_arch(self):
        self.assertEqual(self.detect('Linux', '6.18-arch', 'ID=arch\n').stdout, 'linux:arch:none')

    def test_endeavouros(self):
        self.assertEqual(self.detect('Linux', '6.18', 'ID="endeavouros"\nID_LIKE=arch\n').stdout, 'linux:endeavouros:none')

    def test_ubuntu_native(self):
        self.assertEqual(self.detect('Linux', '6.8-generic', 'ID=ubuntu\n').stdout, 'linux:ubuntu:none')

    def test_wsl2(self):
        for release in ['5.15.153.1-microsoft-standard-WSL2', '6.6.87.2-microsoft-standard']:
            self.assertEqual(self.detect('Linux', release, 'ID=ubuntu\n').stdout, 'linux:ubuntu:2')

    def test_wsl1(self):
        self.assertEqual(self.detect('Linux', '4.4.0-19041-Microsoft', 'ID=ubuntu\n').stdout, 'linux:ubuntu:1')

    def test_macos(self):
        self.assertEqual(self.detect('Darwin', '24.0', '').stdout, 'macos:macos:none')

    def test_unknown_and_unsupported(self):
        self.assertEqual(self.detect('Linux', '6.8', '').stdout, 'linux:unknown:none')
        self.assertNotEqual(self.detect('FreeBSD', '14.0', '').returncode, 0)

    def test_os_release_is_data_not_code(self):
        result = self.detect('Linux', '6.8', 'ID=ubuntu\nOTHER=$(echo UNSAFE >&2)\n')
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout, 'linux:ubuntu:none')


class SourceChecks(unittest.TestCase):
    def test_shell_syntax(self):
        paths = [ROOT / 'setup.sh', ROOT / 'lib/setup.sh', ROOT / 'platform/detect.sh',
                 ROOT / 'tests/run.sh', ROOT / 'tools/git-hooks/pre-commit']
        for p in paths:
            result = run([BASH, '-n', str(p)], BASE_ENV)
            self.assertEqual(result.returncode, 0, str(p) + result.stderr)
        if not ZSH:
            self.skipTest('bash syntax passed; zsh unavailable')
        zpaths = [ROOT / 'config/shared/zshrc', ROOT / 'config/shared/zshenv',
                  ROOT / 'config/optional/helpers.zsh']
        zpaths += list((ROOT / 'platform').glob('*.zsh')) + list((ROOT / 'machines').glob('*.zsh'))
        for p in zpaths:
            result = run([ZSH, '-n', str(p)], BASE_ENV)
            self.assertEqual(result.returncode, 0, str(p) + result.stderr)

    def test_documentation_links_resolve(self):
        # Only public setup docs; do not walk private notes or arbitrary Markdown.
        paths = [ROOT / 'README.md'] + [ROOT / 'docs' / name for name in
                 ['PLATFORMS.md', 'MIGRATION.md', 'FEATURE_PARITY.md', 'TESTING.md']]
        for document in paths:
            for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', document.read_text()):
                if '://' in link or link.startswith(('#', 'mailto:')):
                    continue
                target = link.split('#', 1)[0]
                self.assertTrue((document.parent / target).exists(), f'{document}: {link}')

    def test_config_regressions(self):
        aerospace = (ROOT / '.aerospace.toml').read_text()
        self.assertNotRegex(aerospace, r'(?m)^\s*alt-(left|right)\s*=')
        shared = (ROOT / 'config/shared/zshrc').read_text()
        self.assertIn('bindkey "^[[1;5D" backward-word', shared)
        self.assertIn('bindkey "^[[1;5C" forward-word', shared)
        ghostty = (ROOT / '.config/ghostty/config').read_text()
        for binding in ['ctrl+v=paste_from_clipboard', 'ctrl+shift+v=paste_from_clipboard',
                        'ctrl+shift+c=copy_to_clipboard']:
            self.assertIn('keybind = ' + binding, ghostty)
        karabiner = json.loads((ROOT / '.config/karabiner/assets/complex_modifications/linux-ctrl-swap.json').read_text())
        self.assertIn('mitchellh', json.dumps(karabiner))

    def test_managed_runtime_does_not_load_env_or_private_profiles(self):
        paths = [ROOT / 'setup.sh', ROOT / 'lib/setup.sh']
        for directory in ['config/shared', 'platform', 'machines']:
            paths += [p for p in (ROOT / directory).rglob('*') if p.is_file()]
        for p in paths:
            content = p.read_text()
            self.assertNotIn('.env', content, str(p))
            self.assertNotIn('.vidangel.zsh', content, str(p))
            self.assertNotRegex(content, r'(?m)^\s*alias\s+df=')


if __name__ == '__main__':
    unittest.main(verbosity=2)
