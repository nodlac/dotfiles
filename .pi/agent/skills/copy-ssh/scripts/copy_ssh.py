#!/usr/bin/env python3
"""Request the local terminal clipboard through tmux, never another session."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

MAX_BYTES = 65536

class CopyError(Exception):
    pass

def tmux(*args, input=None):
    try:
        result = subprocess.run(['tmux', *args], input=input, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise CopyError('tmux unavailable or timed out; clipboard receipt is unknown.') from None
    if result.returncode:
        # Do not expose tmux stderr: an error could echo sensitive copied text.
        raise CopyError('tmux command failed; clipboard receipt is unknown.')
    return result.stdout.decode('utf-8', errors='replace')

def select_client(pane, requested=None):
    if not pane or not re.fullmatch(r'%\d+', pane):
        raise CopyError('No valid TMUX_PANE. Use this from the SSH tmux session.')
    sessions = set()
    for line in tmux('list-panes', '-a', '-F', '#{pane_id}\t#{session_name}').splitlines():
        fields = line.split('\t', 1)
        if len(fields) == 2 and fields[0] == pane:
            sessions.add(fields[1])
    if not sessions:
        raise CopyError('Current pane is not available in this tmux server.')
    clients = []
    # client_session is essential; generic session_name may resolve the wrong context.
    for line in tmux('list-clients', '-F', '#{client_name}\t#{client_session}').splitlines():
        fields = line.split('\t', 1)
        if len(fields) == 2 and fields[1] in sessions:
            clients.append(fields[0])
    clients = sorted(set(clients))
    if requested:
        if requested not in clients:
            raise CopyError('Requested client is not attached to this pane\'s session.')
        return requested
    if not clients:
        raise CopyError('No terminal client attached to this pane\'s session; clipboard unchanged.')
    if len(clients) != 1:
        raise CopyError('Multiple clients attached to this pane\'s session. Ask which to use; specify --client.')
    return clients[0]

def copy_payload(payload, requested=None, dry_run=False, pane=None):
    if not payload:
        raise CopyError('Empty content; clipboard unchanged.')
    if len(payload) > MAX_BYTES:
        raise CopyError('Content exceeds 64 KiB; request a smaller selection.')
    try:
        text = payload.decode('utf-8')
    except UnicodeDecodeError:
        raise CopyError('Only UTF-8 text is supported.') from None
    if '\x00' in text:
        raise CopyError('NUL bytes are unsupported; clipboard unchanged.')
    client = select_client(pane if pane is not None else os.environ.get('TMUX_PANE'), requested)
    commands = tmux('list-commands').splitlines()
    modern = any(line.startswith('load-buffer ') and re.search(r'\[[^\]]*w[^\]]*\]', line) for line in commands)
    method = 'load-buffer-stdin' if modern else 'set-buffer-compatible'
    if dry_run:
        return {'status': 'dry-run', 'client': client, 'bytes': len(payload), 'method': method}
    # Re-check membership immediately before sending; no cached or cross-session targets.
    select_client(pane if pane is not None else os.environ.get('TMUX_PANE'), client)
    buffer = 'pi-copy-ssh-' + uuid.uuid4().hex
    cleanup_ok = True
    try:
        if modern:
            tmux('load-buffer', '-w', '-b', buffer, '-t', client, '-', input=payload)
        else:
            # Older server: this is the method confirmed working with Ghostty over SSH.
            tmux('set-buffer', '-w', '-b', buffer, '-t', client, '--', text)
    finally:
        try:
            tmux('delete-buffer', '-b', buffer)
        except CopyError:
            cleanup_ok = False
    return {'status': 'sent', 'client': client, 'bytes': len(payload), 'method': method,
            'temporary_buffer_removed': cleanup_ok, 'local_clipboard_verified': False}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, help='Copy one explicitly requested UTF-8 file, otherwise stdin')
    parser.add_argument('--client', help='Explicitly selected client attached to this pane\'s session')
    parser.add_argument('--dry-run', action='store_true', help='Resolve routing without touching clipboard')
    args = parser.parse_args()
    try:
        if args.file:
            if not args.file.is_file():
                raise CopyError('Requested path is not a regular file.')
            with args.file.open('rb') as f:
                payload = f.read(MAX_BYTES + 1)
        else:
            if sys.stdin.isatty():
                raise CopyError('Provide text on stdin or use --file.')
            payload = sys.stdin.buffer.read(MAX_BYTES + 1)
        print(json.dumps(copy_payload(payload, args.client, args.dry_run)))
        return 0
    except (CopyError, OSError) as exc:
        message = str(exc) if isinstance(exc, CopyError) else 'Requested file could not be read; details withheld.'
        print(json.dumps({'status': 'error', 'message': message}), file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
