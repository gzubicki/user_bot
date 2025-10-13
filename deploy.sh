#!/usr/bin/env bash
set -euo pipefail

REPO_PATH="/opt/user_bot"

cd "$REPO_PATH"

echo "[deploy] Fetching production branch"
git fetch origin production
git pull --ff-only origin production

echo "[deploy] Pulling latest images"
docker compose pull

echo "[deploy] Rebuilding and restarting"
docker compose up -d --build

echo "[deploy] Removing unused images"
docker image prune -f

echo "[deploy] Done"
