#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/data
    chown -R 1000:1000 /app/data
    chmod 700 /app/data 2>/dev/null || true
    find /app/data -maxdepth 1 -type f -exec chmod 600 {} + 2>/dev/null || true
    exec setpriv --reuid=1000 --regid=1000 --init-groups "$@"
fi

exec "$@"
