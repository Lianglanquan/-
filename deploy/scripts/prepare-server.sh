#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="${1:-/srv/qiuzheng}"
SHARED_ROOT="${2:-$APP_ROOT/shared}"

case "$APP_ROOT" in /srv/qiuzheng|/srv/qiuzheng/*) ;; *) echo "invalid APP_ROOT" >&2; exit 2 ;; esac
case "$SHARED_ROOT" in /srv/qiuzheng/shared|/srv/qiuzheng/shared/*) ;; *) echo "invalid SHARED_ROOT" >&2; exit 2 ;; esac

install -d -m 0755 "$APP_ROOT/releases" "$SHARED_ROOT/data/derived" "$SHARED_ROOT/logs"
chown -R ubuntu:ubuntu "$SHARED_ROOT"
if [[ ! -e "$APP_ROOT/current" && -d "$APP_ROOT/app" ]]; then
  ln -s "$APP_ROOT/app" "$APP_ROOT/current"
fi
if [[ -f "$APP_ROOT/app/data/derived/audit.sqlite3" && ! -e "$SHARED_ROOT/data/derived/audit.sqlite3" ]]; then
  cp -a "$APP_ROOT/app/data/derived/." "$SHARED_ROOT/data/derived/"
  chown -R ubuntu:ubuntu "$SHARED_ROOT/data/derived"
fi
echo "prepared $APP_ROOT with persistent data at $SHARED_ROOT/data/derived"
