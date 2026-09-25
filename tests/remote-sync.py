"""Exercise directory sync against a real local OpenSSH SFTP server, without SSH.

Install openssh-sftp-server or set SFTP_SERVER to its extracted executable.
Only the transport is substituted; real SFTP parses batches and copies files.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

src = Path(__file__).resolve().parents[1] / 'src'
server = os.environ.get('SFTP_SERVER', '/usr/lib/openssh/sftp-server')
if not Path(server).is_file():
    raise SystemExit('Install openssh-sftp-server or set SFTP_SERVER to its executable')
client = shutil.which('sftp')
assert client, 'OpenSSH sftp is required'

with tempfile.TemporaryDirectory(prefix='toolkit-remote-sync-') as tmp:
    root = Path(tmp)
    installed = root/'bin'
    shutil.copytree(src, installed, symlinks=True)
    for file in installed.rglob('*'):
        if file.is_file():
            file.chmod(0o755)
    local = root/'local game'
    host = root/"remote game '$;`literal`"
    fresh = root/'fresh checkout'
    host.mkdir()
    fresh.mkdir()
    for entry in ('Assets', 'Packages', 'ProjectSettings', 'Library'):
        (local/entry).mkdir(parents=True)
    (local/'Assets/Scenes').mkdir()
    (local/'Assets/Scenes/Level.unity').write_text('local scene\n')
    (local/'Assets/Scenes/Level.unity.meta').write_text('guid: preserved\n')
    (local/'Assets/.hidden').write_text('hidden\n')
    (local/'Assets/empty').mkdir()
    (local/'Packages/manifest.json').write_text('{}\n')
    (local/'ProjectSettings/ProjectVersion.txt').write_text('editor version\n')
    (local/'Library/cache').write_text('local cache\n')
    (host/'Library').mkdir()
    (host/'Library/cache').write_text('remote cache\n')

    # Run the actual protocol over pipes instead of making a network connection.
    (installed/'sftp').write_text('''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
a = sys.argv[1:]
assert a[0] == '-b'
assert a[2:] == ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', 'windows-unity'], a
root = pathlib.Path(os.environ['TEST_ROOT'])
batch = pathlib.Path(a[1]).read_text()
with (root/'calls').open('a') as f: f.write(json.dumps(batch) + '\\n')
if os.environ.get('FAIL_SFTP'): sys.exit(255)
# Detect overlapping clients; toolkit's local lock must serialize them.
marker = root/'active'
with marker.open('x'): pass
try:
    if os.environ.get('SLOW_SFTP'): time.sleep(0.2)
    batch = batch.replace('cd "C:/Projects/My Game"\\n', 'cd "' + os.environ['TEST_HOST'] + '"\\n', 1)
    r = subprocess.run([os.environ['REAL_SFTP'], '-D', os.environ['SFTP_SERVER'], '-b', '-'], input=batch, text=True)
    sys.exit(r.returncode)
finally:
    marker.unlink()
''')
    (installed/'sftp').chmod(0o755)
    (installed/'sync').write_text('#!/bin/sh\n[ -z "${FAIL_SYNC:-}" ] || exit 1\nexec /usr/bin/sync "$@"\n')
    (installed/'sync').chmod(0o755)
    env = dict(os.environ, UTIL_PATH=str(root/'state'), HOME=str(root/'home'),
               TOOLKIT_HIST_LOCK='1', TEST_ROOT=str(root), TEST_HOST=str(host),
               SFTP_SERVER=server, REAL_SFTP=client,
               PATH=str(installed) + ':' + os.environ['PATH'])

    def call(*args, ok=True, extra=None):
        result = subprocess.run([str(installed/'remote'), *args],
                                env=dict(env, **(extra or {})),
                                text=True, capture_output=True, timeout=30)
        assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
        return result

    def sync(*args, **kwargs):
        return call('sync', *args, **kwargs)

    def setup():
        subprocess.run([str(installed/'remote.bin/setup')], env=env, check=True, capture_output=True)

    setup()
    sync('create', 'game', 'windows-unity', 'C:/Projects/My Game')
    profile = root/'state/remote/sync/game'
    original = profile.read_bytes()
    assert original == b'windows-unity\nC:/Projects/My Game\nAssets\nPackages\nProjectSettings\n'
    assert profile.stat().st_mode & 0o777 == 0o600
    inode = (root/'state/remote/lock').stat().st_ino
    setup()
    assert profile.read_bytes() == original
    assert (root/'state/remote/lock').stat().st_ino == inode
    assert sync('ls').stdout == 'game\twindows-unity\tC:/Projects/My Game\tAssets\tPackages\tProjectSettings\n'
    relative = subprocess.run(['./remote', 'sync', 'ls'], cwd=installed, env=env,
                              text=True, capture_output=True, check=True)
    assert relative.stdout == sync('ls').stdout
    sync('create', 'game', 'windows-unity', str(host), ok=False)
    sync('edit', 'absent', 'windows-unity', str(host), ok=False)
    sync('edit', 'game', 'windows-unity', str(host), ok=False, extra={'FAIL_SYNC': '1'})
    assert profile.read_bytes() == original
    assert not list(profile.parent.glob('.atomic-write.*'))

    for path in ('relative/path', 'C:\\Projects\\Game', 'C:/bad\n!touch hacked', 'C:/bad\r', 'C:/bad"', 'C:/bad*'):
        sync('edit', 'game', 'windows-unity', path, ok=False)
    for entry in ('..', '.', '../Assets', '/Assets', 'Assets/Scenes', '*.cs', 'bad\nline', 'bad\tname', 'C:drive'):
        sync('edit', 'game', 'windows-unity', str(host), entry, ok=False)
    sync('create', '../bad', 'windows-unity', str(host), ok=False)
    sync('create', 'bad', '-oProxyCommand=bad', str(host), ok=False)
    sync('push', 'game', ok=False)
    sync('pull', 'absent', str(fresh), ok=False)
    assert not (root/'calls').exists()

    # Real recursive transfer, repeat overwrite, hidden files, empty directories, .meta preservation.
    assert sync('push', 'game', str(local)).stdout == ''
    assert (host/'Assets/Scenes/Level.unity.meta').read_bytes() == (local/'Assets/Scenes/Level.unity.meta').read_bytes()
    assert (host/'Assets/.hidden').read_text() == 'hidden\n'
    assert (host/'Assets/empty').is_dir()
    assert (host/'Library/cache').read_text() == 'remote cache\n'
    (host/'Assets/keep.txt').write_text('remote-only\n')
    (local/'Assets/Scenes/Level.unity').write_text('x')
    sync('push', 'game', str(local))
    assert (host/'Assets/Scenes/Level.unity').read_text() == 'x'
    assert (host/'Assets/keep.txt').read_text() == 'remote-only\n'
    assert not (host/'Assets/Assets').exists()

    (host/'Assets/Scenes/Level.unity').write_text('edited in Unity\n')
    sync('pull', 'game', str(local))
    assert (local/'Assets/Scenes/Level.unity').read_text() == 'edited in Unity\n'
    assert (local/'Library/cache').read_text() == 'local cache\n'
    sync('pull', 'game', str(fresh))
    assert (fresh/'Assets/Scenes/Level.unity.meta').exists()
    assert not (fresh/'Library').exists()
    sync('pull', 'game', str(fresh))
    assert not (fresh/'Assets/Assets').exists()

    # A second machine can register the same profile with independent state.
    second = root/'second-state'
    subprocess.run([str(installed/'remote.bin/setup')], env=dict(env, UTIL_PATH=str(second)), check=True, capture_output=True)
    sync('create', 'game', 'windows-unity', 'C:/Projects/My Game', extra={'UTIL_PATH': str(second)})
    sync('pull', 'game', str(fresh), extra={'UTIL_PATH': str(second)})

    calls = (root/'calls').read_bytes()
    (local/'Assets/link').symlink_to(root)
    sync('push', 'game', str(local), ok=False)
    sync('pull', 'game', str(local), ok=False)
    (local/'Assets/link').unlink()
    os.mkfifo(local/'Assets/pipe')
    sync('push', 'game', str(local), ok=False)
    (local/'Assets/pipe').unlink()
    assert (root/'calls').read_bytes() == calls
    sync('push', 'game', str(local), ok=False, extra={'FAIL_SFTP': '1'})
    assert not list((root/'state/remote').glob('.sftp.*'))

    # Missing entries fail before transfer. Missing remote selections cannot partially pull.
    sync('edit', 'game', 'windows-unity', str(host), 'Assets', 'missing')
    (host/'Assets/Scenes/Level.unity').write_text('must not pull\n')
    sync('push', 'game', str(local), ok=False)
    sync('pull', 'game', str(local), ok=False)
    assert (local/'Assets/Scenes/Level.unity').read_text() == 'edited in Unity\n'

    # Literal top-level files, dotfiles and names with spaces/shell punctuation.
    special = "notes '$;`not-a-command`.txt"
    (local/special).write_text('literal\n')
    (local/'.gitignore').write_text('Library/\n')
    sync('edit', 'game', 'windows-unity', str(host), special, '.gitignore')
    sync('push', 'game', str(local))
    sync('pull', 'game', str(fresh))
    assert (fresh/special).read_text() == 'literal\n'
    assert (fresh/'.gitignore').read_text() == 'Library/\n'
    assert not (root/'not-a-command').exists()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(sync, 'push', 'game', str(local), extra={'SLOW_SFTP': '1'}) for _ in range(2)]
        for job in jobs:
            job.result()
    sync('edit', 'game', 'windows-unity', 'C:/Projects/My Game')
    assert profile.read_bytes() == original
    sync('rm', 'game')
    assert not profile.exists()
    assert (host/special).exists() and (local/special).exists()
    sync('rm', 'game', ok=False)
    assert sync('ls').stdout == ''

    help_env = dict(env, TOOLKIT_SRC_PATH=str(src), TOOLKIT_BIN_PATH=str(installed))
    subprocess.run(['sh', str(src/'toolkit.bin/toolkit-test'), 'remote'], env=help_env, check=True, capture_output=True)
    print('remote sync: real SFTP push/pull, profiles, failure, concurrency and help checks passed')
