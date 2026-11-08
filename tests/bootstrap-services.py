"""Service scaffolding and foreground launchers in disposable local state."""
import os
from concurrent.futures import ThreadPoolExecutor
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
    env = dict(os.environ, STATE_PATH=str(root/'state'), GSTATE_PATH=str(root/'global'), PORT_STATE_GROUP=str(os.getgid()), HOME=str(root/'home'),
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
    assert configs['go'][2:4] == ['http,fs,db', '-']
    assert configs['empty'][2:4] == ['http,fs,db', '-']
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

    # Go uses its own toolchain and shares the existing environment support.
    go = installed/'go'
    go.write_text('#!/bin/sh\n[ "$1" = mod ] && [ "$2" = init ] || exit 1\n'
                  'printf "module %s\\n" "$3" > go.mod\n')
    go.chmod(0o755)
    npm.write_text('#!/bin/sh\nexit 1\n')
    call('bootstrap', 'service', 'add', 'worker', '--type=go', cwd=fresh)
    worker = fresh/'services/worker'
    assert (worker/'go.mod').read_text() == 'module worker\n'
    assert (worker/'main.go').is_file()
    assert (worker/'Makefile').is_file()
    assert not (worker/'package.json').exists()
    assert list((worker/'env-dir/default').iterdir()) == []
    assert (worker/'env-dir/tester').is_dir()
    assert list((worker/'env-dir/production').iterdir()) == []
    for name, backend, key, value in (
        ('goapi', 'postgres', 'DATABASE_URL', 'postgresql://postgres@localhost:5432/goapi'),
        ('golite', 'sqlite', 'DB_FILE', str(fresh/'db/golite/golite.sqlite')),
    ):
        call('bootstrap', 'db', 'add', name, f'--support={backend}', cwd=fresh)
        call('bootstrap', 'service', 'add', name, '--type=go', '--support=http',
             '--support=fs', '--support=db', cwd=fresh)
        service = fresh/'services'/name
        defaults = service/'env-dir/default'
        assert (defaults/key).read_text() == value + '\n'
        assert (defaults/'WRITE_DIR').read_text() == str(root/'home'/f'.{name}') + '\n'
        assert (defaults/'HOST').read_text() == 'localhost\n'
        assert (defaults/'PORT').read_text().strip().isdigit()
        for file in defaults.iterdir():
            assert (service/'env-dir/tester'/file.name).read_bytes() == file.read_bytes()
            expected = b'#default\n' if file.name == 'WRITE_DIR' else file.read_bytes()
            assert (service/'env-dir/production'/file.name).read_bytes() == expected
    before = (worker/'main.go').read_bytes()
    call('bootstrap', 'service', 'add', 'worker', '--type=go', cwd=fresh, ok=False)
    assert (worker/'main.go').read_bytes() == before
    call('bootstrap', 'service', 'add', 'gopy', '--type=go', '--support=python', cwd=fresh, ok=False)
    assert not (fresh/'services/gopy').exists()
    call('bootstrap', 'service', 'add', 'missingdb', '--type=go', '--support=db', cwd=fresh, ok=False)
    assert not (fresh/'services/missingdb').exists()
    go.write_text('#!/bin/sh\ntouch go.mod\nexit 1\n')
    call('bootstrap', 'service', 'add', 'failedgo', '--type=go', cwd=fresh, ok=False)
    assert not (fresh/'services/failedgo').exists()
    assert not list((fresh/'services').glob('.service.*'))

    # Empty scaffolds must not invoke either failing language toolchain.
    call('bootstrap', 'service', 'add', 'blank', '--type=empty', cwd=fresh)
    blank = fresh/'services/blank'
    assert sorted(file.name for file in blank.iterdir()) == ['Makefile', 'env-dir']
    assert list((blank/'env-dir/default').iterdir()) == []
    assert (blank/'env-dir/tester').is_dir()
    assert list((blank/'env-dir/production').iterdir()) == []
    subprocess.run(['make', 'install', 'build'], cwd=blank, env=env,
                   capture_output=True, text=True, check=True)
    start = subprocess.run(['make', 'start'], cwd=blank, env=env,
                           capture_output=True, text=True)
    assert start.returncode != 0
    assert 'Set the start recipe' in start.stderr
    assert not (blank/'start.log').exists()
    for name, backend, key, value in (
        ('empty_pg', 'postgres', 'DATABASE_URL', 'postgresql://postgres@localhost:5432/empty_pg'),
        ('empty_lite', 'sqlite', 'DB_FILE', str(fresh/'db/empty_lite/empty_lite.sqlite')),
    ):
        call('bootstrap', 'db', 'add', name, f'--support={backend}', cwd=fresh)
        call('bootstrap', 'service', 'add', name, '--type', 'empty', '--support', 'http',
             '--support=fs', '--support=db', cwd=fresh)
        service = fresh/'services'/name
        assert sorted(file.name for file in service.iterdir()) == ['Makefile', 'env-dir']
        defaults = service/'env-dir/default'
        assert sorted(file.name for file in defaults.iterdir()) == [key, 'HOST', 'PORT', 'WRITE_DIR']
        assert (defaults/key).read_text() == value + '\n'
        assert (defaults/'WRITE_DIR').read_text() == str(root/'home'/f'.{name}') + '\n'
        assert (defaults/'HOST').read_text() == 'localhost\n'
        assert (defaults/'PORT').read_text().strip().isdigit()
        for file in defaults.iterdir():
            assert (service/'env-dir/tester'/file.name).read_bytes() == file.read_bytes()
            expected = b'#default\n' if file.name == 'WRITE_DIR' else file.read_bytes()
            assert (service/'env-dir/production'/file.name).read_bytes() == expected

    # Template values are literal, even with metacharacters and placeholder text.
    previous_home = env['HOME']
    env['HOME'] = str(root/'literal & \\ __NAME__ $HOME')
    call('bootstrap', 'service', 'add', 'literal', '--type=empty', '--support=fs', cwd=fresh)
    assert (fresh/'services/literal/env-dir/default/WRITE_DIR').read_text() == env['HOME'] + '/.literal\n'
    env['HOME'] = previous_home
    call('bootstrap', 'service', 'add', 'empty_python', '--type=empty', '--support=python', cwd=fresh, ok=False)
    call('bootstrap', 'service', 'add', 'empty_missing', '--type=empty', '--support=db', cwd=fresh, ok=False)
    assert not (fresh/'services/empty_python').exists()
    assert not (fresh/'services/empty_missing').exists()
    before = (blank/'Makefile').read_bytes()
    call('bootstrap', 'service', 'add', 'blank', '--type=empty', cwd=fresh, ok=False)
    assert (blank/'Makefile').read_bytes() == before

    # Missing fragments fail in staging, before reserving an HTTP port.
    fragment = installed/'bootstrap.bin/template/makefile/service/empty/build'
    fragment.rename(fragment.with_name('build.saved'))
    port_records = root/'global/ports/allocate/ports'
    before = port_records.read_bytes()
    call('bootstrap', 'service', 'add', 'empty_failed', '--type=empty', '--support=http', cwd=fresh, ok=False)
    assert not (fresh/'services/empty_failed').exists()
    assert port_records.read_bytes() == before
    fragment.with_name('build.saved').rename(fragment)

    # The bootstrap lock serializes duplicate additions and preserves the winner.
    def add_empty():
        return subprocess.run([str(installed/'bootstrap'), 'service', 'add', 'empty_race',
                               '--type=empty', '--support=http'], cwd=fresh, env=env,
                              text=True, capture_output=True, timeout=20)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: add_empty(), range(2)))
    assert sorted(result.returncode == 0 for result in results) == [False, True]
    assert (fresh/'services/empty_race/env-dir/default/PORT').is_file()
    assert not list((fresh/'services').glob('.service.*'))
    npm.write_text('#!/bin/sh\nexit 0\n')

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

    # Composed rules preserve each runtime and the optional Python install step.
    for service, expected in (
        (fresh/'services/new', ['npm install', 'npm run build --if-present', 'npm start']),
        (tagger, ['npm install', 'python3 -m venv cli/.venv', 'npm run build --if-present', 'npm start']),
        (worker, ['go mod download', 'go build -o bin/service .', './bin/service']),
        (auth, ['npm install', 'npm run build --if-present', 'npm start']),
    ):
        output = subprocess.check_output(['make', '--no-print-directory', '-n', 'install', 'build', 'start'],
                                         cwd=service, env=env, text=True)
        positions = [output.index(command) for command in expected]
        assert positions == sorted(positions), output
        assert 'envdir "./env-dir/${ENV_USER:-$USER}"' in output
        assert 'pid $!' in output
        assert '__INSTALL__' not in (service/'Makefile').read_text()
    output = subprocess.check_output(['make', '--no-print-directory', '-n', 'install.js', 'consumer'],
                                     cwd=tagger, env=env, text=True)
    assert output.splitlines() == ['npm install', 'envdir "./env-dir/${ENV_USER:-$USER}" cli/.venv/bin/python3 cli/consumer.py']

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
