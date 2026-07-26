#!/bin/bash
# Deploy reports to local Nginx research directory
# canonical: reports/{file} 为唯一正式链接（平铺由 nginx-research.conf 301）
set -e

SRC="public/reports"
ASSETS="public/assets"
DST="/var/www/vicky/research"

echo "Deploying reports to Nginx (canonical: reports/)..."

sudo mkdir -p "$DST/reports" "$DST/assets"

# 报告直传 reports/（不再平铺复制）
for f in "$SRC"/*.html; do
    name=$(basename "$f")
    sudo cp "$f" "$DST/reports/$name"
    sudo chmod 644 "$DST/reports/$name"
    echo "  ✓ reports/$name"
done

# 资产同步（book-style.css / index.css / components/）
sudo cp -r "$ASSETS/." "$DST/assets/"
echo "  ✓ assets/ synced"

# 索引
sudo cp public/index.html "$DST/index.html"
sudo chmod 644 "$DST/index.html"
echo "  ✓ index.html"

# Nginx 配置片段（供运维 include；首次部署人工接入站点 conf）
sudo cp scripts/nginx-research.conf "$DST/../ai-report-nginx.conf" 2>/dev/null || \
    echo "  ! nginx-research.conf 复制跳过（目标目录不可写），人工安装：scripts/nginx-research.conf"

echo "Done. Visit http://192.168.1.100:9090/research/"
