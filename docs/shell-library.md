# Shared shell helpers

Source the files from `src/lib` (installed as `~/.bin/lib`):

```sh
. "$(dirname "$0")/../lib/locking.sh"
. "$(dirname "$0")/../lib/files.sh"

file_lock "$STATE_DIR/lock"
atomic_write "$STATE_DIR/index" generate_new_index argument
```

`file_lock` takes an exclusive `flock` using descriptor 9. It survives `exec` and
releases automatically when the command and any inheriting children exit.
`file_unlock` closes the current process's descriptor when early release is needed.
Do not remove the lock file, and reserve descriptor 9 for this helper.

`atomic_write <destination> <producer> [arguments...]` runs the producer into a
private temporary file beside the destination. If the producer fails, it preserves
the original and cleans up. On success it preserves existing file permissions,
syncs the temporary file, renames it over the destination, and syncs the filesystem.
The caller must acquire a lock before reading/modifying shared state. Pass a
producer command rather than a pipeline so producer failures are detected.

These helpers use Linux `flock`, `mktemp`, and GNU coreutils.
