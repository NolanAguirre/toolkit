"""Isolated UI scaffold checks using the real dispatcher and port allocator."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile

src = Path(__file__).resolve().parents[1] / 'src'
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    installed = root/'bin'
    shutil.copytree(src, installed)
    src = installed
    for file in src.rglob('*'):
        if file.is_file():
            file.chmod(0o755)
    repo = root/'sample'
    repo.mkdir()
    env = dict(os.environ, UTIL_PATH=str(root/'state'), USER='tester',
               TOOLKIT_HIST_LOCK='1', PATH=str(src) + ':' + os.environ['PATH'])

    def call(tool, *args, ok=True, cwd=repo):
        result = subprocess.run([str(src/tool), *args], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=30)
        assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
        return result

    call('bootstrap.bin/setup')
    call('port.bin/setup')
    call('port', 'allocate', 'create', 'sample')
    index = root/'state/ports/allocate/ports'
    plain = repo/'ui/plain'
    assert call('bootstrap', 'ui', 'add', 'plain').stdout.strip() == str(plain)
    package = json.loads((plain/'package.json').read_text())
    assert package['scripts'] == {'start': 'vite', 'build': 'vite build'}
    assert 'component-library' not in package['dependencies']
    assert not (repo/'services').exists()
    assert (plain/'env-dir/default/PORT').read_bytes() == (plain/'env-dir/tester/PORT').read_bytes()
    records = [json.loads(line) for line in index.read_text().splitlines()]
    assert records[0]['name'] == 'ui/plain'
    before = index.read_bytes()
    for args in [('plain',), ('../bad',), ('bad\nname',), ('bad', '--type=nodejs'),
                 ('bad', '--support'), ('bad', '--support=http'),
                 ('bad', '--support=component-library')]:
        call('bootstrap', 'ui', 'add', *args, ok=False)
    assert index.read_bytes() == before
    assert not (repo/'ui/bad').exists()
    (repo/'ui/link').symlink_to(repo/'missing')
    call('bootstrap', 'ui', 'add', 'link', ok=False)

    library = repo/'component-library'
    (library/'src').mkdir(parents=True)
    (library/'package.json').write_text('{"name":"component-library"}\n')
    (library/'src/index.js').write_text('export const value = 1\n')
    (library/'Makefile').write_text('install:\n\techo library-install >> ../order\nbuild:\n\techo library-build >> ../order\n')
    call('bootstrap', 'ui', 'add', 'shared', '--support', 'component-library')
    shared = repo/'ui/shared'
    assert json.loads((shared/'package.json').read_text())['dependencies']['component-library'] == 'file:../../component-library'
    assert (library/'src/index.js').read_text() == 'export const value = 1\n'
    assert 'ui add' in call('bootstrap', 'ui', 'add', '--help').stdout
    # Library install and build must finish before app installation, even with -j.
    npm = src/'npm'
    npm.write_text('#!/bin/sh\necho app-install >> ../../order\n')
    npm.chmod(0o755)
    subprocess.run(['make', '-j4', 'install'], cwd=shared, env=env,
                   check=True, capture_output=True, timeout=30)
    assert (repo/'order').read_text().splitlines() == [
        'library-install', 'library-build', 'app-install']
    npm.unlink()

    def race(_):
        return subprocess.run([str(src/'bootstrap'), 'ui', 'add', 'race'], cwd=repo,
                              env=env, capture_output=True, timeout=30).returncode
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(race, range(2))) == [0, 1]
    assert not list((repo/'ui').glob('.ui.*'))
    records = [json.loads(line) for line in index.read_text().splitlines()]
    assert len([r for r in records if r['name'] == 'ui/race']) == 1

    # A dependency-edit failure must not publish files or reserve a port.
    npm = src/'npm'
    npm.write_text('#!/bin/sh\nexit 1\n')
    npm.chmod(0o755)
    before = index.read_bytes()
    call('bootstrap', 'ui', 'add', 'npm-failed', '--support=component-library', ok=False)
    assert not (repo/'ui/npm-failed').exists()
    assert not list((repo/'ui').glob('.ui.*'))
    assert index.read_bytes() == before

    # A process outside bootstrap can create the target during staging.
    npm.write_text('#!/bin/sh\nmkdir -p "' + str(repo/'ui/appeared') + '"\n')
    call('bootstrap', 'ui', 'add', 'appeared', '--support=component-library', ok=False)
    assert (repo/'ui/appeared').is_dir()
    assert not list((repo/'ui/appeared').iterdir())
    assert not list((repo/'ui').glob('.ui.*'))
    assert any(json.loads(line)['name'] == 'ui/appeared' for line in index.read_text().splitlines())
    npm.unlink()
    records = [json.loads(line) for line in index.read_text().splitlines()]

    no_domain = root/'no-domain'
    no_domain.mkdir()
    call('bootstrap', 'ui', 'add', 'failed', cwd=no_domain, ok=False)
    assert not list((no_domain/'ui').iterdir())
    assert len(index.read_text().splitlines()) == len(records)

print('bootstrap UI checks passed')
