"""Acceptance tests for remote host install-toolkit; no network or real sudo.

Run: python3 tests/remote-install.py
Requires Python 3, jq, tar and flock. Host paths are redirected before execution;
setup and build are real scripts with probes added only to temporary copies.
"""
import concurrent.futures
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


SRC = Path(__file__).resolve().parents[1] / 'src'

# This program runs as the mock ssh, sudo and privileged host utilities.
MOCK = r'''#!/usr/bin/env python3
import fcntl, json, os, pathlib, re, subprocess, sys, time
root = pathlib.Path(os.environ['MOCK_HOST'])
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]

def log(kind, **fields):
    fd = os.open(root/'events', os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    os.write(fd, (json.dumps(dict(kind=kind, **fields)) + '\n').encode())
    os.close(fd)

def redirect(text):
    # Protect paths already redirected by the mock, including the stage argument.
    text = text.replace(str(root), '@@HOST@@')
    text = re.sub(r'/usr/local|/var/lib/s6craft-tools|/etc/sudoers.d|/run/toolkit-remote|/tmp/toolkit-upload',
                  lambda m: '@@HOST@@' + m[0], text)
    text = text.replace('@@HOST@@', str(root))
    # Root scripts may reset PATH. Keep privileged utility mocks in that PATH.
    text = re.sub(r'(?m)^PATH=.*$', 'PATH=' + os.environ['MOCK_HOST_PATH'], text)
    return text

if name == 'ssh':
    command = args[-1]
    options = args[:-2]
    assert args[-2] == '192.0.2.10', args
    assert ('-tt' in options) != ('-T' in options), args
    assert '-t' not in options, args
    def option(flag):
        return options[options.index(flag) + 1]
    ssh_options = [options[i + 1] for i, value in enumerate(options) if value == '-o']
    ssh_options += [value[2:] for value in options if value.startswith('-o') and value != '-o']
    assert 'StrictHostKeyChecking=yes' in ssh_options, args
    assert not any(value.startswith('StrictHostKeyChecking=') and value != 'StrictHostKeyChecking=yes'
                   for value in ssh_options), args
    assert option('-F') == '/dev/null', args
    assert option('-l') == 'deployer' and option('-p') == '2222', args
    assert option('-i') == os.environ['MOCK_IDENTITY'], args
    assert 'IdentitiesOnly=yes' in ssh_options, args
    phase = 'install' if '-tt' in options else ('cleanup' if re.search(r'\brm\b', command) else 'upload')
    log('ssh', phase=phase, args=args)
    assert 's6-sudo' not in command and 'toolkit-remote/run' not in command, command
    env = dict(os.environ, PATH=os.environ['MOCK_HOST_PATH'],
               HOME=str(root/'home/deployer'), STATE_PATH=str(root/'personal'),
               GSTATE_PATH=str(root/'var/lib/s6craft-tools'))
    if phase == 'upload':
        data = sys.stdin.buffer.read()
        if os.environ.get('FAIL_UPLOAD'):
            # Deliver a truncated archive so any partially created stage is real.
            subprocess.run(['sh', '-c', redirect(command)], input=data[:64], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sys.exit(255)
        result = subprocess.run(['sh', '-c', redirect(command)], input=data, env=env,
                                capture_output=True)
        sys.stdout.buffer.write(result.stdout.replace(str(root).encode(), b''))
        sys.stderr.buffer.write(result.stderr)
        if result.returncode == 0:
            (root/('uploaded-' + str(os.getpid()))).touch()
        sys.exit(result.returncode)
    if phase == 'install':
        for script in (root/'tmp').glob('toolkit-upload.*/install.sh'):
            script.write_text(redirect(script.read_text()))
    elif os.environ.get('FAIL_CLEANUP'):
        sys.exit(255)
    sys.exit(subprocess.run(['sh', '-c', redirect(command)], env=env).returncode)
elif name == 'sudo':
    log('sudo', args=args)
    if os.environ.get('FAIL_SUDO'):
        print('sudo: authentication rejected', file=sys.stderr)
        sys.exit(1)
    assert args[0] == 'sh' and pathlib.Path(args[1]).name == 'install.sh', args
    assert args[2] == str(pathlib.Path(args[1]).parent), args
    os.execvp(args[0], args)
elif name == 'id':
    if args == ['-u']: print(0)
    elif args in (['-gn'], ['-gn', 'root']): print('root')
    elif args == ['-un']: print('root')
    else: sys.exit(1)
elif name in ('chown', 'chgrp'):
    log(name, args=args)
elif name == 'getent':
    assert args[0] == 'group', args
    print(args[1] + ':x:1234:')
elif name == 'flock':
    os.execv(os.environ['MOCK_REAL_FLOCK'], ['flock', *args])
elif name in ('systemctl', 'service', 'apt-get', 'apt', 'pkg', 'useradd', 'groupadd', 's6-sudo'):
    log('forbidden', name=name, args=args)
    sys.exit(98)
elif name == 'age':
    sys.exit(0)
elif name == 'age-keygen':
    log('keygen', args=args)
    if args[:1] == ['-y']:
        print('age1fixture-recipient')
    else:
        print('unexpected identity generation', file=sys.stderr)
        sys.exit(99)
elif name == 'probe':
    phase = args[0]
    assert pathlib.Path(os.environ['GSTATE_PATH']) == root/'var/lib/s6craft-tools'
    if phase == 'build':
        assert pathlib.Path(os.environ['TOOLKIT_BIN_PATH']).resolve().is_relative_to(root), 'unsafe bin path'
        assert pathlib.Path(os.environ['TOOLKIT_SRC_PATH']).resolve().is_relative_to(root), 'unsafe source path'
    lock = root/'var/lib/s6craft-tools/toolkit/lock'
    assert os.fstat(9).st_ino == lock.stat().st_ino, 'fd 9 is not the toolkit lock'
    with lock.open('a') as independent:
        try:
            fcntl.flock(independent, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise AssertionError('toolkit lock is not held')
    if phase == 'setup':
        assert set(args[1:]) == {'--shared-only', '--locked'}, args
    log('probe', phase=phase)
    if phase == 'build':
        if os.environ.get('SLOW_BUILD'): time.sleep(.25)
        if os.environ.get('FAIL_BUILD'): sys.exit(73)
else:
    raise AssertionError(name)
'''


class RemoteInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='toolkit-remote-install-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.client = self.root/'client'
        self.source = self.root/'configured checkout/src'
        self.host = self.root/'host'
        self.state = self.root/'state'
        self.global_state = self.root/'global'
        self.host_global = self.host/'var/lib/s6craft-tools'
        self.managed = self.host/'usr/local/src/toolkit/src'
        self.bin = self.host/'usr/local/bin'
        self.mocks = self.root/'mocks'
        self.mocks.mkdir()
        self.local_mocks = self.root/'local-mocks'
        self.local_mocks.mkdir()
        (self.host/'tmp').mkdir(parents=True)
        shutil.copytree(SRC, self.client, symlinks=True)
        shutil.copytree(SRC, self.source, symlinks=True)
        for directory in (self.client, self.source):
            for path in directory.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    path.chmod(path.stat().st_mode | 0o111)
        self.identity = self.root/'identity with spaces'
        self.identity.write_text('SSH mock never reads this key\n')
        mock = self.mocks/'mock'
        mock.write_text(MOCK)
        mock.chmod(0o755)
        for name in ('sudo', 'id', 'chown', 'chgrp', 'getent', 'flock', 'probe',
                     'systemctl', 'service', 'apt-get', 'apt', 'pkg', 'useradd',
                     'groupadd', 's6-sudo', 'age', 'age-keygen'):
            (self.mocks/name).symlink_to(mock)
        (self.local_mocks/'ssh').symlink_to(mock)
        self.env = dict(os.environ, HOME=str(self.root/'home'), USER='tester',
                        STATE_PATH=str(self.state), GSTATE_PATH=str(self.global_state),
                        TOOLKIT_HIST_LOCK='1', MOCK_HOST=str(self.host),
                        MOCK_IDENTITY=str(self.identity), MOCK_REAL_FLOCK=shutil.which('flock') or '',
                        MOCK_HOST_PATH=str(self.mocks) + ':/usr/bin:/bin',
                        PATH=str(self.local_mocks) + ':/usr/bin:/bin')
        # Source choice must come from configuration, not the invoking command's tree.
        (self.source/'source-choice').write_text('configured source\n')
        (self.client/'source-choice').write_text('wrong source\n')
        (self.source/'.hidden-directory').mkdir()
        (self.source/'.hidden-directory/entry').write_text('hidden directory\n')
        (self.source/'.hidden-file').write_text('hidden file\n')
        (self.source/'fixture-templates').mkdir()
        (self.source/'fixture-templates/template').write_text('template ${UNCHANGED}\n')
        (self.source/'fixture-link').symlink_to('source-choice')
        (self.source.parent/'state').mkdir()
        (self.source.parent/'state/private').write_text('must not ship\n')
        # Assert the actual setup/build entry points are invoked with fd 9 locked.
        for name, phase in (('setup', 'setup'), ('toolkit-build', 'build')):
            script = self.source/'toolkit.bin'/name
            body = script.read_text()
            # setup's default bin path is part of the virtual host as well.
            if name == 'setup':
                body = body.replace('/usr/local/bin', str(self.bin))
            script.write_text(body.replace('#!/bin/sh\n',
                              '#!/bin/sh\nprobe ' + phase + ' "$@" || exit $?\n', 1)
                              + '\nprobe ' + phase + '-done || exit $?\n')
        self.global_state.joinpath('toolkit').mkdir(parents=True)
        (self.global_state/'toolkit/toolkit-path').write_text(str(self.source) + '\n')
        self.run_script(self.client/'remote.bin/setup')
        self.remote('host', 'create', 'fixture', 'ssh://deployer@192.0.2.10:2222',
                    '--identity-file', str(self.identity))

    def run_script(self, script, *args, ok=True, extra=None):
        result = subprocess.run(['sh', str(script), *args], env=dict(self.env, **(extra or {})),
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode == 0, ok, (args, result.stdout, result.stderr))
        return result

    def remote(self, *args, **kwargs):
        return self.run_script(self.client/'remote', *args, **kwargs)

    def install(self, **kwargs):
        return self.remote('host', 'install-toolkit', 'fixture', **kwargs)

    def events(self, kind=None):
        path = self.host/'events'
        events = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [event for event in events if kind is None or event['kind'] == kind]

    def assert_clean(self):
        self.assertEqual(list((self.host/'tmp').glob('toolkit-upload.*')), [])
        self.assertFalse(self.events('forbidden'))

    def assert_transport(self, phases):
        self.assertEqual([event['phase'] for event in self.events('ssh')], phases)
        self.assert_clean()

    def seed_preserved_state(self):
        files = {
            self.host_global/'ports/allocate/ports': b'example\t4100\t4199\n',
            self.host_global/'ports/lock': b'',
            self.host/'personal/encrypt/identity': b'-----BEGIN AGE ENCRYPTED FILE-----\nfixture\n',
            self.host/'personal/encrypt/recipient': b'age1fixture-recipient\n',
            self.host/'usr/local/lib/toolkit-remote/version': b'old-runner-version\n',
            self.host/'usr/local/lib/toolkit-remote/run': b'old runner, do not replace\n',
        }
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return files

    def assert_preserved(self, files):
        for path, data in files.items():
            self.assertEqual(path.read_bytes(), data, str(path))

    def test_fresh_install_and_rerun_preserve_state_and_do_not_prune(self):
        preserved = self.seed_preserved_state()
        self.install()
        self.assert_transport(['upload', 'install', 'cleanup'])
        self.assertTrue((self.host_global/'toolkit/managed-source').is_file())
        self.assertEqual((self.host_global/'toolkit/toolkit-path').read_text().strip(), str(self.managed))
        self.assertEqual((self.host_global/'toolkit/bin-path').read_text().strip(), str(self.bin))
        self.assertFalse((self.host/'personal/toolkit').exists())
        self.assert_preserved(preserved)
        inode = (self.host_global/'toolkit/lock').stat().st_ino
        for base in (self.managed, self.bin):
            self.assertEqual((base/'source-choice').read_text(), 'configured source\n')
            self.assertEqual((base/'.hidden-file').read_text(), 'hidden file\n')
            self.assertEqual((base/'.hidden-directory/entry').read_text(), 'hidden directory\n')
            self.assertEqual((base/'fixture-templates/template').read_text(), 'template ${UNCHANGED}\n')
            self.assertTrue((base/'fixture-link').is_symlink())
            self.assertEqual(os.readlink(base/'fixture-link'), 'source-choice')
            self.assertFalse((base/'state').exists())
        (self.source/'source-choice').write_text('updated source\n')
        (self.source/'.hidden-file').unlink()
        self.install()
        self.assertEqual((self.bin/'source-choice').read_text(), 'updated source\n')
        self.assertFalse((self.managed/'.hidden-file').exists(), 'source tree must be replaced')
        self.assertTrue((self.bin/'.hidden-file').exists(), 'install must not prune installed files')
        self.assertEqual((self.host_global/'toolkit/lock').stat().st_ino, inode)
        self.assert_preserved(preserved)
        self.assert_transport(['upload', 'install', 'cleanup'] * 2)

    def test_custom_bin_path_survives_rerun(self):
        config = self.host_global/'toolkit'
        config.mkdir(parents=True)
        custom = self.host/'custom commands'
        (config/'bin-path').write_text(str(custom) + '\n')
        self.install()
        self.install()
        self.assertEqual((config/'bin-path').read_text(), str(custom) + '\n')
        self.assertTrue((custom/'remote').is_file())
        self.assertFalse((self.bin/'remote').exists())
        self.assert_clean()

    def test_conflicting_source_setting_is_refused(self):
        config = self.host_global/'toolkit'
        config.mkdir(parents=True)
        other = self.host/'existing source'
        other.mkdir()
        (other/'sentinel').write_text('keep\n')
        (config/'toolkit-path').write_text(str(other) + '\n')
        self.install(ok=False)
        self.assertEqual((config/'toolkit-path').read_text(), str(other) + '\n')
        self.assertEqual((other/'sentinel').read_text(), 'keep\n')
        self.assertFalse(self.managed.exists())
        self.assertFalse(self.events('probe'))
        self.assert_transport(['upload', 'install', 'cleanup'])

    def test_unmarked_destination_is_refused(self):
        self.managed.mkdir(parents=True)
        (self.managed/'sentinel').write_text('unmanaged source\n')
        self.install(ok=False)
        self.assertEqual((self.managed/'sentinel').read_text(), 'unmanaged source\n')
        self.assertFalse((self.managed/'remote').exists())
        self.assertFalse(self.events('probe'))
        self.assert_transport(['upload', 'install', 'cleanup'])

    def test_missing_local_configuration_never_connects(self):
        (self.global_state/'toolkit/toolkit-path').unlink()
        self.install(ok=False)
        self.assertEqual(self.events(), [])

    def test_missing_host_and_invalid_json_never_connect(self):
        self.remote('host', 'install-toolkit', 'missing', ok=False)
        config = self.state/'remote/hosts/fixture.json'
        config.write_text('{bad json\n')
        self.install(ok=False)
        self.assertEqual(self.events(), [])

    def test_host_lock_prerequisite_failure_is_clean(self):
        # Omit the actual executable, so command -v checks fail too.
        missing = self.root/'host-without-flock'
        missing.mkdir()
        for directory in (Path('/usr/bin'), Path('/bin'), self.mocks):
            for executable in directory.iterdir():
                if executable.name == 'flock' or not executable.is_file():
                    continue
                link = missing/executable.name
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(executable)
        self.install(ok=False, extra={'MOCK_HOST_PATH': str(missing)})
        self.assertFalse((self.bin/'remote').exists())
        self.assertFalse(self.events('probe'))
        self.assert_transport(['upload', 'install', 'cleanup'])

    def test_interrupted_upload_is_clean_and_does_not_run_sudo(self):
        self.install(ok=False, extra={'FAIL_UPLOAD': '1'})
        self.assertFalse(self.events('sudo'))
        self.assertFalse(self.managed.exists())
        self.assert_transport(['upload', 'cleanup'])

    def test_sudo_rejection_is_clean_and_rerunnable(self):
        self.install(ok=False, extra={'FAIL_SUDO': '1'})
        self.assertFalse(self.managed.exists())
        self.assertFalse(self.events('probe'))
        self.assert_transport(['upload', 'install', 'cleanup'])
        self.install()
        self.assertTrue((self.bin/'remote').is_file())
        self.assert_clean()

    def test_build_failure_is_nonzero_clean_and_rerunnable(self):
        preserved = self.seed_preserved_state()
        self.install(ok=False, extra={'FAIL_BUILD': '1'})
        self.assertTrue(self.managed.is_dir())
        self.assertTrue((self.host_global/'toolkit/managed-source').is_file())
        self.assert_preserved(preserved)
        self.assert_transport(['upload', 'install', 'cleanup'])
        self.install()
        self.assertTrue((self.bin/'remote').is_file())
        self.assert_preserved(preserved)
        self.assert_clean()

    def test_cleanup_failure_does_not_mask_build_failure(self):
        self.install(ok=False, extra={'FAIL_BUILD': '1', 'FAIL_CLEANUP': '1'})
        self.assertEqual([event['phase'] for event in self.events('ssh')],
                         ['upload', 'install', 'cleanup'])

    def start_install(self, extra=None):
        process = subprocess.Popen(['sh', str(self.client/'remote'), 'host', 'install-toolkit', 'fixture'],
                                   env=dict(self.env, **(extra or {})), text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def reap():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        self.addCleanup(reap)
        return process

    def test_source_swap_waits_for_global_lock(self):
        self.install()
        lock = self.host_global/'toolkit/lock'
        (self.source/'source-choice').write_text('after lock\n')
        before = len(self.events('sudo'))
        with lock.open('a') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            process = self.start_install()
            deadline = time.monotonic() + 10
            while len(self.events('sudo')) == before and process.poll() is None:
                self.assertLess(time.monotonic(), deadline, 'install never reached sudo')
                time.sleep(.02)
            time.sleep(.2)
            self.assertIsNone(process.poll(), 'installer must wait for the existing lock')
            self.assertEqual((self.managed/'source-choice').read_text(), 'configured source\n')
        output = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0, output)
        self.assertEqual((self.managed/'source-choice').read_text(), 'after lock\n')
        self.assert_clean()

    def test_concurrent_independent_clients_serialize_setup_and_build(self):
        # Separate local registries prevent the local remote lock hiding host races.
        other_state = self.root/'other-client-state'
        shutil.copytree(self.state, other_state)
        first = self.start_install({'SLOW_BUILD': '1'})
        second = self.start_install({'SLOW_BUILD': '1', 'STATE_PATH': str(other_state)})
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda process: process.communicate(timeout=30), (first, second)))
        self.assertEqual([first.returncode, second.returncode], [0, 0], results)
        self.assertEqual([event['phase'] for event in self.events('probe')],
                         ['setup', 'setup-done', 'build', 'build-done'] * 2)
        self.assertEqual(len(self.events('ssh')), 6)
        self.assertEqual(len(list(self.host.glob('uploaded-*'))), 2)
        self.assert_clean()

    def test_runner_version_mismatch_still_requires_separate_deploy_setup(self):
        preserved = self.seed_preserved_state()
        self.install()
        self.assert_preserved(preserved)
        runner = self.root/'runner'
        body = (SRC/'remote.bin/.host/run').read_text()
        body = body.replace('/usr/local/lib/toolkit-remote', str(self.host/'usr/local/lib/toolkit-remote'))
        body = body.replace('PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"', 'PATH="$PATH"')
        runner.write_text(body)
        result = self.run_script(runner, 'new-client-version', 'demo', 'status', 'api:4100',
                                 ok=False, extra={'PATH': self.env['MOCK_HOST_PATH']})
        self.assertIn('host code differs', result.stderr)

    def test_shared_port_setup_skips_personal_state_and_preserves_allocations(self):
        shared = self.root/'port-shared'
        personal = self.root/'unused-personal'
        extra = {'GSTATE_PATH': str(shared), 'STATE_PATH': str(personal),
                 'PATH': self.env['MOCK_HOST_PATH'], 'PORT_STATE_GROUP': 'fixture'}
        self.run_script(SRC/'port.bin/setup', '--shared-only', extra=extra)
        allocation = shared/'ports/allocate/ports'
        allocation.write_text('demo\t4100\t4199\n')
        inode = (shared/'ports/lock').stat().st_ino
        self.run_script(SRC/'port.bin/setup', '--shared-only', extra=extra)
        self.assertEqual(allocation.read_text(), 'demo\t4100\t4199\n')
        self.assertEqual((shared/'ports/lock').stat().st_ino, inode)
        self.assertFalse(personal.exists())

    def test_setup_all_preserves_encrypted_keys_and_propagates_failure(self):
        # Only the selected real setup scripts are installed in this fixture.
        selected = self.root/'selected-bin'
        selected.mkdir()
        shutil.copytree(SRC/'lib', selected/'lib')
        for name in ('encrypt', 'port'):
            (selected/(name + '.bin')).mkdir()
            script = selected/(name + '.bin')/'setup'
            shutil.copyfile(SRC/(name + '.bin')/'setup', script)
            script.chmod(0o755)
        preserved = self.seed_preserved_state()
        extra = {'TOOLKIT_BIN_PATH': str(selected), 'STATE_PATH': str(self.host/'personal'),
                 'GSTATE_PATH': str(self.host_global), 'PATH': self.env['MOCK_HOST_PATH']}
        self.run_script(SRC/'toolkit.bin/toolkit-setup', '--all', extra=extra)
        self.assert_preserved(preserved)
        self.assertFalse(self.events('keygen'), 'existing encrypted identities must not trigger key generation')
        failing = selected/'broken.bin/setup'
        failing.parent.mkdir()
        failing.write_text('#!/bin/sh\nexit 37\n')
        failing.chmod(0o755)
        self.run_script(SRC/'toolkit.bin/toolkit-setup', '--all', ok=False, extra=extra)
        self.assert_preserved(preserved)


if __name__ == '__main__':
    unittest.main()
