#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
# BITVORA EXCHANGE — VPS Setup Script
# Automates complete server setup from fresh Ubuntu 22.04 LTS.
# Idempotent — safe to run multiple times.
#
# Target: Hetzner CX32 / DigitalOcean 4GB (4 vCPU, 8GB RAM, 80GB SSD)
# Usage:  sudo bash setup.sh
# ════════════════════════════════════════════════════════════

set -euo pipefail

# ── Colors ───────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
step() { echo -e "\n${CYAN}════════════════════════════════════════${NC}"; echo -e "${CYAN}  $1${NC}"; echo -e "${CYAN}════════════════════════════════════════${NC}"; }

# ── Pre-checks ───────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    err "This script must be run as root. Use: sudo bash setup.sh"
fi

step "1/9 — System Update"
apt-get update -y && apt-get upgrade -y
apt-get install -y curl wget git unzip software-properties-common \
    apt-transport-https ca-certificates gnupg lsb-release jq
log "System packages updated"

# ── Non-root user ────────────────────────────────────────────
step "2/9 — User Setup"
USERNAME="bitvora"
if id "$USERNAME" &>/dev/null; then
    log "User '$USERNAME' already exists"
else
    useradd -m -s /bin/bash "$USERNAME"
    usermod -aG sudo "$USERNAME"
    log "User '$USERNAME' created and added to sudo group"
fi

# ── SSH Hardening ────────────────────────────────────────────
step "3/9 — SSH Hardening"
SSHD_CONFIG="/etc/ssh/sshd_config"
if ! grep -q "^PermitRootLogin no" "$SSHD_CONFIG" 2>/dev/null; then
    sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' "$SSHD_CONFIG"
    sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CONFIG"
    sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSHD_CONFIG"
    systemctl restart sshd
    log "SSH hardened: root login disabled, password auth disabled"
else
    log "SSH already hardened"
fi

# ── UFW Firewall ─────────────────────────────────────────────
step "4/9 — Firewall (UFW)"
apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
echo "y" | ufw enable
log "UFW firewall configured: 22, 80, 443 open"

# ── Docker ───────────────────────────────────────────────────
step "5/9 — Docker & Docker Compose"
if command -v docker &>/dev/null; then
    log "Docker already installed: $(docker --version)"
else
    curl -fsSL https://get.docker.com | bash
    usermod -aG docker "$USERNAME"
    systemctl enable docker
    systemctl start docker
    log "Docker installed: $(docker --version)"
fi

# Docker Compose (v2 plugin — comes with Docker)
if docker compose version &>/dev/null; then
    log "Docker Compose available: $(docker compose version --short)"
else
    apt-get install -y docker-compose-plugin
    log "Docker Compose installed"
fi

# ── cloudflared ──────────────────────────────────────────────
step "6/9 — Cloudflared"
if command -v cloudflared &>/dev/null; then
    log "cloudflared already installed: $(cloudflared --version)"
else
    curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
    dpkg -i /tmp/cloudflared.deb
    rm /tmp/cloudflared.deb
    log "cloudflared installed: $(cloudflared --version)"
fi

# ── Nginx (host-level, optional — Docker Nginx is primary) ──
step "7/9 — Nginx (host fallback)"
if command -v nginx &>/dev/null; then
    log "Nginx already installed: $(nginx -v 2>&1)"
else
    apt-get install -y nginx
    systemctl disable nginx  # Docker handles Nginx, this is just for host debugging
    log "Nginx installed (disabled — Docker Nginx is primary)"
fi

# ── Node.js (for build tools) ────────────────────────────────
step "8/9 — Node.js"
if command -v node &>/dev/null; then
    log "Node.js already installed: $(node --version)"
else
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
    log "Node.js installed: $(node --version)"
fi

# Install build tools globally
npm install -g terser cssnano-cli 2>/dev/null || true
log "Build tools installed: terser, cssnano-cli"

# ── Directories & Permissions ────────────────────────────────
step "9/9 — Directories & Permissions"
APP_DIR="/home/$USERNAME/bitvora-exchange"
WEB_DIR="/var/www/bitvoraexchange"

mkdir -p "$APP_DIR"
mkdir -p "$WEB_DIR/pages"
mkdir -p "$WEB_DIR/assets/js"
mkdir -p "$WEB_DIR/assets/css"
mkdir -p "$WEB_DIR/admin"

chown -R "$USERNAME:$USERNAME" "$APP_DIR"
chown -R "$USERNAME:$USERNAME" "$WEB_DIR"
log "Directories created and permissions set"

# ════════════════════════════════════════════════════════════
# Health Check
# ════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  BITVORA EXCHANGE — Setup Complete${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "  OS:           $(lsb_release -ds)"
echo -e "  Docker:       $(docker --version 2>/dev/null || echo 'Not found')"
echo -e "  Compose:      $(docker compose version --short 2>/dev/null || echo 'Not found')"
echo -e "  cloudflared:  $(cloudflared --version 2>/dev/null || echo 'Not found')"
echo -e "  Nginx:        $(nginx -v 2>&1 || echo 'Not found')"
echo -e "  Node.js:      $(node --version 2>/dev/null || echo 'Not found')"
echo -e "  npm:          $(npm --version 2>/dev/null || echo 'Not found')"
echo -e "  UFW:          $(ufw status | head -1)"
echo -e "  App dir:      $APP_DIR"
echo -e "  Web dir:      $WEB_DIR"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Copy project files to $APP_DIR"
echo -e "  2. Set up .env in $APP_DIR/backend/"
echo -e "  3. Set CLOUDFLARE_TUNNEL_TOKEN in .env or environment"
echo -e "  4. Run: cd $APP_DIR && docker compose up -d"
echo -e "  5. Run: make build  (to deploy frontend)"
echo ""
