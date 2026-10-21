"""Isolated repository import checks, including existing ports and concurrent imports."""
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
    env = dict(os.environ, UTIL_PATH=str(root/'state'), HOME=str(root/'home'),
               CODEX_HOME=str(root/'home/.codex'),
               USER='tester', ENV_USER='tester', TOOLKIT_HIST_LOCK='1',
               PATH=str(installed) + ':' + os.environ['PATH'])

    def call(tool, *args, cwd=None, ok=True):
        result = subprocess.run([str(installed/tool), *args], cwd=cwd, env=env,
                                text=True, capture_output=True, timeout=20)
        assert (result.returncode == 0) == ok, (args, result.stdout, result.stderr)
        return result.stdout.strip()

    def repo(name, port=None):
        path = root/name
        directory = path/'services/api/env-dir/default'
        directory.mkdir(parents=True)
        if port is not None:
            (directory/'PORT').write_text(str(port) + '\n')
        return path

    def records():
        return [json.loads(line) for line in index.read_text().splitlines()]

    call('bootstrap.bin/setup')
    call('port.bin/setup')
    shared = root/'home/.s6craft'
    (shared/'.cursor/rules').mkdir(parents=True)
    (shared/'.cursor/rules/general.mdc').write_text('shared rules\n')
    (shared/'.cursor/skills/example').mkdir(parents=True)
    (shared/'.cursor/skills/example/SKILL.md').write_text('shared skill\n')
    (shared/'.claude/rules').mkdir(parents=True)
    (shared/'.claude/rules/general.md').write_text('shared claude rule\n')
    (shared/'CLAUDE.md').write_text('shared claude\n')
    (shared/'CODEX.md').write_text('shared codex\n')
    (shared/'ui').mkdir()
    (shared/'ui/CODEX.md').write_text('ui codex\n')
    (shared/'db').mkdir()
    (shared/'db/CODEX.md').write_text('db codex\n')
    (shared/'.cursorignore').write_text('node_modules\n')
    (shared/'.cursorrules').write_text('shared cursor rules\n')
    index = root/'state/ports/allocate/ports'
    existing = repo('existing', 9000)
    (existing/'ui').mkdir()
    call('port', 'allocate', 'create', 'existing')
    call('port', 'allocate', 'set', 'existing', '9000', '-m', 'custom description')
    before = index.read_bytes()
    metadata = root/'state/ports/allocate/existing/9000'
    metadata_before = metadata.read_bytes()
    assert call('bootstrap', 'repo', 'import', str(existing)) == str(existing)
    call('bootstrap', 'repo', 'import', str(existing))
    assert index.read_bytes() == before
    assert metadata.read_bytes() == metadata_before
    assert (root/'state/bootstrap/current_repo').read_text().strip() == 'existing'
    assert (existing/'CLAUDE.md').is_symlink()
    assert (existing/'CLAUDE.md').resolve() == shared/'CLAUDE.md'
    assert (existing/'CODEX.md').resolve() == shared/'CODEX.md'
    assert (existing/'.claude/rules/general.md').resolve() == shared/'.claude/rules/general.md'
    assert (existing/'ui/CODEX.md').resolve() == shared/'ui/CODEX.md'
    assert not (existing/'db').exists()
    codex_config = root/'home/.codex/config.toml'
    assert codex_config.read_text() == 'project_doc_fallback_filenames = ["CODEX.md"]\n'
    codex_config.write_text('model = "x"\n\n[projects."/tmp"]\ntrust_level = "trusted"\n')
    call('bootstrap', 'repo', 'import', str(existing))
    assert codex_config.read_text() == ('project_doc_fallback_filenames = ["CODEX.md"]\nmodel = "x"\n\n'
                                        '[projects."/tmp"]\ntrust_level = "trusted"\n')
    call('bootstrap', 'repo', 'import', str(existing))
    assert codex_config.read_text().count('project_doc_fallback_filenames') == 1
    codex_config.write_text('project_doc_fallback_filenames = ["OTHER.md"]\n')
    call('bootstrap', 'repo', 'import', str(existing), ok=False)
    codex_config.write_text('project_doc_fallback_filenames = ["OTHER.md", "CODEX.md"]\n')
    assert (existing/'.cursorignore').resolve() == shared/'.cursorignore'
    assert (existing/'.cursorrules').resolve() == shared/'.cursorrules'
    assert (existing/'.cursor/rules/general.mdc').resolve() == shared/'.cursor/rules/general.mdc'
    assert (existing/'.cursor/skills/example').resolve() == shared/'.cursor/skills/example'
    # Re-import adds newly shared rules while preserving local files and dangling links.
    (existing/'CLAUDE.md').unlink()
    (existing/'CLAUDE.md').write_text('local instructions\n')
    (existing/'.cursor/rules/general.mdc').unlink()
    (existing/'.cursor/rules/general.mdc').write_text('local rule\n')
    (existing/'.cursorrules').unlink()
    (existing/'.cursorrules').symlink_to(root/'missing-rules')
    (shared/'.cursor/rules/new.mdc').write_text('new shared rule\n')
    call('bootstrap', 'repo', 'import', str(existing))
    assert (existing/'CLAUDE.md').read_text() == 'local instructions\n'
    assert (existing/'.cursor/rules/general.mdc').read_text() == 'local rule\n'
    assert (existing/'.cursorrules').readlink() == root/'missing-rules'
    assert (existing/'.cursor/rules/new.mdc').resolve() == shared/'.cursor/rules/new.mdc'
    # Reject missing sources and linked parent directories before allocating ports.
    missing_rules = repo('missing-rules')
    before = index.read_bytes()
    (shared/'CODEX.md').rename(shared/'saved-codex')
    call('bootstrap', 'repo', 'import', str(missing_rules), ok=False)
    assert index.read_bytes() == before
    assert not (missing_rules/'.cursor').exists()
    (shared/'saved-codex').rename(shared/'CODEX.md')
    linked_rules = repo('linked-rules')
    (linked_rules/'.cursor').symlink_to(shared/'.cursor', target_is_directory=True)
    call('bootstrap', 'repo', 'import', str(linked_rules), ok=False)
    assert index.read_bytes() == before
    assert not (root/'state/bootstrap/repos/linked-rules').exists()
    linked_claude = repo('linked-claude')
    (linked_claude/'.claude').symlink_to(shared/'.claude', target_is_directory=True)
    call('bootstrap', 'repo', 'import', str(linked_claude), ok=False)
    assert index.read_bytes() == before
    assert not (root/'state/bootstrap/repos/linked-claude').exists()

    relative = repo('relative')
    assert call('bootstrap', 'repo', 'import', './relative', cwd=root) == str(relative)
    assert call('bootstrap', 'repo', 'import', '.', cwd=relative) == str(relative)
    assert call('bootstrap', 'repo', 'import', '..', cwd=relative/'services') == str(relative)
    assert call('bootstrap', 'repo', 'import', '../relative', cwd=existing) == str(relative)
    assert call('bootstrap', 'repo', 'import', 'relative/services/..', cwd=root) == str(relative)
    alias = root/'relative-alias'
    alias.symlink_to(relative, target_is_directory=True)
    assert call('bootstrap', 'repo', 'import', './relative-alias', cwd=root) == str(relative)
    assert (root/'state/bootstrap/repos/relative/path').read_text().strip() == str(relative)
    assert not (root/'state/bootstrap/repos/relative-alias').exists()

    fresh = repo('fresh', 9100)
    assert call('bootstrap', 'repo', 'import', str(fresh)) == str(fresh)
    assert any(r['domain'] == 'fresh' and r['port'] == 9100 for r in records())
    assert (root/'state/bootstrap/repos/fresh/path').read_text().strip() == str(fresh)
    assert (fresh/'services/api/env-dir/default/PORT').read_text() == '9100\n'
    # New services can get a port from the imported domain.
    new_port = call('port', 'allocate', 'pull', 'fresh', '-n', 'services/new')
    assert new_port != '9100'
    # Stub only npm; exercise service scaffolding and the real port allocator.
    npm = installed/'npm'
    npm.write_text('#!/bin/sh\nexit 0\n')
    npm.chmod(0o755)
    assert call('bootstrap', 'service', 'add', 'new', '--type=nodejs',
                '--support=http', cwd=fresh) == str(fresh/'services/new')
    assert (fresh/'services/new/env-dir/default/PORT').read_text().strip() == new_port

    named = repo('named')
    call('port', 'allocate', 'create', 'named')
    value = call('port', 'allocate', 'pull', 'named', '-n', 'services/api', '-m', 'keep me')
    portfile = named/'services/api/env-dir/default/PORT'
    portfile.write_text(value + '\n')
    before = index.read_bytes()
    call('bootstrap', 'repo', 'import', str(named))
    assert index.read_bytes() == before
    portfile.write_text('9200\n')
    call('bootstrap', 'repo', 'import', str(named), ok=False)
    assert index.read_bytes() == before

    legacy = repo('legacy', 9300)
    call('port', 'allocate', 'create', 'legacy')
    call('port', 'allocate', 'set', 'legacy', '9300', '-m', 'legacy/services/api')
    before = index.read_bytes()
    call('bootstrap', 'repo', 'import', str(legacy))
    assert index.read_bytes() == before
    (legacy/'services/api/env-dir/default/PORT').write_text('9301\n')
    call('bootstrap', 'repo', 'import', str(legacy), ok=False)
    assert index.read_bytes() == before

    conflict = repo('conflict', 9000)
    call('bootstrap', 'repo', 'import', str(conflict), ok=False)
    assert not (root/'state/bootstrap/repos/conflict').exists()
    assert not (root/'state/ports/allocate/conflict').exists()
    bad = repo('bad', 'not-a-port')
    call('bootstrap', 'repo', 'import', str(bad), ok=False)
    assert not (root/'state/ports/allocate/bad').exists()
    duplicate = repo('duplicate', 9600)
    extra = duplicate/'services/worker/env-dev/default'
    extra.mkdir(parents=True)
    (extra/'PORT').write_text('9600\n')
    call('bootstrap', 'repo', 'import', str(duplicate), ok=False)
    assert not (root/'state/ports/allocate/duplicate').exists()
    empty = root/'empty'
    empty.mkdir()
    call('bootstrap', 'repo', 'import', str(empty), ok=False)
    duplicate_name = repo('other/fresh', 9400)
    call('bootstrap', 'repo', 'import', str(duplicate_name), ok=False)
    assert index.read_bytes() == before

    noport = repo('noport')
    call('port', 'allocate', 'create', 'noport')
    call('port', 'allocate', 'pull', 'noport', '-n', 'services/api')
    before = index.read_bytes()
    call('bootstrap', 'repo', 'import', str(noport))
    assert index.read_bytes() == before
    assert not (noport/'services/api/env-dir/default/PORT').exists()

    selected = repo('selected', 9700)
    userdir = selected/'services/api/env-dir/tester'
    userdir.mkdir()
    (userdir/'PORT').write_text('9701\n')
    call('bootstrap', 'repo', 'import', str(selected))
    assert any(r['port'] == 9701 for r in records())
    assert not any(r['port'] == 9700 for r in records())

    race = repo('race', 9500)
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: call('bootstrap', 'repo', 'import', str(race)), range(2)))
    assert results == [str(race), str(race)]
    assert len([r for r in records() if r['port'] == 9500]) == 1
    call('bootstrap', 'repo', 'rm', 'race')
    assert race.exists()
    call('bootstrap', 'repo', 'import', '--help')
    call('port', 'allocate', 'discover', '--help')

print('bootstrap import checks passed')
