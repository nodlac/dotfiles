"""Recent-file model tests: disposable folders only; no GUI or live user files."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote, urlparse

SCRIPT = Path(__file__).parent / 'templates/scripts/recent-files.py'
spec = importlib.util.spec_from_file_location('recent_files', SCRIPT)
recent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recent)


class RecentFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='firehawk-recent-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.folder = self.home / 'Downloads'
        self.folder.mkdir()

    def file(self, name, modified):
        path = self.folder / name
        path.write_text('fixture')
        os.utime(path, ns=(modified, modified))
        return path

    def test_latest_five_by_modification_time(self):
        for i in range(8):
            self.file(f'file-{i}.txt', 1_000_000_000 + i)
        self.assertEqual([p.name for p, _ in recent.recent_files(self.folder)],
                         ['file-7.txt', 'file-6.txt', 'file-5.txt', 'file-4.txt', 'file-3.txt'])

    def test_hidden_partial_subfolder_and_symlink_excluded(self):
        keep = self.file('completed.pdf', 1)
        for name in ('.hidden', 'active.PART', 'active.crdownload', 'active.download', 'active.tmp'):
            self.file(name, 9)
        (self.folder / 'subfolder').mkdir()
        (self.folder / 'subfolder/nested.txt').write_text('not included')
        (self.folder / 'link.txt').symlink_to(keep)
        (self.folder / 'broken.txt').symlink_to('missing')
        self.assertEqual([p for p, _ in recent.recent_files(self.folder)], [keep])

    def test_missing_or_empty_folder(self):
        self.assertEqual(recent.recent_files(self.folder), [])
        self.assertEqual(recent.recent_files(self.home / 'missing'), [])
        self.assertFalse((self.home / 'missing').exists())

    def test_deterministic_tie_order(self):
        self.file('z.txt', 1)
        self.file('a.txt', 1)
        self.assertEqual([p.name for p, _ in recent.recent_files(self.folder)], ['a.txt', 'z.txt'])

    def test_uri_escaping_preserves_real_filename(self):
        path = self.file('report #1 % résumé.txt', 1)
        uri = recent.file_uri(path)
        self.assertEqual(urlparse(uri).scheme, 'file')
        self.assertEqual(unquote(urlparse(uri).path), str(path))
        self.assertIn('%23', uri)
        self.assertIn('%25', uri)

    def test_refresh_does_not_keep_deleted_files(self):
        path = self.file('old.txt', 1)
        self.assertEqual(len(recent.recent_files(self.folder)), 1)
        path.unlink()
        self.assertEqual(recent.recent_files(self.folder), [])

    def test_only_requested_folders(self):
        self.assertEqual(set(recent.FOLDERS), {'downloads', 'screenshots'})
        self.assertEqual(recent.folder_path('screenshots', self.home), self.home / 'Pictures/Screenshots')

    def test_list_command_without_gui(self):
        path = self.file('report.txt', 1)
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'downloads', '--list'],
                                env={'HOME':str(self.home), 'PATH':os.environ['PATH']},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [path.as_uri()])


if __name__ == '__main__':
    unittest.main()
