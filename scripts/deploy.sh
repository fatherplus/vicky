#!/bin/bash
# Install ai-report Nginx config (alias 直读 public/，不再 cp 报告)
# 架构变更后：Nginx alias → ai-report/public/，server.py 只做 API
set -e

CONF_SRC="scripts/nginx-research.conf"
CONF_DST="/var/www/vicky/ai-report-nginx.conf"

echo "Installing Nginx config..."
sudo cp "$CONF_SRC" "$CONF_DST"
echo "  ✓ $CONF_DST"

echo "Reloading Nginx..."
sudo nginx -t && sudo nginx -s reload
echo "Done. Visit http://192.168.1.100:9090/research/"
