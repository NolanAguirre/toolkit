"""Temporary-state remote tests. SSH and privileged host utilities are mocked.

The received shell script runs locally with /var and /run paths redirected into
this temporary directory. No network access or actual user/ownership changes.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

src = Path(__file__).resolve().parents[1] / 'src'
with tempfile.TemporaryDirectory(prefix='toolkit-remote-') as tmp:
    root = Path(tmp)
    installed = root/'bin'
    shutil.copytree(src, installed)
    for file in installed.rglob('*'):
        if file.is_file():
            file.chmod(0o755)
    host = root/'host'
    host.mkdir()
    (host/'var').mkdir()
    (host/'opt').mkdir()
    (host/'var/run').mkdir(parents=True)
    mocks = root/'host-bin'
    mocks.mkdir()
    utility = mocks/'mock'
    utility.write_text('''#!/usr/bin/env python3
import fcntl, json, os, pathlib, stat, subprocess, sys
root = pathlib.Path(os.environ['MOCK_HOST'])
a = sys.argv[1:]
cmd = pathlib.Path(sys.argv[0]).name
users_file = root/'users.json'
owners_file = root/'owners.json'
users = json.loads(users_file.read_text()) if users_file.exists() else {}
owners = json.loads(owners_file.read_text()) if owners_file.exists() else {}
if cmd == 'uname':
    print(os.environ.get('MOCK_OS', 'Linux'))
elif cmd == 'id':
    if a == ['-u']: print(0)
    elif a[0] == '-gn': print('wheel' if a[1] == 'root' and os.environ.get('MOCK_OS') == 'FreeBSD' else a[1])
    elif a == ['-un']: print(os.environ.get('MOCK_CURRENT_USER', 'root'))
    else: sys.exit(1)
elif cmd == 'getent':
    name = a[1]
    if name not in users: sys.exit(2)
    if a[0] == 'passwd': print(users[name])
    else: print(name + ':x:999:')
elif cmd == 'useradd':
    name = a[-1]
    if name in users: sys.exit(1)
    users[name] = name + ':x:999:999:' + a[a.index('--comment')+1] + ':' + a[a.index('--home-dir')+1] + ':' + a[a.index('--shell')+1]
    users_file.write_text(json.dumps(users))
elif cmd == 'chown':
    assert '-R' not in a
    owners[a[1]] = a[0].split(':')[0]
    owners_file.write_text(json.dumps(owners))
elif cmd == 'stat':
    mode, path = a[1:]
    if mode in ('%U', '%Su'): print(owners.get(path, 'root'))
    elif mode in ('%G', '%Sg'): print('wheel' if owners.get(path, 'root') == 'root' and os.environ.get('MOCK_OS') == 'FreeBSD' else owners.get(path, 'root'))
    elif mode == '%u': print(0 if owners.get(path, 'root') == 'root' else 999)
    elif mode in ('%a', '%Lp'): print(oct(stat.S_IMODE(os.stat(path).st_mode))[2:])
    else: sys.exit(1)
elif cmd == 's6-setlock':
    assert a[:2] == ['-d', '9']
    fd = os.open(a[2], os.O_CREAT | os.O_WRONLY, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    if fd != 9: os.dup2(fd, 9)
    os.set_inheritable(9, True)
    os.execvp(a[3], a[3:])
elif cmd == 's6-setuidgid':
    assert a[0] in users
    os.environ['MOCK_CURRENT_USER'] = a[0]
    os.execvp(a[1], a[1:])
elif cmd == 's6-svok':
    target = pathlib.Path(a[0])
    if not (root/'var/service/.s6-svscan/control').exists(): sys.exit(1)
    if not (root/'var/service'/target.name).is_symlink(): sys.exit(1)
elif cmd == 's6-svc':
    assert a[0] == '-t'
    with (root/'restarts').open('a') as log: log.write(a[1] + '\\n')
elif cmd == 'mv':
    if '-fh' in a: a[a.index('-fh')] = '-fT'
    os.execv('/usr/bin/mv', ['mv'] + a)
elif cmd == 'tar':
    result = subprocess.run(['/usr/bin/tar'] + a)
    if result.returncode: sys.exit(result.returncode)
    if os.environ.get('MOCK_CURRENT_USER') and '-C' in a:
        directory = pathlib.Path(a[a.index('-C')+1])
        for path in [directory, *directory.rglob('*')]: owners[str(path)] = os.environ['MOCK_CURRENT_USER']
        owners_file.write_text(json.dumps(owners))
elif cmd == 'pw':
    name = a[a.index('-n')+1]
    if a[0] == 'groupadd': pass
    elif a[0] == 'useradd':
        assert '-m' not in a and a[a.index('-w')+1] == 'no'
        users[name] = name + ':x:999:999:' + a[a.index('-c')+1] + ':' + a[a.index('-d')+1] + ':' + a[a.index('-s')+1]
        users_file.write_text(json.dumps(users))
    else: sys.exit(1)
elif cmd == 'sync':
    if os.environ.get('FAIL_HOST_SYNC'): sys.exit(1)
elif cmd == 'sysrc':
    config_file = root/'rc.json'
    config = json.loads(config_file.read_text()) if config_file.exists() else {}
    if a[0] == '-n':
        if a[1] not in config: sys.exit(1)
        print(config[a[1]])
    else:
        config.update(value.split('=', 1) for value in a)
        config_file.write_text(json.dumps(config))
elif cmd == 'service':
    assert a[0] == 's6'
    scan = root/'var/service/.s6-svscan'
    if a[1] == 'onestatus': sys.exit(0 if (scan/'control').exists() else 1)
    assert a[1] == 'start'
    scan.mkdir(exist_ok=True)
    os.mkfifo(scan/'control')
elif cmd == 'systemctl':
    if a[0] in ('show', 'daemon-reload'): pass
    elif a == ['enable', '--now', 'toolkit-remote-svscan.service']:
        if os.environ.get('FAIL_SYSTEMD'): sys.exit(1)
        scan = root/'var/service/.s6-svscan'
        scan.mkdir(exist_ok=True)
        os.mkfifo(scan/'control')
    else: sys.exit(1)
elif cmd == 's6-svscanctl':
    assert a == ['-a', str(root/'var/service')]
    if not (root/'var/service/.s6-svscan/control').exists(): sys.exit(1)
elif cmd == 's6-svstat':
    path = pathlib.Path(a[0])
    if os.environ.get('FAIL_SUPERVISOR'): sys.exit(1)
    if path.name == 'log': print('up (pid 123) 10 seconds')
    elif (path/'down').exists() or not (path/'server/current/run').exists(): print('down 10 seconds, normally down')
    else: print('up (pid 124) 10 seconds')
elif cmd in ('s6-envdir', 's6-log', 's6-svscan'):
    sys.exit(0)
else: sys.exit(1)
''')
    utility.chmod(0o755)
    for name in ('uname', 'id', 'getent', 'useradd', 'pw', 'chown', 'stat', 'sync', 'mv', 'tar',
                 's6-setlock', 's6-svok', 's6-svc', 'sysrc', 'service', 'systemctl',
                 's6-svscanctl', 's6-svstat', 's6-setuidgid', 's6-envdir', 's6-log', 's6-svscan'):
        (mocks/name).symlink_to('mock')
    local_sync = installed/'sync'
    local_sync.write_text('#!/bin/sh\n[ -z "${FAIL_LOCAL_SYNC:-}" ] || exit 1\nexec /usr/bin/sync "$@"\n')
    local_sync.chmod(0o755)
    ssh = installed/'ssh' 
    ssh.write_text('''#!/usr/bin/env python3
import os, pathlib, subprocess, sys
assert sys.argv[1:] == ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', 'test-pi', 'sudo -n sh -s'], sys.argv
root = pathlib.Path(os.environ['MOCK_HOST'])
script = sys.stdin.read()
with (root/'ssh-calls').open('a') as log: log.write('call\\n')
(root/'last-script').write_text(script)
if os.environ.get('FAIL_SSH'): sys.exit(255)
script = script.replace('/opt/', str(root/'opt') + '/').replace('/var/run', str(root/'var/run')).replace('/var/service', str(root/'var/service')).replace('/run/systemd/system', str(root/'run/systemd/system')).replace('/etc/systemd/system', str(root/'etc/systemd/system')).replace('/usr/local/etc/rc.d/s6', str(root/'usr/local/etc/rc.d/s6'))
script = script.replace('PATH="/usr/local/sbin:/usr/local/bin:$PATH"', 'PATH="$PATH"')
env = dict(os.environ, PATH=os.environ['MOCK_BIN'] + ':' + os.environ['PATH'])
sys.exit(subprocess.run(['sh', '-s'], input=script, text=True, env=env).returncode)
''')
    ssh.chmod(0o755)
    env = dict(os.environ, UTIL_PATH=str(root/'state'), HOME=str(root/'home'),
               USER='tester', ENV_USER='tester', TOOLKIT_HIST_LOCK='1',
               MOCK_HOST=str(host), MOCK_BIN=str(mocks),
               PATH=str(installed) + ':' + os.environ['PATH'])

    def call(tool, *args, ok=True, extra=None):
        result = subprocess.run([str(installed/tool), *args], env=dict(env, **(extra or {})),
                                text=True, capture_output=True, timeout=30)
        assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    def remote(*args, **kwargs):
        return call('remote', *args, **kwargs)

    def base(service):
        return host/f'var/service-dir/demo-{service}'

    call('remote.bin/setup')
    call('bootstrap.bin/setup')
    repo = root/'demo'
    (repo/'services/api/env-dir/default').mkdir(parents=True)
    (repo/'services/api/env-dir/default/PORT').write_text('8001\n')
    (repo/'services/dns').mkdir()
    (repo/'services/shared.js').write_text('// not a service\n')
    call('bootstrap', 'repo', 'load', str(repo))
    remote('create', 'demo', 'test-pi')
    assert remote('ls') == 'demo\ttest-pi'
    target = root/'state/remote/targets/demo'
    assert target.stat().st_mode & 0o777 == 0o600
    call('remote.bin/setup')
    assert target.read_text() == 'test-pi\n'
    remote('edit', 'demo', 'changed', ok=False, extra={'FAIL_LOCAL_SYNC': '1'})
    assert target.read_text() == 'test-pi\n'
    assert not list(target.parent.glob('.atomic-write.*'))
    remote('create', 'demo', 'test-pi', ok=False)
    remote('edit', 'demo', '-oProxyCommand=bad', ok=False)
    remote('edit', 'demo', 'x\ntrue', ok=False)
    remote('setup', 'all', 'demo', 'extra', ok=False)
    remote('setup', 'service', 'demo', 'missing', ok=False)
    remote('deploy', 'demo', ok=False)
    assert not (host/'ssh-calls').exists()
    remote('setup', 'directories', 'demo', ok=False)
    assert not (host/'var/service-dir').exists()
    remote('setup', 'users', 'demo')
    users_before = (host/'users.json').read_bytes()
    remote('setup', 'users', 'demo')
    assert (host/'users.json').read_bytes() == users_before
    remote('setup', 'service', 'demo', '--all', ok=False)
    remote('setup', 'directories', 'demo')
    (base('api')/'data/keep').write_text('persistent\n')
    remote('setup', 'service', 'demo', 'api')
    assert (base('api')/'run').exists()
    assert not (base('dns')/'run').exists()
    remote('setup', 'service', 'demo', '--all')
    assert (base('api')/'env/PORT').read_text() == '8001\n'
    assert not (base('dns')/'env/PORT').exists()
    assert not (base('api')/'down').exists()
    assert not (base('api')/'server/current').exists()
    api = base('api')
    run = (api/'run').read_text()
    assert f"exec s6-envdir ./env s6-setuidgid 'demo-api' ./server/current/run" in run
    assert f'server/current/api' not in run
    assert 'make --no-print-directory start' not in run
    assert f"exec s6-setuidgid 'demo-apilog' s6-log t s1048576 n100 ./main" in (api/'log/run').read_text()
    assert api.stat().st_mode & 0o777 == 0o755
    assert (api/'env').stat().st_mode & 0o777 == 0o755
    assert (api/'etc').stat().st_mode & 0o777 == 0o755
    assert (api/'bin').stat().st_mode & 0o777 == 0o755
    assert (api/'server').stat().st_mode & 0o777 == 0o755
    assert (api/'data').stat().st_mode & 0o777 == 0o700
    assert (api/'log').stat().st_mode & 0o777 == 0o755
    assert (api/'log/main').stat().st_mode & 0o777 == 0o755
    assert (api/'run').stat().st_mode & 0o777 == 0o755
    assert (api/'log/run').stat().st_mode & 0o777 == 0o755
    assert (api/'bin/deploy').stat().st_mode & 0o777 == 0o755
    assert (api/'env/PORT').stat().st_mode & 0o777 == 0o644
    owners = json.loads((host/'owners.json').read_text())
    assert owners[str(api/'server')] == 'demo-apiowner'
    assert owners[str(api/'data')] == f'demo-api'
    assert owners[str(api/'log/main')] == f'demo-apilog'
    remote('setup', 'supervision', 'demo', ok=False)
    # The host owns scanner startup; setup only registers services with s6.
    scan = host/'var/service/.s6-svscan'
    scan.mkdir()
    os.mkfifo(scan/'control')
    # Host-managed services may share the scanner without toolkit taking them over.
    foreign = host/'var/service/unrelated'
    foreign.mkdir()
    (foreign/'run').write_text('#!/bin/sh\nexec sleep 1000\n')
    link = host/'var/service'/base('api').name
    link.symlink_to(foreign)
    remote('setup', 'supervision', 'demo', ok=False)
    assert link.resolve() == foreign
    link.unlink()
    remote('setup', 'all', 'demo')
    assert foreign.is_dir()
    assert not (host/'etc').exists()
    assert link.resolve() == base('api')
    remote('setup', 'supervision', 'demo')
    assert link.resolve() == base('api')
    assert 'awaiting-runtime' in remote('status', 'demo')
    # A reboot may clear the ephemeral coordination lock, without losing setup.
    (host/'var/run/toolkit-remote.lock').unlink()
    assert 'awaiting-runtime' in remote('status', 'demo')
    (scan/'control').unlink()
    remote('status', 'demo', ok=False)
    remote('setup', 'supervision', 'demo', ok=False)
    os.mkfifo(scan/'control')
    before = (base('api')/'run').read_bytes()
    remote('setup', 'service', 'demo', 'api', ok=False, extra={'FAIL_HOST_SYNC': '1'})
    assert (base('api')/'run').read_bytes() == before
    assert not list(base('api').glob('.atomic-write.*'))
    remote('status', 'demo', ok=False, extra={'FAIL_SUPERVISOR': '1'})
    remote('status', 'demo', ok=False, extra={'FAIL_SSH': '1'})
    assert not list((root/'state/remote').glob('.ssh.*'))
    assert not list((root/'state/remote').glob('.services.*'))
    (base('api')/'env/PORT').write_text('9999\n')
    assert 'port-drift' in remote('status', 'demo', ok=False)
    remote('setup', 'service', 'demo', 'api')
    assert (base('api')/'env/PORT').read_text() == '8001\n'
    # A developer's override follows bootstrap's PORT selection.
    override = repo/'services/api/env-dir/tester'
    override.mkdir()
    (override/'PORT').write_text('8002\n')
    remote('setup', 'service', 'demo', 'api')
    assert (base('api')/'env/PORT').read_text() == '8002\n'
    (override/'PORT').write_text('bad\n')
    calls_before = (host/'ssh-calls').read_bytes()
    remote('setup', 'all', 'demo', ok=False)
    assert (host/'ssh-calls').read_bytes() == calls_before
    (override/'PORT').write_text('8002\n')
    # Preserve explicit operator state on repeat setup.
    (base('api')/'down').write_text('')
    remote('setup', 'all', 'demo')
    assert (base('api')/'down').exists()
    assert (base('api')/'data/keep').read_text() == 'persistent\n'
    # Reject path conflicts without following links or rewriting permissions.
    run = base('api')/'run'
    run.unlink()
    victim = root/'victim'
    victim.write_text('preserve\n')
    run.symlink_to(victim)
    remote('setup', 'service', 'demo', 'api', ok=False)
    assert victim.read_text() == 'preserve\n'
    run.unlink()
    remote('setup', 'service', 'demo', 'api')
    # Concurrent clients share only the host lock, not the local state lock.
    state2 = root/'state2'
    shutil.copytree(root/'state', state2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(remote, 'setup', 'all', 'demo', extra={'UTIL_PATH': str(state)})
                   for state in (root/'state', state2)]
        for future in futures:
            future.result()
    assert (host/'users.json').read_bytes() == users_before
    assert remote('status', 'demo').count('awaiting-runtime') == 2
    # Generated bin/deploy extracts as the owner and activates each service independently.
    release = root/'release-001'
    for name in ('api', 'dns'):
        artifact = release/name
        artifact.mkdir(parents=True)
        (artifact/'run').write_text('#!/bin/sh\nexec sleep 1000\n')
        (artifact/'run').chmod(0o755)
        (artifact/'private.js').write_text('// application code\n')
        (artifact/'private.js').chmod(0o600)
    remote('deploy', 'demo', str(release))
    current = api/'server/current'
    published = current.resolve()
    assert published.parent == api/'server'
    assert published.name.startswith('server-')
    assert not current.readlink().is_absolute()
    assert (published/'private.js').stat().st_mode & 0o777 == 0o644
    owners = json.loads((host/'owners.json').read_text())
    assert owners[str(published/'run')] == 'demo-apiowner'
    assert not (host/'var/repo').exists()
    assert (api/'down').exists()  # Deployment preserves an operator's down flag.
    assert str(api) in (host/'restarts').read_text()
    dns_current = (base('dns')/'server/current').resolve()
    remote('deploy', 'demo', 'api', str(release/'api'))
    assert current.resolve() != published
    assert (base('dns')/'server/current').resolve() == dns_current
    (release/'api/link').symlink_to(root/'victim')
    calls_before = (host/'ssh-calls').read_bytes()
    remote('deploy', 'demo', str(release), ok=False)
    assert (host/'ssh-calls').read_bytes() == calls_before
    (release/'api/link').unlink()
    # A failed owner-side preparation hook leaves current and service state intact.
    previous = current.resolve()
    prepare = api/'bin/deploy-prepare'
    prepare.write_text('#!/bin/sh\nexit 1\n')
    prepare.chmod(0o755)
    restarts = (host/'restarts').read_bytes()
    remote('deploy', 'demo', 'api', str(release/'api'), ok=False)
    assert current.resolve() == previous
    assert (host/'restarts').read_bytes() == restarts
    prepare.unlink()
    for _ in range(4):
        remote('deploy', 'demo', 'api', str(release/'api'))
    assert len(list((api/'server').glob('server-*'))) == 4
    assert current.resolve().is_dir()
    assert not list((root/'state/remote').glob('.deploy.*'))
    assert not list((api/'server').glob('.current.*'))
    # Clients serialize through the host's s6-setlock, preserving all successful releases.
    def publish(state):
        return subprocess.run([str(installed/'remote'), 'deploy', 'demo', 'api', str(release/'api')],
                              env=dict(env, UTIL_PATH=str(state)), capture_output=True, timeout=30).returncode
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(publish, [root/'state', state2])) == [0, 0]
    assert len(list((api/'server').glob('server-*'))) == 4
    # Linux can start just the scanner through systemd when no scanner is running.
    (scan/'control').unlink()
    (host/'run/systemd/system').mkdir(parents=True)
    (host/'etc/systemd/system').mkdir(parents=True)
    (host/'etc/systemd/system').chmod(0o755)
    remote('setup', 'supervision', 'demo')
    launcher = (host/'etc/systemd/system/toolkit-remote-svscan.service').read_text()
    assert f' /{host.relative_to("/")}/var/service' in launcher
    assert 'KillMode=mixed' in launcher
    assert 'demo-api' not in launcher
    # FreeBSD uses native pw/stat/mv and the s6 package rc.d service.
    bsd = root/'freebsd'
    (bsd/'var/run').mkdir(parents=True)
    rc = bsd/'usr/local/etc/rc.d/s6'
    rc.parent.mkdir(parents=True)
    rc.write_text('#!/bin/sh\n')
    rc.chmod(0o755)
    bsd_env = {'MOCK_OS': 'FreeBSD', 'MOCK_HOST': str(bsd)}
    remote('setup', 'all', 'demo', extra=bsd_env)
    assert json.loads((bsd/'rc.json').read_text()) == {'s6_enable': 'YES', 's6_path': str(bsd/'var/service')}
    assert not (bsd/'etc/systemd').exists()
    remote('deploy', 'demo', 'api', str(release/'api'), extra=bsd_env)
    assert (bsd/'var/service-dir/demo-api/server/current/run').is_file()
    # Local creation races have one winner and retain a usable lock inode.
    remote('rm', 'demo')
    lock = root/'state/remote/lock'
    inode = lock.stat().st_ino
    def create():
        return subprocess.run([str(installed/'remote'), 'create', 'demo', 'test-pi'],
                              env=env, capture_output=True, timeout=30).returncode
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: create(), range(2))) == [0, 1]
    assert lock.stat().st_ino == inode
    assert target.read_text() == 'test-pi\n'
    print('remote: local validation, host setup/status, preservation, failures and concurrency passed')
