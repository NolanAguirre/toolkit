#!/bin/sh
# Literal SFTP batch paths: spaces and shell punctuation are data, never code.
# Reject batch delimiters, quoting and glob syntax rather than expanding patterns.
remote_sync_path() {
    case "$1" in
        ''|*\\*|*\**|*\?*|*\[*|*\]*|*\"*|*'
'*)
            return 1
            ;;
    esac
    if printf '%s' "$1" | LC_ALL=C grep -q '[[:cntrl:]]'; then
        return 1
    fi
}

remote_sync_entry() {
    remote_sync_path "$1" || return 1
    case "$1" in
        .|..|*/*|*:*)
            return 1
            ;;
    esac
}
