#!/usr/bin/env bash
# Tail.Link production deployment (Ubuntu 22.04 / 腾讯云轻量)
# sudo DOMAIN=www.taillink.cloud REPO_URL=https://github.com/LeoAI1988/tail-link.git bash deploy/deploy.sh

set -Eeuo pipefail

DOMAIN="${DOMAIN:-}"
APEX_DOMAIN="${APEX_DOMAIN:-}"
PROJECT_DIR="${PROJECT_DIR:-/opt/tail-link}"
REPO_URL="${REPO_URL:-}"
ENV_FILE="/etc/tail-link.env"
STATE_DIR="/var/lib/tail-link"

if [[ -n "$DOMAIN" && -z "$APEX_DOMAIN" && "$DOMAIN" == www.* ]]; then
    APEX_DOMAIN="${DOMAIN#www.}"
fi

echo "================================================"
echo "  Tail.Link production deployment"
echo "  DOMAIN = ${DOMAIN:-HTTP only}"
echo "================================================"

echo "[1/8] Installing system dependencies..."
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip nginx git curl openssl \
    certbot python3-certbot-nginx

echo "[2/8] Updating source without deleting runtime data..."
if [[ -n "$REPO_URL" ]]; then
    if [[ -d "$PROJECT_DIR/.git" ]]; then
        if [[ -f "$PROJECT_DIR/backend/agent_match.db" ]]; then
            install -d -m 0700 /var/backups/tail-link
            cp -a "$PROJECT_DIR/backend/agent_match.db" \
                "/var/backups/tail-link/agent_match-$(date +%Y%m%d-%H%M%S).db"
        fi
        git -C "$PROJECT_DIR" pull --ff-only
    elif [[ -e "$PROJECT_DIR" ]]; then
        echo "ERROR: $PROJECT_DIR exists but is not a Git repository. Refusing to overwrite it."
        exit 1
    else
        git clone "$REPO_URL" "$PROJECT_DIR"
    fi
else
    PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi
echo "    Project directory: $PROJECT_DIR"

echo "[3/8] Preparing service account, database and secrets..."
if ! id -u tail-link >/dev/null 2>&1; then
    useradd --system --home "$STATE_DIR" --shell /usr/sbin/nologin tail-link
fi
install -d -o tail-link -g tail-link -m 0750 "$STATE_DIR"
if [[ -f "$PROJECT_DIR/backend/agent_match.db" && ! -f "$STATE_DIR/agent_match.db" ]]; then
    cp -a "$PROJECT_DIR/backend/agent_match.db" "$STATE_DIR/agent_match.db"
fi
touch "$STATE_DIR/agent_match.db"
chown tail-link:tail-link "$STATE_DIR/agent_match.db"
chmod 0600 "$STATE_DIR/agent_match.db"

if [[ ! -f "$ENV_FILE" ]]; then
    # Keep the restrictive umask scoped to the secrets file only. Leaving it
    # active would make the subsequently-created virtualenv inaccessible to
    # the unprivileged service account.
    (
        umask 077
        cat > "$ENV_FILE" <<EOF
TAIL_LINK_ENV=production
TAIL_LINK_DB_PATH=$STATE_DIR/agent_match.db
TAIL_LINK_ADMIN_TOKEN=$(openssl rand -hex 32)
TAIL_LINK_PUBLIC_URL=${DOMAIN:+https://$DOMAIN}
TAIL_LINK_CONSENT_TTL_MINUTES=60
EOF
    )
else
    chmod 0600 "$ENV_FILE"
    if [[ -n "$DOMAIN" ]]; then
        if grep -q '^TAIL_LINK_PUBLIC_URL=' "$ENV_FILE"; then
            sed -i "s#^TAIL_LINK_PUBLIC_URL=.*#TAIL_LINK_PUBLIC_URL=https://$DOMAIN#" "$ENV_FILE"
        else
            echo "TAIL_LINK_PUBLIC_URL=https://$DOMAIN" >> "$ENV_FILE"
        fi
    fi
fi

echo "[4/8] Installing Python dependencies..."
python3 -m venv "$PROJECT_DIR/backend/venv"
"$PROJECT_DIR/backend/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/backend/venv/bin/pip" install -r "$PROJECT_DIR/backend/requirements.txt"
# Repair permissions from older deployments that created the virtualenv while
# umask 077 was active. The application code contains no secrets; runtime
# secrets remain protected in $ENV_FILE and $STATE_DIR.
chmod -R a+rX "$PROJECT_DIR/backend/venv"

echo "[5/8] Configuring systemd..."
cat > /etc/systemd/system/tail-link.service <<EOF
[Unit]
Description=Tail.Link FastAPI Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tail-link
Group=tail-link
WorkingDirectory=$PROJECT_DIR/backend
EnvironmentFile=$ENV_FILE
ExecStart=$PROJECT_DIR/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=always
RestartSec=3
TimeoutStopSec=20
Environment=PYTHONUNBUFFERED=1
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=$STATE_DIR

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable tail-link
systemctl restart tail-link

echo "[6/8] Checking application health..."
for _ in {1..15}; do
    if curl -fsS http://127.0.0.1:8000/health | grep -q '"status":"ok"'; then
        echo "    FastAPI is healthy on 127.0.0.1:8000"
        break
    fi
    sleep 1
done
curl -fsS http://127.0.0.1:8000/health >/dev/null || {
    journalctl -u tail-link -n 80 --no-pager
    exit 1
}

echo "[7/8] Configuring Nginx..."
NGINX_CONF="/etc/nginx/sites-available/tail-link"
if [[ -n "$DOMAIN" ]]; then
    SERVER_NAMES="$DOMAIN"
    [[ -n "$APEX_DOMAIN" ]] && SERVER_NAMES="$SERVER_NAMES $APEX_DOMAIN"
else
    SERVER_NAMES="_"
fi
sed "s/_SERVER_NAMES_/$SERVER_NAMES/g" \
    "$PROJECT_DIR/deploy/nginx-tail-link.conf" > "$NGINX_CONF"
ln -sfn "$NGINX_CONF" /etc/nginx/sites-enabled/tail-link
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "[8/8] Configuring HTTPS..."
if [[ -n "$DOMAIN" ]]; then
    CERT_ARGS=(-d "$DOMAIN")
    [[ -n "$APEX_DOMAIN" ]] && CERT_ARGS+=(-d "$APEX_DOMAIN")
    EMAIL="${EMAIL:-admin@${APEX_DOMAIN:-$DOMAIN}}"
    certbot --nginx "${CERT_ARGS[@]}" --non-interactive --agree-tos \
        --email "$EMAIL" --redirect --keep-until-expiring
    nginx -t
    systemctl reload nginx
    curl -fsS "https://$DOMAIN/health" >/dev/null
    echo "    HTTPS health check passed: https://$DOMAIN/health"
else
    echo "    DOMAIN is empty; HTTPS was skipped."
fi

echo "================================================"
echo "  Deployment complete"
if [[ -n "$DOMAIN" ]]; then
    DEPLOY_URL="https://$DOMAIN"
else
    DEPLOY_URL="http://SERVER_IP"
fi
echo "  URL: $DEPLOY_URL"
echo "  Admin token: stored only in $ENV_FILE"
echo "  Note: Tencent Cloud firewall must allow TCP 80 and 443."
echo "================================================"
