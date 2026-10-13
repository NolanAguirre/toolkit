# Remote deployment variants

`remote` supports two workflows:

- `remote sync push|pull` copies selected files into existing directories on Windows
  or other SFTP hosts. Use this for Unity development and other directory-copy deployments.
- `remote deploy` publishes immutable application releases on prepared Linux hosts.

## Directory-copy deployments (Windows / Unity)

```sh
toolkit build
toolkit setup remote
remote sync create my-game windows-unity 'C:/Projects/My Game'
remote sync ls
remote sync push my-game /path/to/local/MyGame
remote sync pull my-game /path/to/local/MyGame
```

`windows-unity` is an existing SSH config alias with the host, user, port and key
configured there. The Windows machine needs OpenSSH Server with its SFTP subsystem
enabled and the destination project directory already created and writable by that
user. Establish the host key first. The client uses batch authentication and strict
host-key checking. No sudo, remote shell commands, bootstrap repository registration,
toolkit installation on Windows, or extra sidecar is needed. See Microsoft's
[OpenSSH setup instructions](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse).

The transfer uses OpenSSH `sftp` directly, so it does not depend on the remote
PowerShell/cmd quoting rules or the client's choice of legacy SCP versus SFTP.
Use an absolute remote path with forward slashes; drive paths such as
`C:/Projects/My Game` and `/C:/Projects/My Game` are accepted. A Unix host can use
`/home/user/projects/game`. Paths with spaces work. Glob characters, double quotes,
backslashes and control characters are rejected in registered paths.

The default selection is **Assets, Packages, ProjectSettings**. Entire selected
directories are copied, including hidden files and Unity `.meta` files. Unity's
generated `Library`, `Temp`, `Logs`, `Obj`, `UserSettings` and build outputs outside
those directories are not selected. Custom selections replace the default:

```sh
remote sync create content windows-unity 'D:/Shared/Content' textures config.json
remote sync edit my-game windows-unity 'C:/Projects/My Game' Assets Packages ProjectSettings .gitignore
```

Each selection must name a literal **top-level** file or directory within the
project. No globs, nested paths, `.` or `..` selections are accepted. Include any
additional source roots or local package dependencies explicitly. Push checks every
selected local entry before connecting. Pull checks that every remote selection
exists before copying. The local project directory must already exist; initialize
a second machine with the same profile and an empty destination:

```sh
toolkit setup remote
remote sync create my-game windows-unity 'C:/Projects/My Game'
mkdir -p "$HOME/projects/MyGame"
remote sync pull my-game "$HOME/projects/MyGame"
```

Configure the same SSH alias and authentication on that machine first. Profiles
store no local project path, so any existing directory can be the push source or
pull destination. Profiles live in `$UTIL_PATH/remote/sync/<name>` as plain text:
SSH alias, absolute remote directory, then one selected entry per line. Create/edit
replace that file atomically; new profiles have mode 0600. Setup preserves profiles, and
`remote sync rm my-game` removes only the local profile. `remote sync ls` prints
tab-separated name, alias, directory and selected entries.

This is explicit directional copying: all selected files transfer each time,
matching destination files are overwritten in place, and destination-only files
remain. There is no deletion propagation, timestamp comparison, conflict merging,
build step or process restart. A rename therefore leaves the old destination name;
remove it explicitly when needed. Pull before switching machines, then push your
edits. Keep project trees free of links/special files: local selected trees are
checked, but remote trees must be trusted ordinary files and directories.

Transfers are not transactional. A connection failure can leave partially written
files; fix the error and repeat the same direction to overwrite them completely.
The local lock covers validation and the entire transfer, but does not coordinate
other machines or Unity/editor writes. Avoid overlapping clients and editing during
a transfer; wait for success before running/importing the project in Unity.
Progress/diagnostics go to stderr, and transfer failures return nonzero.

## Linux host preparation

`remote` prepares service users, directories, s6 runners and supervision links over
SSH. Deployments use an explicit IP address or DNS hostname, SSH user, port and
optional local identity-file path. No homelab files or SSH config entries are needed.

```sh
toolkit build
toolkit setup bootstrap
toolkit setup remote
bootstrap repo load ../my-project
remote create my-project 192.168.1.50 --user deployer
# Equivalent connection-string forms:
# remote create my-project deployer@example.com
# remote create my-project ssh://deployer@example.com:2222 --identity-file /home/you/.ssh/deploy_key
remote ls
remote setup all my-project
remote status my-project
```

Accepts `user@host`, `ssh://user@host:port`, bare IP/DNS hosts with `--user`, and
bracketed IPv6 such as `ssh://deployer@[2001:db8::1]:2222`. A user is required;
the port defaults to 22. `--user`, `--port` and `--identity-file` override values
from the connection string. Passwords, remote paths and arbitrary SSH options
are not accepted. A DNS hostname must already resolve; saving a target does not
create DNS records. IP addresses work without DNS.
Toolkit command history skips target create/edit arguments so even rejected
connection strings containing a password are not recorded there.

Use `remote edit my-project deployer@other.example.com` to replace the complete
connection configuration, and `remote rm my-project` to remove the local
registration. Both leave the host untouched. Repository arguments are registered
bootstrap **names**, not paths. The dashboard's Deployment target form and
`POST /api/repos/:name/target` save the same configuration.

Each target is a plain JSON file at
`$UTIL_PATH/remote/connections/<repo>.json`, created with mode 0600:

```json
{
  "host": "example.com",
  "user": "deployer",
  "port": 2222,
  "identityFile": "/home/you/.ssh/deploy_key"
}
```

`identityFile` is a path, never the key contents; `null` uses default keys or the
SSH agent. The shell commands use `jq` to read/write JSON, validate it before use,
and atomically replace it under the remote lock. `remote ls` returns tab-separated
repo, host, user, port and identity path (empty when unset). `toolkit setup remote`
initializes local state and preserves existing settings; run it after updating.
Existing one-line aliases in `remote/targets/<repo>` remain supported with their
old SSH-config behavior. `remote edit` creates a JSON connection that takes
precedence; `remote rm` removes both registrations. Legacy `remote ls` rows have
only repo and alias columns.

New connections use `ssh -F /dev/null` so neither user nor system SSH config
changes their destination. Batch authentication, strict host-key checking and
`sudo -n sh -s` remain in effect. Establish host trust and key access first, using
the same explicit connection values, for example:

```sh
ssh -F /dev/null -p 2222 -i /home/you/.ssh/deploy_key deployer@example.com
```

The SSH user needs noninteractive root access for host operations. Saving settings
makes no connection and stores no passwords or private keys. Runtime dependencies,
builds, migrations, DNS/nginx configuration and health checks remain application
responsibilities.

## Host prerequisites and ordering

The supported host is Linux with GNU coreutils, util-linux `flock`, `getent`,
shadow `useradd`, a nologin shell, and s6 on the sudo shell's PATH. There is no
package installation or distribution detection. Users can be prepared before s6
is installed. The supervision step requires systemd to be running and installs
`/etc/systemd/system/toolkit-remote-svscan.service`, with
`ExecStart=<resolved-s6-svscan-path> /var/service`, restart on failure, and
`WantedBy=multi-user.target`. It reloads systemd, then enables and starts this
dedicated scanner unit. It does not replace the host init system. Other init
systems are not supported. A conflicting unit, drop-in, or independently managed
scanner owning `/var/service` is rejected. Initial scanner installation also
rejects unrelated entries already in its scan directory; setup does not take it
over. No target OS or SSH alias is assumed for the Raspberry Pi.

Individual commands report missing prerequisites rather than running other steps:

- `remote setup users <repo>` creates three locked system accounts per service.
- `remote setup directories <repo>` requires those accounts and creates the layout.
- `remote setup service <repo> <service>` configures one service; `--all` selects
  every service in the current repository inventory.
- `remote setup supervision <repo>` requires configured services, installed s6 and
  running systemd; installs the boot unit, creates links, enables/starts the scanner
  and asks s6 to scan for them.
- `remote setup all <repo>` runs users, directories, all services, then supervision.

A failed batch can leave completed steps in place. Correct the prerequisite and
retry. There is no rollback of previously completed host operations.

## Inventory and ports

The bootstrap registry resolves the repository path. Real immediate subdirectories
of `services/` each default to one deployment service, regardless of implementation language.
Loose shared files are ignored; service-directory symlinks are rejected. No remote
service registry is maintained, and the repository's `infrastructure/` directory
is not used.

PORT lookup matches bootstrap import: inspect `env-dir` and `env-dev`, use
`$ENV_USER` (or `$USER`, then `default` if neither is set), and fall back to
`default/PORT` when that file is missing. Empty ports are skipped. Conflicting
sources, duplicate deployment ports and invalid port numbers fail before
SSH. Services without PORT are valid. Port allocation remains owned by bootstrap
and port; remote never allocates a port or copies their registry. Explicitly set
`ENV_USER=default` when that is the desired source.

Only PORT is copied into the host environment; other environment files, credentials,
application-specific configuration and host bindings must be supplied separately.
Rerunning service setup updates PORT from the repository and removes the remote
PORT file when the source no longer specifies one. Status reports port drift.
The bootstrap registry is locked while the snapshot and operation run; direct
manual edits to repository files are outside that lock.

## Multiple deployment services in one source folder

An optional `services/<folder>/remote-services` file replaces that folder's default
single-service entry. Each line contains `deployment-name:PORT_VARIABLE`, or
`deployment-name:-` for a service without a listening port. Blank lines and lines
starting with `#` are allowed. For example, keep both implementations in
`services/tgr/` and declare:

```text
tgr:PORT
tgr-consumer:-
```

This creates independent `tgr` and `tgr-consumer` deployment services. Each has its
own runtime/deployment/log accounts, s6 supervision, environment, logs, releases
and current release selection. The source folder is not an additional deployment
service unless listed. Folders without this file retain the original behavior.
`bootstrap service add tgr --type=nodejs --support=http --support=python` generates
these declarations, a Node `run` launcher and a Python `run-consumer` launcher.
Existing folders can opt in by adding the declaration file themselves.

Port variables are read from the source folder's `env-dir`/`env-dev`, using the
same user/default selection described above. An explicit variable must resolve
to a nonempty valid port; its value is installed as the deployed service's `PORT`.
Use `-` to skip port lookup entirely. Additional HTTP processes can reference
other variables such as `METRICS_PORT`. Remote does not allocate those ports.
Names must be unique across the entire repository, including implicit folder
names. The existing lowercase Unix account naming and 27-character combined
`<repo>-<service>` limit apply. Invalid declarations, duplicate names and duplicate
ports anywhere in the inventory fail before SSH, even for single-service commands.
Declaration files must be regular files, not symlinks, and contain at least one service.

Package separate artifacts from the same source folder:

```text
.release/build-001/
    tgr/
        run                 # copied from services/tgr/run
        index.js
        ...                 # Node runtime files and production dependencies
    tgr-consumer/
        run                 # copied from services/tgr/run-consumer
        cli/
            consumer.py
            fsqueue.py
            requirements.txt
```

The worker launcher expects `cli/.venv/bin/python3` in its artifact after host
preparation. Create that environment and install dependencies on the host using
an application-owned `bin/deploy-prepare` hook; do not copy the local virtual
environment. Adapt the launcher to the real consumer entrypoint when adopting an
existing service, such as TGR's `cli/tgr_tag.py --consumer`. Both launchers inherit
the host environment and stay in the foreground; they do not load development
`env-dir` files. Packaging and dependency preparation remain application-owned.

```sh
remote setup all my-repo
remote deploy my-repo .release/build-001
# Deploy only the consumer without switching or restarting the API:
remote deploy my-repo tgr-consumer .release/build-001/tgr-consumer
remote setup service my-repo tgr-consumer
remote status my-repo
remote releases my-repo
```

For filesystem queues, application host setup must give both runtime accounts
access to a shared, persistent queue directory, and configure the same `QUEUE_DIR`
in both host environments. Their private `data/` directories are separate.
Consumers sharing a GPU also need access to the same `GPU_LOCK_PATH` file.
Remote still copies only PORT; queue paths, shared group/ACL permissions, model
caches and other environment values are application configuration. Reuse the
existing API deployment name when adding a consumer to preserve its host identity.
Removing or renaming a declaration does not delete the old host service.

## Layout and runtime contract

Each service gets a stable key: the first 16 hex characters of SHA-256 over
`<repo>/<service>`. Its directory name is `<repo>--<service>--<key>`, avoiding
cross-repository name collisions. The three users are `rt-<key>` (runtime),
`dp-<key>` (deployment owner), and `lg-<key>` (logging). All have private primary
groups, no created home, locked initial passwords and nologin shells. Existing
accounts must match the recorded toolkit identity, home and primary group.

```text
/var/service/<unit> -> /var/service-dir/<unit>
/var/service-dir/<unit>/             root, 0755
    run                            root, 0755
    down                           root, 0644 (created with the first runner)
    env/                           root, 0755
        PORT                       root, 0644 (if configured)
    etc/                           root, 0755
    bin/                           root, 0755
    server/                        deployment owner, 0755
    data/                          runtime user, 0700
    log/                           root, 0755
        run                        root, 0755
        main/                      logging user, 0700
```

The root-owned runner loads `env/` with `s6-envdir`, drops to the runtime user,
and executes `./server/current/run` from the service directory. That executable
must stay in the foreground and handle its own application working directory.
Setup creates neither `current` nor application files and does not infer a launch
command from a development Makefile. This contract works for every service type,
including DNS and nginx, once its runtime executable/configuration exists.
Binding privileged ports and other application privileges are not configured.

The logging runner uses `s6-log` with timestamps and ten approximately 1 MiB
rotated files. New applications remain down, while the logger may start when the
scanner discovers the service. Repeat setup preserves an operator's down/up
choice, rewrites managed runners atomically, and never sends a service restart.
It does not recursively chown trees. Conflicting directory owners/modes, existing
account identities, file symlinks, or supervision links cause errors. Existing
application data and releases are preserved. Removing a service from the repo
also does not remove its existing host users/directories/links.

`remote status <repo>` prints tab-separated service, setup state, runtime state and
expected PORT (`-` means absent). It checks users, directories, runners, port,
links, active/enabled systemd scanner, service supervisor and logger. `ready / awaiting-runtime` means a deliberately
down service has no executable runtime yet and is a successful setup result.
Other down services, absent supervision and incomplete setup return nonzero.
Status requires sudo too; it leaves service configuration unchanged. All host
operations, including status, open or create the coordination lock at
`/run/lock/toolkit-remote.lock`. They never unlink an active lock file.

## Implementation and verification

Commands follow the shared dispatcher. The local initializer occupies
`remote.bin/setup`, so `remote-setup` selects the host script to send.
Each host operation has its own script under `.host/`, with shared helpers in
`lib/remote-host.sh`; the whole input is staged before connecting. Local and host state
replacements use the shared atomic-write helper. Local remote and bootstrap locks
cover the operation; a stable host lock serializes separate clients as well.

Run `python3 tests/remote.py` for temporary-state tests with mocked SSH, user
management, ownership and s6. The actual generated shell scripts execute against
redirected temporary paths, exercising state changes, preservation, atomic-write
failure and concurrent clients. These checks do not exercise a real SSH server,
real user creation, actual systemd boot behavior or actual s6 supervision. No real
host actions are needed for the tests. Run `toolkit test remote` for public command help checks.

## Release artifacts and identities

```sh
remote deploy my-repo /path/to/.release/build-001
remote deploy my-repo api /path/to/.release/build-001/api
remote releases my-repo
```

A repository bundle contains one directory per selected service, each with an
executable `run` and its runtime files. Single-service deployment takes that
service directory directly. The current toolkit does not deploy a root Makefile
bundle into `/opt`; older application-specific packaging (including legacy
homelab releases) must be adapted before using this service-artifact workflow.
Package an explicit allowlist, excluding credentials and mutable application data.

The client creates each service's tar.gz and SHA-256 before SSH. The host verifies
the hash, extracts as the deployment owner into
`/var/service-dir/<repo>-<service>/server/server-<timestamp>-<random>`, and runs an
optional `bin/deploy-prepare` hook as that owner. The root deploy command records
metadata before atomically switching `server/current` and requesting an s6 restart.
An operator's `down` flag remains in effect. Successful deployment does not prove
that the new process has started or passed an application health check.

Four recent release directories are retained, plus an older release still named
by the startup record. Failed preparation or metadata generation preserves the
previous selection. Failures after activation can leave the new release selected;
inspect `remote releases` before retrying. Services in a bundle activate separately,
so a later service failure does not roll back earlier services.

Metadata lives beside the service's `run` file, outside s6's private `supervise/`:

```text
/var/service-dir/my-repo-api/
  run
  release                       # last successfully recorded selection
  running-release               # release launched by run, PID and process start
  releases/server-...            # immutable identity for each deployed release
  server/current -> server-...
  server/server-.../run
```

These are root-owned, atomically replaced plain TSV files, readable without a
language runtime. Release records contain `release`, `commit`, `commit_source`,
`dirty`, `archive_sha256`, and `deployed_at`. The archive hash identifies the exact
uploaded compressed artifact, not a later filesystem tree or files modified by
`deploy-prepare`. Metadata records are kept even when old runtime directories are
pruned. They do not contain passwords, environment values, or application logs.

For reliable build provenance, the application packager should place a full
lowercase Git commit hash in each artifact's `.toolkit-commit` when building it.
That is recorded as `commit_source=artifact`, with dirty state unknown. Without
that file, the toolkit records the registered checkout's HEAD and whether it has
uncommitted/untracked changes at deployment time (`checkout-at-deploy`). That
fallback is informational: an older prebuilt artifact need not match that HEAD.
Non-Git sources report an unknown commit. The archive hash is always computed.

The generated runner pins the resolved release path before executing it and
records its PID/start time. `remote releases` asks s6 for the supervised PID and
compares that identity with the startup record. It prints TSV rows with four
columns: service, scope (`runtime`, `selected`, `running`), key, value. Runtime
identity is `verified`, `not-running`, or `unknown`. A still-running old process
can therefore differ from the newly selected release. An SSH or supervisor error,
stale startup record, old/custom runner, or missing metadata never becomes an
invented running commit. Verification identifies the launched process/artifact;
it is not an application health check or proof of ongoing file integrity.

After updating the local toolkit, existing hosts need their generated deploy
commands and standard runners upgraded:

```sh
remote setup service my-repo --all
```

Setup upgrades an exact old toolkit-generated runner and preserves custom runners.
It does not restart services. New identity records appear on the next deployment
and process start. A custom runner must explicitly adopt the recording/pinned-path
behavior before its running identity can be verified. Old releases cannot recover
the original tar hash after the archive has been discarded. New deploy clients
reject old host deploy scripts with an instruction to update them first.

The dashboard's **Check host via SSH** action calls `remote releases` with a bounded
timeout. It reports selected and verified running identities separately, including
SSH failures. It does not deploy, restart, or trigger a supervisor scan. SSH keeps
batch mode and strict host-key checking; establish trust through the normal SSH
workflow before checking a new host.

Reusable application Makefiles live in `src/bootstrap.bin/template/deployment/`.
Their package step must produce the per-service artifact layout above. Application
scripts still own builds, migrations, health checks and any customized runners.
