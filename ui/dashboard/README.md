# React UI

Run `make install`, then `make start`. Start runs Vite in the background using
`envdir` and `env-dir/${ENV_USER:-$USER}`; output goes to `start.log`.
For foreground development, use `envdir ./env-dir/$USER npm start`.
`npm start` alone uses env-dir/default unless HOST and PORT are supplied.
Use Node 20.19+ or 22.12+ (see package.json).

Open the /<app-name>/ URL printed by Vite. The port is allocated under ui/<name>
in the repository's existing port domain. Vite fails if that port is occupied.
If using a reverse proxy, forward this prefix, including WebSocket upgrades.

`make build` creates dist/. Serve it beneath the same /<app-name>/ prefix;
configure your production server's SPA fallback if adding client-side routing.

Development mounts the dev inspector and proxies `/dashboard/harness-api` to
the harness API (`HARNESS_PROXY_TARGET`, default `http://127.0.0.1:6000`).
The inspector comes from the sibling visual-prompter component library.
Production builds leave it out.
