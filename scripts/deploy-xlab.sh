#!/bin/bash
# Deploy ai-report code to xlab-test (192.168.191.121)
# 同步代码/模板/资产/指南，保留远端报告数据
set -e

HOST="xlab-test"
DST="/opt/ai-report"

echo "Deploying to $HOST:$DST ..."

rsync -avz --delete \
  --exclude='.git' \
  --exclude='taste-skill/' \
  --exclude='tests/' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='.pi-subagents/' \
  --exclude='.superpowers/' \
  --exclude='.pytest_cache/' \
  --exclude='.omo/' \
  --exclude='.pi/' \
  --exclude='docs/' \
  --exclude='ai-report/' \
  --exclude='public/reports/' \
  --exclude='public/index.html' \
  --exclude='convert_to_book.py' \
  --exclude='convert_gamekb.py' \
  --exclude='scripts/deploy.sh' \
  --exclude='scripts/deploy-xlab.sh' \
  --exclude='scripts/migrate_shared_css.py' \
  --exclude='scripts/publish_why_this_book.py' \
  --exclude='scripts/why-this-book-content.html' \
  --exclude='scripts/nginx-research.conf' \
  --exclude='scripts/nginx-xlab.conf' \
  ./ "$HOST:$DST/"

echo "Installing Nginx config..."
scp scripts/nginx-xlab.conf "$HOST:/tmp/ai-report-nginx.conf"
ssh "$HOST" "sudo cp /tmp/ai-report-nginx.conf /etc/nginx/conf.d/ai-report.conf && sudo nginx -t && sudo nginx -s reload"

echo "Restarting service..."
ssh "$HOST" "systemctl restart ai-report && sleep 1 && systemctl is-active ai-report"

echo "Done. http://192.168.191.121:9092/research/"
