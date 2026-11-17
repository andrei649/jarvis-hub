#!/bin/sh
# deploy/docker/entrypoint.sh — start Nerva in a container as an unprivileged user (H573).
#
# The image creates a `nerva` user (uid/gid 1000). This entrypoint starts as root only
# long enough to:
#
#   1. remap `nerva` to the host user that should own the files — NERVA_UID / NERVA_GID,
#      or PUID / PGID (the spelling NAS images use) — so files written to a bind mount
#      land owned by that user rather than by root;
#   2. hand the data root (JARVIS_HOME, /data by default) and /app/logs to that user
#      when they are not already its own;
#   3. drop every privilege with setpriv (uid, gid, supplementary groups; no new
#      privileges) and exec the command, so the hub is never root.
#
# Started with `--user` (already not root), it changes nothing and execs the command.
# uid/gid 0 is refused: a remap to root would undo the point of the remap.
set -eu

target_uid="${NERVA_UID:-${PUID:-1000}}"
target_gid="${NERVA_GID:-${PGID:-1000}}"
data_root="${JARVIS_HOME:-/data}"

if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

case "$target_uid" in ''|*[!0-9]*) echo "nerva-entrypoint: NERVA_UID/PUID must be a number" >&2; exit 64 ;; esac
case "$target_gid" in ''|*[!0-9]*) echo "nerva-entrypoint: NERVA_GID/PGID must be a number" >&2; exit 64 ;; esac
if [ "$target_uid" -eq 0 ] || [ "$target_gid" -eq 0 ]; then
    echo "nerva-entrypoint: refusing to run the hub as root (uid/gid 0); pick the host user's ids" >&2
    exit 64
fi

if [ "$(id -g nerva)" != "$target_gid" ]; then
    groupmod -o -g "$target_gid" nerva
fi
if [ "$(id -u nerva)" != "$target_uid" ]; then
    usermod -o -u "$target_uid" -g "$target_gid" nerva
fi

for dir in "$data_root" /app/logs; do
    mkdir -p "$dir"
    # Only walk the tree when its top is not already the target's: a large data root
    # is not re-owned on every start, and a symlink is never followed (-h, no -L).
    if [ "$(stat -c '%u:%g' "$dir")" != "$target_uid:$target_gid" ]; then
        chown -hR "$target_uid:$target_gid" "$dir"
    fi
done

exec setpriv --reuid="$target_uid" --regid="$target_gid" --init-groups --no-new-privs -- "$@"
