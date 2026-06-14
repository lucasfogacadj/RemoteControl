#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
DEPLOY_REMOTE="${DEPLOY_REMOTE:-origin}"
DEPLOY_LOCK_FILE="${DEPLOY_LOCK_FILE:-${TMPDIR:-/tmp}/remotecontrol-deploy.lock}"
CONTROL_PORT="${CONTROL_PORT:-8090}"
DEPLOY_HEALTH_URL="${DEPLOY_HEALTH_URL:-http://127.0.0.1:${CONTROL_PORT}/health}"
DEPLOY_HEALTH_ATTEMPTS="${DEPLOY_HEALTH_ATTEMPTS:-30}"
DEPLOY_HEALTH_INTERVAL_SECONDS="${DEPLOY_HEALTH_INTERVAL_SECONDS:-2}"
DEPLOY_HEALTH_TIMEOUT_SECONDS="${DEPLOY_HEALTH_TIMEOUT_SECONDS:-5}"
DEPLOY_VERIFY_GIT_SIGNATURES="${DEPLOY_VERIFY_GIT_SIGNATURES:-0}"

log() {
  printf '[remotecontrol-deploy] %s\n' "$*"
}

verify_commit_signature() {
  local commit_sha="$1"

  if [[ "$DEPLOY_VERIFY_GIT_SIGNATURES" != "1" ]]; then
    log "Verificacao de assinatura Git desativada para esta execucao."
    return
  fi

  if git -C "$PROJECT_ROOT" verify-commit "$commit_sha" >/dev/null 2>&1; then
    return
  fi

  log "Commit $commit_sha nao possui assinatura Git valida neste servidor. Abortando deploy."
  exit 1
}

ensure_clean_worktree() {
  if [[ -n "$(git -C "$PROJECT_ROOT" status --porcelain --untracked-files=no)" ]]; then
    log "Checkout possui alteracoes locais rastreadas. Abortando para evitar sobrescrita."
    exit 1
  fi
}

update_checkout() {
  ensure_clean_worktree

  git -C "$PROJECT_ROOT" fetch "$DEPLOY_REMOTE" "$DEPLOY_BRANCH"
  local remote_sha
  remote_sha="$(git -C "$PROJECT_ROOT" rev-parse "$DEPLOY_REMOTE/$DEPLOY_BRANCH")"
  verify_commit_signature "$remote_sha"

  if git -C "$PROJECT_ROOT" show-ref --verify --quiet "refs/heads/$DEPLOY_BRANCH"; then
    local current_branch
    current_branch="$(git -C "$PROJECT_ROOT" branch --show-current || true)"
    if [[ "$current_branch" != "$DEPLOY_BRANCH" ]]; then
      git -C "$PROJECT_ROOT" checkout "$DEPLOY_BRANCH"
    fi
  else
    git -C "$PROJECT_ROOT" checkout -B "$DEPLOY_BRANCH" "$remote_sha"
  fi

  local local_sha
  local_sha="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"
  if [[ "$local_sha" != "$remote_sha" ]]; then
    log "Atualizando checkout de $local_sha para $remote_sha."
    git -C "$PROJECT_ROOT" merge --ff-only "$remote_sha"
  fi
}

compose_up() {
  log "Subindo hub com Docker Compose na porta ${CONTROL_PORT}."
  (
    cd "$PROJECT_ROOT"
    docker compose up -d --build
  )
}

wait_for_health() {
  local attempt
  for attempt in $(seq 1 "$DEPLOY_HEALTH_ATTEMPTS"); do
    if curl -fsS --max-time "$DEPLOY_HEALTH_TIMEOUT_SECONDS" "$DEPLOY_HEALTH_URL" >/dev/null; then
      log "Health check OK em $DEPLOY_HEALTH_URL."
      return
    fi
    log "Aguardando health check ($attempt/$DEPLOY_HEALTH_ATTEMPTS)."
    sleep "$DEPLOY_HEALTH_INTERVAL_SECONDS"
  done

  log "Health check falhou em $DEPLOY_HEALTH_URL."
  docker compose -f "$PROJECT_ROOT/docker-compose.yml" ps || true
  exit 1
}

main() {
  exec 9>"$DEPLOY_LOCK_FILE"
  if ! flock -n 9; then
    log "Outro deploy ja esta em execucao."
    exit 0
  fi

  update_checkout
  compose_up
  wait_for_health

  log "Deploy concluido em $(git -C "$PROJECT_ROOT" rev-parse HEAD)."
}

main "$@"

