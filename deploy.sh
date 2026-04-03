#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# Enterprise Claw — One-Command VPS Deployment
#
# Usage:
#   ./deploy.sh              # first-time setup + deploy
#   ./deploy.sh update       # pull latest code + restart containers
#   ./deploy.sh logs         # tail all logs
#   ./deploy.sh stop         # stop containers
#
# Requirements: Docker + Docker Compose installed on the VPS.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/pk210495/Enterprise_claw.git}"
BRANCH="${BRANCH:-claude/refine-enterprise-claw-yVckN}"
APP_DIR="${APP_DIR:-/opt/enterprise_claw}"
COMPOSE="docker compose"

# ── Colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}▶ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
err()  { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

# ── Helpers ───────────────────────────────────────────────────────────────────
require_cmd() { command -v "$1" &>/dev/null || err "$1 is not installed."; }

check_env() {
    if [[ ! -f "$APP_DIR/.env" ]]; then
        warn ".env not found. Copying from .env.example …"
        cp "$APP_DIR/.env.example" "$APP_DIR/.env"
        warn "Edit $APP_DIR/.env with your API keys, then re-run: ./deploy.sh update"
        exit 0
    fi
}

ensure_security_md() {
    local sec_dir="$APP_DIR/storage/security"
    local sec_file="$sec_dir/Security.md"
    mkdir -p "$sec_dir"
    if [[ ! -f "$sec_file" ]]; then
        log "Creating default Security.md …"
        cat > "$sec_file" <<'EOF'
# Organisational Security Policy

## Principles
1. Data privacy: never exfiltrate user data outside the configured workspace.
2. No credential leakage: do not log or store API keys in plaintext.
3. Least privilege: only access files within the workspace directory.
4. Human oversight: high-risk actions require explicit human approval.
5. Audit trail: all agent actions are logged in the session history.

## Forbidden Actions
- Mass deletion of files without human approval
- External network calls outside of configured provider endpoints
- Modification of benchmark evaluation code
- Bypassing the autonomy tier gate for BLOCK-class actions
EOF
        chmod 444 "$sec_file"
        log "Security.md created and locked (read-only)"
    fi
}

# ── Subcommands ───────────────────────────────────────────────────────────────

cmd_update() {
    log "Pulling latest code from $BRANCH …"
    cd "$APP_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
    log "Rebuilding and restarting containers …"
    $COMPOSE build --pull
    $COMPOSE up -d
    log "Done. Run './deploy.sh logs' to watch output."
}

cmd_logs() {
    cd "$APP_DIR"
    $COMPOSE logs -f --tail=100
}

cmd_stop() {
    cd "$APP_DIR"
    $COMPOSE down
    log "Containers stopped."
}

cmd_install() {
    log "Installing Enterprise Claw on this VPS …"

    require_cmd docker
    require_cmd git

    # Clone or update
    if [[ -d "$APP_DIR/.git" ]]; then
        log "Repo already cloned. Pulling …"
        cd "$APP_DIR"
        git fetch origin && git checkout "$BRANCH" && git pull origin "$BRANCH"
    else
        log "Cloning repository …"
        git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
        cd "$APP_DIR"
    fi

    check_env
    ensure_security_md

    # Create SSL cert placeholder if missing (self-signed for development)
    if [[ ! -f "$APP_DIR/nginx/certs/fullchain.pem" ]]; then
        warn "No TLS certs found. Generating self-signed cert for dev use …"
        warn "For production, replace nginx/certs/ with real certs from Let's Encrypt."
        mkdir -p "$APP_DIR/nginx/certs"
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout "$APP_DIR/nginx/certs/privkey.pem" \
            -out "$APP_DIR/nginx/certs/fullchain.pem" \
            -subj "/CN=enterprise-claw" 2>/dev/null || \
            warn "openssl not available — HTTPS nginx profile disabled"
    fi

    log "Building Docker images …"
    $COMPOSE build --pull

    log "Starting services …"
    $COMPOSE up -d

    log ""
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log "  Enterprise Claw is running!"
    log ""
    log "  Agent API:        http://$(curl -s ifconfig.me):8000"
    log "  API docs:         http://$(curl -s ifconfig.me):8000/docs"
    log "  WhatsApp bridge:  http://$(curl -s ifconfig.me):8001"
    log ""
    log "  Twilio webhook URL:  https://YOUR_DOMAIN/twilio/webhook"
    log "  Meta webhook URL:    https://YOUR_DOMAIN/meta/webhook"
    log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ── Main ──────────────────────────────────────────────────────────────────────
case "${1:-install}" in
    install) cmd_install ;;
    update)  cmd_update  ;;
    logs)    cmd_logs    ;;
    stop)    cmd_stop    ;;
    *)       err "Unknown command: $1. Use: install | update | logs | stop" ;;
esac
