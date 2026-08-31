#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="${APP_ROOT:-/srv/qiuzheng}"
REPOSITORY="${REPOSITORY:-$APP_ROOT/source}"
REPOSITORY_URL="${REPOSITORY_URL:-https://github.com/Lianglanquan/-.git}"
INCOMING="$APP_ROOT/incoming"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
LOCK_FILE="$APP_ROOT/.deploy-poll.lock"

exec 9>"$LOCK_FILE"
flock -n 9 || exit 0
install -d -m 0700 "$INCOMING"
if [[ ! -d "$REPOSITORY/.git" ]]; then
  install -d -m 0755 "$(dirname "$REPOSITORY")"
  git clone --quiet --depth 1 --single-branch --branch "$BRANCH" "$REPOSITORY_URL" "$REPOSITORY"
fi
git config --global --add safe.directory "$REPOSITORY" 2>/dev/null || true
git -C "$REPOSITORY" fetch --quiet "$REMOTE" "$BRANCH"
target="$(git -C "$REPOSITORY" rev-parse "$REMOTE/$BRANCH")"
active="$(readlink -f "$APP_ROOT/current" 2>/dev/null || true)"
if [[ "$active" == "$APP_ROOT/releases/$target" ]]; then
  exit 0
fi

stage="$(mktemp -d "$INCOMING/poll-$target.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
git -C "$REPOSITORY" archive --format=tar "$target" -- . ':(exclude)data/raw' ':(exclude)data/derived' > "$stage/source.tar"
mkdir -p "$stage/source"
tar -xf "$stage/source.tar" -C "$stage/source"
rm -f "$stage/source.tar"
if [[ -f "$stage/source/package.json" ]]; then
  (cd "$stage/source" && npm ci --silent && npm run build)
fi
mkdir -p "$stage/source/dist"
if [[ ! -f "$stage/source/dist/index.html" ]]; then
  echo "frontend build did not produce dist/index.html" >&2
  exit 1
fi
archive="$INCOMING/release-$target.tar.gz"
tar -C "$stage/source" --exclude='.env*' --exclude='.git' --exclude='node_modules' -czf "$archive" .
sudo APP_ROOT="$APP_ROOT" SHARED_ROOT="$APP_ROOT/shared" bash "$APP_ROOT/current/deploy/scripts/deploy-release.sh" "$archive" "$target"
echo "polled and deployed $target"
