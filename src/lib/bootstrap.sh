#!/bin/sh
. "$(dirname "$0")/../../lib/files.sh"

bootstrap_error() { echo "error: $*" >&2; exit 1; }

bootstrap_name() {
    # grep -z checks the whole argument, including any embedded newlines.
    if [ "$1" = ports ] || ! printf '%s' "$1" | grep -zq '^[A-Za-z0-9][A-Za-z0-9._-]*$'; then
        bootstrap_error 'repo names must start with a letter or digit and contain only letters, digits, dots, underscores or hyphens (ports is reserved)'
    fi
}

# Resolve the repository containing the caller's current root, never another selection.
bootstrap_repo_entry() (
    match=
    for registered in "$STATE_DIR"/repos/*/path; do
        [ -f "$registered" ] || continue
        if [ "$(cat "$registered")" = "$1" ]; then
            [ -z "$match" ] || bootstrap_error 'multiple repository registrations match this path; repair the bootstrap registry'
            match=${registered%/path}
        fi
    done
    [ -n "$match" ] || bootstrap_error 'repository is not registered; run bootstrap repo load . from the repository root first'
    printf '%s\n' "$match"
)

# Publish a complete entry before selecting it. Caller holds the bootstrap lock.
bootstrap_register() (
    name=$1
    path=$2
    entry="$STATE_DIR/repos/$name"
    if [ -d "$entry" ]; then
        if [ "$(cat "$entry/path")" != "$path" ]; then
            bootstrap_error "repo name already registered: $name"
        fi
    else
        for existing in "$STATE_DIR"/repos/*/path; do
            [ -f "$existing" ] || continue
            if [ "$(cat "$existing")" = "$path" ]; then
                bootstrap_error "path already registered: $path"
            fi
        done
        pending=$(mktemp -d "$STATE_DIR/.repo.XXXXXX")
        trap 'rm -rf -- "$pending"' 0
        trap 'exit 1' HUP INT TERM
        atomic_write "$pending/path" printf '%s\n' "$path"
        atomic_write "$pending/port_domain" printf '%s\n' "$name"
        mkdir -- "$pending/databases"
        mv -T -- "$pending" "$entry"
    fi
    mkdir -p -- "$entry/databases"
    atomic_write "$STATE_DIR/current_repo" printf '%s\n' "$name"
    printf '%s\n' "$path"
)
