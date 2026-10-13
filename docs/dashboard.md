# Local dashboard and REST API

The dashboard lives in `ui/dashboard` and the Node.js API in `services/api`.
Both were created with bootstrap. The toolkit port domain is 6700–6799:
API 6700, UI 6701, nginx 6760. nginx is the browser entry point.

```sh
make install
make start
```

Open <http://localhost:6760/dashboard/>. In development the page includes the
dev inspector (hold Alt, or latch Dev in the corner panel). Its harness form and
session list call `/dashboard/harness-api`, which nginx proxies to the harness
API at `http://127.0.0.1:6000/api`.
The inspector is omitted from production builds. Development reads it from
the sibling `visual-prompter/component-library`.

Requires `nginx`, `envdir`, Node.js matching
`ui/dashboard/package.json`, and installed, initialized `bootstrap` and `port`
commands on PATH. Keep the installed toolkit up to date with this checkout.
`UTIL_PATH` selects toolkit state (normally `$HOME/.cerberus`). Install and initialize
`remote` for deployment and host inspection. Target configuration also requires `jq`.

`make start` starts the API and UI in the background using `env-dir/$ENV_USER`,
falling back to `env-dir/$USER`, with logs in each application's `start.log`.
It then runs nginx in the foreground; Ctrl-C stops nginx. nginx writes access
logs in `services/nginx/.runtime/access.log` and errors to stderr.
For foreground application development, run
`envdir "./env-dir/${ENV_USER:-$USER}" npm start` in each application directory
in separate terminals; Ctrl-C stops them. Plain `npm start` uses the default
HOST/PORT files unless overridden by environment variables. Run
`make services.nginx.start` separately if the API and UI are already running.
nginx forwards `/dashboard/` (including hot-reload WebSockets) to Vite and `/api`
to the API. Vite has no proxy configuration. Upstream addresses are explicit in
`services/nginx/routes/dashboard.conf`; update that file if application ports or
the harness target change. `API_URL` and `HARNESS_PROXY_TARGET` are no longer used.

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
  states otherwise. This check does not deploy or restart services.
  Local packages alone are not evidence of an active deployment.
- Save a deployment target in the Deployments tab using an IP address, DNS
  hostname, `user@host` or `ssh://user@host:port`. Supply an SSH user for bare hosts;
  optionally override the port or provide an absolute SSH key path on the API
  machine. Settings are stored in `$UTIL_PATH/remote/connections/<repo>.json`;
  no SSH config entry or homelab configuration is required. Saving only changes
  local JSON, never contacts the host or creates DNS records. Existing aliases
  remain usable until replaced. Unsaved target changes disable host checks and
  deployment so they cannot accidentally use the previously saved destination.
- Deploy a prepared release directory from the Deployments tab. Choose all
  services (a bundle containing `<service>/run` for every service), or one
  service (its directory containing `run` directly). Local `.release/` paths
  are suggested; any absolute artifact directory accessible to the API is accepted.
  The API invokes `remote deploy` against the repo's registered target, then the
  UI checks host status even after a failure. Prepare the host with
  `remote setup all <repo>` first. This uploads artifacts, selects releases and requests s6
  restarts; services marked down stay down. It does not build, run migrations,
  or check application health. UI assets must be packaged in their serving service.
  See [artifact layout and host setup](remote.md#release-artifacts-and-identities).

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
| GET | `/api/repos/:name/deployments` | Local `files`, `releases`, service names in `services`, `remoteTarget`, `remoteConnection`, `remoteError` |
| POST | `/api/repos/:name/target` | `{ host, user, port?, identityFile? }` or `{ connection, user?, port?, identityFile? }`; returns `{ target }` |
| POST | `/api/repos/:name/deployments` | `{ releasePath, service? }`; absolute artifact directory; returns `{ releasePath, service, output }` |
| GET | `/api/repos/:name/releases` | SSH check: `{ checkedAt, services, error }`; service `runtime`, `selected`, `running` fields |

`support` defaults to an empty list except databases, which require one backend.
Creates/imports return HTTP 201 with `{ path }`; selection returns HTTP 200.
Errors return `{ error }`: 400 for invalid input, 403 for origin/header rejection,
404 for missing routes/repos, 409 for conflicts, 413 for oversized bodies,
415 for non-JSON mutations, 422 for CLI validation failures, 503 for unavailable
executables, and 504 for command timeout/output limits. Commands are limited to
120 seconds and 1 MiB per output stream; timeout terminates the command process
group. Bodies are limited to 16 KiB. Partial CLI work is retained for inspection.
Deployments return HTTP 200 after the command completes, not after application
health verification. Omit `service` to deploy all services. Concurrent deployments
of the same repo through this API instance return 409; the remote CLI also holds
its local and host locks. A failed deployment may have activated some services;
check `/api/repos/:name/releases` before retrying. Terminating the local SSH client
on timeout does not guarantee the host operation stopped.

Mutations require `Content-Type: application/json` and `X-Toolkit-Request: 1`.
The browser supplies both. For example, to add a UI to a registered repo:

```sh
curl --fail-with-body http://localhost:6760/api/repos/my-repo/uis \
  -H 'Content-Type: application/json' \
  -H 'X-Toolkit-Request: 1' \
  -d '{"name":"dashboard"}'
```

To save a target (creates or replaces its complete configuration):

```sh
curl --fail-with-body http://localhost:6760/api/repos/my-repo/target \
  -H 'Content-Type: application/json' \
  -H 'X-Toolkit-Request: 1' \
  -d '{"connection":"ssh://deployer@example.com:2222","identityFile":"/home/you/.ssh/deploy_key"}'
```

Use either `host` or `connection`. Explicit `user` and numeric `port` override
connection-string values. Port defaults to 22 and omitted/null `identityFile`
uses default keys or the SSH agent. Returned target fields are `host`, `user`,
`port`, `identityFile` and `legacy` (true only for old alias registrations).
Target updates during an active deployment through this API instance return 409.

To deploy a prepared bundle (add `"service":"api"` and point `releasePath` to
that service's artifact directory for a single-service deployment):

```sh
curl --fail-with-body http://localhost:6760/api/repos/my-repo/deployments \
  -H 'Content-Type: application/json' \
  -H 'X-Toolkit-Request: 1' \
  -d '{"releasePath":"/home/you/projects/my-repo/.release/build-001"}'
```

The API binds only to loopback and requires a loopback Host header. Browser
requests must be same-origin, including through nginx. There is no CORS
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
