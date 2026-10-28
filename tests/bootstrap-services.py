"""Node/Python scaffolding and foreground launchers in disposable local state."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

src = Path(__file__).resolve().parents[1] / 'src'
with tempfile.TemporaryDirectory(prefix='toolkit-bootstrap-service-') as tmp:
    root = Path(tmp)
    installed = root/'bin'
    shutil.copytree(src, installed)
    for file in installed.rglob('*'):
        if file.is_file():
            file.chmod(0o755)
    env = dict(os.environ, UTIL_PATH=str(root/'state'), HOME=str(root/'home'),
               USER='tester', ENV_USER='tester', TOOLKIT_HIST_LOCK='1',
               PATH=str(installed) + ':' + os.environ['PATH'])

    def call(tool, *args, cwd=None, ok=True):
        result = subprocess.run([str(installed/tool), *args], cwd=cwd, env=env,
                                text=True, capture_output=True, timeout=20)
        assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    call('bootstrap.bin/setup')
    call('port.bin/setup')
    catalog = call('bootstrap', 'service', 'type', 'ls').splitlines()
    assert catalog[0].split('\t') == ['type', 'label', 'options', 'required', 'description']
    configs = {row.split('\t')[0]: row.split('\t') for row in catalog[1:]}
    assert configs['nodejs'][2:4] == ['http,fs,db', '-']
    assert configs['node-ml'][2:4] == ['http,fs,db,python', 'python']
    call('bootstrap', 'service', 'type', 'ls', 'unexpected', ok=False)
    fresh = root/'fresh'
    (fresh/'services').mkdir(parents=True)
    call('bootstrap', 'repo', 'load', str(fresh))
    call('port', 'allocate', 'create', 'fresh')
    npm = installed/'npm'
    npm.write_text('#!/bin/sh\nexit 0\n')
    npm.chmod(0o755)
    call('bootstrap', 'service', 'add', 'new', '--type=nodejs', cwd=fresh)
    call('bootstrap', 'service', 'add', 'tagger', '--type=nodejs',
         '--support=http', '--support=python', cwd=fresh)
    tagger = fresh/'services/tagger'
    assert (tagger/'remote-services').read_text() == 'tagger:PORT\ntagger-consumer:-\n'
    assert not (fresh/'services/tagger-consumer').exists()
    assert (tagger/'run').stat().st_mode & 0o111
    assert (tagger/'run-consumer').stat().st_mode & 0o111
    assert (tagger/'cli/consumer.py').is_file()
    # Launch from elsewhere as remote does, inheriting the host environment.
    node = installed/'node'
    node.write_text('#!/bin/sh\nprintf "%s:%s:%s\\n" "$PWD" "$1" "$QUEUE_DIR"\n')
    node.chmod(0o755)
    launcher_env = dict(env, QUEUE_DIR='/host/shared/queue')
    output = subprocess.check_output([str(tagger/'run')], cwd=root, env=launcher_env, text=True)
    assert output.strip() == f'{tagger}:index.js:/host/shared/queue'
    python = tagger/'cli/.venv/bin/python3'
    python.parent.mkdir(parents=True)
    shutil.copy(node, python)
    output = subprocess.check_output([str(tagger/'run-consumer')], cwd=root, env=launcher_env, text=True)
    assert output.strip() == f'{tagger}:cli/consumer.py:/host/shared/queue'
    call('bootstrap', 'service', 'add', 'batch', '--type=nodejs', '--support=python', cwd=fresh)
    assert (fresh/'services/batch/remote-services').read_text() == 'batch:-\nbatch-consumer:-\n'
    assert not (fresh/'services/new/remote-services').exists()
    call('bootstrap', 'service', 'add', 'ml', '--type=node-ml', cwd=fresh)
    assert (fresh/'services/ml/cli/consumer.py').is_file()
    assert (fresh/'services/ml/remote-services').read_text() == 'ml:-\nml-consumer:-\n'

    before = (tagger/'remote-services').read_bytes()
    call('bootstrap', 'service', 'add', 'tagger', '--type=nodejs', '--support=python', cwd=fresh, ok=False)
    assert (tagger/'remote-services').read_bytes() == before
    assert not list((fresh/'services').glob('.service.*'))

    # Auth services need OpenResty, no nginx, and a fresh PostgreSQL database.
    template = src/'bootstrap.bin/template'
    assert configs['auth'][2:4] == ['http,db', 'http,db']
    site = root/'site'
    (site/'services').mkdir(parents=True)
    call('bootstrap', 'repo', 'load', str(site))
    call('port', 'allocate', 'create', 'site', '-s', '7300')
    call('bootstrap', 'db', 'add', 'auth', '--support=postgres', cwd=site)
    call('bootstrap', 'db', 'add', 'lite', '--support=sqlite', cwd=site)
    deploy = site/'db/auth/deploy/v1.000.0.sql'
    plan = site/'db/auth/sqitch.plan'
    untouched = deploy.read_bytes()
    original_plan = plan.read_text()

    def add_auth(name='auth', ok=False):
        return call('bootstrap', 'service', 'add', name, '--type=auth',
                    '--support=http', '--support=db', cwd=site, ok=ok)

    def unchanged():
        assert not (site/'services/auth').exists()
        assert deploy.read_bytes() == untouched
        assert not (site/'services/openresty/routes/auth.conf').exists()
        assert not list((site/'services').glob('.service.*'))

    add_auth()
    unchanged()
    (site/'services/nginx').mkdir()
    call('bootstrap', 'openresty', 'add', cwd=site)
    (site/'services/nginx/nginx.conf').write_text('# configured\n')
    add_auth()
    unchanged()
    (site/'services/nginx/nginx.conf').unlink()
    add_auth('lite')
    assert not (site/'services/lite').exists()
    call('bootstrap', 'service', 'add', 'auth', '--type=auth', '--support=fs', cwd=site, ok=False)
    unchanged()
    deploy.write_text(untouched.decode() + '-- edited\n')
    add_auth()
    deploy.write_bytes(untouched)
    unchanged()
    plan.write_text(original_plan + 'v1.001.0 [v1.000.0] 2026-01-01T00:00:00Z Toolkit <toolkit@localhost> # next\n')
    add_auth()
    plan.write_text(original_plan)
    unchanged()

    # A failed npm install leaves no service, route or migration behind.
    npm.write_text('#!/bin/sh\n[ "$1" != install ]\n')
    add_auth()
    unchanged()
    npm.write_text('#!/bin/sh\nexit 0\n')

    auth = site/'services/auth'
    assert add_auth(ok=True) == str(auth)
    assert deploy.read_bytes() == (template/'auth/deploy.sql').read_bytes()
    assert (site/'db/auth/revert/v1.000.0.sql').read_text() == ''
    assert (site/'db/auth/verify/v1.000.0.sql').read_text() == ''
    assert (auth/'index.js').read_bytes() == (template/'auth/index.js').read_bytes()
    port = (auth/'env-dir/default/PORT').read_text().strip()
    assert (auth/'env-dir/tester/PORT').read_text().strip() == port
    assert (auth/'env-dir/default/HOST').read_text() == '127.0.0.1\n'
    assert (auth/'env-dir/default/DATABASE_URL').read_text() == 'postgresql://postgres@localhost:5432/auth\n'
    route = (site/'services/openresty/routes/auth.conf').read_text()
    assert route == (template/'auth/route.conf').read_text().replace('__PORT__', port)
    assert f'proxy_pass http://127.0.0.1:{port}/auth/login;' in route
    before = route
    add_auth()
    assert (site/'services/openresty/routes/auth.conf').read_text() == before

    # Optional live check of the migration against a disposable database.
    if shutil.which('psql') and subprocess.run(['psql', '-h', 'localhost', '-U', 'postgres', '-Atc', 'select 1'],
                                               capture_output=True).returncode == 0:
        database = f'toolkit_auth_test_{os.getpid()}'
        connection = ['psql', '-h', 'localhost', '-U', 'postgres', '-v', 'ON_ERROR_STOP=1', '-Atq']
        subprocess.run(connection + ['-c', f'create database {database}'], check=True)
        try:
            def sql(statement, ok=True):
                result = subprocess.run(connection + ['-d', database, '-c', statement],
                                        text=True, capture_output=True)
                assert (result.returncode == 0) == ok, (statement, result.stderr)
                return result.stdout.strip()
            for _ in range(2):
                subprocess.run(connection + ['-d', database, '-f', str(deploy)], check=True,
                               env=dict(os.environ, PGOPTIONS='-c client_min_messages=warning'))
            user = sql("select id from auth.register('a@example.com', 'correct horse')")
            assert sql("select id from auth.authenticate('A@Example.com', 'correct horse')") == user
            assert sql("select id is null from auth.authenticate('a@example.com', 'wrong password')") == 't'
            assert sql("select id is null from auth.authenticate('b@example.com', 'correct horse')") == 't'
            assert sql("select password_hash like '$2a$%' from auth_private.users") == 't'
            sql("select auth.register('a@example.com', 'another password')", ok=False)
            sql("select auth.register('c@example.com', 'short')", ok=False)
            sql(f"select auth.register('c@example.com', '{'x' * 73}')", ok=False)
            sql("select auth.register('not-an-email', 'long enough')", ok=False)
        finally:
            subprocess.run(connection + ['-c', f'drop database {database}'], check=True)

print('bootstrap service scaffolding and foreground launchers passed')
