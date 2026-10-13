# React UI

Run `make install`, then `make start`. Start runs Vite in the background using
`envdir` and `env-dir/${ENV_USER:-$USER}`; output goes to `start.log`.
For foreground development, use `envdir ./env-dir/$USER npm start`.
`npm start` alone uses env-dir/default unless HOST and PORT are supplied.
Use Node 20.19+ or 22.12+ (see package.json).

Open <http://localhost:6760/dashboard/> through nginx. The repository root's
`make start` starts the API, Vite and nginx; use `make services.nginx.start` if
the applications are already running. Vite serves the UI on port 6701 and fails
if that port is occupied. nginx forwards its prefix and WebSocket upgrades.

`make build` creates dist/. Serve it beneath the same /<app-name>/ prefix;
configure your production server's SPA fallback if adding client-side routing.

Development mounts the dev inspector. nginx proxies `/dashboard/harness-api` to
the harness API at `http://127.0.0.1:6000/api` and `/api` to the toolkit API on 6700.
Configure upstreams in `services/nginx/routes/dashboard.conf`; Vite has no proxy.
The inspector comes from the sibling visual-prompter component library.
Production builds leave it out.
