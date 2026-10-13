# Local dashboard and REST API

The dashboard lives in `ui/dashboard` and the Node.js API in `services/api`.
Both were created with bootstrap. The toolkit port domain is 6700–6799:
API 6700, UI 6701.

```sh
make install
make start
```

Open <http://localhost:6701/dashboard/>. Requires `envdir`, Node.js matching
`ui/dashboard/package.json`, and installed, initialized `bootstrap` and `port`
commands on PATH. Keep the installed toolkit up to date with this checkout.
`UTIL_PATH` selects toolkit state (normally `$HOME/.cerberus`). `remote` is optional
for displaying the registered remote target.

`make start` uses `env-dir/$ENV_USER`, falling back to `env-dir/$USER`, and logs
in each directory's `start.log`. For foreground development, run
`envdir "./env-dir/${ENV_USER:-$USER}" npm start` in each application directory
in separate terminals; Ctrl-C stops them. Plain `npm start` uses the default
HOST/PORT files unless overridden by environment variables. Vite proxies `/api`
to the API environment's HOST/PORT; `API_URL` overrides its target.

## Dashboard workflows

- Create a new repo in an existing absolute parent directory, optionally with
  nginx support. Bootstrap links shared `~/.s6craft` rules and reserves ports.
  This has the same semantics as `bootstrap repo create`; it does not run `git init`.
- Import an existing repo containing a real `services/` directory. Bootstrap
  discovers its ports and preserves existing files. Import can be repeated.
- Select a repo to inspect its services, UIs, databases and ports. Browsing does
  not change bootstrap's global selection; **Set current** does.
- Add a Node.js service with HTTP, filesystem and/or same-name database support;
  add a React/Vite UI, optionally using an existing component library; or add
  a PostgreSQL/SQLite Sqitch scaffold. Scaffolding does not install dependencies,
  start apps, create service application code, or run database migrations.
- View local `.release/` directories and known deployment configuration files.
  Release timestamps are directory modification times, not deployment times.
  The SSH target comes from local `remote ls` state. **Check host via SSH** reads
  the selected release and verifies the running release against s6 process state.
  It displays commit/archive hashes when recorded, and explicit unknown/error
  states otherwise. No deployment scripts, restarts or application health checks
  run. Local packages alone are not evidence of an active deployment.

The service uses fixed CLI executables and argument arrays without a shell.
Bootstrap owns validation, state updates, port allocation and locks. Repo-scoped
operations resolve the registered path and run there, independent of the global
selection. Existing scaffolds are never overwritten. Failures can leave partial
work under bootstrap's existing recovery rules; inspect the repo before retrying.
The API never automatically retries mutations.

## REST endpoints

All payloads and responses are JSON. Names in URL paths identify registered repos.

| Method | Path | Body / result |
| --- | --- | --- |
| GET | `/api/health` | API health |
| GET | `/api/config` | Default new-repo parent directory |
| GET | `/api/repos` | `{ repos: [{ name, path, current }] }` |
| POST | `/api/repos` | `{ name, parentPath, support: [] }`; support: `nginx` |
| POST | `/api/repos/import` | `{ path }`, absolute existing repo path |
| GET | `/api/repos/:name` | Repo plus `services`, `uis`, `databases` inventories |
| POST | `/api/repos/:name/select` | `{}`; set bootstrap's current repo |
| POST | `/api/repos/:name/services` | `{ name, support: [] }`; `http`, `fs`, `db` |
| POST | `/api/repos/:name/uis` | `{ name, support: [] }`; `component-library` |
| POST | `/api/repos/:name/databases` | `{ name, support: ["sqlite"] }` or `["postgres"]` |
| GET | `/api/repos/:name/deployments` | Local `files`, `releases`, `remoteTarget`, `remoteError` |
| GET | `/api/repos/:name/releases` | SSH check: `{ checkedAt, services, error }`; service `runtime`, `selected`, `running` fields |

`support` defaults to an empty list except databases, which require one backend.
Creates/imports return HTTP 201 with `{ path }`; selection returns HTTP 200.
Errors return `{ error }`: 400 for invalid input, 403 for origin/header rejection,
404 for missing routes/repos, 409 for conflicts, 413 for oversized bodies,
415 for non-JSON mutations, 422 for CLI validation failures, 503 for unavailable
executables, and 504 for command timeout/output limits. Commands are limited to
120 seconds and 1 MiB per output stream; timeout terminates the command process
group. Bodies are limited to 16 KiB. Partial CLI work is retained for inspection.

Mutations require `Content-Type: application/json` and `X-Toolkit-Request: 1`.
The browser supplies both. For example, to add a UI to a registered repo:

```sh
curl --fail-with-body http://localhost:6700/api/repos/my-repo/uis \
  -H 'Content-Type: application/json' \
  -H 'X-Toolkit-Request: 1' \
  -d '{"name":"dashboard"}'
```

The API binds only to loopback and requires a loopback Host header. Browser
requests must be same-origin, including through the Vite proxy. There is no CORS
or network authentication: this is a local tool, with the filesystem privileges
of the API process. Network hosting requires an authentication design first.

`make test` exercises real shell scaffolding against temporary HOME, toolkit
state and repositories, including concurrent additions, failure recovery,
request validation and local deployment inspection. `make build` writes UI
assets to `ui/dashboard/dist`; production hosting would need to serve them at
`/dashboard/` and route `/api` to the Node service.

Live release checks time out after 30 seconds. SSH errors return `error` and an
empty services list, never stale success data. See [release identity and host
upgrades](remote.md#release-artifacts-and-identities) for metadata semantics.
