#!/bin/bash
# Deploy ai-report to 个人环境 (deploy-host / 192.168.1.100)
# P4：同步 ai_report/ 包 + views/ + templates/ + public/assets/ + skill/（+ 过渡 shim），
#     安装纯反代 Nginx 配置 + 新版 systemd 服务（-m ai_report.web）
# 运行位置：本机开发机即可（ssh deploy-host）；在 deploy-host 上运行亦可（rsync 自连，无害）。
# 注意：ssh 非交互执行 sudo 需要 hgf 已配置 NOPASSWD（原脚本在本机交互 sudo 的前提一致）。
set -e

HOST="deploy-host"
DST="/home/deploy/ai-report"

echo "Deploying to $HOST:$DST ..."

# 同步清单 = 代码包 + 模板 + 平台资产 + 写作规范（spec §10）
# 显式清单而非 ./ 全量同步：
#   - 不用 --delete——显式清单下 --delete 会按目录比对清空远端未列目录
#     （public/reports/、data/、knowledge/、.git 等），违背"保留远端数据"原则；
#     代价是远端被删过的本地文件会残留，可接受。
#   - data/ 排除——保护远端 sqlite DB + L0 快照（同 public/reports/ 待遇）。
#   - 过渡期 shim（server.py/distill.py/html_to_md.py）一并同步：远端旧 ExecStart
#     （python3 server.py）经 shim 委托 ai_report 包，两条入口都能跑，切换平滑；
#     P4 收尾删除 shim 后，从清单去掉这三项即可。
#   - views/ 属 P3 产物可能暂不存在——先过滤已存在的项，容忍缺目录（rsync 遇缺失源会报错）。
MANIFEST="ai_report views templates public/assets skill server.py distill.py html_to_md.py"
SRCS=""
for s in $MANIFEST; do
    [ -e "$s" ] && SRCS="$SRCS $s"
done
[ -n "$SRCS" ] || { echo "! 同步清单为空，退出"; exit 1; }

rsync -avz \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='data/' \
  $SRCS "$HOST:$DST/"

# 顺序：先起 app 再切 Nginx——旧 alias 继续伺服静态直到 app 在 9091 验证起来，
# 切换纯反代零停机窗口；set -e 下 app 起不来则 Nginx 保持旧配置（不切代理）。
echo "Installing systemd service (python3 -m ai_report.web)..."
scp scripts/ai-report.service "$HOST:/tmp/ai-report.service"
ssh "$HOST" "sudo cp /tmp/ai-report.service /etc/systemd/system/ai-report.service && sudo systemctl daemon-reload && sudo systemctl restart ai-report && sleep 1 && systemctl is-active ai-report"

echo "Installing Nginx config (纯反代)..."
scp scripts/nginx-research.conf "$HOST:/tmp/ai-report-nginx.conf"
ssh "$HOST" "sudo cp /tmp/ai-report-nginx.conf /var/www/vicky/ai-report-nginx.conf && sudo nginx -t && sudo nginx -s reload"

echo "Done. http://192.168.1.100:9090/research/"
