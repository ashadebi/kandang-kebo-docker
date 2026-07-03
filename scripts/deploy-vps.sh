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

copy_project() {
  if command -v rsync >/dev/null 2>&1; then
    rsync -az --delete \
      --exclude ".git" \
      --exclude "__pycache__" \
      --exclude ".env" \
      --exclude "data/panel.sqlite" \
      --exclude "data/custom-certs" \
      --exclude "data/letsencrypt" \
      --exclude "data/sftp/ssh_host_*_key" \
      -e "ssh -p $SSH_PORT -o StrictHostKeyChecking=accept-new" \
      "$PROJECT_DIR/" "$TARGET:$REMOTE_DIR/"
  else
    tar -C "$PROJECT_DIR" \
      --exclude ".git" \
      --exclude "__pycache__" \
      --exclude ".env" \
      --exclude "data/panel.sqlite" \
      --exclude "data/custom-certs" \
      --exclude "data/letsencrypt" \
      --exclude "data/sftp/ssh_host_*_key" \
      -czf - . | ssh_cmd "mkdir -p '$REMOTE_DIR' && tar -C '$REMOTE_DIR' -xzf -"
  fi
}

remote_prepare_host() {
  ssh_cmd "set -e
if [ \"\$(id -u)\" -ne 0 ]; then echo 'Remote user must be root.'; exit 1; fi
apt-get update
apt-get install -y ca-certificates curl gnupg rsync openssh-client
if ! command -v docker >/dev/null 2>&1; then
  apt-get install -y docker.io docker-compose
else
  apt-get install -y docker-compose || true
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
  local host_home_root="${HOST_HOME_ROOT:-/home}"
  local public_network="${PUBLIC_NETWORK:-hosting-public}"
  local fallback_host_regexp="${FALLBACK_HOST_REGEXP:-.+}"

  ssh_cmd "cat > '$REMOTE_DIR/.env' <<EOF
PANEL_DOMAIN=$panel_domain
LETSENCRYPT_EMAIL=$letsencrypt_email
ADMIN_USERNAME=$admin_username
ADMIN_PASSWORD=$admin_password
SESSION_SECRET=$session_secret
HOST_HOME_ROOT=$host_home_root
HOST_PROJECT_ROOT=$REMOTE_DIR
PUBLIC_NETWORK=$public_network
SFTP_PORT=2222
FALLBACK_HOST_REGEXP=$fallback_host_regexp
EOF
chmod 600 '$REMOTE_DIR/.env'
"
}

remote_start_stack() {
  ssh_cmd "set -e
cd '$REMOTE_DIR'
mkdir -p data/sftp data/letsencrypt
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
  docker-compose up -d --build
fi
"
}

remote_prepare_host
copy_project
remote_write_env
remote_start_stack

echo "Deploy selesai: $TARGET:$REMOTE_DIR"
echo "Panel domain: ${PANEL_DOMAIN:-panel.example.com}"
