#!/bin/sh
# atomic_write <destination> <producer> [args...]
# Publish producer stdout only on success. Caller must hold the relevant lock.
atomic_write() (
    [ "$#" -ge 2 ] || { echo "usage: atomic_write <destination> <producer> [args...]" >&2; exit 1; }
    _atomic_dest=$1
    shift
    umask 077
    _atomic_tmp=$(mktemp "$(dirname "$_atomic_dest")/.atomic-write.XXXXXX") || exit 1
    trap 'rm -f -- "$_atomic_tmp"' 0
    trap 'exit 1' HUP INT TERM
    "$@" > "$_atomic_tmp" || exit $?
    if [ -f "$_atomic_dest" ]; then
        chmod --reference="$_atomic_dest" "$_atomic_tmp" || exit 1
    fi
    sync -f "$_atomic_tmp" || exit 1
    mv -fT -- "$_atomic_tmp" "$_atomic_dest" || exit 1
    sync -f "$(dirname "$_atomic_dest")"
)
