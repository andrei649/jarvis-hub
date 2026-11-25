#!/bin/sh
# deploy/docker/entrypoint.sh — start Nerva in a container as an unprivileged user (H573).
#
# The image creates a `nerva` user (uid/gid 1000). This entrypoint starts as root only
# long enough to:
#
#   1. remap `nerva` to the host user that should own the files — NERVA_UID / NERVA_GID,
#      or PUID / PGID (the spelling NAS images use) — so files written to a bind mount
#      land owned by that user rather than by root;
#   2. hand the data root (NERVA_HOME or JARVIS_HOME, /data by default) and /app/logs to
#      that user when they are not already its own;
#   3. drop every privilege with setpriv (uid, gid, supplementary groups, inheritable and
#      bounding capabilities; no new privileges), check that the process is no longer
#      root, and exec the command, so the hub is never root.
#
# Started with `--user` (already not root), it changes nothing and execs the command.
# Ids must be whole numbers from 1 to 2147483647: 0 is root, and 4294967295 is
# (uid_t)-1, which setpriv would leave as root. A data root of /, /app or a parent of
# /app is refused (the remap would hand the image's code to the hub's user).
set -eu

target_uid="${NERVA_UID:-${PUID:-1000}}"
target_gid="${NERVA_GID:-${PGID:-1000}}"
data_root="${NERVA_HOME:-${JARVIS_HOME:-/data}}"

if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

# Digits only, no leading zero, at most 10 digits — checked as text before any
# arithmetic, so no value can overflow the shell's integers.
valid_id() {
    case "$1" in ''|*[!0-9]*|0*) return 1 ;; esac
    [ "${#1}" -le 10 ] || return 1
    [ "${#1}" -lt 10 ] && return 0
    # Ten digits: compare as text against the largest allowed value.
    [ "$(printf '%s\n%s\n' "$1" 2147483647 | LC_ALL=C sort | tail -n 1)" = 2147483647 ]
}
if ! valid_id "$target_uid" || ! valid_id "$target_gid"; then
    echo "nerva-entrypoint: NERVA_UID/PUID and NERVA_GID/PGID must be whole numbers from 1 to 2147483647 (not root)" >&2
    exit 64
fi

case "$data_root" in
    /*) ;;
    *) echo "nerva-entrypoint: the data root must be an absolute path" >&2; exit 64 ;;
esac
trimmed="$(printf '%s' "$data_root" | sed 's#/*$##')"
case "$trimmed" in
    ''|/app|*/..|*/../*|*/.|*/./*)
        echo "nerva-entrypoint: refusing data root $data_root (/, /app, a parent of /app or a dotted path)" >&2
        exit 64 ;;
esac

if [ "$(id -g nerva)" != "$target_gid" ]; then
    groupmod -o -g "$target_gid" nerva
fi
if [ "$(id -u nerva)" != "$target_uid" ]; then
    usermod -o -u "$target_uid" -g "$target_gid" nerva
fi

for dir in "$trimmed" /app/logs; do
    mkdir -p "$dir"
    # Only walk the tree when its top is not already the target's: a large data root
    # is not re-owned on every start, and a symlink is never followed (-h, no -L).
    if [ "$(stat -c '%u:%g' "$dir")" != "$target_uid:$target_gid" ]; then
        chown -hR "$target_uid:$target_gid" "$dir"
    fi
done

exec setpriv --reuid="$target_uid" --regid="$target_gid" --init-groups \
    --inh-caps=-all --bounding-set=-all --no-new-privs -- \
    sh -c 'if [ "$(id -u)" = 0 ] || [ "$(id -g)" = 0 ]; then echo "nerva-entrypoint: still root after the drop; refusing to start" >&2; exit 70; fi; exec "$@"' \
    nerva-entrypoint "$@"
