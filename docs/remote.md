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

`remote` prepares service users, directories, s6 runners and supervision links on
Linux hosts over SSH. `remote deploy` transfers a prepared release and invokes its
shipped Makefile. The application owns package installation, DNS/nginx configuration,
migrations, release activation, process control and health checks.

```sh
toolkit build
toolkit setup bootstrap
toolkit setup remote
bootstrap repo load ../homelab
remote create homelab my-pi
remote ls
remote setup users homelab
remote setup directories homelab
remote setup service homelab --all
remote setup supervision homelab
remote status homelab
```

`my-pi` is an existing SSH config alias. Configure its HostName, User, Port and
IdentityFile in SSH configuration and establish its known-host entry separately.
Commands use batch SSH, strict host-key checking and `sudo -n sh -s`; the SSH user
needs noninteractive root access. No password or SSH private key is stored here.
Use `remote edit homelab other-alias` to replace a target, and `remote rm homelab`
to remove the local registration. Removing a target never changes its host.
Repository arguments are registered bootstrap **names**, not paths.

Local state is `$UTIL_PATH/remote/targets/<repo>`, one SSH alias per file, plus
lock/history directories. `toolkit setup remote` initializes this local state;
`remote setup ...` performs host actions. Repeated initialization preserves targets.
A target may be removed even after its bootstrap registration is removed.

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
of `services/` are the service inventory, regardless of implementation language.
Loose shared files are ignored; service-directory symlinks are rejected. No remote
service registry is maintained, and the repository's `infrastructure/` directory
is not used.

PORT lookup matches bootstrap import: inspect `env-dir` and `env-dev`, use
`$ENV_USER` (or `$USER`, then `default` if neither is set), and fall back to
`default/PORT` when that file is missing. Empty ports are skipped. Conflicting
sources, duplicate selected-service ports and invalid port numbers fail before
SSH. Services without PORT are valid. Port allocation remains owned by bootstrap
and port; remote never allocates a port or copies their registry. Explicitly set
`ENV_USER=default` when that is the desired source.

Only PORT is copied into the host environment; other environment files, credentials,
application-specific configuration and host bindings must be supplied separately.
Rerunning service setup updates PORT from the repository and removes the remote
PORT file when the source no longer specifies one. Status reports port drift.
The bootstrap registry is locked while the snapshot and operation run; direct
manual edits to repository files are outside that lock.

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

## Application releases and Makefile templates

```sh
remote deploy homelab /path/to/homelab/.release/20260918T030000Z
```

The directory name identifies an immutable release. The directory must contain
regular files/directories and a root `Makefile` exposing `deployment.deploy`.
Build and package locally first, using an explicit application allowlist which
excludes databases, environment files, credentials, node_modules and development
servers. The toolkit stages a complete archive before SSH, normalizes new release
permissions, extracts into a temporary host directory, then publishes it at
`/opt/<repo>/releases/<name>`. Existing names fail without replacement. It runs
`make deployment.deploy` there as root. Only deploy trusted application code.
An application failure returns nonzero and retains the release for inspection.
There is no automatic database rollback or release pruning.

Reusable Makefile/root-forwarding and host-workflow templates live in
`src/bootstrap.bin/template/deployment/`. Copy these into the application's
`deployment/` directory, replace `__REPO__`, and include `deployment/root.mk` from
the root Makefile. Implement the small application-specific scripts named by the
targets. Copy `src/lib/files.sh`, `src/lib/remote-host.sh` and
`src/remote.bin/.host/validate` into `deployment/toolkit/`; copy the host setup
scripts too when the application ships standalone host preparation. These are
ordinary shipped files: the host needs neither the source toolkit checkout nor
the local registration state. Review/update the copied helpers when updating the
toolkit. The template validator holds the same stable host lock throughout the
workflow; transfer releases that lock before invoking the application's validator.

Homelab implements the workflow in its own `deployment/Makefile`. From its checkout,
`make deployment.push` builds both UIs, packages a fresh release and calls remote.
On the host, `sudo make -C /opt/homelab/current deployment.status` checks runtime
health; replace `status` with `restart` to restart. A manually copied release under
`/opt/homelab/releases/<name>` can be installed with
`sudo make -C /opt/homelab/releases/<name> deployment.deploy`.

Homelab uses the API runtime account for all its cooperating processes, with
private shared state in `/var/lib/homelab`; the toolkit's separate deployment/log
accounts and existing service data directories are preserved. Its setup replaces
the generic runners to select this common application identity. If running
`remote setup service` later, follow with homelab's `deployment.setup` before
restarting. Only its root-owned private dnsmasq executable receives port-binding
capability. The shipped installation expects compatible Node >=22.13 at
`/opt/node` and installs the Debian host dependencies. Migration failures leave
services stopped for repair; migrations are forward-only. Backups precede repeat
migrations, and no local database is transferred. Deployments include a short
stop/migrate/start window, and old releases/backups are retained for manual cleanup.
