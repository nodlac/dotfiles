import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('copy_ssh', Path(__file__).parents[1]/'scripts/copy_ssh.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

class ClipboardTests(unittest.TestCase):
    def fake(self, modern=False, clients='/dev/pts/16\tmy-session\n', panes='%12\tmy-session\n'):
        calls=[]
        def command(*args, input=None):
            calls.append((args,input))
            if args[0]=='list-panes':return panes
            if args[0]=='list-clients':return clients
            if args[0]=='list-commands':return 'load-buffer [-w] [-b buffer-name] [-t target-client] path' if modern else 'load-buffer [-b buffer-name] [-t target-client] path'
            return ''
        return calls,command

    def test_modern_uses_stdin_and_cleans_buffer(self):
        calls,cmd=self.fake(modern=True)
        with patch.object(m,'tmux',cmd):result=m.copy_payload(b'https://example.com/',pane='%12')
        send=next(c for c in calls if c[0][0]=='load-buffer')
        self.assertEqual(send[1],b'https://example.com/')
        self.assertNotIn('https://example.com/',send[0])
        self.assertEqual(result['status'],'sent')
        self.assertFalse(result['local_clipboard_verified'])
        self.assertTrue(any(c[0][0]=='delete-buffer' for c in calls))

    def test_compatible_method_treats_text_as_data(self):
        calls,cmd=self.fake()
        text='--flag; $(do-not-run) "hello"\n🍵'
        with patch.object(m,'tmux',cmd):result=m.copy_payload(text.encode(),pane='%12')
        send=next(c for c in calls if c[0][0]=='set-buffer')
        self.assertEqual(send[0][-2:],('--',text))
        self.assertEqual(result['method'],'set-buffer-compatible')
        self.assertTrue(all(c[0][0]!='run-shell' for c in calls))

    def test_dry_run_does_not_write(self):
        calls,cmd=self.fake()
        with patch.object(m,'tmux',cmd):result=m.copy_payload(b'hello',dry_run=True,pane='%12')
        self.assertEqual(result['status'],'dry-run')
        self.assertFalse(any(c[0][0] in ['load-buffer','set-buffer','delete-buffer'] for c in calls))

    def test_foreign_session_not_targeted(self):
        calls,cmd=self.fake(clients='/dev/pts/0\tother-session\n')
        with patch.object(m,'tmux',cmd),self.assertRaises(m.CopyError):m.copy_payload(b'hello',pane='%12')
        self.assertFalse(any(c[0][0]=='set-buffer' for c in calls))

    def test_uses_client_session_not_generic_session_context(self):
        calls,cmd=self.fake()
        with patch.object(m,'tmux',cmd):m.copy_payload(b'hello',dry_run=True,pane='%12')
        self.assertTrue(any('#{client_name}\t#{client_session}' in c[0] for c in calls))

    def test_multiple_clients_refused(self):
        _,cmd=self.fake(clients='/dev/pts/1\tmy-session\n/dev/pts/2\tmy-session\n')
        with patch.object(m,'tmux',cmd),self.assertRaises(m.CopyError):m.copy_payload(b'hello',pane='%12')

    def test_explicit_client_within_session(self):
        _,cmd=self.fake(clients='/dev/pts/1\tmy-session\n/dev/pts/2\tmy-session\n')
        with patch.object(m,'tmux',cmd):result=m.copy_payload(b'hello',requested='/dev/pts/2',dry_run=True,pane='%12')
        self.assertEqual(result['client'],'/dev/pts/2')

    def test_explicit_foreign_client_refused(self):
        _,cmd=self.fake()
        with patch.object(m,'tmux',cmd),self.assertRaises(m.CopyError):m.copy_payload(b'hello',requested='/dev/pts/0',pane='%12')

    def test_pane_linked_into_two_sessions_is_ambiguous(self):
        _,cmd=self.fake(panes='%12\ta\n%12\tb\n',clients='/dev/pts/1\ta\n/dev/pts/2\tb\n')
        with patch.object(m,'tmux',cmd),self.assertRaises(m.CopyError):m.copy_payload(b'hello',pane='%12')

    def test_invalid_payloads_do_not_call_tmux(self):
        for payload in [b'',b'x'*(m.MAX_BYTES+1),b'\xff',b'a\0b']:
            with self.subTest(payload_length=len(payload)),patch.object(m,'tmux') as cmd,self.assertRaises(m.CopyError):
                m.copy_payload(payload,pane='%12')
            cmd.assert_not_called()

    def test_missing_pane(self):
        with patch.object(m,'tmux') as cmd,self.assertRaises(m.CopyError):m.copy_payload(b'hello',pane='')
        cmd.assert_not_called()

    def test_tmux_failure_hides_stderr(self):
        import subprocess
        bad=subprocess.CompletedProcess(['tmux'],1,stdout=b'',stderr=b'secret-content')
        with patch.object(m.subprocess,'run',return_value=bad),self.assertRaises(m.CopyError) as error:m.tmux('set-buffer')
        self.assertNotIn('secret',str(error.exception))

    def test_timeout_hides_payload(self):
        import subprocess
        with patch.object(m.subprocess,'run',side_effect=subprocess.TimeoutExpired(['secret-content'],10)),self.assertRaises(m.CopyError) as error:m.tmux('set-buffer')
        self.assertNotIn('secret',str(error.exception))

if __name__=='__main__':unittest.main()
