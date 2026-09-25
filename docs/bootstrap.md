# Bootstrap services

## Create a repository

`bootstrap repo create <name>` links the shared `AGENTS.md`, `.cursorignore`,
Cursor rules and skills from `~/.s6craft`, and links the repository's
`.cursorrules` to `~/.s6craft/.cursorrules`. The source
`.cursorrules` must exist before creation; edits to it apply to all linked repos.

## Import an existing repository

```sh
bootstrap repo import /path/to/my-repo
cd /path/to/my-repo
bootstrap service add api --type=nodejs --support=http
```

Relative paths are resolved from the current working directory. For example,
`bootstrap repo import .`, `bootstrap repo import ../my-repo`, and
`bootstrap repo import ./my-repo` all store and print the canonical absolute
repository path, resolving symlinks and `..` components.

Import recognizes repositories with a real `services/` directory, registers their
canonical path, and selects them in bootstrap state. The directory basename is
the repository name and port domain. It reuses an existing domain or creates a
100-port block for adding new services. No Git metadata or shared rules are required.

Existing service ports are imported using `port allocate discover`: scan `env-dir`
and `env-dev`, read `ENV_USER/PORT` (or `USER/PORT`), and fall back to `default/PORT`.
Services without a PORT file remain on disk and need no port reservation; bootstrap
does not maintain a separate service registry. Import does not scaffold or change
repository files. Other directories with these environment layouts, such as `ui`,
are discovered too.

Existing reservations are checked by port, stable service name, and legacy
discovery description before adding allocations. Their identities and descriptions
are preserved. Conflicting ownership or a service already assigned a different
port causes an error before reservations are written. Repeating import is safe.
If a later write fails, completed reservations remain available for retry.

Both bootstrap and port must be initialized. `bootstrap repo load` remains the
lighter operation that only registers/selects a directory without importing ports.

## Add a service

Run from the repository root:

```sh
bootstrap service add api --type=nodejs --support=http --support=fs
```

This creates `services/api`, runs `npm init -y`, and creates `env-dir/default`
and `env-dir/$USER`. Both environment directories receive the same initial values:

- `--support=http`: `HOST` is `localhost`; `PORT` is allocated from the existing
  port domain matching the repository directory's name, using `services/api` as
  the stable allocation name.
- `--support=fs`: `WRITE_DIR` is the expanded absolute `$HOME/.api` path. The
  storage directory itself is not created.

Support options are optional and repeatable, and also accept separate values
such as `--support http`. Only `nodejs`, `http`, and `fs` are currently supported.
Without support options, both environment directories are empty. No application
code or dependencies are generated. Service names use lowercase letters, digits,
dots, underscores and hyphens, starting with a letter or digit.

Each service includes a simple Makefile. Plain `make` displays the echo-only help:

- `make install` runs `npm install`.
- `make build` runs `npm run build --if-present`; add a build script when needed.
- `make start` loads `env-dir/$ENV_USER` (or `env-dir/$USER`) with `envdir`, then
  runs `npm start` in the background, logging to `start.log` and printing its PID.

The generated npm start script runs `node index.js`; add your application in
`index.js` before starting. `make start` requires `envdir`. Set `ENV_USER=default`
to use the default environment directory.

Bootstrap must be initialized (`toolkit setup bootstrap`), and npm must be
available. HTTP support additionally requires the initialized port toolkit and
an existing domain; `bootstrap repo create` already creates that domain.

Existing service paths are never overwritten. Scaffolding occurs in a temporary
directory and is cleaned up on failure. If publishing fails after port allocation,
the stable reservation remains available for a retry. Concurrent bootstrap
operations share the bootstrap lock; port allocation uses the port toolkit's lock.

## Add a UI

Run from the repository root, whose port domain must already exist:

```sh
bootstrap ui add dashboard
cd ui/dashboard
make install
make start
```

UIs are always JavaScript React apps using Vite, separate from `services/`.
There is no `--type` option. The scaffold includes application code, npm scripts,
a Makefile, and matching `HOST=localhost` and `PORT` files in `env-dir/default`
and `env-dir/$USER`. Ports use the stable allocation name `ui/dashboard` in the
current directory's domain. The app is served at `/dashboard/`; Vite fails if its
port is already occupied. A reverse proxy must forward this prefix and WebSocket
upgrades. New projects need an initialized port toolkit and a domain (for example,
`port allocate create <repository-directory-name> -s 6100`).
For direct browser access, use a browser-allowed port range: the allocator's
default first port, 6000, is browser-blocked. A reverse proxy can still forward
to it internally.

`make install` installs dependencies, `make build` creates production assets in
`dist/`, and `make start` runs Vite in the background using `envdir`, with output
in `start.log`. `ENV_USER` selects an environment directory, falling back to
`USER`. For foreground development use `envdir ./env-dir/$USER npm start`;
`npm start` alone reads the default environment files. Serve production assets
under the same URL prefix. The generated package declares its Node requirement.

The Makefile templates live alongside `template/makefile/nodejs` in
`src/bootstrap.bin/template/makefile/`: `ui` for a plain UI and
`ui-component-library` for library support. `bootstrap ui add` selects the
matching template. Both provide `help`, `install`, `build`, and `start`.

To use an existing repository-root component library:

```sh
bootstrap ui add dashboard --support=component-library
```

This requires `component-library/package.json`, `src/index.js`, and `Makefile`.
It adds a `file:../../component-library` dependency without copying or creating
library files. `make install` runs the library's install and build targets before
installing app dependencies. `make build` first runs its build target. In
development Vite reads the library's source, supports JSX in `.js` files, and refreshes on source edits. Components
must import their own CSS; the built library CSS import is ignored in development.
Production uses the library's built package exports and
`component-library/dist/component-library.css`. React, ReactDOM, and
react-virtuoso are deduplicated to the app's copies.

Names follow the same character rules as services. Existing paths (including
symlinks) are rejected. Creation shares the bootstrap lock and stages files
before publishing; failures clean up staging and retain any allocated port for
retry. Scaffolding does not install dependencies.
