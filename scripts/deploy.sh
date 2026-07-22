#!/bin/bash
# Deploy reports to local Nginx research directory
set -e

SRC="public/reports"
DST="/var/www/vicky/research"

echo "Deploying reports to Nginx..."

# Copy reports
for f in "$SRC"/*.html; do
    name=$(basename "$f")
    sudo cp "$f" "$DST/$name"
    sudo chmod 644 "$DST/$name"
    echo "  ✓ $name"
done

# Copy index
sudo cp public/index.html "$DST/index.html"
sudo chmod 644 "$DST/index.html"
echo "  ✓ index.html"

echo "Done. Visit http://192.168.1.100:9090/research/"