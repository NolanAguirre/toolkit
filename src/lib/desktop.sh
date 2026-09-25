#!/bin/sh
# Shared validation, quoting and GNOME placement for the desktop commands.
desktop_error() {
    echo "error: $*" >&2
    exit 1
}
desktop_name() {
    case "$1" in
        ''|[!a-zA-Z0-9]*|*[!a-zA-Z0-9._-]*)
            desktop_error "invalid name: $1"
            ;;
    esac
}
desktop_number() {
    case "$1" in
        ''|0*|*[!0-9]*)
            desktop_error 'workspace number must be a positive integer without leading zeros'
            ;;
    esac
    [ "${#1}" -le 3 ] || desktop_error 'workspace number must be between 1 and 999'
}
desktop_workspace() {
    desktop_name "$1"
    WORKSPACE_DIR="$STATE_DIR/workspaces/$1"
    [ -f "$WORKSPACE_DIR/config" ] || desktop_error "unknown workspace: $1"
}
desktop_kind() {
    case "$1" in
        tab|cursor|brave|background)
            ;;
        window:*)
            [ -n "${1#window:}" ] || desktop_error 'window: requires an application class'
            ;;
        *)
            desktop_error 'kind must be tab, cursor, brave, background, or window:<application-class>'
            ;;
    esac
}
# Produce a single POSIX-shell word, including embedded quotes and newlines.
desktop_quote() {
    printf "'"
    printf '%s' "$1" | sed "s/'/'\\\\''/g"
    printf "'"
}
desktop_bus() {
    _desktop_method=$1
    shift
    gdbus call --session --dest org.gnome.Shell \
        --object-path /local/nolan/DesktopBootstrap \
        --method "local.nolan.DesktopBootstrap.$_desktop_method" "$@"
}
desktop_place() {
    _desktop_kind=$1
    _desktop_workspace=$2
    shift 2
    desktop_bus Arm "$_desktop_kind" "$_desktop_workspace" >/dev/null
    "$@" 9>&- >> "$DESKTOP_RUN/launch.log" 2>&1 &
    _desktop_attempt=0
    while [ "$_desktop_attempt" -lt 50 ]; do
        _desktop_status=$(desktop_bus Status) || return 1
        case "$_desktop_status" in
            *placed*)
                desktop_bus Cancel >/dev/null
                return 0
                ;;
            *waiting*)
                ;;
            *)
                desktop_bus Cancel >/dev/null
                desktop_error "window placement failed: $_desktop_status; see $DESKTOP_RUN/launch.log"
                ;;
        esac
        sleep 1
        _desktop_attempt=$((_desktop_attempt + 1))
    done
    desktop_bus Cancel >/dev/null
    desktop_error "window placement timed out; see $DESKTOP_RUN/launch.log"
}
