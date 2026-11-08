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

# Stable process identity, including its start time, prevents stale PID-only matches.
process_identity() {
    LC_ALL=C ps -o lstart= -p "$1" | sed 's/^[[:space:]]*//'
}

release_value() {
    awk -F '\t' -v key="$2" '$1 == key { print $2 }' "$1"
}

# Prepare only the dedicated write directory, never recursively take over existing data.
prepare_write_directory() (
    write_dir=$1
    runtime=$2
    case "$write_dir" in
        ''|/|*/|*//*|*/./*|*/../*|*/.|*/..)
            fail 'WRITE_DIR must be an absolute directory without dot components or trailing slashes'
            ;;
        /*)
            ;;
        *)
            fail 'WRITE_DIR must be an absolute directory'
            ;;
    esac
    [ "$(printf '%s' "$write_dir" | LC_ALL=C tr -d '[:cntrl:]')" = "$write_dir" ] || fail 'WRITE_DIR contains control characters'
    parent=$write_dir
    while [ "$parent" != / ]; do
        [ ! -L "$parent" ] || fail "WRITE_DIR must not traverse a symlink: $parent"
        parent=${parent%/*}
        [ -n "$parent" ] || parent=/
    done
    if [ -e "$write_dir" ]; then
        [ -d "$write_dir" ] || fail "WRITE_DIR is not a directory: $write_dir"
    else
        mkdir -p "$write_dir"
    fi
    chown "$runtime:$(id -gn "$runtime")" "$write_dir"
    chmod 700 "$write_dir"
    s6-setuidgid "$runtime" sh -c '[ -r "$1" ] && [ -w "$1" ] && [ -x "$1" ]' sh "$write_dir" ||
        fail "$runtime needs read, write and traversal access to WRITE_DIR and traversal access to its parents: $write_dir"
)

service_run_script() {
    printf '#!/bin/sh\n# toolkit-release-run-v1\nset -e\nservice_dir=%s\nruntime=%s\n' "$base" "$runtime"
    cat <<'RUN'
exec 2>&1
. "$service_dir/bin/toolkit-host.sh"
root_group=$(id -gn root)
release=$(CDPATH= cd "$service_dir/server/current" && pwd -P)
case "$release" in
    "$service_dir"/server/server-*)
        ;;
    *)
        fail 'current points outside the release directory'
        ;;
esac
metadata="$service_dir/releases/${release##*/}"
require_file_target "$metadata"
require_file_target "$service_dir/running-release"
identity=$(process_identity "$$")
[ -n "$identity" ] || fail 'cannot read process start identity'
# s6 is the sole writer of this record; it does not start a second run concurrently.
# Use a pinned release path: activation may change current while this process starts.
record=$(mktemp "$service_dir/.running.XXXXXX")
trap 'rm -f "$record"' 0
trap 'exit 1' HUP INT TERM
if [ -f "$metadata" ]; then
    cat "$metadata" > "$record"
else
    printf 'release\t%s\ncommit\tunknown\narchive_sha256\tunknown\n' "${release##*/}" > "$record"
fi
printf 'pid\t%s\nprocess_start\t%s\n' "$$" "$identity" >> "$record"
atomic_to "$service_dir/running-release" "root:$root_group" 644 cat "$record"
rm -f "$record"
trap - 0 HUP INT TERM
RUN
    # Emit the previous runner exactly when checking whether an upgrade is safe.
    if [ "${1:-}" != legacy ]; then
        cat <<'RUN'
# toolkit-production-env-v1
environment="$service_dir/releases/${release##*/}.env"
if [ -d "$environment" ]; then
    # Load checkout values only after dropping privileges, including PATH and loader settings.
    exec s6-envdir "$service_dir/env" s6-setuidgid "$runtime" s6-envdir "$environment" "$release/run"
fi
RUN
    fi
    cat <<'RUN'
exec s6-envdir "$service_dir/env" s6-setuidgid "$runtime" "$release/run"
RUN
}

# Emit the root-owned, service-local deployment command.
service_deploy_script() {
    printf '#!/bin/sh\n# toolkit-release-metadata-v1\n# toolkit-production-env-v1\nset -e\nservice_dir=%s\nservice_owner=%s\nruntime=%s\n' "$base" "$owner" "$runtime"
    cat <<'DEPLOY'
. "$service_dir/bin/toolkit-host.sh"
case "${1:-}" in
    --)
        [ "$(id -un)" = "$service_owner" ] || fail 'release extraction must run as the service owner'
        umask 022
        release=$(mktemp -d "$service_dir/server/server-$(date -u +%Y%m%d%H%M%S)-XXXXXX")
        chmod 755 "$release"
        tar xzf - -C "$release"
        [ -x "$release/run" ] || fail "release needs an executable run: $release"
        if [ -x "$service_dir/bin/deploy-prepare" ]; then
            (cd "$release" && "$service_dir/bin/deploy-prepare") >&2
        fi
        printf '%s\n' "$release"
        exit 0
        ;;
    --activate)
        [ "$(id -un)" = "$service_owner" ] || fail 'activation must run as the service owner'
        release=$2
        server="$service_dir/server"
        case "$release" in
            "$server"/server-*)
                ;;
            *)
                fail 'invalid release path'
                ;;
        esac
        [ ! -e "$server/current" ] || [ -L "$server/current" ] || fail 'current must be a symlink'
        next=$(mktemp -d "$server/.current.XXXXXX")
        trap 'rm -rf "$next"' 0
        trap 'exit 1' HUP INT TERM
        ln -s "${release##*/}" "$next/current"
        atomic_move "$next/current" "$server/current"
        # Retain four releases plus a still-running older release during slow restarts.
        running=
        if [ -f "$service_dir/running-release" ]; then
            running=$(release_value "$service_dir/running-release" release)
        fi
        retained=1
        ls -1dt "$server"/server-* | while IFS= read -r previous; do
            [ "$previous" != "$release" ] || continue
            [ "${previous##*/}" != "$running" ] || continue
            [ -d "$previous" ] && [ ! -L "$previous" ] || continue
            retained=$((retained + 1))
            if [ "$retained" -gt 4 ]; then
                rm -rf "$previous"
            fi
        done
        exit 0
        ;;
esac
[ "$#" -ge 1 ] && [ "$#" -le 3 ] || fail "usage: $0 tarball [metadata [env-directory]]"
[ "$(id -u)" -eq 0 ] || fail 'run the deployment command as root'
if [ "${TOOLKIT_REMOTE_LOCKED:-}" != 1 ]; then
    [ ! -L /var/run/toolkit-remote.lock ] || fail 'host lock must not be a symlink'
    exec s6-setlock -d 9 /var/run/toolkit-remote.lock env TOOLKIT_REMOTE_LOCKED=1 "$0" "$@"
fi
[ -f "$1" ] && [ ! -L "$1" ] || fail 'tarball must be a regular file'
s6-svok "$service_dir" || fail 'service must be registered with s6 before deployment'
case "$(uname -s)" in
    Linux)
        archive_hash=$(sha256sum "$1")
        archive_hash=${archive_hash%% *}
        ;;
    FreeBSD)
        archive_hash=$(sha256 -q "$1")
        ;;
esac
commit=unknown
commit_source=unknown
dirty=unknown
if [ "$#" -ge 2 ]; then
    [ -f "$2" ] && [ ! -L "$2" ] || fail 'metadata must be a regular file'
    [ "$(wc -l < "$2" | tr -d ' ')" = 4 ] || fail 'invalid release metadata'
    commit=$(release_value "$2" commit)
    commit_source=$(release_value "$2" commit_source)
    dirty=$(release_value "$2" dirty)
    expected_hash=$(release_value "$2" archive_sha256)
    [ "$expected_hash" = "$archive_hash" ] || fail 'archive SHA-256 mismatch'
    if [ "$commit" != unknown ]; then
        case "$commit" in
            ''|*[!0-9a-f]*)
                fail 'invalid commit hash'
                ;;
        esac
        [ "${#commit}" -eq 40 ] || [ "${#commit}" -eq 64 ] || fail 'invalid commit hash'
    fi
    case "$commit_source" in
        artifact|checkout-at-deploy|unknown)
            ;;
        *)
            fail 'invalid commit source'
            ;;
    esac
    case "$dirty" in
        true|false|unknown)
            ;;
        *)
            fail 'invalid dirty flag'
            ;;
    esac
fi
root_group=$(id -gn root)
require_directory "$service_dir/releases" root 755
require_file_target "$service_dir/release"
# The root shell opens the private upload before privileges are dropped.
release=$(s6-setuidgid "$service_owner" "$0" -- < "$1")
case "$release" in
    "$service_dir"/server/server-*)
        ;;
    *)
        fail 'invalid extracted release path'
        ;;
esac
metadata="$service_dir/releases/${release##*/}"
environment="$metadata.env"
mkdir -m 700 "$environment"
chown "root:$(id -gn "$runtime")" "$environment"
if [ "$#" -eq 3 ]; then
    [ -d "$3" ] && [ ! -L "$3" ] || fail 'environment must be a real directory'
    for file in "$3"/* "$3"/.[!.]* "$3"/..?*; do
        [ -e "$file" ] || [ -L "$file" ] || continue
        key=${file##*/}
        case "$key" in
            ''|[!a-zA-Z_]*|*[!a-zA-Z0-9_]*)
                fail "invalid environment key: $key"
                ;;
        esac
        [ -f "$file" ] && [ ! -L "$file" ] || fail "expected a regular environment file: $file"
        atomic_to "$environment/$key" "root:$(id -gn "$runtime")" 640 cat "$file"
    done
fi
write_dir='#default'
if [ -f "$environment/WRITE_DIR" ]; then
    # Match envdir's first-line and trailing-whitespace rules when preparing the path.
    write_dir=$(sed -n '1{s/[[:blank:]]*$//;p;}' "$environment/WRITE_DIR")
fi
case "$write_dir" in
    '#default')
        write_dir="$service_dir/data"
        prepare_write_directory "$write_dir" "$runtime"
        atomic_to "$environment/WRITE_DIR" "root:$(id -gn "$runtime")" 640 printf '%s\n' "$write_dir"
        ;;
    *)
        prepare_write_directory "$write_dir" "$runtime"
        ;;
esac
chmod 750 "$environment"
atomic_to "$metadata" "root:$root_group" 644 printf 'release\t%s\ncommit\t%s\ncommit_source\t%s\ndirty\t%s\narchive_sha256\t%s\ndeployed_at\t%s\n' \
    "${release##*/}" "$commit" "$commit_source" "$dirty" "$archive_hash" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
s6-setuidgid "$service_owner" "$0" --activate "$release"
atomic_to "$service_dir/release" "root:$root_group" 644 cat "$metadata"
# Environment snapshots follow the same release retention policy as code.
for previous_env in "$service_dir/releases"/server-*.env; do
    [ -d "$previous_env" ] && [ ! -L "$previous_env" ] || continue
    previous=${previous_env##*/}
    if [ ! -d "$service_dir/server/${previous%.env}" ]; then
        rm -rf "$previous_env"
    fi
done
s6-svc -t "$service_dir"
printf '%s\n' "$release"
DEPLOY
}

# start_scanner: find s6 and reuse a running /var/service scanner, or start one through systemd / FreeBSD rc.d.
start_scanner() {
    scanner=$(command -v s6-svscan) || fail 'install s6 first'
    scannerctl=$(command -v s6-svscanctl) || fail 'install s6 first'
    case "$scanner:$scannerctl" in
        *[!a-zA-Z0-9/:._-]*) fail 'unsupported s6 executable path' ;;
    esac
    case "$scanner" in
        /*) ;;
        *) fail 's6-svscan must resolve to an absolute path' ;;
    esac
    case "$scannerctl" in
        /*) ;;
        *) fail 's6-svscanctl must resolve to an absolute path' ;;
    esac
    # Other host services may already share this scanner. Never replace a running scanner.
    if ! "$scannerctl" -a /var/service 2>/dev/null; then
        case "$(uname -s)" in
            Linux)
                [ -d /run/systemd/system ] || fail 'start s6-svscan /var/service through the host startup first'
                command -v systemctl >/dev/null || fail 'systemctl is required to start the s6 scanner on this host'
                unit_file=/etc/systemd/system/toolkit-remote-svscan.service
                require_directory /etc/systemd/system root 755
                require_file_target "$unit_file"
                unit_content=$(cat <<UNIT
[Unit]
Description=Toolkit s6 scanner
After=local-fs.target

[Service]
Type=simple
ExecStart=$scanner /var/service
ExecStop=$scannerctl -t /var/service
Restart=on-failure
KillMode=mixed
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNIT
)
                if [ -f "$unit_file" ]; then
                    [ "$(cat "$unit_file")" = "$unit_content" ] || fail "conflicting scanner launcher: $unit_file"
                else
                    fragment=$(systemctl show --property=FragmentPath --value toolkit-remote-svscan.service)
                    [ -z "$fragment" ] || fail "scanner launcher already provided by $fragment"
                fi
                dropins=$(systemctl show --property=DropInPaths --value toolkit-remote-svscan.service)
                [ -z "$dropins" ] || fail "conflicting scanner drop-ins: $dropins"
                atomic_to "$unit_file" "root:$root_group" 644 printf '%s\n' "$unit_content"
                systemctl daemon-reload
                systemctl enable --now toolkit-remote-svscan.service 9>&-
                ;;
            FreeBSD)
                [ -x /usr/local/etc/rc.d/s6 ] || fail 'install the FreeBSD sysutils/s6 package first'
                configured_scan=$(sysrc -n s6_path 2>/dev/null || :)
                [ -z "$configured_scan" ] || [ "$configured_scan" = /var/service ] || fail "s6_path already points to $configured_scan"
                sysrc s6_enable=YES s6_path=/var/service
                if ! service s6 onestatus >/dev/null 2>&1; then
                    env -u TOOLKIT_REMOTE_LOCKED service s6 start 9>&-
                fi
                ;;
        esac
        attempt=0
        until "$scannerctl" -a /var/service 2>/dev/null; do
            [ "$attempt" -lt 10 ] || fail 's6 scanner did not become ready within 10 seconds'
            sleep 1
            attempt=$((attempt + 1))
        done
    fi
}
