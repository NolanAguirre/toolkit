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

    before = (tagger/'remote-services').read_bytes()
    call('bootstrap', 'service', 'add', 'tagger', '--type=nodejs', '--support=python', cwd=fresh, ok=False)
    assert (tagger/'remote-services').read_bytes() == before
    assert not list((fresh/'services').glob('.service.*'))

print('bootstrap service scaffolding and foreground launchers passed')
