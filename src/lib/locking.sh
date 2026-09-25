#!/bin/sh
# file_lock <path>: hold one exclusive lock on descriptor 9, including through
# exec. The kernel releases it when all inheriting processes exit. Never unlink
# the lock file: replacing it would allow processes to lock different inodes.
file_lock() {
    [ "$#" -eq 1 ] || { echo "usage: file_lock <path>" >&2; return 1; }
    exec 9>>"$1"
    flock -x 9
}

file_unlock() {
    exec 9>&-
}
