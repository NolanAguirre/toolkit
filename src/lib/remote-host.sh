#!/bin/sh
# Shared helpers sent to the host before its validation and command scripts.
fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

service_names() {
    service=${1%:*}
    port=${1##*:}
    unit="$repo-$service"
    case "$unit" in
        [!a-z_]*|*[!a-z0-9_-]*)
            fail 'remote repo and service names must form a lowercase Unix account name'
            ;;
    esac
    [ "${#unit}" -le 27 ] || fail 'repo-service must be at most 27 characters (including the hyphen)'
    base="/var/service-dir/$unit"
    runtime=$unit
    owner="${unit}owner"
    logger="${unit}log"
    # Changing names must not silently start another instance beside an old service.
    for legacy in /var/service-dir/"$repo--$service--"*; do
        if [ -e "$legacy" ] || [ -L "$legacy" ]; then
            fail "migrate the legacy service directory before setup: $legacy"
        fi
    done
}

file_owner() {
    case "$(uname -s)" in
        Linux) stat -c %U "$1" ;;
        FreeBSD) stat -f %Su "$1" ;;
    esac
}

file_group() {
    case "$(uname -s)" in
        Linux) stat -c %G "$1" ;;
        FreeBSD) stat -f %Sg "$1" ;;
    esac
}

file_mode() {
    case "$(uname -s)" in
        Linux) stat -c %a "$1" ;;
        FreeBSD) stat -f %Lp "$1" ;;
    esac
}

atomic_move() {
    case "$(uname -s)" in
        Linux) mv -fT "$1" "$2" ;;
        FreeBSD) mv -fh "$1" "$2" ;;
    esac
}

require_directory() {
    [ -d "$1" ] && [ ! -L "$1" ] || fail "missing real directory: $1; run remote setup directories"
    [ "$(file_owner "$1")" = "$2" ] || fail "unexpected owner of $1 (expected $2)"
    [ "$(file_group "$1")" = "$(id -gn "$2")" ] || fail "unexpected group of $1"
    [ "$(file_mode "$1")" = "$3" ] || fail "unexpected permissions on $1 (expected $3)"
}

make_directory() {
    if [ -e "$1" ] || [ -L "$1" ]; then
        require_directory "$1" "$2" "$3"
    else
        mkdir -p "$1"
        chown "$2:$(id -gn "$2")" "$1"
        chmod "$3" "$1"
    fi
}

require_user() {
    account=$(getent passwd "$1") || fail "missing user $1; run remote setup users"
    IFS=: read -r account_name account_pass account_uid account_gid \
        account_comment account_home account_shell <<PASSWD
$account
PASSWD
    [ "$account_comment" = "toolkit/$repo/$service/$2" ] || fail "conflicting user $1"
    [ "$account_home" = "$3" ] || fail "conflicting user $1"
    case "$account_shell" in
        /usr/sbin/nologin|/sbin/nologin)
            ;;
        *)
            fail "user $1 must have a nologin shell"
            ;;
    esac
    [ "$(id -gn "$1")" = "$1" ] || fail "user $1 needs its own primary group"
}

create_user() {
    if getent passwd "$1" >/dev/null; then
        require_user "$@"
        return
    fi
    nologin=/usr/sbin/nologin
    [ -x "$nologin" ] || nologin=/sbin/nologin
    [ -x "$nologin" ] || fail 'nologin is required'
    if getent group "$1" >/dev/null; then
        fail "group $1 already exists without the service user"
    fi
    case "$(uname -s)" in
        Linux)
            command -v useradd >/dev/null || fail 'install shadow useradd first'
            useradd --system --user-group --no-create-home --home-dir "$3" \
                --shell "$nologin" --comment "toolkit/$repo/$service/$2" "$1"
            ;;
        FreeBSD)
            pw groupadd -n "$1"
            pw useradd -n "$1" -g "$1" -d "$3" -s "$nologin" -w no \
                -c "toolkit/$repo/$service/$2"
            ;;
    esac
}

require_users() {
    require_user "$runtime" runtime "$base/data"
    require_user "$owner" owner "$base/server"
    require_user "$logger" log "$base/log/main"
}

require_layout() {
    require_directory /var/service-dir root 755
    require_directory /var/service root 755
    require_directory "$base" root 755
    require_directory "$base/env" root 755
    require_directory "$base/etc" root 755
    require_directory "$base/bin" root 755
    require_directory "$base/server" "$owner" 755
    require_directory "$base/data" "$runtime" 700
    require_directory "$base/log" root 755
    require_directory "$base/log/main" "$logger" 755
}

require_file_target() {
    [ ! -L "$1" ] || fail "refusing symlink: $1"
    if [ -e "$1" ]; then
        [ -f "$1" ] && [ "$(file_owner "$1")" = root ] || fail "expected root-owned file: $1"
    fi
}

# atomic_to <destination> <owner:group> <mode> <producer> [args...]
atomic_to() (
    destination=$1
    ownership=$2
    mode=$3
    shift 3
    require_file_target "$destination"
    temporary=$(mktemp "$(dirname "$destination")/.atomic-write.XXXXXX") || exit 1
    trap 'rm -f "$temporary"' 0
    trap 'exit 1' HUP INT TERM
    "$@" > "$temporary" || exit $?
    chown "$ownership" "$temporary" || exit 1
    chmod "$mode" "$temporary" || exit 1
    sync || exit 1
    atomic_move "$temporary" "$destination" || exit 1
)

# Emit the root-owned, service-local deployment command, like the reference setup.
service_deploy_script() {
    printf '#!/bin/sh\nset -e\nservice_dir=%s\nservice_owner=%s\n' "$base" "$owner"
    cat <<'DEPLOY'
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
if [ "${1:-}" = -- ]; then
    [ "$(id -un)" = "$service_owner" ] || fail 'release extraction must run as the service owner'
    umask 022
    server="$service_dir/server"
    [ ! -e "$server/current" ] || [ -L "$server/current" ] || fail 'current must be a symlink'
    release=$(mktemp -d "$server/server-$(date -u +%Y%m%d%H%M%S)-XXXXXX")
    chmod 755 "$release"
    tar xzf - -C "$release"
    [ -x "$release/run" ] || fail "release needs an executable run: $release"
    # Optional application preparation runs as the deployment owner before activation.
    if [ -x "$service_dir/bin/deploy-prepare" ]; then
        (cd "$release" && "$service_dir/bin/deploy-prepare")
    fi
    next=$(mktemp -d "$server/.current.XXXXXX")
    trap 'rm -rf "$next"' 0
    trap 'exit 1' HUP INT TERM
    ln -s "${release##*/}" "$next/current"
    case "$(uname -s)" in
        Linux) mv -fT "$next/current" "$server/current" ;;
        FreeBSD) mv -fh "$next/current" "$server/current" ;;
    esac
    # Keep four releases, always retaining the active release even after a clock change.
    retained=1
    ls -1dt "$server"/server-* | while IFS= read -r previous; do
        [ "$previous" != "$release" ] || continue
        [ -d "$previous" ] && [ ! -L "$previous" ] || continue
        retained=$((retained + 1))
        if [ "$retained" -gt 4 ]; then
            rm -rf "$previous"
        fi
    done
    printf '%s\n' "$release"
    exit 0
fi
[ "$#" -eq 1 ] || fail "usage: $0 tarball"
[ "$(id -u)" -eq 0 ] || fail 'run the deployment command as root'
if [ "${TOOLKIT_REMOTE_LOCKED:-}" != 1 ]; then
    [ ! -L /var/run/toolkit-remote.lock ] || fail 'host lock must not be a symlink'
    exec s6-setlock -d 9 /var/run/toolkit-remote.lock env TOOLKIT_REMOTE_LOCKED=1 "$0" "$@"
fi
[ -f "$1" ] || fail 'tarball must be a regular file'
s6-svok "$service_dir" || fail 'service must be registered with s6 before deployment'
# The root shell opens the private upload before privileges are dropped.
s6-setuidgid "$service_owner" "$0" -- < "$1"
s6-svc -t "$service_dir"
DEPLOY
}
