const { spawn } = require('node:child_process')
const { readFileSync } = require('node:fs')
const fs = require('node:fs/promises')
const { createServer } = require('node:http')
const path = require('node:path')

const root = path.resolve(__dirname, '../..')
const env = (name) => process.env[name] || readFileSync(path.join(__dirname, 'env-dir/default', name), 'utf8').trim()
const repoName = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const itemName = /^[a-z0-9][a-z0-9._-]*$/

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status }
}

// No shell interpolation. Kill the whole command group on timeout/output overflow.
function command(tool, args, cwd = root, { timeout = 120000, readOnly = false } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(tool, args, { cwd, detached: true, stdio: ['ignore', 'pipe', 'pipe'] })
    let stdout = '', stderr = '', failure
    const stop = (message) => {
      failure = new ApiError(504, readOnly ? message : `${message} Inspect state before retrying; the command may have completed some steps.`)
      try { process.kill(-child.pid, 'SIGKILL') } catch {}
    }
    const timer = setTimeout(() => stop('Toolkit command timed out.'), timeout)
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', chunk => { stdout += chunk; if (stdout.length > 1024 * 1024) stop('Toolkit output limit exceeded.') })
    child.stderr.on('data', chunk => { stderr += chunk; if (stderr.length > 1024 * 1024) stop('Toolkit output limit exceeded.') })
    child.on('error', error => {
      clearTimeout(timer)
      reject(new ApiError(503, `Cannot run ${tool}: ${error.message}`))
    })
    child.on('close', code => {
      clearTimeout(timer)
      if (failure) return reject(failure)
      if (code === 0) return resolve(stdout.trimEnd())
      const message = stderr.trim() || stdout.trim() || `${tool} exited with status ${code}`
      const status = /already|path appeared|conflict|occupied/i.test(message) ? 409 : 422
      reject(new ApiError(status, message.slice(-6000)))
    })
  })
}

async function repositories() {
  const output = await command('bootstrap', ['repo', 'ls'])
  return output.split('\n').filter(Boolean).map(line => {
    const [marker, name, repoPath] = line.split('\t')
    return { name, path: repoPath, current: marker === '*' }
  })
}

function validName(value, pattern = repoName) {
  if (typeof value !== 'string' || value.length > 128 || !pattern.test(value) || value === 'ports') {
    throw new ApiError(400, 'Use a valid name with letters, digits, dots, underscores or hyphens; start with a letter or digit. “ports” is reserved.')
  }
  return value
}

function absolutePath(value) {
  if (typeof value !== 'string' || !path.isAbsolute(value) || /[\x00-\x1f\x7f]/.test(value)) {
    throw new ApiError(400, 'Provide an absolute filesystem path without control characters.')
  }
  return value
}

function fields(body, allowed) {
  if (Object.keys(body).some(key => !allowed.includes(key))) throw new ApiError(400, 'Unexpected request field.')
}

function supportOptions(value = [], allowed) {
  if (!Array.isArray(value) || value.some(option => !allowed.includes(option)) || new Set(value).size !== value.length) {
    throw new ApiError(400, `Supported options: ${allowed.join(', ') || 'none'}.`)
  }
  return value.map(option => `--support=${option}`)
}

const serviceTypes = async () => {
  const output = await command('bootstrap', ['service', 'type', 'ls'], root, { readOnly: true })
  return Object.fromEntries(output.split('\n').slice(1).filter(Boolean).map(line => {
    const [type, label, options, required, hint] = line.split('\t')
    return [type, { label, options: options === '-' ? [] : options.split(','), required: required === '-' ? [] : required.split(','), hint }]
  }))
}

async function jsonBody(request) {
  if (request.headers['x-toolkit-request'] !== '1') throw new ApiError(403, 'The X-Toolkit-Request: 1 header is required.')
  if (request.headers['content-type']?.split(';')[0].trim() !== 'application/json') throw new ApiError(415, 'Send application/json.')
  const chunks = []
  let size = 0
  for await (const chunk of request) {
    size += chunk.length
    if (size > 16384) throw new ApiError(413, 'Request body exceeds 16 KiB.')
    chunks.push(chunk)
  }
  try {
    const body = JSON.parse(Buffer.concat(chunks).toString())
    if (!body || Array.isArray(body) || typeof body !== 'object') throw new Error()
    return body
  } catch { throw new ApiError(400, 'Send a JSON object.') }
}

// Inventory reads only regular directories/files beneath the registered repo.
async function entries(directory) {
  try {
    if (!(await fs.lstat(directory)).isDirectory()) return []
    return (await fs.readdir(directory, { withFileTypes: true })).filter(entry => entry.isDirectory() && !entry.name.startsWith('.')).sort((a, b) => a.name.localeCompare(b.name))
  } catch (error) {
    if (error.code === 'ENOENT') return []
    throw error
  }
}

async function regularFile(directory, relative) {
  try {
    const file = path.join(directory, relative)
    const real = await fs.realpath(file)
    if (!real.startsWith(`${directory}${path.sep}`) || !(await fs.stat(real)).isFile()) return null
    return real
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return null
    throw error
  }
}

async function databaseEngine(repo, name) {
  const state = process.env.STATE_PATH || path.join(process.env.HOME || require('node:os').homedir(), '.s6craft-tools')
  if (!state || !repoName.test(repo.name) || !/^[a-z][a-z0-9_]{0,62}$/.test(name)) return null
  let registry
  try {
    registry = await fs.realpath(path.resolve(state, 'bootstrap/repos', repo.name, 'databases'))
  } catch (error) {
    if (error.code === 'ENOENT') return null
    throw error
  }
  const file = await regularFile(registry, `${name}/engine`)
  if (!file) return null
  const value = (await fs.readFile(file, 'utf8')).trim()
  return value === 'postgres' || value === 'sqlite' ? value : null
}

async function inventory(repo, folder) {
  const items = await entries(path.join(repo.path, folder))
  return Promise.all(items.map(async item => {
    const relative = `${folder}/${item.name}`
    let port = null
    const user = process.env.ENV_USER || process.env.USER || 'default'
    if (folder !== 'db') {
      for (const environment of ['env-dir', 'env-dev']) {
        const selected = repoName.test(user) && user !== '.' && user !== '..' ? user : 'default'
        const file = await regularFile(repo.path, `${relative}/${environment}/${selected}/PORT`) || await regularFile(repo.path, `${relative}/${environment}/default/PORT`)
        if (file) {
          const value = (await fs.readFile(file, 'utf8')).trim()
          port = /^\d{1,5}$/.test(value) && Number(value) > 0 && Number(value) <= 65535 ? Number(value) : null
          break
        }
      }
    }
    return {
      name: item.name,
      path: path.join(repo.path, relative),
      port,
      ...(folder === 'db' ? { engine: await databaseEngine(repo, item.name) } : {}),
    }
  }))
}

async function registeredRemotes() {
  const output = await command('remote', ['host', 'ls'], root, { readOnly: true })
  return output.split('\n').filter(Boolean).map(line => {
    const [name, host, user, port, identityFile] = line.split('\t')
    return { name, host, user, port: Number(port), identityFile: identityFile || null }
  })
}

async function remoteConnection(repo) {
  const targets = await command('remote', ['ls'], root, { readOnly: true })
  const record = targets.split('\n').map(line => line.split('\t')).find(([name]) => name === repo.name)
  if (!record) return null
  const [, host, user, port, identityFile] = record
  return { host, user: user || null, port: port ? Number(port) : null, identityFile: identityFile || null, legacy: !user }
}

async function deployments(repo) {
  const releases = await entries(path.join(repo.path, '.release'))
  const files = []
  for (const filename of ['deployment/Makefile', 'deployment/root.mk', 'deployment/build', 'deployment/package', 'deployment/status']) {
    if (await regularFile(repo.path, filename)) files.push(filename)
  }
  let target = null, remoteError = null
  try {
    target = await remoteConnection(repo)
  } catch (error) { remoteError = error.message }
  return {
    files, remoteTarget: target?.host || null, remoteConnection: target, remoteError,
    services: (await inventory(repo, 'services')).map(service => service.name),
    releases: (await Promise.all(releases.map(async release => {
      const releasePath = path.join(repo.path, '.release', release.name)
      return { name: release.name, path: releasePath, modifiedAt: (await fs.stat(releasePath)).mtime.toISOString() }
    }))).sort((a, b) => b.modifiedAt.localeCompare(a.modifiedAt) || b.name.localeCompare(a.name)),
  }
}

async function runningReleases(repo) {
  const checkedAt = new Date().toISOString()
  try {
    const output = await command('remote', ['releases', repo.name], root, { timeout: 30000, readOnly: true })
    const services = new Map()
    const keys = ['state', 'pid', 'identity', 'release', 'commit', 'commit_source', 'dirty', 'archive_sha256', 'deployed_at', 'process_start']
    for (const line of output.split('\n').filter(Boolean)) {
      const [name, scope, key, value, extra] = line.split('\t')
      if (!itemName.test(name) || !['runtime', 'selected', 'running'].includes(scope) || !keys.includes(key) || value === undefined || extra !== undefined) {
        throw new Error('Unexpected release status output. Update the installed remote toolkit.')
      }
      if (!services.has(name)) services.set(name, { name, runtime: {}, selected: {}, running: {} })
      services.get(name)[scope][key] = value
    }
    if (!services.size) throw new Error('The host returned no service release information.')
    return { checkedAt, services: [...services.values()], error: null }
  } catch (error) {
    return { checkedAt, services: [], error: error.message }
  }
}

function createApi() {
  const deploying = new Set()
  return createServer(async (request, response) => {
    let deploymentName
    const send = (status, value) => {
      response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' })
      response.end(JSON.stringify(value))
    }
    try {
      // Require a loopback Host and same-origin browser requests, including through nginx.
      const host = request.headers.host || ''
      if (!/^(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$/.test(host)) throw new ApiError(403, 'Only localhost requests are accepted.')
      if ((request.headers.origin && request.headers.origin !== `http://${host}`) || request.headers['sec-fetch-site'] === 'cross-site') {
        throw new ApiError(403, 'Cross-origin requests are not accepted.')
      }
      const pathname = new URL(request.url, `http://${host}`).pathname
      let parts
      try { parts = pathname.split('/').filter(Boolean).map(decodeURIComponent) } catch { throw new ApiError(400, 'Invalid URL encoding.') }
      if (parts[0] !== 'api') throw new ApiError(404, 'Not found')
      const removal = request.method === 'DELETE' && parts[1] === 'repos' && parts[3] === 'services' && parts.length === 5
      if (!['GET', 'POST'].includes(request.method) && !removal) {
        response.setHeader('Allow', 'GET, POST')
        throw new ApiError(405, 'Method not allowed')
      }
      const get = request.method === 'GET'
      if (pathname === '/api/health' && get) return send(200, { status: 'ok' })
      if (pathname === '/api/remotes' && get) return send(200, { remotes: await registeredRemotes() })
      if (pathname === '/api/config' && get) return send(200, { parentPath: path.dirname(root), serviceTypes: await serviceTypes() })
      if (pathname === '/api/repos' && get) return send(200, { repos: await repositories() })
      if (pathname === '/api/repos' && !get) {
        const body = await jsonBody(request)
        fields(body, ['name', 'parentPath', 'support'])
        const name = validName(body.name)
        const parent = absolutePath(body.parentPath)
        const options = supportOptions(body.support, ['nginx'])
        const output = await command('bootstrap', ['repo', 'create', name, ...options], parent)
        return send(201, { path: output })
      }
      if (pathname === '/api/repos/import' && !get) {
        const body = await jsonBody(request)
        fields(body, ['path'])
        return send(201, { path: await command('bootstrap', ['repo', 'import', absolutePath(body.path)]) })
      }
      if (parts[1] !== 'repos' || parts.length < 3 || (parts.length > 4 && !removal)) throw new ApiError(404, 'Not found')
      if (removal && request.headers['x-toolkit-request'] !== '1') throw new ApiError(403, 'The X-Toolkit-Request: 1 header is required.')
      const name = validName(parts[2])
      const action = parts[3]
      if (action === 'target' && !get && deploying.has(name)) throw new ApiError(409, 'Wait for the deployment to finish before changing its target.')
      // Claim before registry lookup: remote deploy holds the bootstrap lock too.
      if (action === 'deployments' && !get) {
        if (deploying.has(name)) throw new ApiError(409, 'A deployment is already in progress for this repository.')
        deploying.add(name)
        deploymentName = name
      }
      const repo = (await repositories()).find(repo => repo.name === name)
      if (!repo) throw new ApiError(404, 'Repository is not registered.')
      try { repo.path = await fs.realpath(repo.path) } catch { throw new ApiError(404, 'Registered repository directory is missing.') }
      if (removal) {
        const service = validName(parts[4], itemName)
        try {
          if (!(await fs.lstat(path.join(repo.path, 'services'))).isDirectory()) throw new ApiError(422, 'services/ must be a real directory, not a symlink.')
          if (!(await fs.lstat(path.join(repo.path, 'services', service))).isDirectory()) throw new ApiError(404, 'Service not found.')
        } catch (error) {
          if (error.code === 'ENOENT') throw new ApiError(404, 'Service not found.')
          throw error
        }
        return send(200, { path: await command('bootstrap', ['service', 'rm', service], repo.path) })
      }
      if (parts.length === 3 && get) {
        const [services, uis, databases] = await Promise.all([inventory(repo, 'services'), inventory(repo, 'ui'), inventory(repo, 'db')])
        return send(200, { repo, services, uis, databases })
      }
      if (action === 'deployments' && get) return send(200, await deployments(repo))
      if (action === 'releases' && get) return send(200, await runningReleases(repo))
      if (action === 'target' && !get) {
        const body = await jsonBody(request)
        fields(body, ['remoteName'])
        const remoteName = body.remoteName
        if (typeof remoteName !== 'string' || !repoName.test(remoteName)) throw new ApiError(400, 'Choose a registered remote.')
        await command('remote', ['use', name, remoteName], repo.path)
        return send(200, { target: await remoteConnection(repo) })
      }
      if (action === 'deployments' && !get) {
        const body = await jsonBody(request)
        fields(body, ['releasePath', 'service'])
        const target = await remoteConnection(repo)
        const remotes = await registeredRemotes()
        const registered = target && remotes.some(remote => remote.host === target.host && remote.user === target.user && remote.port === target.port && remote.identityFile === target.identityFile)
        if (!registered) throw new ApiError(422, 'Choose and save a registered remote before deploying. The saved target is missing or no longer matches the registry.')
        const releasePath = absolutePath(body.releasePath)
        const service = body.service === undefined ? null : validName(body.service, itemName)
        try {
          const args = ['deploy', name]
          if (service) args.push(service)
          args.push(releasePath)
          const output = await command('remote', args, repo.path)
          return send(200, { releasePath, service, output })
        } catch (error) {
          throw new ApiError(error.status || 500, `${error.message} Deployment may have partially completed. Check host release status before retrying; stopping the local command does not guarantee the remote operation stopped.`)
        }
      }
      if (!get && ['select', 'services', 'uis', 'databases'].includes(action)) {
        const body = await jsonBody(request)
        if (action === 'select') {
          fields(body, [])
          return send(200, { path: await command('bootstrap', ['repo', 'load', repo.path]) })
        }
        fields(body, action === 'services' ? ['name', 'type', 'support'] : ['name', 'support'])
        const folder = { services: 'services', uis: 'ui', databases: 'db' }[action]
        try {
          if (!(await fs.lstat(path.join(repo.path, folder))).isDirectory()) throw new ApiError(422, `${folder}/ must be a real directory, not a symlink.`)
        } catch (error) {
          if (error.code !== 'ENOENT') throw error
        }
        let args
        if (action === 'services') {
          const type = body.type === undefined ? 'nodejs' : body.type
          const types = await serviceTypes()
          if (typeof type !== 'string' || !Object.hasOwn(types, type)) throw new ApiError(400, `Choose a service type: ${Object.keys(types).join(' or ')}.`)
          const config = types[type]
          const options = supportOptions(body.support, config.options)
          for (const required of config.required) {
            if (!options.includes(`--support=${required}`)) options.push(`--support=${required}`)
          }
          args = ['service', 'add', validName(body.name, itemName), `--type=${type}`, ...options]
        }
        if (action === 'uis') args = ['ui', 'add', validName(body.name, itemName), ...supportOptions(body.support, ['component-library'])]
        if (action === 'databases') {
          validName(body.name, /^[a-z][a-z0-9_]{0,62}$/)
          const options = supportOptions(body.support, ['postgres', 'sqlite'])
          if (options.length !== 1) throw new ApiError(400, 'Choose exactly one database backend: postgres or sqlite.')
          args = ['db', 'add', body.name, ...options]
        }
        return send(201, { path: await command('bootstrap', args, repo.path) })
      }
      throw new ApiError(404, 'Not found')
    } catch (error) {
      if (!error.status) console.error(error)
      send(error.status || 500, { error: error.status ? error.message : 'Unable to read repository files. Check the API log.' })
    } finally { if (deploymentName) deploying.delete(deploymentName) }
  })
}

if (require.main === module) {
  const host = env('HOST')
  if (!['localhost', '127.0.0.1', '::1'].includes(host)) throw new Error('Toolkit API must bind to a loopback address.')
  const server = createApi()
  server.listen(Number(env('PORT')), host, () => {
    console.log(`Toolkit API: http://${host}:${server.address().port}/api/health`)
  })
}

module.exports = { createApi }
