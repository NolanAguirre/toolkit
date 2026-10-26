#!/bin/sh
remote_error() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

remote_token() {
    case "$1" in
        ''|[!a-zA-Z0-9]*|*[!a-zA-Z0-9._-]*)
            return 1
            ;;
    esac
}

# Connection values are data, never shell fragments or SSH options.
remote_connection_validate() {
    case "$REMOTE_TARGET" in
        ''|-*|*[!a-zA-Z0-9.:-]*)
            remote_error 'host must be an IP address or DNS hostname, without a scheme or port'
            ;;
    esac
    case "$REMOTE_USER" in
        ''|[!a-zA-Z0-9_]*|*[!a-zA-Z0-9_.-]*)
            remote_error 'SSH user must be a simple account name'
            ;;
    esac
    case "$REMOTE_PORT" in
        ''|*[!0-9]*)
            remote_error 'SSH port must be between 1 and 65535'
            ;;
    esac
    [ "${#REMOTE_PORT}" -le 5 ] && [ "$REMOTE_PORT" -ge 1 ] && [ "$REMOTE_PORT" -le 65535 ] || remote_error 'SSH port must be between 1 and 65535'
    case "$REMOTE_IDENTITY" in
        ''|/*)
            ;;
        *)
            remote_error 'identity file must be an absolute path'
            ;;
    esac
    if [ "$(printf '%s' "$REMOTE_IDENTITY" | LC_ALL=C tr -d '[:cntrl:]')" != "$REMOTE_IDENTITY" ]; then
        remote_error 'identity file path must not contain control characters'
    fi
}

# Preserve existing one-line aliases until explicitly replaced with a direct host.
remote_target_load() {
    REMOTE_TARGET=
    REMOTE_USER=
    REMOTE_PORT=
    REMOTE_IDENTITY=
    if [ "${1%/*}" = "$REMOTE_STATE/connections" ] || jq -e 'type == "object"' "$1" >/dev/null 2>&1; then
        jq -e -s 'length == 1 and (.[0] | keys - ["host", "user", "port", "identityFile"] == [] and
            (.host | type == "string") and (.user | type == "string") and
            (.port | type == "number" and . == floor and . >= 1 and . <= 65535) and
            (.identityFile == null or (.identityFile | type == "string")) and
            (to_entries | all(.value | if type == "string" then test("[\u0000-\u001f\u007f]") | not else true end)))' "$1" >/dev/null || remote_error 'invalid target JSON'
        REMOTE_TARGET=$(jq -r '.host' "$1")
        REMOTE_USER=$(jq -r '.user' "$1")
        REMOTE_PORT=$(jq -r '.port' "$1")
        REMOTE_IDENTITY=$(jq -r '.identityFile // ""' "$1")
        remote_connection_validate
    else
        REMOTE_TARGET=$(cat "$1")
        remote_token "$REMOTE_TARGET" || remote_error 'invalid target file; replace it with remote edit'
    fi
}

# Stage complete scripts on both ends before executing under the portable s6 lock.
remote_send() (
    payload=$(mktemp "$REMOTE_STATE/.ssh.XXXXXX")
    trap 'rm -f -- "$payload"' 0
    trap 'exit 1' HUP INT TERM
    cat > "$payload" <<'WRAPPER'
#!/bin/sh
set -e
[ "$(id -u)" -eq 0 ] || { echo 'error: root access through sudo -n is required' >&2; exit 1; }
PATH="/usr/local/sbin:/usr/local/bin:$PATH"
export PATH
command -v s6-setlock >/dev/null || { echo 'error: install s6 first' >&2; exit 1; }
umask 077
[ ! -L /var/run/toolkit-remote.lock ] || { echo 'error: host lock must not be a symlink' >&2; exit 1; }
remote_host_script=$(mktemp /tmp/toolkit-host.XXXXXX)
trap 'rm -f "$remote_host_script"' 0
trap 'exit 1' HUP INT TERM
cat > "$remote_host_script" <<'TOOLKIT_HOST_SCRIPT'
WRAPPER
    cat >> "$payload" <<SCRIPT
#!/bin/sh
set -e
repo='$REMOTE_REPO'
SCRIPT
    printf 'set --' >> "$payload"
    while IFS= read -r entry; do
        printf " '%s'" "$entry" >> "$payload"
    done < "$REMOTE_MANIFEST"
    printf '\n' >> "$payload"
    cat "$REMOTE_BIN/../lib/remote-host.sh" >> "$payload"
    cat "$REMOTE_BIN/.host/validate" >> "$payload"
    if [ -n "${REMOTE_ARCHIVE:-}" ]; then
        cat >> "$payload" <<'SCRIPT'
archive=$(mktemp /tmp/toolkit-release.XXXXXX)
trap 'rm -f "$archive"' 0
trap 'exit 1' HUP INT TERM
base64 -d > "$archive" <<'TOOLKIT_RELEASE_ARCHIVE'
SCRIPT
        base64 "$REMOTE_ARCHIVE" >> "$payload"
        printf 'TOOLKIT_RELEASE_ARCHIVE\n' >> "$payload"
    fi
    for step in "$@"; do
        if [ "$step" = service ]; then
            # Install the same portable atomic-write helpers used by host commands.
            printf "host_helpers=\$(cat <<'TOOLKIT_HOST_HELPERS'\n" >> "$payload"
            cat "$REMOTE_BIN/../lib/remote-host.sh" >> "$payload"
            printf '\nTOOLKIT_HOST_HELPERS\n)\n' >> "$payload"
        fi
        cat "$REMOTE_BIN/.host/$step" >> "$payload"
    done
    cat >> "$payload" <<'WRAPPER'
TOOLKIT_HOST_SCRIPT
s6-setlock -d 9 /var/run/toolkit-remote.lock env TOOLKIT_REMOTE_LOCKED=1 sh "$remote_host_script"
WRAPPER
    set -- -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10
    if [ -n "$REMOTE_USER" ]; then
        set -- "$@" -F /dev/null -l "$REMOTE_USER" -p "$REMOTE_PORT"
        if [ -n "$REMOTE_IDENTITY" ]; then
            set -- "$@" -o IdentitiesOnly=yes -i "$REMOTE_IDENTITY"
        fi
    fi
    ssh "$@" "$REMOTE_TARGET" 'sudo -n sh -s' < "$payload"
)

# Caller validates connection fields and holds the remote state lock.
remote_connection_write() {
    atomic_write "$REMOTE_CONFIG" jq -n --arg host "$REMOTE_TARGET" --arg user "$REMOTE_USER" --arg port "$REMOTE_PORT" --arg identity "$REMOTE_IDENTITY" \
        '{host: $host, user: $user, port: ($port | tonumber), identityFile: (if $identity == "" then null else $identity end)}'
}
