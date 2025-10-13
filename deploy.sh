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

DEFAULT_COMPOSE_FILE="docker-compose.yml"
COMPOSE_FILE_ENV="${COMPOSE_FILE:-}"
if [[ -n "$COMPOSE_FILE_ENV" ]]; then
  IFS=':' read -r -a compose_files_input <<<"$COMPOSE_FILE_ENV"
else
  compose_files_input=("$DEFAULT_COMPOSE_FILE")
fi

COMPOSE_ARGS=()
for compose_file_entry in "${compose_files_input[@]}"; do
  [[ -z "$compose_file_entry" ]] && continue
  if [[ "$compose_file_entry" != /* ]]; then
    compose_file_path="$REPO_DIR/$compose_file_entry"
  else
    compose_file_path="$compose_file_entry"
  fi
  if [[ ! -f "$compose_file_path" ]]; then
    echo "❌ Brak pliku konfiguracji Docker Compose: $compose_file_path" >&2
    echo "   Upewnij się, że repozytorium w $REPO_DIR zawiera aktualny plik docker-compose.yml" >&2
    echo "   (lub ustaw zmienną COMPOSE_FILE wskazującą prawidłowe pliki)." >&2
    exit 1
  fi
  COMPOSE_ARGS+=(-f "$compose_file_path")
done

if [[ ${#COMPOSE_ARGS[@]} -eq 0 ]]; then
  echo "❌ Lista plików Docker Compose jest pusta – sprawdź zmienną COMPOSE_FILE." >&2
  exit 1
fi

compose_cmd=(docker compose "${COMPOSE_ARGS[@]}")


# jeśli podane GHCR_USER/GHCR_PAT/IMAGE i brak logowania – zaloguj jak w content_manager
if [[ -n "${GHCR_USER:-}" && -n "${GHCR_PAT:-}" && -n "${IMAGE:-}" ]]; then
  if ! docker pull "$IMAGE" >/dev/null 2>&1; then
    echo "🔐 Logowanie do ghcr.io…" >&2
    echo "$GHCR_PAT" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
  fi
fi
echo "🚀 Deploy: aktualizacja kontenerów" >&2

if [[ -n "${IMAGE:-}" ]]; then
  "${compose_cmd[@]}" pull
else
  "${compose_cmd[@]}" pull --ignore-pull-failures
fi

up_args=(-d)
if [[ -n "${IMAGE:-}" && "${FORCE_BUILD:-0}" != "1" ]]; then
  up_args=(--no-build "${up_args[@]}")
else
  up_args=(--build "${up_args[@]}")
fi

"${compose_cmd[@]}" up "${up_args[@]}"

echo "🔄 Migracje Alembic" >&2
"${compose_cmd[@]}" run --rm app alembic upgrade head

echo "🧹 Czyszczenie nieużywanych obrazów" >&2
docker image prune -f >/dev/null

echo "✅ Deploy zakończony powodzeniem" >&2
