"""Exercise nginx additions against isolated installations, repositories and port state."""
import concurrent.futures
import json
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
    env = dict(os.environ, STATE_PATH=str(root/'state'), GSTATE_PATH=str(root/'global'), PORT_STATE_GROUP=str(os.getgid()), HOME=str(root/'home'),
               USER='tester', ENV_USER='tester', TOOLKIT_HIST_LOCK='1',
               PATH=str(installed) + ':' + os.environ['PATH'])

    def call(tool, *args, cwd=None, ok=True, environment=None):
        result = subprocess.run([str(installed/tool), *args], cwd=cwd,
                                env=environment or env, text=True,
                                capture_output=True, timeout=30)
        assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    def repo(name, start, count=100):
        path = root/name
        (path/'services').mkdir(parents=True)
        call('bootstrap', 'repo', 'load', str(path))
        call('port', 'allocate', 'create', name, '-s', str(start), '-c', str(count))
        return path

    def add(path, **kwargs):
        return call('bootstrap', 'nginx', 'add', cwd=path, **kwargs)

    call('bootstrap.bin/setup')
    call('port.bin/setup')
    index = root/'global/ports/allocate/ports'
    project = repo('project', 6700)
    original_makefile = 'start:\n\t@echo existing\n'
    (project/'Makefile').write_text(original_makefile)
    api = project/'services/api/env-dir'
    (api/'default').mkdir(parents=True)
    (api/'tester').mkdir()
    (api/'default/PORT').write_text('6700\n')
    (api/'tester/PORT').write_text('6701\n')
    missing = project/'services/worker/env-dir/default'
    missing.mkdir(parents=True)
    # Accept the empty directory left by repo create without nginx support.
    nginx = project/'services/nginx'
    nginx.mkdir()
    assert add(project) == str(nginx)
    assert (nginx/'env-dir/default/PORT').read_text() == '6760\n'
    assert (nginx/'env-dir/tester/PORT').read_text() == '6760\n'
    assert (nginx/'env-dir/default/HOST').read_text() == 'localhost\n'
    assert (nginx/'env-dir/tester/HOST').read_text() == 'localhost\n'
    assert (nginx/'routes').is_dir()
    for filename in ('Makefile', 'start', 'nginx.conf'):
        assert (nginx/filename).read_bytes() == (src/'bootstrap.bin/template/nginx'/filename).read_bytes()
    assert (project/'Makefile').read_text() == original_makefile
    assert (api/'default/PORT').read_text() == '6700\n'
    assert (api/'tester/PORT').read_text() == '6701\n'
    assert not (missing/'PORT').exists()
    assert not (missing.parent/'tester').exists()
    before = index.read_bytes()
    (nginx/'routes/custom.conf').write_text('# keep me\n')
    add(project, ok=False)
    assert index.read_bytes() == before
    assert (nginx/'routes/custom.conf').read_text() == '# keep me\n'
    assert not list((project/'services').glob('.nginx.*'))

    fallback = repo('fallback', 6800)
    call('port', 'allocate', 'set', 'fallback', '6860', '-m', 'occupied')
    add(fallback, environment=dict(env, ENV_USER='default'))
    assert (fallback/'services/nginx/env-dir/default/PORT').read_text() == '6800\n'

    # Reuse a retained named reservation after a failed earlier publication.
    retry = repo('retry', 6900)
    reserved = call('port', 'allocate', 'pull', 'retry', '-n', 'services/nginx')
    add(retry)
    assert (retry/'services/nginx/env-dir/default/PORT').read_text().strip() == reserved

    failed = repo('failed', 7000, count=1)
    call('port', 'allocate', 'pull', 'failed', '-n', 'services/occupied')
    add(failed, ok=False)
    assert not (failed/'services/nginx').exists()
    assert not list((failed/'services').glob('.nginx.*'))
    call('port', 'allocate', 'rm', '-p', '7000')
    add(failed)

    unregistered = root/'unregistered'
    unregistered.mkdir()
    add(unregistered, ok=False)
    assert list(unregistered.iterdir()) == []
    no_domain = root/'no-domain'
    no_domain.mkdir()
    call('bootstrap', 'repo', 'load', str(no_domain))
    add(no_domain, ok=False)
    assert not (no_domain/'services/nginx').exists()

    unsafe = repo('unsafe', 7100)
    (unsafe/'services/nginx').symlink_to(project/'services/nginx', target_is_directory=True)
    add(unsafe, ok=False)
    (unsafe/'services/nginx').unlink()
    (unsafe/'services').rmdir()
    (unsafe/'services').symlink_to(project/'services', target_is_directory=True)
    add(unsafe, ok=False)
    add(unsafe, ok=False, environment=dict(env, ENV_USER='../bad'))

    race = repo('race', 7200)
    def attempt(_):
        return subprocess.run([str(installed/'bootstrap'), 'nginx', 'add'],
                              cwd=race, env=env, capture_output=True, timeout=30).returncode
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(attempt, range(2))) == [0, 1]
    records = [json.loads(line) for line in index.read_text().splitlines()]
    assert len([r for r in records if r['domain'] == 'race' and r.get('name') == 'services/nginx']) == 1
    assert not list((race/'services').glob('.nginx.*'))
    call('bootstrap', 'nginx', 'add', '--help')
    call('bootstrap', 'nginx', 'add', 'extra', cwd=race, ok=False)
    call('port', 'allocate', 'default', '--service', cwd=race, ok=False)

print('bootstrap nginx checks passed')
