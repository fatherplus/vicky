#!/bin/bash
# Deploy reports to local Nginx research directory
set -e

SRC="public/reports"
DST="/var/www/vicky/research"

echo "Deploying reports to Nginx..."

# Copy reports (flat, 兼容旧链接 research/xxx.html)
for f in "$SRC"/*.html; do
    name=$(basename "$f")
    sudo cp "$f" "$DST/$name"
    sudo chmod 644 "$DST/$name"
    echo "  ✓ $name"
done

# Also copy into reports/ subdir (目录页用 reports/xxx.html 链接，与 GitLab Pages 路径一致)
sudo mkdir -p "$DST/reports"
for f in "$SRC"/*.html; do
    name=$(basename "$f")
    sudo cp "$f" "$DST/reports/$name"
    sudo chmod 644 "$DST/reports/$name"
done
echo "  ✓ reports/ subdir synced"

# Copy index
sudo cp public/index.html "$DST/index.html"
sudo chmod 644 "$DST/index.html"
echo "  ✓ index.html"

echo "Done. Visit http://192.168.1.100:9090/research/"
