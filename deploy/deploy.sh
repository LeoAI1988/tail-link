#!/usr/bin/env bash
# Tail.Link 一键部署脚本 (Ubuntu 22.04 / 腾讯云轻量服务器)
# 用法: 在服务器上 git clone 仓库后, cd 到项目根目录, 执行:
#   sudo DOMAIN=你的域名 bash deploy/deploy.sh
# 若暂时没有域名, 执行: sudo bash deploy/deploy.sh (仅 HTTP, 跳过 HTTPS)

set -e

DOMAIN="${DOMAIN:-}"
PROJECT_DIR="/opt/tail-link"
REPO_URL="${REPO_URL:-}"   # 可选: 直接从 GitHub clone

echo "================================================"
echo "  Tail.Link 部署脚本  (腾讯云轻量 Ubuntu 22.04)"
echo "  DOMAIN = ${DOMAIN:-（未设置, 仅 HTTP）}"
echo "================================================"

# 1. 安装系统依赖
echo "[1/7] 安装系统依赖..."
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx git curl

# 2. 拉取/更新代码
if [ -n "$REPO_URL" ]; then
    echo "[2/7] 从 GitHub 克隆代码..."
    rm -rf "$PROJECT_DIR"
    git clone "$REPO_URL" "$PROJECT_DIR"
else
    echo "[2/7] 使用当前目录作为项目代码..."
    PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi
cd "$PROJECT_DIR"
echo "    项目目录: $PROJECT_DIR"

# 3. 创建 venv 并安装依赖
echo "[3/7] 创建 Python 虚拟环境并安装依赖..."
python3 -m venv "$PROJECT_DIR/backend/venv"
"$PROJECT_DIR/backend/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/backend/venv/bin/pip" install -r "$PROJECT_DIR/backend/requirements.txt"

# 4. 配置 systemd 服务
echo "[4/7] 配置 systemd 服务..."
# 修正 service 文件里的 venv 路径（Ubuntu venv 在 bin/）
cat > /etc/systemd/system/tail-link.service <<EOF
[Unit]
Description=Tail.Link FastAPI Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR/backend
ExecStart=$PROJECT_DIR/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable tail-link
systemctl restart tail-link
sleep 2

# 5. 健康检查
echo "[5/7] 服务健康检查..."
if curl -s http://127.0.0.1:8000/health | grep -q "ok"; then
    echo "    ✅ FastAPI 服务已启动 (127.0.0.1:8000)"
else
    echo "    ❌ 服务启动失败, 查看日志: journalctl -u tail-link -n 50"
    exit 1
fi

# 6. 配置 Nginx
echo "[6/7] 配置 Nginx..."
NGINX_CONF="/etc/nginx/sites-available/tail-link"
if [ -n "$DOMAIN" ]; then
    sed "s/_SERVER_NAME_/$DOMAIN/g" "$PROJECT_DIR/deploy/nginx-tail-link.conf" > "$NGINX_CONF"
else
    # 无域名: 仅 HTTP 反代
    cat > "$NGINX_CONF" <<EOF
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 10m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
fi
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/tail-link
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx
echo "    ✅ Nginx 已配置"

# 7. HTTPS (仅当提供域名)
if [ -n "$DOMAIN" ]; then
    echo "[7/7] 申请 Let's Encrypt HTTPS 证书..."
    apt-get install -y certbot python3-certbot-nginx
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "${EMAIL:-admin@$DOMAIN}" --redirect || \
        echo "    ⚠️  HTTPS 申请失败, 可稍后手动运行: certbot --nginx -d $DOMAIN"
    echo "    ✅ HTTPS 已配置"
else
    echo "[7/7] 跳过 HTTPS (未提供域名)"
fi

echo ""
echo "================================================"
echo "  ✅ 部署完成!"
if [ -n "$DOMAIN" ]; then
    echo "  访问地址: https://$DOMAIN"
else
    PUBLIC_IP=$(curl -s http://metadata.tencentyun.com/latest/meta-data/public-ipv4 2>/dev/null || curl -s ifconfig.me)
    echo "  访问地址: http://$PUBLIC_IP"
fi
echo "  服务状态: systemctl status tail-link"
echo "  查看日志: journalctl -u tail-link -f"
echo "================================================"
