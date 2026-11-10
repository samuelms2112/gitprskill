#!/usr/bin/env bash
# Deploy da plataforma em um Droplet DigitalOcean com Ubuntu 24.04.
#
# Uso (como root, dentro da pasta do projeto ou com APP_DIR apontando para ela):
#   sudo bash scripts/deploy_digitalocean.sh
#
# É idempotente: pode ser executado de novo para atualizar a aplicação.
# Variáveis opcionais:
#   REPO_URL   se o projeto ainda não existir em APP_DIR, é clonado desta URL.
#   APP_DIR    pasta de instalação (padrão: /opt/github-management).
#   SWAP_SIZE  tamanho do swap (padrão: 4G).

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/github-management}"
REPO_URL="${REPO_URL:-}"
SWAP_SIZE="${SWAP_SIZE:-4G}"
COMPOSE_FILE="docker-compose.prod.yml"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31mERRO: %s\033[0m\n' "$*" >&2; exit 1; }

require_root() {
  [[ "${EUID}" -eq 0 ]] || fail "execute como root: sudo bash scripts/deploy_digitalocean.sh"
}

ensure_swap() {
  log "Swap de ${SWAP_SIZE} em /swapfile"
  if swapon --show=NAME --noheadings | grep -qx '/swapfile'; then
    echo "Swap já ativo."
    return
  fi
  if [[ -f /swapfile ]]; then
    swapoff /swapfile 2>/dev/null || true
  else
    fallocate -l "${SWAP_SIZE}" /swapfile
  fi
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  # Menos agressivo com swap: prefere a RAM e só usa o swap sob pressão real.
  sysctl -w vm.swappiness=20 >/dev/null
  grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=20' >> /etc/sysctl.conf
  echo "Swap ativo: $(swapon --show=SIZE --noheadings | head -n1)"
}

install_docker() {
  log "Docker Engine e Docker Compose V2"
  if ! command -v docker >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y ca-certificates curl git
    curl -fsSL https://get.docker.com | sh
  fi
  systemctl enable --now docker >/dev/null 2>&1 || true
  docker compose version >/dev/null 2>&1 || fail "o plugin 'docker compose' (V2) não está disponível"
  echo "$(docker --version) | $(docker compose version --short)"
}

prepare_source() {
  log "Código da aplicação em ${APP_DIR}"
  if [[ ! -d "${APP_DIR}/.git" && ! -f "${APP_DIR}/${COMPOSE_FILE}" ]]; then
    [[ -n "${REPO_URL}" ]] || fail "APP_DIR não existe e REPO_URL não foi informado"
    git clone "${REPO_URL}" "${APP_DIR}"
  elif [[ -d "${APP_DIR}/.git" ]]; then
    git -C "${APP_DIR}" pull --ff-only
  fi
  cd "${APP_DIR}"
  [[ -f "${COMPOSE_FILE}" ]] || fail "${COMPOSE_FILE} não encontrado em ${APP_DIR}"
}

check_env() {
  log "Conferindo o arquivo .env"
  [[ -f .env ]] || fail ".env não existe. Crie com: cp .env.prod.example .env  (e preencha os campos)"
  if grep -Eq '^[A-Z_]+=.*(troque|seu-dominio)' .env; then
    fail ".env ainda tem valores de exemplo (troque/seu-dominio). Corrija antes de continuar."
  fi
  for key in DOMAIN POSTGRES_PASSWORD JWT_SECRET_KEY GITHUB_OAUTH_CLIENT_ID GITHUB_OAUTH_CLIENT_SECRET \
             GITHUB_APP_ID GITHUB_APP_PRIVATE_KEY GITHUB_WEBHOOK_SECRET; do
    value="$(env_value "${key}")"
    [[ -n "${value}" ]] || fail "variável obrigatória vazia no .env: ${key}"
  done
  echo ".env OK."
}

env_value() {
  # Último valor de uma chave do .env. Ausente = vazio (não aborta: quem chama decide).
  grep -E "^$1=" .env | tail -n1 | cut -d= -f2- || true
}

start_stack() {
  log "Subindo a stack de produção (build pode levar alguns minutos)"
  docker compose -f "${COMPOSE_FILE}" up -d --build
}

wait_healthy() {
  local container="$1" attempts=60
  log "Aguardando ${container} ficar saudável"
  until [[ "$(docker inspect --format '{{.State.Health.Status}}' "${container}" 2>/dev/null)" == "healthy" ]]; do
    attempts=$((attempts - 1))
    [[ "${attempts}" -gt 0 ]] || fail "${container} não ficou saudável a tempo. Veja: docker compose -f ${COMPOSE_FILE} logs ${container}"
    sleep 5
  done
  echo "${container} saudável."
}

run_migrations() {
  log "Migrações do banco (alembic upgrade head)"
  docker compose -f "${COMPOSE_FILE}" exec -T backend alembic upgrade head
}

prepare_claude_login() {
  # Os volumes do Claude Code precisam existir antes do primeiro start; senão o Docker cria pastas no lugar dos arquivos.
  log "Pastas de login do Claude Code no host"
  mkdir -p /root/.claude
  [[ -f /root/.claude.json ]] || echo '{}' > /root/.claude.json
  chmod 700 /root/.claude
  chmod 600 /root/.claude.json
}

check_claude_login() {
  log "Sessão do Claude Code"
  if docker compose -f "${COMPOSE_FILE}" exec -T worker claude auth status >/dev/null 2>&1; then
    echo "Claude Code autenticado."
  else
    echo "AVISO: o Claude Code ainda não está logado. Faça o login no servidor:"
    echo "  docker compose -f ${COMPOSE_FILE} exec worker claude auth login"
    echo "Enquanto isso, a fila fica pausada (AUTH_REQUIRED) e nenhum PR é descartado."
  fi
}

summary() {
  local domain
  domain="$(env_value DOMAIN)"
  log "Pronto"
  echo "Aplicação:  https://${domain}"
  echo "Health:     https://${domain}/api/v1/health"
  echo "Webhook do GitHub App: https://${domain}/api/v1/webhooks/github"
  echo "Callback do OAuth:     https://${domain}/api/v1/auth/github/callback"
  echo
  echo "Logs:    docker compose -f ${COMPOSE_FILE} logs -f"
  echo "Status:  docker compose -f ${COMPOSE_FILE} ps"
}

main() {
  require_root
  ensure_swap
  install_docker
  prepare_source
  check_env
  prepare_claude_login
  start_stack
  wait_healthy "$(docker compose -f "${COMPOSE_FILE}" ps -q backend)"
  run_migrations
  check_claude_login
  summary
}

main "$@"
