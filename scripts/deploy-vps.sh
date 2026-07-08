#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "Usage: $0 root@SERVER [SSH_PORT]"
  echo "Example: $0 root@10.1.1.200 2282"
  exit 1
fi

TARGET="$1"
SSH_PORT="${2:-22}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DIR="${HOST_PROJECT_ROOT:-/opt/docker-hosting-panel}"

ssh_cmd() {
  ssh -p "$SSH_PORT" -o StrictHostKeyChecking=accept-new "$TARGET" "$@"
}

rsync_excludes=(
  --exclude ".git"
  --exclude "__pycache__"
  --exclude ".env"
  --exclude "docker-compose.override.yml"
  --exclude "data/panel.sqlite"
  --exclude "data/custom-certs"
  --exclude "data/letsencrypt"
  --exclude "data/sftp/users.conf"
  --exclude "data/sftp/ssh_host_*_key"
  --exclude "data/sftp/ssh_host_*_key.pub"
  --exclude "traefik/dynamic/site-wafs.yml"
)

dotenv_quote() {
  local value="${1-}"
  value="${value//$'\r'/}"
  if [[ "$value" == *$'\n'* ]]; then
    echo "Environment values must not contain newlines." >&2
    exit 1
  fi
  printf "'%s'" "${value//\'/\'\\\'\'}"
}

copy_project() {
  if command -v rsync >/dev/null 2>&1; then
    rsync -az --delete \
      "${rsync_excludes[@]}" \
      -e "ssh -p $SSH_PORT -o StrictHostKeyChecking=accept-new" \
      "$PROJECT_DIR/" "$TARGET:$REMOTE_DIR/"
  else
    tar -C "$PROJECT_DIR" \
      --exclude ".git" \
      --exclude "__pycache__" \
      --exclude ".env" \
      --exclude "docker-compose.override.yml" \
      --exclude "data/panel.sqlite" \
      --exclude "data/custom-certs" \
      --exclude "data/letsencrypt" \
      --exclude "data/sftp/users.conf" \
      --exclude "data/sftp/ssh_host_*_key" \
      --exclude "data/sftp/ssh_host_*_key.pub" \
      --exclude "traefik/dynamic/site-wafs.yml" \
      -czf - . | ssh_cmd "mkdir -p '$REMOTE_DIR' && tar -C '$REMOTE_DIR' -xzf -"
  fi
}

remote_prepare_host() {
  ssh_cmd "set -e
if [ \"\$(id -u)\" -ne 0 ]; then echo 'Remote user must be root.'; exit 1; fi
apt-get update
apt-get install -y ca-certificates curl gnupg rsync openssh-client
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
  fi
  . /etc/os-release
  echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \${VERSION_CODENAME} stable\" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
mkdir -p '$REMOTE_DIR'
systemctl enable --now docker || true
"
}

remote_write_env() {
  local panel_domain="${PANEL_DOMAIN:-panel.example.com}"
  local letsencrypt_email="${LETSENCRYPT_EMAIL:-admin@example.com}"
  local admin_username="${ADMIN_USERNAME:-admin}"
  local admin_password="${ADMIN_PASSWORD:-change-this-password}"
  local session_secret="${SESSION_SECRET:-$(openssl rand -hex 32 2>/dev/null || date +%s%N)}"
  local session_idle_timeout_seconds="${SESSION_IDLE_TIMEOUT_SECONDS:-1800}"
  local host_home_root="${HOST_HOME_ROOT:-/home}"
  local public_network="${PUBLIC_NETWORK:-hosting-public}"
  local fallback_host_regexp="${FALLBACK_HOST_REGEXP:-.+}"
  local sftp_port="${SFTP_PORT:-2222}"

  ssh_cmd "cat > '$REMOTE_DIR/.env' <<EOF
PANEL_DOMAIN=$(dotenv_quote "$panel_domain")
LETSENCRYPT_EMAIL=$(dotenv_quote "$letsencrypt_email")
ADMIN_USERNAME=$(dotenv_quote "$admin_username")
ADMIN_PASSWORD=$(dotenv_quote "$admin_password")
SESSION_SECRET=$(dotenv_quote "$session_secret")
SESSION_IDLE_TIMEOUT_SECONDS=$(dotenv_quote "$session_idle_timeout_seconds")
HOST_HOME_ROOT=$(dotenv_quote "$host_home_root")
HOST_PROJECT_ROOT=$(dotenv_quote "$REMOTE_DIR")
PUBLIC_NETWORK=$(dotenv_quote "$public_network")
SFTP_PORT=$(dotenv_quote "$sftp_port")
FALLBACK_HOST_REGEXP=$(dotenv_quote "$fallback_host_regexp")
EOF
chmod 600 '$REMOTE_DIR/.env'
"
}

remote_start_stack() {
  ssh_cmd "set -e
cd '$REMOTE_DIR'
mkdir -p data/sftp data/letsencrypt data/custom-certs traefik/dynamic
if [ ! -f data/sftp/users.conf ]; then
  printf 'panel-placeholder:disabled:82:82:upload\n' > data/sftp/users.conf
fi
if [ ! -f data/sftp/ssh_host_ed25519_key ]; then
  ssh-keygen -t ed25519 -N '' -f data/sftp/ssh_host_ed25519_key
fi
if [ ! -f data/sftp/ssh_host_rsa_key ]; then
  ssh-keygen -t rsa -b 4096 -N '' -f data/sftp/ssh_host_rsa_key
fi
chmod 600 data/sftp/ssh_host_*_key
if docker compose version >/dev/null 2>&1; then
  docker compose up -d --build
else
  echo 'Docker Compose v2 is not available after installation.' >&2
  exit 1
fi
"
}

remote_prepare_host
copy_project
remote_write_env
remote_start_stack

echo "Deploy selesai: $TARGET:$REMOTE_DIR"
echo "Panel domain: ${PANEL_DOMAIN:-panel.example.com}"
