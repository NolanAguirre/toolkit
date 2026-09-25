# Checking command help

Run `python3 tests/bootstrap.py` for isolated repository import checks, including
existing named and legacy reservations, conflicts, concurrent imports, and adding
a service afterward. The test uses disposable installed commands and state, with
npm stubbed so it does not install packages.

```sh
toolkit test bootstrap
toolkit test port
toolkit test encrypt
toolkit test --all
```

The command builds disposable installed commands from the configured source,
parses `toolkit ls`, and invokes each selected command with `--help`. Every
command must exit successfully and emit a `Usage: ` line. Template directories
are excluded from the listing. Unknown tool names fail rather than passing with
zero checks.

`--all` discovers tool names from `toolkit ls` and uses `xargs -P 4` to run one
test invocation per tool, with up to four running concurrently. Output may
interleave; each check includes its tool and command name. Any failed invocation
makes the overall command fail.

Each run gets a private directory under `$UTIL_PATH/toolkit/tests/` with its own
`HOME`, `UTIL_PATH`, install directory, temporary directory and working directory.
The runner deletes its run directory on exit and returns a nonzero status if a
check fails. Concurrent runs do not move live state or replace active lock files.

The runner is entirely shell-based and has no Python dependency. It checks help
only, not state-changing behavior. This is filesystem isolation for cooperating
commands, not an OS security sandbox.

Run `python3 tests/bootstrap-ui.py` for isolated Vite scaffold checks using the
real dispatcher and port allocator: plain/library output, invalid inputs,
existing paths, missing libraries and domains, cleanup, and concurrent creation.
It requires npm but does not install packages or alter a real component library.

Run `python3 tests/remote.py` for remote setup/status checks. SSH and privileged
host tools are mocked; generated POSIX shell runs against temporary paths. The
suite verifies local registrations, prerequisites, per-service/all setup, ports,
repeat setup, data preservation, failures and concurrent independent clients. No
real remote host is contacted. See [remote.md](remote.md) for host requirements.

Run `python3 tests/remote-sync.py` for directory-copy profiles and real SFTP
push/pull behavior over local pipes. It requires OpenSSH `sftp` and
`/usr/lib/openssh/sftp-server` (the `openssh-sftp-server` package); set `SFTP_SERVER`
to use an executable extracted elsewhere. No SSH daemon or network connection is
used. Checks cover overwrite/merge behavior, Unity metadata, hidden files, empty
directories, a second client's state, literal path handling, selection validation,
local links/special files, transfer/atomic-write failure and concurrent local
transfers. Windows drive paths are redirected to a temporary directory by the test
transport; an actual Windows OpenSSH host is not exercised.
