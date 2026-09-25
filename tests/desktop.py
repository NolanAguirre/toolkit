"""Isolated desktop command checks; does not launch real desktop applications."""
import concurrent.futures
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time

src = Path(__file__).resolve().parents[1] / 'src'
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    env = dict(os.environ, UTIL_PATH=str(root/'state'), HOME=str(root/'home'),
               XDG_CONFIG_HOME=str(root/'config'), TOOLKIT_HIST_LOCK='1')
    (root/'home').mkdir()
    repo = root/"repo with 'quotes' and spaces"
    repo.mkdir()

    def call(*args, ok=True):
        result = subprocess.run(['sh', str(src/'desktop'), *args], env=env, text=True, capture_output=True)
        assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
        return result

    subprocess.run([str(src/'desktop.bin/setup')], env=env, check=True, capture_output=True)
    call('workspace', 'create', 'demo', '2', str(repo))
    call('workspace', 'create', '../escape', '2', str(repo), ok=False)
    call('workspace', 'edit', 'demo', '0', str(repo), ok=False)
    call('command', 'create', 'demo', '10-service', 'tab', "printf '%s\\n' 'a | b'; make start")
    call('command', 'create', 'demo', '20-shell', 'tab', ':')
    call('command', 'create', 'demo', '30-editor', 'cursor', 'cursor --new-window .')
    command = root/'state/desktop/workspaces/demo/commands/10-service/run'
    before = command.read_text()
    call('command', 'edit', 'demo', '10-service', 'if then', ok=False)
    assert command.read_text() == before
    call('workspace', 'edit', 'demo', '4', str(repo))
    assert 'Workspace 4 [demo]' in call('start', '--dry-run').stdout
    call('workspace', 'create', 'other', '1', str(repo))
    call('command', 'mv', 'demo', '30-editor', 'other', '10-editor')
    assert 'cursor' in call('command', 'ls', 'other').stdout
    call('autostart', 'create')
    startup = root/'config/autostart/desktop-bootstrap.desktop'
    assert 'start --login' in startup.read_text()
    call('autostart', 'rm')
    assert not startup.exists()

    def contender(_):
        return subprocess.run(['sh', str(src/'desktop'), 'workspace', 'create', 'race', '3', str(repo)], env=env, capture_output=True).returncode

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(contender, range(2))) == [0, 1]
    subprocess.run([str(src/'desktop.bin/setup')], env=env, check=True, capture_output=True)
    assert command.read_text() == before
    call('workspace', 'mv', 'other', 'renamed')
    call('workspace', 'rm', 'renamed')
    assert repo.exists()
    mocks = root/'bin'
    mocks.mkdir()
    scripts = {
        'gdbus': '#!/bin/sh\nprintf "(\047placed\047,)\\n"\n',
        'gsettings': '#!/bin/sh\ncase "$*" in *dynamic-workspaces*) echo false;; *) echo 5;; esac\n',
        'gnome-terminal': '#!/usr/bin/python3\nimport os,sys,json\ntry:\n os.fstat(9); raise RuntimeError("inherited lock")\nexcept OSError: pass\nopen(os.environ["ARGS"],"w").write(json.dumps(sys.argv[1:]))\n',
    }
    for name, contents in scripts.items():
        path = mocks/name
        path.write_text(contents)
        path.chmod(0o755)
    runtime = root/'runtime'
    runtime.mkdir()
    env.update(PATH=str(mocks)+':'+env['PATH'], XDG_RUNTIME_DIR=str(runtime), ARGS=str(root/'args.json'))
    call('start', 'demo')
    for _ in range(30):
        if (root/'args.json').exists():
            break
        time.sleep(.1)
    args = json.loads((root/'args.json').read_text())
    assert args.count('--window') == 1 and args.count('--tab') == 1, args
    assert args[args.index('--working-directory')+1] == str(repo)
    payload = shlex.split(args[args.index('--command')+1])[-1]
    subprocess.run(['sh', '-n', '-c', payload], check=True)
    assert not call('start', 'demo').stdout.startswith('Workspace')
    # All-or-nothing preflight: invalid later workspace must prevent any launching.
    call('workspace', 'edit', 'race', '6', str(repo))
    (root/'args.json').unlink()
    call('start', '--force', ok=False)
    assert not (root/'args.json').exists()
    print('PASS: CRUD, failure preservation, concurrency, setup, autostart, terminal quoting/grouping, lock closure, duplicate skips, preflight.')
