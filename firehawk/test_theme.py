import importlib.machinery
import importlib.util
import json
import os
from unittest import mock
from pathlib import Path
import tempfile
import unittest

path = Path(__file__).parent / 'firehawk-theme'
loader = importlib.machinery.SourceFileLoader('firehawk', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
theme = importlib.util.module_from_spec(spec)
loader.exec_module(theme)


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def test_hostname_alias(self):
        self.assertEqual(theme.resolve(hostname='supernerd', home=self.home)[0], 'behemoth')

    def test_unknown_falls_back(self):
        self.assertEqual(theme.resolve(hostname='new-ship', home=self.home)[0], 'default')

    def test_explicit_overrides_host(self):
        self.assertEqual(theme.resolve('default', hostname='behemoth', home=self.home)[0], 'default')

    def test_local_override(self):
        p = self.home / '.config/firehawk/profile'
        p.parent.mkdir(parents=True)
        p.write_text('behemoth\n')
        self.assertEqual(theme.resolve(hostname='new-ship', home=self.home)[0], 'behemoth')

    def test_unsafe_name_rejected(self):
        with self.assertRaises(ValueError):
            theme.resolve('../../etc/passwd', home=self.home)

    def test_generate_and_activate(self):
        profile, data, colors = theme.resolve('behemoth', home=self.home)
        output = self.home / 'generated'
        theme.build(output, profile, data, colors, self.home)
        for p in output.rglob('*'):
            if p.is_file() and p.suffix not in ('.png',):
                self.assertNotIn('@@', p.read_text().replace('@DEFAULT_AUDIO_SINK@', '').replace('@DEFAULT_AUDIO_SOURCE@', ''))
        bar = json.loads((output / 'waybar/config.jsonc').read_text())
        self.assertEqual('BEHEMOTH', bar['custom/identity']['format'])
        self.assertNotIn('FIREHAWK', (output / 'hypr/hyprlock.conf').read_text())
        self.assertIn('EMBER', (output / 'hypr/hyprlock.conf').read_text())
        folder_modules = [name for name in bar['modules-left'] if name in ('custom/downloads', 'custom/screenshots')]
        self.assertEqual(folder_modules, ['custom/downloads', 'custom/screenshots'])
        self.assertIn('recent-files.py', bar['custom/downloads']['on-click'])
        self.assertTrue((output / 'scripts/recent-files.py').is_file())
        self.assertTrue((output / 'scripts/recent-files.css').is_file())
        from PIL import Image
        with Image.open(output / 'wallpaper.png') as wallpaper:
            self.assertEqual(wallpaper.size, (2560, 1440))
        current = self.home / '.config/firehawk/current'
        current.parent.mkdir(parents=True)
        current.symlink_to(output)
        theme.activate(self.home)
        theme.activate(self.home)
        self.assertTrue((self.home / '.config/hypr/hyprland.lua').is_file())

    def test_keyboard_remap_is_device_scoped(self):
        mapping = (theme.ROOT / 'templates/hypr/keyboards.lua').read_text()
        self.assertIn('hl.device', mapping)
        self.assertNotIn('hl.config', mapping)
        self.assertIn('apple-inc.-magic-keyboard-with-touch-id-and-numeric-keypad', mapping)
        self.assertIn('altwin:swap_alt_win,caps:escape', mapping)
        self.assertNotIn('moergo', mapping.lower())
        profile, data, colors = theme.resolve('behemoth', home=self.home)
        output = self.home / 'generated'
        theme.build(output, profile, data, colors, self.home)
        self.assertEqual(mapping, (output / 'hypr/keyboards.lua').read_text())
        self.assertIn('/hypr/keyboards.lua', (output / 'hypr/hyprland.lua').read_text())

    def test_apply_is_idempotent_and_repairs_corruption(self):
        first = theme.apply_theme(self.home, 'behemoth')
        second = theme.apply_theme(self.home, 'behemoth')
        self.assertEqual(first, second)
        (first / 'waybar/style.css').write_text('damaged')
        repaired = theme.apply_theme(self.home, 'behemoth')
        self.assertNotEqual(first, repaired)
        self.assertTrue(first.is_dir())  # Old generations retained.

    def test_failed_build_preserves_current(self):
        first = theme.apply_theme(self.home, 'behemoth')
        with mock.patch.object(theme, 'wallpaper', side_effect=OSError('fixture failure')):
            with self.assertRaises(OSError):
                theme.apply_theme(self.home, 'default', force=True)
        self.assertEqual((self.home / '.config/firehawk/current').resolve(), first)
        self.assertEqual(len(list((self.home / '.local/state/firehawk/generations').iterdir())), 1)

    def test_symlink_parents_rejected(self):
        outside = self.home / 'outside'
        outside.mkdir()
        (self.home / '.config').symlink_to(outside)
        for action in (theme.apply_theme, theme.activate, theme.deactivate):
            with self.assertRaises(ValueError):
                action(self.home)
        self.assertEqual(list(outside.iterdir()), [])

    def test_deactivate_only_removes_owned_links(self):
        theme.apply_theme(self.home, 'behemoth')
        theme.activate(self.home)
        waybar = self.home / '.config/waybar'
        waybar.unlink()
        waybar.mkdir()
        (waybar / 'custom').write_text('keep')
        theme.deactivate(self.home)
        self.assertEqual((waybar / 'custom').read_text(), 'keep')
        self.assertFalse((self.home / '.config/hypr').exists())

    def test_mobile_modules_and_color_override(self):
        profile, data, colors = theme.resolve('default', home=self.home)
        data['mobile'] = True
        colors['orange'] = '#FF7700'
        output = self.home / 'generated'
        theme.build(output, profile, data, colors, self.home)
        bar = json.loads((output / 'waybar/config.jsonc').read_text())
        self.assertIn('battery', bar['modules-right'])
        self.assertIn('#FF7700', (output / 'colors.css').read_text())

    def test_preview_does_not_write(self):
        theme.resolve('behemoth', home=self.home)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_screenshot_cancel_does_not_capture(self):
        import subprocess
        bindir = self.home / 'bin'
        bindir.mkdir()
        for name, code in {'slurp': 'exit 1', 'grim': 'touch "$HOME/unexpected"', 'wl-copy': 'touch "$HOME/unexpected"'}.items():
            script = bindir / name
            script.write_text('#!/bin/sh\n'+code+'\n')
            script.chmod(0o755)
        result = subprocess.run(['bash', str(theme.ROOT / 'templates/scripts/screenshot'), 'region-copy'],
                                env={'HOME':str(self.home), 'PATH':str(bindir)+os.pathsep+os.environ['PATH']})
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.home / 'unexpected').exists())

    def test_conflicts_not_replaced(self):
        output = self.home / 'generated'
        output.mkdir()
        (output / 'manifest.json').write_text('{}')
        config = self.home / '.config'
        (config / 'firehawk').mkdir(parents=True)
        (config / 'firehawk/current').symlink_to(output)
        (config / 'waybar').mkdir()
        with self.assertRaises(ValueError):
            theme.activate(self.home)
        self.assertFalse((config / 'hypr').exists())
        self.assertTrue((config / 'waybar').is_dir())


class DeploymentTests(unittest.TestCase):
    """Use the main bootstrap's allowlisted, disposable-home fixture."""
    def setUp(self):
        spec = importlib.util.spec_from_file_location('fixture_setup', theme.ROOT.parent / 'tests/test_setup.py')
        fixture_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture_module)
        self.fixture = fixture_module.SetupTests(methodName='test_help')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.prepare_firehawk()
        self.options = ('--machine', 'behemoth', '--profile', 'desktop', '--desktop', 'firehawk', '--theme-profile', 'behemoth')

    def test_full_setup_is_idempotent_and_preserves_i3(self):
        f = self.fixture
        i3 = f.home / '.config/i3'
        i3.mkdir(parents=True)
        (i3 / 'config').write_text('existing i3')
        f.setup(*self.options)
        self.assertTrue((f.home / '.config/hypr/hyprland.lua').is_file())
        self.assertTrue((f.home / '.local/bin/firehawk-theme').is_symlink())
        current = f.home / '.config/firehawk/current'
        first = current.readlink()
        timestamp = current.lstat().st_mtime_ns
        f.setup(*self.options)
        self.assertEqual(current.readlink(), first)
        self.assertEqual(current.lstat().st_mtime_ns, timestamp)
        self.assertEqual((i3 / 'config').read_text(), 'existing i3')

    def test_main_setup_backs_up_conflicts_and_preserves_local_overrides(self):
        f = self.fixture
        waybar = f.home / '.config/waybar'
        waybar.mkdir(parents=True)
        (waybar / 'custom').write_text('original')
        local = f.home / '.config/firehawk/local.lua'
        local.parent.mkdir()
        local.write_text('-- personal configuration')
        f.setup(*self.options, '--replace')
        backups = list((f.home / '.local/state/dotfiles/backups').iterdir())
        self.assertEqual((backups[0] / '.config/waybar/custom').read_text(), 'original')
        self.assertEqual(local.read_text(), '-- personal configuration')

    def test_package_upgrade_is_explicit_and_uses_shared_manifest(self):
        f = self.fixture
        bindir = f.base / 'bin'
        bindir.mkdir()
        for name, body in {'pacman': 'exit 99', 'sudo': 'printf "%s\\n" "$*" > "$HOME/package-command"'}.items():
            script = bindir / name
            script.write_text('#!/bin/sh\n' + body + '\n')
            script.chmod(0o755)
        f.env['PATH'] = str(bindir) + os.pathsep + f.env['PATH']
        f.setup(*self.options, '--install-packages')
        command = (f.home / 'package-command').read_text()
        self.assertTrue(command.startswith('pacman -Syu --needed '))
        self.assertIn('hyprland', command)
        self.assertIn('python-pillow', command)
        self.assertNotIn('i3-wm', command)


if __name__ == '__main__':
    unittest.main()
