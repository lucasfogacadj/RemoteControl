#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
DEPLOY_REMOTE="${DEPLOY_REMOTE:-origin}"
DEPLOY_SCRIPT="${DEPLOY_SCRIPT:-$PROJECT_ROOT/scripts/deploy.sh}"
CONTROL_PORT="${CONTROL_PORT:-8090}"
DEPLOY_HEALTH_URL="${DEPLOY_HEALTH_URL:-http://127.0.0.1:${CONTROL_PORT}/health}"
DEPLOY_HEALTH_TIMEOUT_SECONDS="${DEPLOY_HEALTH_TIMEOUT_SECONDS:-5}"
DEPLOY_REDEPLOY_IF_UNHEALTHY="${DEPLOY_REDEPLOY_IF_UNHEALTHY:-1}"
DEPLOY_VERIFY_GIT_SIGNATURES="${DEPLOY_VERIFY_GIT_SIGNATURES:-0}"

log() {
  printf '[remotecontrol-deploy-check] %s\n' "$*"
}

url_is_healthy() {
  curl -fsS --max-time "$DEPLOY_HEALTH_TIMEOUT_SECONDS" "$DEPLOY_HEALTH_URL" >/dev/null 2>&1
}

verify_commit_signature() {
  local commit_sha="$1"

  if [[ "$DEPLOY_VERIFY_GIT_SIGNATURES" != "1" ]]; then
    return
  fi

  if git -C "$PROJECT_ROOT" verify-commit "$commit_sha" >/dev/null 2>&1; then
    return
  fi

  log "Commit $commit_sha nao possui assinatura Git valida neste servidor. Abortando deploy."
  exit 1
}

main() {
  if [[ ! -f "$DEPLOY_SCRIPT" ]]; then
    log "Script de deploy nao encontrado em $DEPLOY_SCRIPT."
    exit 1
  fi

  git -C "$PROJECT_ROOT" fetch "$DEPLOY_REMOTE" "$DEPLOY_BRANCH" >/dev/null

  local current_sha remote_sha
  current_sha="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"
  remote_sha="$(git -C "$PROJECT_ROOT" rev-parse "$DEPLOY_REMOTE/$DEPLOY_BRANCH")"

  if git -C "$PROJECT_ROOT" merge-base --is-ancestor "$remote_sha" "$current_sha"; then
    if [[ "$DEPLOY_REDEPLOY_IF_UNHEALTHY" == "1" ]] && ! url_is_healthy; then
      log "Sem mudancas novas, mas health check falhou. Reexecutando deploy."
      verify_commit_signature "$remote_sha"
      exec /bin/bash "$DEPLOY_SCRIPT"
    fi

    log "Sem mudancas novas em $DEPLOY_REMOTE/$DEPLOY_BRANCH. Servico saudavel."
    exit 0
  fi

  verify_commit_signature "$remote_sha"
  log "Mudanca detectada: $current_sha -> $remote_sha. Iniciando deploy."
  exec /bin/bash "$DEPLOY_SCRIPT"
}

main "$@"

