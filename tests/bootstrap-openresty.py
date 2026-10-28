"""Exercise OpenResty and memcached additions against isolated repositories and port state."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


src = Path(__file__).resolve().parents[1] / 'src'
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    installed = root/'bin'
    shutil.copytree(src, installed)
    for file in installed.rglob('*'):
        if file.is_file():
            file.chmod(0o755)
    env = dict(os.environ, UTIL_PATH=str(root/'state'), HOME=str(root/'home'),
               USER='tester', ENV_USER='tester', TOOLKIT_HIST_LOCK='1',
               PATH=str(installed) + ':' + os.environ['PATH'])

    def call(tool, *args, cwd=None, ok=True, environment=None):
        result = subprocess.run([str(installed/tool), *args], cwd=cwd,
                                env=environment or env, text=True,
                                capture_output=True, timeout=30)
        assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
        return result.stdout.strip() if ok else result.stderr

    def repo(name, start, count=100):
        path = root/name
        (path/'services').mkdir(parents=True)
        call('bootstrap', 'repo', 'load', str(path))
        call('port', 'allocate', 'create', name, '-s', str(start), '-c', str(count))
        return path

    def add(path, **kwargs):
        return call('bootstrap', 'openresty', 'add', cwd=path, **kwargs)

    call('bootstrap.bin/setup')
    call('port.bin/setup')
    template = src/'bootstrap.bin/template'
    index = root/'state/ports/allocate/ports'

    # Scaffolding and ports, accepting the empty nginx directory from repo create.
    project = repo('project', 6700)
    (project/'services/nginx').mkdir()
    api = project/'services/api/env-dir/default'
    api.mkdir(parents=True)
    (api/'PORT').write_text('6700\n')
    openresty = project/'services/openresty'
    memcached = project/'services/memcached'
    assert add(project).splitlines() == [str(openresty), str(memcached)]
    assert (openresty/'env-dir/default/PORT').read_text() == '6760\n'
    assert (openresty/'env-dir/tester/PORT').read_text() == '6760\n'
    assert (openresty/'env-dir/default/HOST').read_text() == 'localhost\n'
    memcached_port = (memcached/'env-dir/default/PORT').read_text()
    assert memcached_port == '6701\n'
    assert (memcached/'env-dir/tester/PORT').read_text() == memcached_port
    assert (memcached/'env-dir/default/HOST').read_text() == '127.0.0.1\n'
    assert (openresty/'routes').is_dir() and not list((openresty/'routes').iterdir())
    for filename in ('Makefile', 'start', 'nginx.conf', 'lua/session.lua'):
        assert (openresty/filename).read_bytes() == (template/'openresty'/filename).read_bytes()
    assert (openresty/'.gitignore').read_text() == '/.runtime/\n'
    assert (memcached/'Makefile').read_bytes() == (template/'memcached/Makefile').read_bytes()
    assert (api/'PORT').read_text() == '6700\n'
    assert not list((project/'services').glob('.openresty.*'))
    for directory in (openresty, memcached):
        subprocess.run(['make', '-s', '-C', str(directory), 'help'], check=True, capture_output=True)

    # The start script fails clearly without OpenResty and keeps the secret out of env-dir.
    started = subprocess.run(['make', '-s', '-C', str(openresty), 'start'], env=dict(env, PATH='/usr/bin:/bin'),
                             text=True, capture_output=True, timeout=30)
    assert started.returncode != 0 and 'openresty is not installed' in started.stderr, started.stderr
    assert not list(openresty.glob('env-dir/*/SESSION_SECRET'))

    # Re-running changes nothing.
    before = index.read_bytes()
    (openresty/'routes/custom.conf').write_text('# keep me\n')
    assert 'path already exists' in add(project, ok=False)
    assert index.read_bytes() == before
    assert (openresty/'routes/custom.conf').read_text() == '# keep me\n'
    assert (memcached/'env-dir/default/PORT').read_text() == memcached_port
    assert not list((project/'services').glob('.openresty.*'))

    # nginx add is rejected once OpenResty is present.
    assert 'OpenResty' in call('bootstrap', 'nginx', 'add', cwd=project, ok=False)
    assert not list((project/'services/nginx').iterdir())

    # OpenResty add is rejected when nginx is configured.
    configured = repo('configured', 6800)
    call('bootstrap', 'nginx', 'add', cwd=configured)
    before = index.read_bytes()
    assert 'nginx is configured' in add(configured, ok=False)
    assert index.read_bytes() == before
    assert not (configured/'services/openresty').exists()
    assert not (configured/'services/memcached').exists()

    # A leftover memcached directory blocks the whole command.
    leftover = repo('leftover', 6900)
    (leftover/'services/memcached').mkdir()
    add(leftover, ok=False)
    assert not (leftover/'services/openresty').exists()

    # A busy preferred port falls back, and the default user writes one env-dir.
    fallback = repo('fallback', 7000)
    call('port', 'allocate', 'set', 'fallback', '7070', '-m', 'occupied')
    add(fallback, environment=dict(env, ENV_USER='default'))
    assert (fallback/'services/openresty/env-dir/default/PORT').read_text() == '7000\n'
    assert (fallback/'services/memcached/env-dir/default/PORT').read_text() == '7001\n'
    assert sorted(p.name for p in (fallback/'services/openresty/env-dir').iterdir()) == ['default']

    # A failed memcached allocation removes everything but completed reservations.
    full = repo('full', 7100, count=1)
    add(full, ok=False)
    assert not (full/'services/openresty').exists()
    assert not (full/'services/memcached').exists()
    assert not list((full/'services').glob('.openresty.*'))

    unregistered = root/'unregistered'
    unregistered.mkdir()
    add(unregistered, ok=False)
    assert list(unregistered.iterdir()) == []
    call('bootstrap', 'openresty', 'add', '--help')
    call('bootstrap', 'openresty', 'add', 'extra', cwd=fallback, ok=False)

print('bootstrap openresty checks passed')
