#!/bin/sh
# Small helpers shared by port allocation commands. validate holds the lock.
. "$(dirname "$0")/../../lib/files.sh"
PORT_ROOT="$STATE_DIR/allocate"
PORT_INDEX="$PORT_ROOT/ports"

port_error() { printf 'error: %s\n' "$*" >&2; exit 1; }

port_domain() {
    # grep -z checks the whole argument, including any embedded newlines.
    if [ "$1" = ports ] || ! printf '%s' "$1" | grep -zq '^[A-Za-z0-9][A-Za-z0-9._-]*$'; then
        port_error "invalid domain: $1"
    fi
}

port_number() {
    if ! printf '%s' "$1" | grep -zq '^[0-9][0-9]*$'; then
        port_error "expected a port or count from 1 to 65535"
    fi
    # Normalize leading zeroes without shell octal arithmetic or integer overflow.
    awk -v n="$1" 'BEGIN { if (n+0 < 1 || n+0 > 65535) exit 1; printf "%.0f\n", n }' ||
        port_error "expected a port or count from 1 to 65535"
}

port_require_domain() {
    port_domain "$1"
    if [ ! -f "$PORT_ROOT/$1/.domain.json" ]; then
        port_error "unknown domain: $1; create it first"
    fi
}

port_record() {
    jq -c --argjson port "$1" 'select(.port == $port)' "$PORT_INDEX"
}

# The index owns identity. Ignore metadata left behind by an interrupted rename.
port_metadata() (
    record=$1
    domain=$(printf '%s\n' "$record" | jq -r '.domain')
    port=$(printf '%s\n' "$record" | jq -r '.port')
    metadata="$PORT_ROOT/$domain/$port"
    if [ -f "$metadata" ]; then
        jq -c --argjson record "$record" \
            'if .name == $record.name then . else $record end' "$metadata"
    else
        printf '%s\n' "$record"
    fi
)

# Save current metadata, appending a new reservation before publishing its file.
# Arguments: record JSON, new (0/1), message supplied (0/1), message.
port_save() (
    record=$1
    domain=$(printf '%s\n' "$record" | jq -r '.domain')
    port=$(printf '%s\n' "$record" | jq -r '.port')
    metadata="$PORT_ROOT/$domain/$port"
    if [ "$2" = 0 ] && [ -f "$metadata" ]; then
        record=$(port_metadata "$record")
    fi
    if [ "$3" = 1 ]; then
        record=$(printf '%s\n' "$record" | jq -c --arg message "$4" '.message = $message')
    fi
    if [ "$2" = 1 ]; then
        printf '%s\n' "$record" >> "$PORT_INDEX"
        sync -f "$PORT_INDEX"
    fi
    if [ "$2" = 1 ] || [ "$3" = 1 ] || [ ! -f "$metadata" ]; then
        atomic_write "$metadata" printf '%s\n' "$record"
    fi
    printf '%s\n' "$port"
)
