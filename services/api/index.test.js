const assert = require('node:assert/strict')
const { execFileSync } = require('node:child_process')
const { chmodSync, cpSync, existsSync, mkdtempSync, mkdirSync, readdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } = require('node:fs')
const { tmpdir } = require('node:os')
const path = require('node:path')
const { test } = require('node:test')
const { request } = require('node:http')
const { createApi } = require('./index')

const headers = { 'Content-Type': 'application/json', 'X-Toolkit-Request': '1' }

test('REST bootstrap workflows use real shell commands and isolated state', async (t) => {
  const directory = mkdtempSync(path.join(tmpdir(), 'toolkit-api-'))
  const original = { ...process.env }
  let server
  t.after(async () => {
    if (server) await new Promise(resolve => server.close(resolve))
    for (const key of ['UTIL_PATH', 'TOOLKIT_HIST_LOCK', 'PATH', 'HOME', 'USER', 'ENV_USER']) {
      if (original[key] === undefined) delete process.env[key]
      else process.env[key] = original[key]
    }
    rmSync(directory, { recursive: true, force: true })
  })
  const installed = path.join(directory, 'bin')
  cpSync(path.resolve(__dirname, '../../src'), installed, { recursive: true, verbatimSymlinks: true })
  for (const entry of readdirSync(installed, { recursive: true, withFileTypes: true })) {
    if (entry.isFile()) chmodSync(path.join(entry.parentPath, entry.name), 0o755)
  }
  Object.assign(process.env, { UTIL_PATH: path.join(directory, 'state'), TOOLKIT_HIST_LOCK: '1', PATH: `${installed}:${original.PATH}`, HOME: path.join(directory, 'home'), USER: 'tester', ENV_USER: 'tester' })
  const rules = path.join(process.env.HOME, '.s6craft')
  mkdirSync(path.join(rules, '.cursor/rules'), { recursive: true })
  writeFileSync(path.join(rules, 'AGENTS.md'), '# Test rules\n')
  writeFileSync(path.join(rules, '.cursorignore'), '')
  writeFileSync(path.join(rules, '.cursorrules'), '# Test rules\n')
  execFileSync(path.join(installed, 'bootstrap.bin/setup'))
  execFileSync(path.join(installed, 'port.bin/setup'))
  execFileSync(path.join(installed, 'remote.bin/setup'))
  server = createApi()
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const url = `http://127.0.0.1:${server.address().port}`
  const get = route => fetch(`${url}${route}`)
  const post = (route, body) => fetch(`${url}${route}`, { method: 'POST', headers, body: JSON.stringify(body) })
  const repoPath = path.join(directory, 'example')

  await t.test('creates and imports repos without changing existing files', async () => {
    assert.deepEqual(await (await get('/api/health')).json(), { status: 'ok' })
    assert.deepEqual(await (await get('/api/repos')).json(), { repos: [] })
    const created = await post('/api/repos', { name: 'example', parentPath: directory, support: ['nginx'] })
    assert.equal(created.status, 201, JSON.stringify(await created.clone().json()))
    assert.equal((await created.json()).path, repoPath)
    assert.ok(existsSync(path.join(repoPath, 'services/nginx/Makefile')))
    assert.equal((await post('/api/repos', { name: 'example', parentPath: directory })).status, 409)
    mkdirSync(path.join(directory, 'imported/services/api/env-dir/default'), { recursive: true })
    writeFileSync(path.join(directory, 'imported/services/api/env-dir/default/PORT'), '19001\n')
    writeFileSync(path.join(directory, 'imported/keep.txt'), 'preserve me')
    const imported = await post('/api/repos/import', { path: path.join(directory, 'imported') })
    assert.equal(imported.status, 201, JSON.stringify(await imported.clone().json()))
    assert.equal(readFileSync(path.join(directory, 'imported/keep.txt'), 'utf8'), 'preserve me')
    assert.equal((await post('/api/repos/import', { path: path.join(directory, 'imported') })).status, 201)
    mkdirSync(path.join(directory, 'conflict/services/api/env-dir/default'), { recursive: true })
    writeFileSync(path.join(directory, 'conflict/services/api/env-dir/default/PORT'), '19001\n')
    assert.equal((await post('/api/repos/import', { path: path.join(directory, 'conflict') })).status, 409)
    assert.equal(existsSync(path.join(process.env.UTIL_PATH, 'bootstrap/repos/conflict')), false)
    assert.equal((await (await get('/api/repos')).json()).repos.find(repo => repo.current).name, 'imported')
  })

  await t.test('adds database, service and UI to the explicit repo, despite global selection', async () => {
    const database = await post('/api/repos/example/databases', { name: 'api', support: ['sqlite'] })
    assert.equal(database.status, 201, JSON.stringify(await database.clone().json()))
    const service = await post('/api/repos/example/services', { name: 'api', support: ['http', 'db', 'fs'] })
    assert.equal(service.status, 201, JSON.stringify(await service.clone().json()))
    assert.equal(readFileSync(path.join(repoPath, 'services/api/env-dir/default/DB_FILE'), 'utf8').trim(), path.join(repoPath, 'db/api/api.sqlite'))
    assert.equal(readFileSync(path.join(directory, 'imported/services/api/env-dir/default/PORT'), 'utf8'), '19001\n')
    const ui = await post('/api/repos/example/uis', { name: 'dashboard' })
    assert.equal(ui.status, 201, JSON.stringify(await ui.clone().json()))
    const details = await (await get('/api/repos/example')).json()
    assert.deepEqual(details.services.map(item => item.name), ['api', 'nginx'])
    assert.deepEqual(details.uis.map(item => item.name), ['dashboard'])
    assert.deepEqual(details.databases.map(item => item.name), ['api'])
    assert.notEqual(details.services[0].port, details.uis[0].port)
    assert.equal((await post('/api/repos/example/select', {})).status, 200)
    assert.equal((await (await get('/api/repos')).json()).repos.find(repo => repo.current).name, 'example')
  })

  await t.test('service types enforce the Python scaffold for Node ML', async () => {
    const config = await (await get('/api/config')).json()
    assert.deepEqual(Object.keys(config.serviceTypes), ['nodejs', 'node-ml'])
    assert.deepEqual(config.serviceTypes.nodejs.required, [])
    assert.deepEqual(config.serviceTypes['node-ml'].required, ['python'])
    assert.deepEqual(config.serviceTypes['node-ml'].options, ['http', 'fs', 'db', 'python'])
    const plain = await post('/api/repos/imported/services', { name: 'plain', type: 'nodejs', support: [] })
    assert.equal(plain.status, 201, JSON.stringify(await plain.clone().json()))
    assert.equal(existsSync(path.join(directory, 'imported/services/plain/cli')), false)
    // Even a client omitting the required option must get the ML scaffold.
    const ml = await post('/api/repos/imported/services', { name: 'ml', type: 'node-ml', support: [] })
    assert.equal(ml.status, 201, JSON.stringify(await ml.clone().json()))
    const mlPath = path.join(directory, 'imported/services/ml')
    assert.ok(existsSync(path.join(mlPath, 'cli/consumer.py')))
    assert.ok(existsSync(path.join(mlPath, 'cli/fsqueue.py')))
    assert.equal(readFileSync(path.join(mlPath, 'remote-services'), 'utf8'), 'ml:-\nml-consumer:-\n')
    assert.equal(readFileSync(path.join(mlPath, 'env-dir/default/QUEUE_DIR'), 'utf8').trim(), '/tmp/imported/queues/ml')
    const explicit = await post('/api/repos/imported/services', { name: 'ml-http', type: 'node-ml', support: ['http', 'python'] })
    assert.equal(explicit.status, 201, JSON.stringify(await explicit.clone().json()))
    assert.equal(readFileSync(path.join(directory, 'imported/services/ml-http/remote-services'), 'utf8'), 'ml-http:PORT\nml-http-consumer:-\n')
    assert.ok(existsSync(path.join(directory, 'imported/services/ml-http/env-dir/default/PORT')))
    for (const body of [
      { type: 'unknown' }, { type: null }, { type: 'nodejs', support: ['python'] },
      { type: 'node-ml', support: ['unknown'] }, { type: 'node-ml', support: ['python', 'python'] },
    ]) {
      assert.equal((await post('/api/repos/imported/services', { name: 'invalid', ...body })).status, 400)
      assert.equal(existsSync(path.join(directory, 'imported/services/invalid')), false)
    }
  })

  await t.test('concurrent duplicate additions publish once and preserve port reservations', async () => {
    const responses = await Promise.all([
      post('/api/repos/example/services', { name: 'worker', support: ['http'] }),
      post('/api/repos/example/services', { name: 'worker', support: ['http'] }),
    ])
    assert.deepEqual(responses.map(response => response.status).sort(), [201, 409])
    const records = readFileSync(path.join(process.env.UTIL_PATH, 'ports/allocate/ports'), 'utf8').trim().split('\n').map(JSON.parse)
    assert.equal(records.filter(record => record.domain === 'example' && record.name === 'services/worker').length, 1)
    assert.equal(readdirSync(path.join(repoPath, 'services')).some(name => name.startsWith('.service.')), false)
  })

  await t.test('reports CLI failures and rejects malformed names/options before mutation', async () => {
    assert.equal((await post('/api/repos/example/uis', { name: 'library-ui', support: ['component-library'] })).status, 422)
    assert.equal(existsSync(path.join(repoPath, 'ui/library-ui')), false)
    assert.equal((await post('/api/repos/example/services', { name: 'missingdb', support: ['db'] })).status, 422)
    assert.equal(existsSync(path.join(repoPath, 'services/missingdb')), false)
    assert.equal((await post('/api/repos/example/services', { name: '../escape' })).status, 400)
    assert.equal((await post('/api/repos/example/services', { name: 'x;touch-owned' })).status, 400)
    assert.equal((await post('/api/repos/example/services', { name: 'api2', support: ['unknown'] })).status, 400)
    assert.equal((await post('/api/repos/example/services', { name: 'api2', cwd: '/tmp' })).status, 400)
    assert.equal((await post('/api/repos/example/databases', { name: 'bad', support: ['sqlite', 'postgres'] })).status, 400)
    assert.equal((await post('/api/repos', { name: 'bad', parentPath: '.' })).status, 400)
    assert.equal((await post('/api/repos/not-registered/services', { name: 'api' })).status, 404)
    assert.equal((await get('/api/repos/%ZZ')).status, 400)
    const invalid = await fetch(`${url}/api/repos`, { method: 'POST', headers, body: '{' })
    assert.equal(invalid.status, 400)
    assert.equal((await post('/api/repos', { name: 'a'.repeat(17000) })).status, 413)
  })

  await t.test('rejects cross-site writes and hostile host headers', async () => {
    assert.equal((await fetch(`${url}/api/repos`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).status, 403)
    assert.equal((await fetch(`${url}/api/repos`, { method: 'POST', headers: { ...headers, Origin: 'https://example.com' }, body: '{}' })).status, 403)
    assert.equal((await fetch(`${url}/api/repos`, { method: 'POST', headers: { ...headers, 'Content-Type': 'text/plain' }, body: '{}' })).status, 415)
    const hostileHostStatus = await new Promise((resolve, reject) => {
      const req = request(`${url}/api/repos`, { headers: { Host: 'attacker.example' } }, response => {
        response.resume()
        resolve(response.statusCode)
      })
      req.on('error', reject)
      req.end()
    })
    assert.equal(hostileHostStatus, 403)
    assert.equal((await fetch(`${url}/api/repos`, { method: 'DELETE' })).status, 405)
  })

  await t.test('saves direct hosts and SSH connection strings as JSON without contacting hosts', async () => {
    writeFileSync(path.join(installed, 'ssh'), '#!/bin/sh\ntouch "$UTIL_PATH/unexpected-ssh"\nexit 1\n', { mode: 0o755 })
    const config = path.join(process.env.UTIL_PATH, 'remote/connections/example.json')
    let response = await post('/api/repos/example/target', { host: '192.0.2.20', user: 'deployer' })
    assert.equal(response.status, 200, JSON.stringify(await response.clone().json()))
    assert.deepEqual((await response.json()).target, { host: '192.0.2.20', user: 'deployer', port: 22, identityFile: null, legacy: false })
    assert.deepEqual(JSON.parse(readFileSync(config, 'utf8')), { host: '192.0.2.20', user: 'deployer', port: 22, identityFile: null })
    response = await post('/api/repos/example/target', { host: '192.0.2.21' })
    assert.equal(response.status, 200)
    assert.deepEqual((await response.json()).target, { host: '192.0.2.21', user: require('node:os').userInfo().username, port: 22, identityFile: null, legacy: false })
    response = await post('/api/repos/example/target', { connection: 'ssh://alice@[2001:db8::1]:2200', identityFile: '/tmp/key with spaces' })
    assert.equal(response.status, 200, JSON.stringify(await response.clone().json()))
    assert.deepEqual((await response.json()).target, { host: '2001:db8::1', user: 'alice', port: 2200, identityFile: '/tmp/key with spaces', legacy: false })
    const unchanged = readFileSync(config, 'utf8')
    for (const body of [{}, { host: 'host', connection: 'user@host' }, { host: '\n' }, { connection: 'user@host', port: 65536 }, { connection: 'user@host', port: '22' }, { connection: 'user@host', user: '-root' }, { connection: 'user@host', identityFile: 'relative' }, { connection: 'user@host', password: 'never-store' }]) {
      assert.equal((await post('/api/repos/example/target', body)).status, 400)
    }
    for (const connection of ['user:password@host', 'ssh://user@host/path', 'user@host:bad']) {
      assert.equal((await post('/api/repos/example/target', { connection })).status, 422)
    }
    assert.equal(readFileSync(config, 'utf8'), unchanged)
    assert.equal((await fetch(`${url}/api/repos/example/target`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"connection":"user@host"}' })).status, 403)
    response = await post('/api/repos/example/target', { connection: 'deployer@test-host' })
    assert.equal(response.status, 200)
    const inventory = await (await get('/api/repos/example/deployments')).json()
    assert.equal(inventory.remoteTarget, 'test-host')
    assert.deepEqual(inventory.remoteConnection, { host: 'test-host', user: 'deployer', port: 22, identityFile: null, legacy: false })
    assert.equal(existsSync(path.join(process.env.UTIL_PATH, 'unexpected-ssh')), false)
  })

  await t.test('deploys bundles and individual services through the real remote command', async () => {
    const releasePath = path.join(directory, 'prepared release;literal')
    for (const service of ['api', 'nginx', 'worker']) {
      mkdirSync(path.join(releasePath, service), { recursive: true })
      writeFileSync(path.join(releasePath, service, 'run'), '#!/bin/sh\nexit 0\n', { mode: 0o755 })
    }
    writeFileSync(path.join(process.env.UTIL_PATH, 'remote/targets/example'), 'test-host\n')
    const ssh = path.join(installed, 'ssh')
    const capture = path.join(process.env.UTIL_PATH, 'ssh-payload')
    const sshSuccess = '#!/bin/sh\nprintf "%s\\n" "$@" > "$UTIL_PATH/ssh-args"\ncat > "$UTIL_PATH/ssh-payload"\nprintf "deployed\\n"\n'
    writeFileSync(ssh, sshSuccess, { mode: 0o755 })
    // Global selection must not choose the deployment destination.
    await post('/api/repos/imported/select', {})
    const deployed = await post('/api/repos/example/deployments', { releasePath })
    assert.equal(deployed.status, 200, JSON.stringify(await deployed.clone().json()))
    assert.deepEqual(await deployed.json(), { releasePath, service: null, output: 'deployed' })
    assert.match(readFileSync(path.join(process.env.UTIL_PATH, 'ssh-args'), 'utf8'), /StrictHostKeyChecking=yes\n-o\nConnectTimeout=10\n-F\n\/dev\/null\n-l\ndeployer\n-p\n22\ntest-host\nsudo -n sh -s/)
    const payload = readFileSync(capture, 'utf8')
    assert.match(payload, /repo='example'/)
    const archive = path.join(directory, 'bundle.tar.gz')
    writeFileSync(archive, Buffer.from(payload.split("<<'TOOLKIT_RELEASE_ARCHIVE'\n")[1].split('\nTOOLKIT_RELEASE_ARCHIVE')[0], 'base64'))
    assert.deepEqual(execFileSync('tar', ['-tzf', archive], { encoding: 'utf8' }).trim().split('\n'), ['api.tar.gz', 'api.release', 'nginx.tar.gz', 'nginx.release', 'worker.tar.gz', 'worker.release'])
    const single = await post('/api/repos/example/deployments', { releasePath: path.join(releasePath, 'api'), service: 'api' })
    assert.equal(single.status, 200)
    assert.equal((await single.json()).service, 'api')
    assert.match(readFileSync(capture, 'utf8'), /set -- 'api:[0-9]+'\n/)
    assert.deepEqual((await (await get('/api/repos/example/deployments')).json()).services, ['api', 'nginx', 'worker'])

    rmSync(capture)
    for (const body of [{}, { releasePath: '.' }, { releasePath: '/tmp\n' }, { releasePath, service: '../api' }, { releasePath, service: null }, { releasePath, target: 'other-host' }]) {
      assert.equal((await post('/api/repos/example/deployments', body)).status, 400)
    }
    assert.equal((await post('/api/repos/not-registered/deployments', { releasePath })).status, 404)
    assert.equal((await fetch(`${url}/api/repos/example/deployments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ releasePath }) })).status, 403)
    assert.equal((await fetch(`${url}/api/repos/example/deployments`, { method: 'POST', headers: { ...headers, Origin: 'https://example.com' }, body: JSON.stringify({ releasePath }) })).status, 403)
    assert.equal((await post('/api/repos/imported/deployments', { releasePath })).status, 422)
    assert.equal((await post('/api/repos/example/deployments', { releasePath, service: 'unknown' })).status, 422)
    assert.equal((await post('/api/repos/example/deployments', { releasePath: path.join(directory, 'missing') })).status, 422)
    const linked = path.join(directory, 'linked-release')
    symlinkSync(releasePath, linked)
    assert.equal((await post('/api/repos/example/deployments', { releasePath: linked })).status, 422)
    chmodSync(path.join(releasePath, 'worker/run'), 0o644)
    const malformed = await post('/api/repos/example/deployments', { releasePath })
    assert.equal(malformed.status, 422)
    assert.match((await malformed.json()).error, /executable run/)
    assert.equal(existsSync(capture), false, 'invalid requests must not reach SSH')
    chmodSync(path.join(releasePath, 'worker/run'), 0o755)

    writeFileSync(ssh, '#!/bin/sh\ncat > /dev/null\necho "SSH connection failed" >&2\nexit 255\n')
    const failed = await post('/api/repos/example/deployments', { releasePath })
    assert.equal(failed.status, 422)
    assert.match((await failed.json()).error, /SSH connection failed.*partially completed/)

    // Hold SSH after remote has acquired the bootstrap lock. A second POST must
    // reject immediately instead of waiting on repo ls and deploying again later.
    const entered = path.join(process.env.UTIL_PATH, 'ssh-entered')
    const release = path.join(process.env.UTIL_PATH, 'ssh-release')
    writeFileSync(ssh, '#!/bin/sh\ncat > /dev/null\ntouch "$UTIL_PATH/ssh-entered"\nwhile [ ! -f "$UTIL_PATH/ssh-release" ]; do sleep 0.05; done\necho deployed\n')
    const pending = post('/api/repos/example/deployments', { releasePath })
    try {
      for (let attempt = 0; attempt < 100 && !existsSync(entered); attempt++) await new Promise(resolve => setTimeout(resolve, 50))
      assert.ok(existsSync(entered), 'deployment reached SSH')
      const duplicate = await fetch(`${url}/api/repos/example/deployments`, { method: 'POST', headers, body: JSON.stringify({ releasePath }), signal: AbortSignal.timeout(2000) })
      assert.equal(duplicate.status, 409)
      const retarget = await fetch(`${url}/api/repos/example/target`, { method: 'POST', headers, body: JSON.stringify({ connection: 'user@other-host' }), signal: AbortSignal.timeout(2000) })
      assert.equal(retarget.status, 409)
    } finally {
      writeFileSync(release, '')
      assert.equal((await pending).status, 200)
    }
    writeFileSync(ssh, sshSuccess)
    assert.equal((await post('/api/repos/example/deployments', { releasePath })).status, 200, 'deployment slot is released after completion')
  })

  await t.test('deployment inventory is local and ignores external symlink data', async () => {
    mkdirSync(path.join(repoPath, '.release/20261012T010000Z'), { recursive: true })
    mkdirSync(path.join(repoPath, 'deployment'))
    writeFileSync(path.join(repoPath, 'deployment/Makefile'), 'status:\n\ttouch should-never-run\n')
    writeFileSync(path.join(process.env.UTIL_PATH, 'remote/targets/example'), 'test-host\n')
    // Exercise the real remote dispatcher/validation with a non-network SSH fixture.
    const ssh = path.join(installed, 'ssh')
    writeFileSync(ssh, '#!/bin/sh\nprintf "api\\truntime\\tstate\\tup\\napi\\truntime\\tpid\\t123\\napi\\truntime\\tidentity\\tverified\\napi\\trunning\\tcommit\\t' + 'a'.repeat(40) + '\\napi\\trunning\\tarchive_sha256\\t' + 'b'.repeat(64) + '\\napi\\tselected\\trelease\\tserver-new\\n"\n')
    chmodSync(ssh, 0o755)
    const live = await (await get('/api/repos/example/releases')).json()
    assert.equal(live.error, null)
    assert.equal(live.services[0].runtime.identity, 'verified')
    assert.equal(live.services[0].running.commit, 'a'.repeat(40))
    assert.equal(live.services[0].running.archive_sha256, 'b'.repeat(64))
    writeFileSync(ssh, '#!/bin/sh\necho "Host key verification failed." >&2\nexit 255\n')
    const failedLive = await (await get('/api/repos/example/releases')).json()
    assert.deepEqual(failedLive.services, [])
    assert.match(failedLive.error, /Host key verification failed/)
    writeFileSync(ssh, '#!/bin/sh\nprintf "unexpected output\\n"\n')
    assert.match((await (await get('/api/repos/example/releases')).json()).error, /Unexpected release status/)
    const external = path.join(directory, 'external')
    mkdirSync(external)
    symlinkSync(external, path.join(repoPath, '.release/external'))
    symlinkSync(external, path.join(repoPath, 'services/external'))
    const deployment = await (await get('/api/repos/example/deployments')).json()
    assert.deepEqual(deployment.files, ['deployment/Makefile'])
    assert.equal(deployment.remoteTarget, 'test-host')
    assert.deepEqual(deployment.releases.map(release => release.name), ['20261012T010000Z'])
    assert.equal(existsSync(path.join(repoPath, 'deployment/should-never-run')), false)
    assert.equal((await (await get('/api/repos/example')).json()).services.some(service => service.name === 'external'), false)
    const empty = await (await get('/api/repos/imported/deployments')).json()
    assert.deepEqual(empty.releases, [])
    assert.deepEqual(empty.files, [])
    assert.equal(empty.remoteTarget, null)
    symlinkSync(external, path.join(directory, 'imported/ui'))
    assert.equal((await post('/api/repos/imported/uis', { name: 'escape' })).status, 422)
    assert.equal(existsSync(path.join(external, 'escape')), false)
    rmSync(path.join(process.env.UTIL_PATH, 'remote/lock'))
    assert.match((await (await get('/api/repos/example/deployments')).json()).remoteError, /setup remote/)
  })
})
