#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$SCRIPT_DIR}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env}"

# wczytaj zmienne z .env (jeśli istnieje) – tak jak w content_manager
set -a
[[ -f "$ENV_FILE" ]] && . "$ENV_FILE"
set +a

cd "$REPO_DIR"


# jeśli podane GHCR_USER/GHCR_PAT/IMAGE i brak logowania – zaloguj jak w content_manager
if [[ -n "${GHCR_USER:-}" && -n "${GHCR_PAT:-}" && -n "${IMAGE:-}" ]]; then
  if ! docker pull "$IMAGE" >/dev/null 2>&1; then
    echo "🔐 Logowanie do ghcr.io…" >&2
    echo "$GHCR_PAT" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
  fi
fi
echo "🚀 Deploy: aktualizacja kontenerów" >&2

docker compose pull

docker compose up -d --build

echo "🔄 Migracje Alembic" >&2
docker compose run --rm app alembic upgrade head

echo "🧹 Czyszczenie nieużywanych obrazów" >&2
docker image prune -f >/dev/null

echo "✅ Deploy zakończony powodzeniem" >&2
