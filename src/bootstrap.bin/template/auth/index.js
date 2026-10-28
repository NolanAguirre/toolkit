const http = require('node:http')
const { Pool } = require('pg')

const host = process.env.HOST || '127.0.0.1'
const port = Number(process.env.PORT)
// Credentials come from ~/.pgpass or PGPASSWORD, never from DATABASE_URL.
const pool = new Pool({ connectionString: process.env.DATABASE_URL })

const sendJson = (res, status, body) => {
  const payload = JSON.stringify(body)
  res.writeHead(status, { 'Content-Type': 'application/json' })
  res.end(payload)
}

const httpError = (status, message) => Object.assign(new Error(message), { status })

const readJson = (req) => new Promise((resolve, reject) => {
  let body = ''
  req.setEncoding('utf8')
  req.on('data', (chunk) => {
    body += chunk
    if (body.length > 16384) {
      reject(httpError(413, 'request body too large'))
      req.destroy()
    }
  })
  req.on('end', () => {
    try {
      resolve(JSON.parse(body))
    } catch {
      reject(httpError(400, 'request body must be JSON'))
    }
  })
  req.on('error', reject)
})

const readCredentials = async (req) => {
  const body = await readJson(req)
  if (!body || typeof body.email !== 'string' || typeof body.password !== 'string') {
    throw httpError(400, 'email and password are required')
  }
  return body
}

const routes = {
  'GET /auth/health': (_req, res) => {
    sendJson(res, 200, { ok: true, service: 'auth' })
  },
  'POST /auth/register': async (req, res) => {
    const { email, password } = await readCredentials(req)
    try {
      const { rows } = await pool.query('select id, email from auth.register($1, $2)', [email, password])
      sendJson(res, 201, { id: rows[0].id, email: rows[0].email })
    } catch (err) {
      if (err.code === '23505') {
        throw httpError(409, 'email is already registered')
      }
      if (err.code === '22023' || err.code === '23514') {
        throw httpError(400, err.code === '23514' ? 'email is invalid' : err.message)
      }
      throw err
    }
  },
  'POST /auth/login': async (req, res) => {
    const { email, password } = await readCredentials(req)
    const { rows } = await pool.query('select id, email from auth.authenticate($1, $2)', [email, password])
    if (!rows[0] || !rows[0].id) {
      throw httpError(401, 'invalid email or password')
    }
    sendJson(res, 200, { id: rows[0].id, email: rows[0].email })
  },
}

const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname
  const handler = routes[`${req.method} ${pathname}`]
  if (!handler) {
    sendJson(res, 404, { error: 'not found' })
    return
  }
  Promise.resolve(handler(req, res)).catch((err) => {
    if (err.status) {
      sendJson(res, err.status, { error: err.message })
      return
    }
    console.error(err)
    sendJson(res, 500, { error: 'internal error' })
  })
})

const shutdown = () => {
  server.close(() => {
    pool.end().then(() => process.exit(0))
  })
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)

server.listen(port, host, () => {
  console.log(`auth listening on http://${host}:${port}`)
})
