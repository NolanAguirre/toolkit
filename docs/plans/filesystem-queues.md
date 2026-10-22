# Filesystem queue provisioning plan

Status: planned. The commands, generated files, and setup behavior below describe
the implementation to add; they are not existing queue commands.

Bootstrap will provision named filesystem queues for existing services, including
local directories, deployment ownership and permissions, trigger FIFOs, and
environment variables. A service can have multiple queues, added independently
after the service is created.

Queue runtime libraries will be implemented later in language-specific
repositories. This change does not implement message producers, consumers, retry
daemons, or a database or WAL.

## Command interface

Run from a registered repository root:

```sh
bootstrap queue create media thumbnails
bootstrap queue create media transcodes --support=retry --support=idempotency
```

The proposed interface is:

```text
bootstrap queue create <service> <queue> [--support=retry] [--support=idempotency]
```

Accept both `--support=value` and `--support value`. Support options are repeatable;
repeating the same option has no additional effect. Reject unknown options.

Require an existing real `services/<service>` directory. Reuse service-name
validation. Queue names must match `[a-z][a-z0-9_]*`, giving an unambiguous mapping
to environment variable names. Names are unique within their service.

Creation writes the queue definition and setup targets, provisions the default
and selected local environments, and prints the selected environment's absolute
queue path on stdout. Diagnostics go to stderr. An identical request is safe to
repeat; a different definition at the same location is a conflict, not an
implicit configuration update.

Adding a queue does not run npm, allocate ports, scaffold another service, or
require Python. Queue creation is independent of the service implementation type.

## Paths and environment configuration

The queue root is always:

```text
<WRITE_DIR>/queues/<queue-name>
```

Write one environment file per queue, named `<QUEUE_NAME>_QUEUE_DIR`, with the
queue name uppercased. For example:

```text
services/media/env-dir/default/THUMBNAILS_QUEUE_DIR
services/media/env-dir/nolan/THUMBNAILS_QUEUE_DIR
```

With `WRITE_DIR=/var/lib/myrepo/media`, the expanded values are:

```sh
THUMBNAILS_QUEUE_DIR=/var/lib/myrepo/media/queues/thumbnails
TRANSCODES_QUEUE_DIR=/var/lib/myrepo/media/queues/transcodes
```

Read `WRITE_DIR` independently from each target environment. For local creation,
use `env-dir/default` and `env-dir/${ENV_USER:-$USER}`, handling the same directory
only once. Require the selected environment name to be a valid single directory
component. Require each target's `WRITE_DIR` to contain one nonempty absolute
path; do not silently copy the default path into another environment or fall
back to `/tmp`, `$HOME`, or toolkit state.

Preflight both environments before changing either. Different environment
directories may intentionally resolve to the same queue root. Provision that
root idempotently, without assigning it separate queue identities.

Write missing queue variables, preserve matching values, and reject conflicting
values. Preserve unrelated environment files. Changing `WRITE_DIR` does not move
existing messages; path migration and replacement of conflicting queue variables
require a separate explicit operation outside this initial feature.

The trigger FIFO is always `<QUEUE_NAME>_QUEUE_DIR/trigger`. No additional FIFO
environment variable is needed.

## Filesystem layout

```text
<WRITE_DIR>/queues/<queue-name>/
    tmp/
    queue/
    processing/
    complete/
    failed/
    retry/          # When retry support is enabled
    idempotency/    # When idempotency support is enabled
    trigger         # FIFO, not a regular file
```

Use these exact lifecycle names. There is no `pending`, `done`, or `completed`
directory in this contract. Keep all message lifecycle directories on the same
local filesystem so runtime transitions can use atomic renames.

Use a single `idempotency` directory for per-key coordination and acceptance
records. Do not add a separate `locks` directory for idempotency. Bootstrap only
creates this directory; it does not create, rewrite, expire, or remove individual
key files.

## Queue definitions

Store source-controlled definitions and generated setup files alongside the
service. Proposed layout:

```text
services/media/queues/thumbnails/
    retry-enabled
    idempotency-enabled
    local/
        directory-mode
        fifo-mode
    deployment/
        owner
        group
        members
        directory-mode
        fifo-mode
    Makefile
    validate
    setup
    toolkit/
        files.sh
        locking.sh
```

Feature files contain `0` or `1`. Scalar settings contain one value per file;
`members` contains one account name per line. Read values as data, never by
sourcing configuration as shell code. The directory name identifies the queue;
do not duplicate absolute local runtime paths in the definition.

Local ownership defaults to the invoking user and their primary group.
Deployment account names must be configured explicitly or resolved from an
existing unambiguous deployment identity. Do not invent runtime users or silently
grant access to every service account. Missing deployment settings do not block
local creation, but must block deployment provisioning with a useful error.

The source definitions are authoritative. Avoid a second registry of queue
definitions under `$UTIL_PATH`. Existing bootstrap registration and locking state
remain under `$UTIL_PATH/bootstrap`; application messages live under `WRITE_DIR`.
If implementation needs additional toolkit state, initialize it in bootstrap's
`setup`, preserving existing state on repeated setup.

## Local setup implementation

Generate an explicit root Makefile target for each queue:

```sh
make queue.media.thumbnails.setup
ENV_USER=default make queue.media.thumbnails.setup
```

Each root forwarder needs a `.PHONY` declaration and an echo-only help entry.
Forward to the generated queue Makefile, whose `setup` target selects the service
environment and invokes its validator. Do not add wildcard forwarding rules.

Run these operations in order:

1. Validate arguments, definition files, environment paths, existing objects,
   permissions, and the expected queue variable before modifying state.
2. Acquire or inherit the existing bootstrap lock through the validator. Creation
   already holds this lock; generated setup must not deadlock by acquiring it
   again through an independent descriptor.
3. Create a missing `WRITE_DIR` and the `queues` parent when permitted. For an
   existing `WRITE_DIR`, preserve its ownership and permissions; fail if it
   cannot support the requested queue access.
4. Create the queue root and each required lifecycle directory with explicit
   commands. Create optional directories only when their feature is enabled.
5. Create `trigger` with `mkfifo` if missing. Reuse an existing FIFO without
   replacing its inode.
6. Apply the configured ownership and modes to managed directories and the FIFO.
7. Publish missing environment values with the shared atomic-write helper after
   the corresponding filesystem setup succeeds.

Local mode defaults are `0700` for directories and `0600` for the FIFO. The
generated scripts remain POSIX shell and use ordinary filesystem utilities.
Fixed directory sequences should be explicit commands, not loops over a
hard-coded list. Loops are appropriate for discovered queue definitions or
configured group members.

## Deployment integration

Provision queues during the application's existing `deployment.setup` step,
after runtime account preparation and before starting the new release. The
current deployment template runs setup before stopping an existing release, so
setup must preserve live queue files, FIFOs, and runtime lock objects.

The generated deployment entry point accepts the actual host environment
directory and reads its `WRITE_DIR`. Never package expanded developer queue paths
as host configuration. If a source service has multiple deployments through
`remote-services`, explicitly identify which runtime environments need the queue
variable and which accounts need filesystem access. Do not derive additional
queue roots merely from deployment aliases.

For shared deployment access, the proposed defaults are:

| Resource | Mode |
| --- | --- |
| Managed queue directories | `2770` |
| Trigger FIFO | `0660` |

Use the configured owner and group. Require existing runtime users, create a
dedicated queue group if necessary, and add only explicitly configured members
without removing their other memberships. Ensure the owner also has the required
group access. Existing processes gain new supplementary groups when restarted;
new membership alone does not update running processes.

Check parent-directory traversal for the intended accounts. An existing private
`WRITE_DIR` may need an application-owned permissions change before a second
account can access it. Report that conflict rather than broadly changing parent
directories or unrelated service data.

Setgid directories provide group inheritance; the later runtime library must
also use suitable message and idempotency file modes or umasks. Directory
permissions alone do not guarantee that cooperating users can read or lock newly
written files.

Use the deployment validator's existing stable host lock. Package the generated
queue setup scripts, definitions, and required shell helpers with the release;
host setup must not depend on the developer's toolkit checkout or local registry.
Preserve application-owned deployment scripts when adding explicit setup calls.

Ship no messages, temporary payloads, FIFOs, or idempotency records in release
archives. Queue data must remain outside versioned release directories. Write
deployed environment files using the application's host environment conventions,
including modes and ownership that let the intended runtime accounts read them.

## Safe repeated execution

Reject regular files or symbolic links where managed directories are expected,
and reject anything other than a FIFO at `trigger`. Validate path components so
managed queue paths cannot escape the configured `WRITE_DIR` through symlinks or
parent traversal. Check for nested filesystem boundaries before accepting a
layout intended for atomic message moves.

Repeated setup creates missing resources and reconciles permissions on managed
directories and the FIFO. It does not recursively chmod or chown message files,
move messages, truncate acceptance records, or replace a live FIFO or lock file.

Preflight conflicts before publication. Use staging and the shared
`atomic_write` helper for definitions, environment files, and Makefile updates.
When generating content fails, preserve its original destination. Treat generated
setup scripts and Makefile changes as owned sections or explicitly generated
files; never replace unrelated service or application code.

Creation touches several files and directories, so do not promise an all-or-nothing
transaction. On partial failure, report the failed step, retain valid published
configuration and runtime state, and allow an identical request to complete the
missing work. Clean up only unpublished scaffolding owned by the failed command.
Never remove a runtime queue as rollback: a producer could already be using it.

If a feature is disabled later, preserve its existing directory and contents.
Automatic deletion, queue renaming, configuration edits, and message migration
are outside the first command's scope.

## Compatibility with current scaffolding

The existing Python support, including the `node-ml` service type, generates a
single `QUEUE_DIR` beneath `/tmp`, a Python consumer, GPU lock configuration, and
deployment launchers. Leave these files and values unchanged.

The new named queues use `<QUEUE_NAME>_QUEUE_DIR` and are independent of that
legacy runtime. Do not silently connect the old consumer to the new directory
layout or migrate its messages. Any migration or adaptation belongs to a later
explicit change.

Existing useful integration points are:

| Path | Role in this implementation |
| --- | --- |
| `src/bootstrap.bin/validate` | Bootstrap preflight and lock ownership. |
| `src/lib/bootstrap.sh` | Resolve the current registered repository. |
| `src/lib/files.sh` | Atomic configuration replacement. |
| `src/lib/locking.sh` | Reusable shell locking helper. |
| `src/bootstrap.bin/db/add` | Existing staging and explicit Makefile forwarding pattern. |
| `src/bootstrap.bin/template/deployment/` | Application-owned host setup and deployment lock integration. |

## Later runtime implementation

The agreed direction for a language-specific library is:

1. Prepare a complete message in private temporary storage on the queue's
   filesystem, then atomically publish it into `tmp/<key>`.
2. With idempotency enabled, the filename is the key. Reusing a key means the
   same immutable payload. Replacing a complete prepared tmp file is permitted
   under that contract; simultaneous in-place writes to it are not.
3. Coordinate submissions per key, then atomically publish the prepared message
   into `queue`. Different keys must not wait on a queue-wide writer lock.
4. Notify consumers through the trigger FIFO. Treat the filesystem as the source
   of queued work, so startup and reconciliation can recover missed notifications.
5. A consumer locks a message, claims it into `processing`, performs the work,
   and moves it into `complete`, `failed`, or `retry` according to the result.
6. A retry daemon returns eligible soft failures from `retry` to `queue` and
   signals the FIFO. Dead-letter detection handles abandoned work separately.

Bootstrap does not implement this protocol. The later library must settle the
acceptance-record format and the crash window between publication and recording
acceptance. The two renames do not atomically commit the separate idempotency
record. Consumer claim locking and per-key producer locking must be designed
together; do not assume unrelated locks make lifecycle lookups consistent.

Also settle safe orphan cleanup, idempotency retention, retry eligibility and
limits, in-flight recovery, and power-loss durability. Do not use a fixed timeout
or an unlocked marker alone as proof that a producer died. A stable file used
for `flock` cannot be replaced through the configuration atomic-write helper
while other processes may use it for coordination.

## Implementation steps

1. Add `src/bootstrap.bin/queue/create` with concise `##<help>` documentation,
   POSIX argument handling, repository/service validation, and repeat-safe
   definition creation.
2. Add templates under `src/bootstrap.bin/template/queue/` for configuration,
   setup, validation, Makefiles, and explicit root forwarders. Copy only the
   small reusable shell helpers needed by generated scripts.
3. Implement local directory/FIFO provisioning and per-environment
   `<QUEUE_NAME>_QUEUE_DIR` generation. Keep application storage under `WRITE_DIR`.
4. Add the application deployment integration for host paths, account/group
   access, and packaging of setup definitions. Preserve existing remote service
   behavior and the legacy Python queue scaffold.
5. Add usage documentation and focused provisioning tests. Keep runtime message
   handling and language packages out of this implementation.

## Acceptance criteria

The future implementation should be evaluated in temporary directories for:

- Two queues on one existing service, and the same queue name on two services
  with distinct `WRITE_DIR` values, producing independent paths and variables.
- Different default, user, and deployment `WRITE_DIR` values resolving correctly.
- Missing or invalid `WRITE_DIR`, invalid names, and conflicting environment
  values failing before avoidable mutations.
- The exact required directory layout, optional feature directories, and a real
  FIFO at `trigger`, with no separate idempotency lock directory.
- Actual access as configured deployment users, including parent traversal,
  group inheritance, FIFO access, and environment readability.
- Repeated creation and setup preserving messages, acceptance records, FIFO
  identity, unrelated environment files, and existing Makefile content.
- Conflicting file types, symlinks, filesystem boundaries, permission failures,
  and interrupted setup leaving a clear, recoverable result.
- Concurrent setup requests producing one consistent definition without
  deadlocking on inherited locks.
- Packaged host setup functioning without local bootstrap registration and
  excluding queue contents and development paths.
- Existing Python queue scaffolding remaining unchanged.

The verification work includes `sh -n` for shipped shell scripts and focused
behavior tests. Run it during an implementation turn when authorized under the
repository instructions; this plan does not execute it.
