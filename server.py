#!/usr/bin/env python3
"""
AI Report Service — 轻量 HTTP API
=================================
接受 agent 提交的 HTML 内容，用统一模板渲染，保存并部署。

启动: python3 server.py [--port 9091]
API:
  POST /api/reports  — 创建报告
  GET  /api/reports  — 列出所有报告
  GET  /api/health   — 健康检查
"""

import json
import os
import re
import sys
import shutil
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ============================================================
# 配置
# ============================================================
REPO_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = REPO_DIR / "template" / "report.html"
REPORTS_DIR = REPO_DIR / "public" / "reports"
INDEX_PATH = REPO_DIR / "public" / "index.html"
NGINX_DIR = Path("/var/www/vicky/research")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9091

# ============================================================
# 模板渲染
# ============================================================
def render(template: str, **kwargs) -> str:
    """替换 {{KEY}} 占位符"""
    for key, val in kwargs.items():
        template = template.replace("{{" + key + "}}", str(val))
    return template


def build_index(reports: list[dict]) -> str:
    """生成索引页 HTML"""
    items = ""
    for r in reports:
        items += f"""<a class="report-item" href="{r['file']}">
<span class="report-date">{r['date_display']}</span>
<span class="report-title">{r['title']}</span>
</a>
"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>研究报告</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue","PingFang SC","Microsoft YaHei",sans-serif;color:#1d1d1f;background:#fff;line-height:1.75;-webkit-font-smoothing:antialiased}}
.container{{max-width:900px;margin:0 auto;padding:0 40px}}
header{{padding:100px 0 60px;text-align:center}}
header h1{{font-size:40px;font-weight:700;letter-spacing:-1px;margin-bottom:8px}}
header p{{font-size:17px;color:#86868b}}
.report-list{{display:flex;flex-direction:column;gap:4px;padding-bottom:80px}}
.report-item{{display:flex;align-items:baseline;gap:16px;padding:14px 20px;border-radius:12px;transition:background 0.15s ease;text-decoration:none;color:inherit}}
.report-item:hover{{background:#f5f5f7}}
.report-date{{flex-shrink:0;font-size:13px;color:#86868b;font-family:"SF Mono","Fira Code",monospace;width:85px}}
.report-title{{font-size:16px;font-weight:600;color:#1d1d1f}}
.report-item:hover .report-title{{color:#0C4A6E}}
.section-header{{font-size:13px;font-weight:600;color:#86868b;text-transform:uppercase;letter-spacing:1px;padding:24px 20px 8px;border-bottom:1px solid #f0f0f0;margin-bottom:4px}}
footer{{padding:40px 0;text-align:center;font-size:13px;color:#86868b;border-top:1px solid #f0f0f0}}
footer a{{color:#0C4A6E;text-decoration:none}}
@media(max-width:768px){{.container{{padding:0 16px}}header{{padding:60px 0 40px}}header h1{{font-size:28px}}.report-date{{display:none}}}}
</style>
</head>
<body>
<div class="container">
<header><h1>研究报告</h1><p>AI 自动生成的技术研究归档</p></header>
<div class="section-header">最新报告</div>
<div class="report-list">
{items}
</div>
<footer><p>研究报告 &middot; ai-report</p><p>共 {len(reports)} 篇</p></footer>
</div>
</body>
</html>"""


# ============================================================
# 核心操作
# ============================================================
def list_reports() -> list[dict]:
    """扫描 reports 目录，按日期倒序"""
    result = []
    if not REPORTS_DIR.exists():
        return result
    for f in sorted(REPORTS_DIR.glob("*.html"), reverse=True):
        name = f.name
        # 提取日期
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", name)
        date_display = date_match.group(1)[5:] if date_match else "??-??"
        # 提取标题
        content = f.read_text(encoding="utf-8")
        title_match = re.search(r"<title>(.+?)</title>", content)
        title = title_match.group(1) if title_match else name
        result.append({"file": name, "title": title, "date_display": date_display})
    return result


def create_report(title: str, slug: str, tag: str, content: str) -> dict:
    """创建一篇新报告"""
    # 1. 读取模板
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # 2. 渲染
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{today}-{slug}.html"
    html = render(template,
        TITLE=title,
        HERO_TAG=tag,
        SUBTITLE="",
        DATE=today,
        AUTHOR="Hermes Agent",
        CONTENT=content,
    )

    # 3. 保存到 repo
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / filename
    report_path.write_text(html, encoding="utf-8")

    # 4. 重建索引
    reports = list_reports()
    index_html = build_index(reports)
    INDEX_PATH.write_text(index_html, encoding="utf-8")

    # 5. 部署到 Nginx（需要 sudo）
    nginx_report = NGINX_DIR / filename
    nginx_index = NGINX_DIR / "index.html"
    nginx_reports_dir = NGINX_DIR / "reports"
    deployed = False
    try:
        subprocess.run(["sudo", "cp", str(report_path), str(nginx_report)], check=True)
        subprocess.run(["sudo", "chmod", "644", str(nginx_report)], check=True)
        subprocess.run(["sudo", "cp", str(INDEX_PATH), str(nginx_index)], check=True)
        subprocess.run(["sudo", "chmod", "644", str(nginx_index)], check=True)
        # 确保 reports/ 子目录也有软链接
        subprocess.run(["sudo", "mkdir", "-p", str(nginx_reports_dir)], check=True)
        subprocess.run(["sudo", "ln", "-sf", f"../{filename}", str(nginx_reports_dir / filename)], check=True)
        deployed = True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[warn] Nginx deploy failed: {e}", file=sys.stderr)

    return {
        "ok": True,
        "file": filename,
        "url": f"http://192.168.1.100:9090/research/{filename}",
        "deployed": deployed,
    }


# ============================================================
# HTTP Server
# ============================================================
class Handler(BaseHTTPRequestHandler):
    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/health":
            self._json({"ok": True, "service": "ai-report"})
        elif self.path == "/api/reports":
            self._json({"ok": True, "reports": list_reports()})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/api/reports":
            self._json({"error": "not found"}, 404)
            return

        # 读取 body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "invalid JSON"}, 400)
            return

        title = data.get("title", "").strip()
        slug = data.get("slug", "").strip()
        tag = data.get("tag", "研究报告")
        content = data.get("content", "")

        if not title or not slug or not content:
            self._json({"ok": False, "error": "title, slug, content 都是必填"}, 400)
            return

        # 清理 slug
        slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")

        try:
            result = create_report(title, slug, tag, content)
            self._json(result, 201)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    print(f"📄 ai-report service starting on :{PORT}")
    print(f"   Template: {TEMPLATE_PATH}")
    print(f"   Reports:  {REPORTS_DIR}")
    print(f"   Index:    {INDEX_PATH}")
    print(f"   Nginx:    {NGINX_DIR}")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 shutting down")
        server.shutdown()