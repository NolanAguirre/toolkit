# Port allocation

```sh
port allocate create my-repo -c 20
port allocate create another-repo -s 30000 -e 30099
port allocate pull my-repo -n web -m "development server"
port allocate set my-repo 8080 -m "fixed service port"
port allocate ls
port allocate rm -p 8080
port allocate rm -d my-repo
```

Run `port allocate discover` from a repository root to register its development
ports under the current directory's name. Create that domain first with
`port allocate create <name>` if it does not exist yet.
Alternatively, `port allocate discover --create-domain` creates a missing
100-port domain under the same lock, after validating the discovered ports.

Discovery recursively searches `env-dir` and `env-dev` directories, reading
`$ENV_USER/PORT` (or `$USER/PORT` when `ENV_USER` is unset), with `default/PORT`
as the fallback when that file is missing. Empty files are skipped. It reads only
`PORT` files, without executing them or modifying project configuration; `.env`
files are not included. Dependency directories (`node_modules`, `.venv`, `venv`)
and `.git` are skipped, and directory symlinks are not followed.

Each reservation gets a message such as `visual-prompter/services/vpr`.
Discovery prints reserved port numbers, checks invalid values, duplicate discovered
ports, ownership conflicts and service identity conflicts before writing, and
holds the allocation lock throughout. Repeated runs preserve existing reservation
identities and messages. A service already reserved at another port is rejected,
including legacy discovery descriptions and nginx reservations. Ports no longer
found are retained; use `rm` to release them.

Run `port allocate default` from the same repository root to fill missing ports.
It scans the same directories and first registers existing port values. Where
neither the selected user's `PORT` nor the fallback `default/PORT` exists, it
allocates a stable port for the service and creates `$ENV_USER/PORT` (or
`$USER/PORT`). Existing files, including empty files, are preserved. It only
visits existing `env-dir` and `env-dev` directories; it does not create those
directories for services that have none.

Services named `nginx` are allocated first, preferring the domain's hundred
boundary plus ten times its thousands digit: `6060`, `6160`, `6260`, then
`7070`, `7170`, `7270`, and `8080`, `8180`, etc. If that port is occupied or
outside the domain's range, the lowest free port in the range is used. Existing
service reservations, including legacy reservations described as `nginx`, are
reused. Other services receive the lowest free port with their relative path as
the stable allocation name.

`default` prints each newly written port. The allocation lock covers scanning,
reservation and file creation; files are created without overwriting a file that
appears during the scan. Completed work and reservations are retained if a later
step fails. After fixing the failure, rerun the command to reuse those allocations.

`pull` prints only the port number. The same domain/name always returns the same
port; supplying a message updates its metadata. `set` reserves a specific port,
including ports outside the domain's automatic block. Repeating it for the same
domain is safe; a different domain cannot take an already allocated port.

Ranges are inclusive. `-c` chooses a dedicated contiguous block; without options,
100 ports are chosen. Automatic blocks start at hundred boundaries from port 6000 upward,
avoiding existing blocks and allocations. `-s` alone reserves 100 ports; `-s` with `-c` is also supported.
Manual allocations do not consume automatic capacity unless they lie within the
block. Automatic pulls skip all previously allocated ports, across every domain.

State lives under `$UTIL_PATH/ports` (normally `~/.cerberus/ports`):

```text
ports/
  lock
  history/
  allocate/
    ports                # append-only JSON-lines reservation journal
    my-repo/
      .domain.json       # automatic range
      10000              # JSON metadata: port, domain, name, message, timestamp
      8080
```

Validation holds an exclusive `flock` on `lock` through command execution. The
kernel releases it when the command exits. Every new reservation is appended and
synced before its metadata file is atomically written. Repeated pulls and metadata
updates do not rewrite the journal. A retry recovers a missing metadata file from
its journal record. An invalid journal causes commands to fail rather than risk
reusing a port.

`rm -p <port>` (or `--port`) finds the port globally, atomically rewrites the
index without that reservation, and removes its metadata. Its domain remains.
`rm -d <domain>` (or `--domain`) removes every reservation for the domain,
including manually assigned ports outside its range, then removes the domain
directory. Its automatic range becomes available again. Exactly one flag is required.
Other index lines are preserved exactly. Appending is the normal write path;
removal is the exception.

This records reservations; it does not bind sockets or prevent unrelated programs
from using a port.

`ls` groups ports by domain, sorted by domain name and then port number. It shows
the current name and message, with `-` for missing values and empty domains labeled.

The commands are Bourne shell scripts using `jq` for JSON state, `awk` for port
selection and table formatting, and the shared shell locking/atomic-write helpers.
There is no Python runtime dependency. Existing JSON state remains compatible.

`port kill 3000 4000 8080` force-kills processes using any of those TCP or UDP
ports, using `lsof` or `fuser`. It validates the entire list first and signals each
PID only once. Like the original `kill-port` script, it uses SIGKILL. Killing a
process does not release its allocation; use `port allocate rm` for that.
