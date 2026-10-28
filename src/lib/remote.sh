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
    _remote_json=0
    case "$1" in
        "$REMOTE_STATE"/connections/*)
            _remote_json=1
            ;;
    esac
    if [ "$_remote_json" = 1 ] || jq -e 'type == "object"' "$1" >/dev/null 2>&1; then
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

# Legacy connections/<repo>.json and targets/<repo> are target default until connections/<repo>/ exists.
remote_target_path() {
    _remote_directory="$REMOTE_STATE/connections/$REMOTE_REPO"
    if [ ! -d "$_remote_directory" ] && [ "$1" = default ]; then
        if [ -f "$_remote_directory.json" ]; then
            printf '%s\n' "$_remote_directory.json"
            return
        fi
        if [ -f "$REMOTE_STATE/targets/$REMOTE_REPO" ]; then
            printf '%s\n' "$REMOTE_STATE/targets/$REMOTE_REPO"
            return
        fi
    fi
    printf '%s\n' "$_remote_directory/$1.json"
}

remote_target_names() {
    _remote_directory="$REMOTE_STATE/connections/$REMOTE_REPO"
    if [ -d "$_remote_directory" ]; then
        for _remote_file in "$_remote_directory"/*.json; do
            [ -f "$_remote_file" ] || continue
            _remote_name=${_remote_file##*/}
            printf '%s\n' "${_remote_name%.json}"
        done
    elif [ -f "$_remote_directory.json" ] || [ -f "$REMOTE_STATE/targets/$REMOTE_REPO" ]; then
        printf 'default\n'
    fi
}

# remote_targets_select [a,b]: write "name<TAB>path" lines to $REMOTE_TARGETS; every target must load.
remote_targets_select() {
    if [ -n "$1" ]; then
        _remote_names=$(printf '%s\n' "$1" | tr ',' '\n')
    else
        _remote_names=$(remote_target_names)
    fi
    [ -n "$_remote_names" ] || remote_error 'target missing; use remote create <repo> <host-or-connection> [--name target]'
    printf '%s\n' "$_remote_names" | awk '{ if (seen[$0]++) exit 1 }' || remote_error 'duplicate target name'
    : > "$REMOTE_TARGETS"
    printf '%s\n' "$_remote_names" | while IFS= read -r _remote_name; do
        remote_token "$_remote_name" || remote_error "invalid target name: $_remote_name"
        _remote_path=$(remote_target_path "$_remote_name")
        [ -f "$_remote_path" ] || remote_error "unknown target: $_remote_name"
        (remote_target_load "$_remote_path") || exit 1
        printf '%s\t%s\n' "$_remote_name" "$_remote_path" >> "$REMOTE_TARGETS"
    done || exit 1
}

# Build one complete script for every target; staged on the host before executing under the portable s6 lock.
remote_payload() {
    cat <<'WRAPPER'
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
    cat <<SCRIPT
#!/bin/sh
set -e
repo='$REMOTE_REPO'
SCRIPT
    printf 'set --'
    while IFS= read -r entry; do
        printf " '%s'" "$entry"
    done < "$REMOTE_MANIFEST"
    printf '\n'
    cat "$REMOTE_BIN/../lib/remote-host.sh"
    cat "$REMOTE_BIN/.host/validate"
    if [ -n "${REMOTE_ARCHIVE:-}" ]; then
        cat <<'SCRIPT'
archive=$(mktemp /tmp/toolkit-release.XXXXXX)
trap 'rm -f "$archive"' 0
trap 'exit 1' HUP INT TERM
base64 -d > "$archive" <<'TOOLKIT_RELEASE_ARCHIVE'
SCRIPT
        base64 "$REMOTE_ARCHIVE"
        printf 'TOOLKIT_RELEASE_ARCHIVE\n'
    fi
    for step in "$@"; do
        if [ "$step" = service ]; then
            # Install the same portable atomic-write helpers used by host commands.
            printf "host_helpers=\$(cat <<'TOOLKIT_HOST_HELPERS'\n"
            cat "$REMOTE_BIN/../lib/remote-host.sh"
            printf '\nTOOLKIT_HOST_HELPERS\n)\n'
        fi
        cat "$REMOTE_BIN/.host/$step"
    done
    cat <<'WRAPPER'
TOOLKIT_HOST_SCRIPT
s6-setlock -d 9 /var/run/toolkit-remote.lock env TOOLKIT_REMOTE_LOCKED=1 sh "$remote_host_script"
WRAPPER
}

# remote_ssh <payload>: run a built payload on the loaded target.
remote_ssh() (
    payload=$1
    set -- -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10
    if [ -n "$REMOTE_USER" ]; then
        set -- "$@" -F /dev/null -l "$REMOTE_USER" -p "$REMOTE_PORT"
        if [ -n "$REMOTE_IDENTITY" ]; then
            set -- "$@" -o IdentitiesOnly=yes -i "$REMOTE_IDENTITY"
        fi
    fi
    ssh "$@" "$REMOTE_TARGET" 'sudo -n sh -s' < "$payload"
)

# remote_each step...: run the steps on every $REMOTE_TARGETS line in parallel, prefixing output by target.
remote_each() (
    work=$(mktemp -d "$REMOTE_STATE/.each.XXXXXX")
    trap 'rm -rf -- "$work"' 0
    trap 'exit 1' HUP INT TERM
    remote_payload "$@" > "$work/payload"
    tab=$(printf '\t')
    while IFS="$tab" read -r name path; do
        (
            {
                {
                    status=0
                    (remote_target_load "$path" && remote_ssh "$work/payload") || status=$?
                    printf '%s\n' "$status" > "$work/$name.status"
                } 2>&1 1>&3 3>&- | sed "s/^/$name$tab/" >&2
            } 3>&1 | sed "s/^/$name$tab/"
        ) &
    done < "$REMOTE_TARGETS"
    wait
    failed=0
    while IFS="$tab" read -r name path; do
        if [ "$(cat "$work/$name.status" 2>/dev/null)" = 0 ]; then
            printf 'ok %s\n' "$name" >&2
        else
            printf 'failed %s\n' "$name" >&2
            failed=1
        fi
    done < "$REMOTE_TARGETS"
    exit "$failed"
)

remote_connection_json() {
    jq -n --arg host "$REMOTE_TARGET" --arg user "$REMOTE_USER" --arg port "$REMOTE_PORT" --arg identity "$REMOTE_IDENTITY" \
        '{host: $host, user: $user, port: ($port | tonumber), identityFile: (if $identity == "" then null else $identity end)}'
}

# Caller validates connection fields and holds the remote state lock.
# With $REMOTE_TARGET_NAME, write the repo target after moving any legacy file to connections/<repo>/default.json.
remote_connection_write() {
    if [ -z "${REMOTE_TARGET_NAME:-}" ]; then
        atomic_write "$REMOTE_CONFIG" remote_connection_json
        return
    fi
    _remote_directory="$REMOTE_STATE/connections/$REMOTE_REPO"
    _remote_alias="$REMOTE_STATE/targets/$REMOTE_REPO"
    if [ ! -d "$_remote_directory" ]; then
        if [ -f "$_remote_directory.json" ]; then
            mkdir -- "$_remote_directory"
            mv -- "$_remote_directory.json" "$_remote_directory/default.json"
            rm -f -- "$_remote_alias"
        elif [ -f "$_remote_alias" ]; then
            # Aliases are not JSON, so only replacing target default migrates them.
            [ "$REMOTE_TARGET_NAME" = default ] || remote_error 'legacy alias target; replace it first with remote edit <repo> <host-or-connection>'
            mkdir -- "$_remote_directory"
            if ! atomic_write "$_remote_directory/default.json" remote_connection_json; then
                rmdir -- "$_remote_directory"
                return 1
            fi
            rm -- "$_remote_alias"
            return
        else
            mkdir -- "$_remote_directory"
        fi
    fi
    atomic_write "$_remote_directory/$REMOTE_TARGET_NAME.json" remote_connection_json
}
