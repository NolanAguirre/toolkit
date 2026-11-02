"""Standalone host preparation acceptance tests; no root, network or services.

Run: python3 tests/remote-prepare.py
Requires Python 3 and ordinary shell utilities, including flock and sha256sum.
Only temporary script copies are redirected; privileged commands are mocks.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

SRC = Path(__file__).resolve().parents[1] / 'src'
STEPS = ('users', 'directories', 'service', 'supervision', 'deploy', 'releases', 'status')
MOCK = r'''#!/usr/bin/python3
import fcntl, json, os, pathlib, sys
root = pathlib.Path(os.environ['MOCK_ROOT'])
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with (root/'events').open('a') as stream:
    stream.write(json.dumps([name, args]) + '\n')
accounts = root/'accounts.json'
data = json.loads(accounts.read_text())
def save():
    accounts.write_text(json.dumps(data))
def require_lock():
    lock = root/'host/var/run/toolkit-remote.lock'
    assert os.fstat(9).st_ino == lock.stat().st_ino, 'wrong runner lock'
    with lock.open('a') as other:
        try:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        raise AssertionError('runner lock not held')
if name == 'id':
    if args == ['-u']:
        print(os.environ.get('MOCK_UID', '0'))
    elif args == ['-gn', 'root']:
        print('root')
    elif len(args) == 2 and args[0] == '-u' and args[1] in data['users']:
        print(data['users'][args[1]]['uid'])
    else:
        sys.exit(1)
elif name == 'uname':
    print('Linux')
elif name == 'getent':
    assert args[0] == 'group', args
    if args[1] not in data['groups']:
        sys.exit(2)
    print(args[1] + ':x:5000:')
elif name == 'groupadd':
    require_lock()
    assert len(args) == 1 and args[0] not in data['groups'], args
    data['groups'].append(args[0])
    save()
elif name == 'usermod':
    require_lock()
    assert args[:2] == ['-a', '-G'] and len(args) == 4, args
    memberships = data['users'][args[3]]['groups']
    if args[2] not in memberships:
        memberships.append(args[2])
    save()
elif name == 'chgrp':
    data['file_groups'][args[1]] = args[0]
    save()
elif name == 'chown':
    require_lock()
elif name == 'stat':
    if args[:2] == ['-c', '%U']:
        print('root')
    elif args[:2] == ['-c', '%G']:
        print(data['file_groups'].get(args[2], 'root'))
    else:
        os.execv(os.environ['REAL_STAT'], ['stat', *args])
elif name == 's6-setlock':
    assert args[:2] == ['-d', '9'], args
    fd = os.open(args[2], os.O_CREAT | os.O_WRONLY, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.dup2(fd, 9)
    os.set_inheritable(9, True)
    os.execvp(args[3], args[3:])
elif name == 'apt-get':
    assert os.environ['DEBIAN_FRONTEND'] == 'noninteractive'
elif name in ('s6-svscanctl', 's6-svok', 's6-svc'):
    require_lock()
elif name == 'sync':
    pass
else:
    raise AssertionError('unexpected privileged operation: ' + name)
'''


class PrepareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='remote-prepare-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.host = self.root/'host'
        self.source = self.root/'src'
        self.mocks = self.root/'bin'
        self.mocks.mkdir()
        self.accounts = self.root/'accounts.json'
        self.accounts.write_text(json.dumps({
            'users': {'alice': {'uid': 1001, 'groups': ['staff', 'docker']},
                      'bob': {'uid': 1002, 'groups': ['staff', 'audio']}},
            'groups': ['root', 'staff', 'docker', 'audio'], 'file_groups': {}}))
        self.env = {'PATH': str(self.mocks), 'HOME': str(self.root/'home'),
                    'STATE_PATH': str(self.root/'personal'), 'MOCK_ROOT': str(self.root),
                    'REAL_STAT': shutil.which('stat'), 'LC_ALL': 'C'}
        # An allowlist keeps unexpected account/service commands off PATH entirely.
        for name in ('sh', 'env', 'dirname', 'sed', 'mkdir', 'mktemp', 'cp', 'chmod',
                     'mv', 'rm', 'cat', 'sha256sum', 'flock', 'ln', 'readlink', 'tr'):
            executable = shutil.which(name)
            self.assertIsNotNone(executable, name)
            (self.mocks/name).symlink_to(executable)
        mock = self.mocks/'mock'
        mock.write_text(MOCK)
        mock.chmod(0o755)
        for name in ('id', 'uname', 'getent', 'groupadd', 'usermod', 'chgrp', 'chown',
                     'stat', 's6-setlock', 'apt-get', 'sync', 's6-svscan',
                     's6-svscanctl', 's6-svok', 's6-svc', 's6-ipcserver',
                     's6-ipcserver-access', 's6-sudod', 'ssh', 'sudo', 'useradd',
                     'systemctl', 'service'):
            (self.mocks/name).symlink_to(mock)
        files = ['remote.bin/this/install-dependencies', 'remote.bin/this/setup-deploy',
                 'remote.bin/host/bootstrap', 'remote.bin/host/install', 'port.bin/setup',
                 'lib/remote.sh', 'lib/remote-host.sh', 'lib/locking.sh',
                 'remote.bin/.host/validate', 'remote.bin/.host/run']
        files += ['remote.bin/.host/' + step for step in STEPS]
        for relative in files:
            target = self.source/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            body = (SRC/relative).read_text()
            body = re.sub(r'(?<![\w$}/.-])(?:/usr/local|/var/run|/var/lib/s6craft-tools|/var/service-dir|'
                          r'/var/service|/etc|/run|/tmp)',
                          lambda match: str(self.host) + match[0], body)
            body = re.sub(r'(?m)^PATH=.*$', 'PATH="' + str(self.mocks) + '"', body)
            target.write_text(body)
        for relative in ('etc', 'var/run', 'run/toolkit-remote', 'tmp'):
            (self.host/relative).mkdir(parents=True, exist_ok=True)
        (self.host/'etc/os-release').write_text('ID=ubuntu\n')
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.bind(str(self.host/'run/toolkit-remote/sudod.sock'))
        self.addCleanup(self.socket.close)
        self.lib = self.host/'usr/local/lib/toolkit-remote'
        self.ports = self.host/'var/lib/s6craft-tools/ports'
        self.rules = self.host/'etc/toolkit-remote/rules/uid'

    def run_script(self, relative, *args, code=0, extra_env=None):
        path = self.source/relative
        result = subprocess.run(['/bin/sh', str(path), *args], cwd=self.root,
                                env={**self.env, **(extra_env or {})},
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def events(self):
        path = self.root/'events'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def no_personal_state(self):
        self.assertFalse((self.root/'home').exists())
        self.assertFalse((self.root/'personal').exists())
        self.assertFalse((self.host/'var/lib/s6craft-tools/remote').exists())

    def assert_runner(self):
        files = ['lib/remote-host.sh', 'remote.bin/.host/validate', 'remote.bin/.host/run']
        files += ['remote.bin/.host/' + step for step in STEPS]
        digest = hashlib.sha256(b''.join((self.source/path).read_bytes() for path in files))
        self.assertEqual((self.lib/'version').read_text(), digest.hexdigest() + '\n')
        self.assertEqual({p.name for p in self.lib.iterdir()},
                         {'remote-host.sh', 'validate', 'run', 'version', *STEPS})
        for path in files:
            self.assertEqual((self.lib/Path(path).name).read_bytes(), (self.source/path).read_bytes())
        daemon = (self.host/'var/service-dir/toolkit_remote/run').read_text()
        self.assertIn('s6-ipcserver-access -v0 -i ' + str(self.rules.parent), daemon)
        self.assertIn('s6-sudod -t 30000 ' + str(self.lib/'run'), daemon)

    def test_dependencies_and_alias_install_only_expected_packages(self):
        expected = set('ca-certificates age openssh-server openssh-client s6 sudo util-linux '
                       'procps libc-bin coreutils findutils sed grep mawk passwd tar gzip curl '
                       'git jq rsync nodejs npm python3 python3-venv python3-dev build-essential '
                       'daemontools nginx'.split())
        for command in ('this/install-dependencies', 'host/bootstrap'):
            self.run_script('remote.bin/' + command)
        events = self.events()
        self.assertEqual([name for name, _ in events], ['id', 'apt-get', 'apt-get'] * 2)
        for offset in (0, 3):
            self.assertEqual(events[offset + 1][1], ['-o', 'DPkg::Lock::Timeout=120', 'update'])
            args = events[offset + 2][1]
            self.assertEqual(args[:5], ['-o', 'DPkg::Lock::Timeout=120', 'install', '-y', '--no-install-recommends'])
            self.assertEqual(set(args[5:]), expected)
            self.assertEqual(len(args[5:]), len(expected))
        self.assertFalse(self.lib.exists())
        self.assertFalse(self.ports.exists())
        self.no_personal_state()

    def test_aliases_forward_arguments_and_help_without_state(self):
        for direct, alias in (('this/install-dependencies', 'host/bootstrap'),
                              ('this/setup-deploy', 'host/install')):
            first = self.run_script('remote.bin/' + direct, '--help')
            second = self.run_script('remote.bin/' + alias, '--help')
            self.assertEqual(first.stdout, second.stdout)
            first = self.run_script('remote.bin/' + direct, 'one', 'two', code=2)
            second = self.run_script('remote.bin/' + alias, 'one', 'two', code=2)
            self.assertEqual(first.stderr, second.stderr)
        self.assertEqual(self.events(), [])
        self.no_personal_state()

    def test_preparation_requires_root_ubuntu_and_existing_user(self):
        for command in ('this/install-dependencies', 'this/setup-deploy'):
            args = ('alice',) if command.endswith('setup-deploy') else ()
            self.run_script('remote.bin/' + command, *args, code=1, extra_env={'MOCK_UID': '1001'})
        (self.host/'etc/os-release').write_text('ID=debian\n')
        self.run_script('remote.bin/host/bootstrap', code=1)
        result = self.run_script('remote.bin/host/install', 'missing', code=1)
        self.assertIn('unknown user: missing', result.stderr)
        self.assertFalse(self.ports.exists())
        self.assertFalse(self.lib.exists())
        self.assertFalse(any(name in ('apt-get', 'groupadd', 'usermod', 'useradd')
                             for name, _ in self.events()))

    def test_standalone_setup_and_alias_preserve_users_memberships_and_ports(self):
        first = self.run_script('remote.bin/this/setup-deploy', 'alice')
        self.assertIn('Reconnect as alice to apply membership in s6craft-tools.', first.stdout)
        self.assertIn('runner ready\t' + str(self.host/'run/toolkit-remote/sudod.sock'), first.stdout)
        self.assert_runner()
        allocation = self.ports/'allocate/ports'
        allocation.write_text('existing-app\t4100\nother-app\t4200\n')
        before = allocation.read_bytes()
        lock_inode = (self.ports/'lock').stat().st_ino
        (self.rules/'1001/allow').write_text('prior authorization\n')
        for user in ('bob', 'bob'):
            result = self.run_script('remote.bin/host/install', user)
            self.assertIn('Reconnect as bob to apply membership in s6craft-tools.', result.stdout)
            self.assertEqual((self.rules/'1001/allow').read_text(), 'prior authorization\n')
            self.assertTrue((self.rules/'1002/allow').is_file())
            self.assertEqual(allocation.read_bytes(), before)
            self.assertEqual((self.ports/'lock').stat().st_ino, lock_inode)
        data = json.loads(self.accounts.read_text())
        self.assertEqual(data['users']['alice']['groups'], ['staff', 'docker', 's6craft-tools'])
        self.assertEqual(data['users']['bob']['groups'], ['staff', 'audio', 's6craft-tools'])
        self.assertEqual([args for name, args in self.events() if name == 'groupadd'], [['s6craft-tools']])
        self.assert_runner()
        self.no_personal_state()

    def test_existing_registry_group_is_preserved_and_conflicts_rejected(self):
        self.ports.joinpath('allocate').mkdir(parents=True)
        self.ports.joinpath('lock').touch()
        allocation = self.ports/'allocate/ports'
        allocation.write_text('legacy-app\t5100\n')
        data = json.loads(self.accounts.read_text())
        data['groups'].append('legacy-ports')
        data['file_groups'][str(self.ports)] = 'legacy-ports'
        self.accounts.write_text(json.dumps(data))
        result = self.run_script('remote.bin/this/setup-deploy', 'alice')
        self.assertIn('membership in legacy-ports', result.stdout)
        self.assertEqual(allocation.read_text(), 'legacy-app\t5100\n')
        data = json.loads(self.accounts.read_text())
        self.assertEqual(data['users']['alice']['groups'], ['staff', 'docker', 'legacy-ports'])
        before = self.accounts.read_bytes()
        result = self.run_script('remote.bin/host/install', 'bob', code=1,
                                 extra_env={'PORT_STATE_GROUP': 'replacement'})
        self.assertIn('preserve that group', result.stderr)
        self.assertEqual(self.accounts.read_bytes(), before)
        self.assertFalse(any(name in ('chgrp', 'groupadd') for name, _ in self.events()))
        self.no_personal_state()

    def test_setup_waits_for_existing_runner_lock(self):
        lock = self.host/'var/run/toolkit-remote.lock'
        with lock.open('a') as held:
            inode = lock.stat().st_ino
            fcntl.flock(held, fcntl.LOCK_EX)
            process = subprocess.Popen(['/bin/sh', str(self.source/'remote.bin/this/setup-deploy'), 'alice'],
                                       cwd=self.root, env=self.env, text=True,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not any(name == 's6-setlock' for name, _ in self.events()):
                    self.assertIsNone(process.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.02)
                self.assertIsNone(process.poll())
                self.assertFalse(self.lib.exists())
                self.assertFalse(self.ports.exists())
                fcntl.flock(held, fcntl.LOCK_UN)
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stdout + stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()
        self.assertEqual(lock.stat().st_ino, inode)
        self.assert_runner()

    def test_installed_runner_rejects_unrestricted_operations(self):
        self.run_script('remote.bin/this/setup-deploy', 'alice')
        version = (self.lib/'version').read_text().strip()
        before = len(self.events())
        for step in ('install-dependencies', 'setup-deploy', 'install-toolkit', 'sh', '../status',
                     'status,sh'):
            result = self.run_script(self.lib/'run', version, 'demo', step, 'api:4100', code=1)
            self.assertIn('step not allowed:', result.stderr)
        self.assertFalse(any(name == 's6-setlock' for name, _ in self.events()[before:]))
        # Probe only the dispatch boundary: real privileged steps were byte-checked above.
        (self.lib/'validate').write_text('test "$TOOLKIT_REMOTE_LOCKED" = 1\n')
        for step in STEPS:
            (self.lib/step).write_text("printf '%s\\n' 'allowed " + step + "'\n")
        result = self.run_script(self.lib/'run', version, 'demo', ','.join(STEPS), 'api:4100')
        self.assertEqual(result.stdout.splitlines(), ['allowed ' + step for step in STEPS])
        self.no_personal_state()


if __name__ == '__main__':
    unittest.main(verbosity=2)
