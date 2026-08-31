#!/usr/bin/env bash
set -Eeuo pipefail

ARCHIVE="${1:?archive path required}"
COMMIT="${2:?commit sha required}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="${APP_ROOT:-/srv/qiuzheng}"
SHARED_ROOT="${SHARED_ROOT:-$APP_ROOT/shared}"
RELEASES="$APP_ROOT/releases"
CURRENT="$APP_ROOT/current"
RELEASE="$RELEASES/$COMMIT"
STAGING="$RELEASES/.staging-$COMMIT-$$"
PREVIOUS=""

[[ "$COMMIT" =~ ^[0-9a-f]{7,64}$ ]] || { echo "invalid commit sha" >&2; exit 2; }
[[ -f "$ARCHIVE" ]] || { echo "archive not found" >&2; exit 2; }
case "$APP_ROOT" in /srv/qiuzheng|/srv/qiuzheng/*) ;; *) echo "invalid APP_ROOT" >&2; exit 2 ;; esac

if tar --list --file "$ARCHIVE" | grep -Eq '(^/|(^|/)\.\.(\/|$))'; then
  echo "archive contains unsafe paths" >&2
  exit 2
fi

"$SCRIPT_DIR/prepare-server.sh" "$APP_ROOT" "$SHARED_ROOT"
if [[ -L "$CURRENT" ]]; then PREVIOUS="$(readlink -f "$CURRENT")"; fi
if [[ "$PREVIOUS" == "$RELEASE" ]]; then
  curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8000/ready >/dev/null
  rm -f "$ARCHIVE"
  echo "already deployed $COMMIT"
  exit 0
fi
trap 'rm -rf "$STAGING"' EXIT
rm -rf "$STAGING"
install -d -m 0755 "$STAGING/data"
tar --extract --file "$ARCHIVE" --directory "$STAGING" --no-same-owner --no-same-permissions
test -f "$STAGING/backend/app/main.py"
test -f "$STAGING/dist/index.html"
ln -sfn "$SHARED_ROOT/data/derived" "$STAGING/data/derived"
chown -R root:root "$STAGING"

if [[ ! -x /srv/qiuzheng/venv/bin/python ]]; then
  python3 -m venv /srv/qiuzheng/venv
fi
/srv/qiuzheng/venv/bin/pip install --disable-pip-version-check --quiet -r "$STAGING/backend/requirements.txt"
QIUZHENG_DATA_ROOT="$SHARED_ROOT/data/derived" /srv/qiuzheng/venv/bin/python -m compileall -q "$STAGING/backend/app"

if [[ -e "$RELEASE" || -L "$RELEASE" ]]; then rm -rf "$RELEASE"; fi
mv -T "$STAGING" "$RELEASE"
ln -sfn "$RELEASE" "$APP_ROOT/current.next"
mv -Tf "$APP_ROOT/current.next" "$CURRENT"
systemctl daemon-reload
systemctl restart qiuzheng.service
for _ in {1..30}; do
  if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8000/ready >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8000/ready >/dev/null || {
  if [[ -n "$PREVIOUS" && -d "$PREVIOUS" ]]; then
    ln -sfn "$PREVIOUS" "$APP_ROOT/current.next"
    mv -Tf "$APP_ROOT/current.next" "$CURRENT"
    systemctl restart qiuzheng.service
  fi
  echo "release health check failed; previous release restored" >&2
  exit 1
}

find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort -r | tail -n +6 | while read -r old; do
  [[ "$RELEASES/$old" == "$PREVIOUS" || "$RELEASES/$old" == "$(readlink -f "$CURRENT")" ]] || rm -rf "$RELEASES/$old"
done
rm -f "$ARCHIVE"
echo "deployed $COMMIT"
