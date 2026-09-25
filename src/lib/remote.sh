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
        cat "$REMOTE_BIN/.host/$step" >> "$payload"
    done
    cat >> "$payload" <<'WRAPPER'
TOOLKIT_HOST_SCRIPT
s6-setlock -d 9 /var/run/toolkit-remote.lock env TOOLKIT_REMOTE_LOCKED=1 sh "$remote_host_script"
WRAPPER
    ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 \
        "$REMOTE_TARGET" 'sudo -n sh -s' < "$payload"
)
