#!/usr/bin/env python3
"""
AI Report Service — 轻量 HTTP API
=================================
接受 agent 提交的 HTML 内容，用统一模板渲染，保存并部署。

启动: python3 server.py [--port 9091]
API:
  POST /api/reports   — 创建报告
  GET  /api/reports   — 列出所有报告
  GET  /api/guide     — Agent 写作指南（markdown）
  GET  /api/skill     — 下载写作指南（.md 文件）
  GET  /api/template  — 查看 HTML 模板
  GET  /api/health    — 健康检查
"""

import json
import os
import html
import re
import sys
import shutil
import subprocess
from datetime import datetime
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ============================================================
# 配置
# ============================================================
REPO_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = REPO_DIR / "template" / "report.html"
REPORTS_DIR = REPO_DIR / "public" / "reports"
INDEX_PATH = REPO_DIR / "public" / "index.html"
NGINX_DIR = Path("/var/www/vicky/research")
PUBLIC_DIR = REPO_DIR / "public"

def _parse_port() -> int:
    try:
        return int(sys.argv[1])
    except (IndexError, ValueError):
        return 9091


PORT = _parse_port()
GUIDE_PATH = REPO_DIR / "skill" / "AGENT-GUIDE.md"

# ============================================================
# 模板渲染
# ============================================================
def render(template: str, **kwargs) -> str:
    """替换 {{KEY}} 占位符"""
    for key, val in kwargs.items():
        template = template.replace("{{" + key + "}}", str(val))
    return template


_INDEX_TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 研究报告集 · 目录</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;900&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="assets/index.css">
</head>
<body>
<div id="ribbon"></div>
<header class="runninghead">
  <div class="inner"><span class="book">《AI 研究报告集》</span><span class="chapter">目录 · CONTENTS</span></div>
</header>

<main class="page">
  <div class="frontispiece">
    <div class="kicker">AI-REPORT · 研究文库</div>
    <div class="titleblock">
      <div class="seal" aria-hidden="true">藏</div>
      <h1>AI <span class="mark">研究</span>报告集</h1>
      <p class="subtitle">技术研究与方案归档 —— 开源项目、算法机制与工程实践的深度研究。</p>
    </div>
    <div class="volume">
      <span class="vtag">第一卷</span><span class="sep">·</span>
      <span>__YEAR__</span><span class="sep">·</span>
      <span>共 __TOTAL__ 篇</span>
    </div>
  </div>
  __FRONTMATTER__
  <div class="contents">
    <div class="chead"><h2>目录</h2></div>
    <div class="csub">CONTENTS · 按时间倒序 · 技术研究</div>

    <div class="searchbox reveal">
      <span class="search-ic">检</span>
      <input type="text" id="tocSearch" placeholder="输入关键词，模糊匹配报告标题……" autocomplete="off">
      <span class="search-hint" id="searchHint"></span>
    </div>
    <div class="noresult" id="noresult">没有匹配的报告</div>

    __TOC__
  </div>

  <div class="agentpage">
    <div class="acard reveal">
      <div class="aseal" aria-hidden="true">启</div>
      <div class="akicker">FOR AGENTS · 写作入口</div>
      <h2 class="atitle">AI Agent 接入</h2>
      <p class="adesc">本平台为 AI Agent 提供统一的研究报告发布入口。把提示词交给你的 Agent，或让它下载 Skill——它会先读写作规范，再按统一的“书”风格提交报告，自动套用主题色、版式与导航。</p>
      <div class="asteps">
        <div class="astep"><span class="anum">壹</span><div><b>读规范</b><code>GET /api/guide</code></div></div>
        <div class="astep"><span class="anum">贰</span><div><b>看模板</b><code>GET /api/template</code></div></div>
        <div class="astep"><span class="anum">叁</span><div><b>交报告</b><code>POST /api/reports</code></div></div>
      </div>
      <div class="abtns">
        <button class="abtn primary" onclick="copyPrompt()">复制提示词</button>
        <a class="abtn ghost" id="skillLink" href="/api/skill" download="ai-report-skill.md">下载 Skill</a>
      </div>
    </div>
  </div>

  <footer class="colophon">
    <div class="book">《AI 研究报告集》· 第一卷</div>
    <div class="pg">ai-report · <a href="https://github.com/fatherplus/vicky">github.com/fatherplus/vicky</a></div>
  </footer>
</main>

<script>
var ribbon=document.getElementById('ribbon');
function setRibbon(){var h=document.documentElement;ribbon.style.width=(h.scrollTop/(h.scrollHeight-h.clientHeight)*100)+'%';}
addEventListener('scroll',setRibbon,{passive:true});setRibbon();
var io=('IntersectionObserver' in window)?new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target);}});},{threshold:.08}):null;
document.querySelectorAll('.reveal').forEach(function(el){if(io)io.observe(el);else el.classList.add('in');});
/* 目录检索（模糊匹配标题）*/
var si=document.getElementById('tocSearch'),hint=document.getElementById('searchHint'),nores=document.getElementById('noresult');
var items=Array.prototype.slice.call(document.querySelectorAll('.toc-item'));
var fasc=Array.prototype.slice.call(document.querySelectorAll('.fascicle'));
si.addEventListener('input',function(){
  var q=this.value.trim().toLowerCase(),shown=0;
  items.forEach(function(it){var hit=!q||it.textContent.toLowerCase().indexOf(q)>=0;it.style.display=hit?'':'none';if(hit)shown++;});
  hint.textContent=q?shown+' 篇匹配':'';
  fasc.forEach(function(f){var n=f.nextElementSibling,any=false;while(n&&!n.classList.contains('fascicle')){if(n.classList.contains('toc-item')&&n.style.display!=='none')any=true;n=n.nextElementSibling;}f.style.display=any?'':'none';});
  nores.style.display=(q&&shown===0)?'block':'none';
});
/* Agent 接入：API 地址随当前主机推导（同主机 :9091）*/
var API=location.protocol+'//'+location.hostname+':9091';
document.getElementById('skillLink').href=API+'/api/skill';
function copyText(s){
  if(navigator.clipboard&&navigator.clipboard.writeText)return navigator.clipboard.writeText(s);
  return new Promise(function(res,rej){
    var ta=document.createElement('textarea');ta.value=s;
    ta.style.cssText='position:fixed;opacity:0;top:0;left:0';
    document.body.appendChild(ta);ta.focus();ta.select();
    var ok=false;try{ok=document.execCommand('copy');}catch(e){}
    ta.remove();ok?res():rej(new Error('copy failed'));
  });
}
function toast(msg){
  var t=document.createElement('div');t.className='atoast show';t.textContent=msg;document.body.appendChild(t);
  setTimeout(function(){t.classList.remove('show');setTimeout(function(){t.remove();},400);},1800);
}
function copyPrompt(){
  var p=`当你需要写技术研究报告时，使用 ai-report 平台。
1. 读取写作规范：GET ${API}/api/guide
2. 查看 HTML 模板结构：GET ${API}/api/template
3. 按规范写内容，提交：POST ${API}/api/reports
   Body: {"title":"标题", "slug":"slug", "tag":"标签", "content":"<section class='reveal'><div class='wrap'>...</div></section>"}
4. 查看已发布报告：GET ${API}/api/reports`;
  copyText(p).then(function(){toast('已复制到剪贴板');})
    .catch(function(){toast('复制失败，请手动选择文本');});
}
</script>
</body>
</html>"""


def build_index(reports: list[dict]) -> str:
    """生成书风格索引页。tag 以 META 开头的文档归入「卷首」（关于本书），
    其余按时间倒序进目录。"""
    total = len(reports)
    front = [r for r in reports if r.get("tag", "").upper().startswith("META")]
    research = [r for r in reports if not r.get("tag", "").upper().startswith("META")]
    # 卷首区（关于本书）
    fm = [
        f'<a class="fm-item reveal" href="reports/{r["file"]}">'
        f'<span class="fm-seal" aria-hidden="true">序</span>'
        f'<span class="fm-body"><span class="fm-title">{html.escape(r["title"])}</span>'
        f'<span class="fm-desc">{html.escape(r.get("subtitle") or "关于这个平台本身的设计说明。")}</span></span>'
        f'<span class="fm-arrow">→</span></a>'
        for r in front
    ]
    frontmatter = ""
    if fm:
        frontmatter = ('<div class="frontmatter">\n    <div class="fm-label">卷首 · 关于本书</div>\n    '
                       + "\n    ".join(fm) + "\n  </div>")
    # 目录（仅研究类，按时间倒序）
    months = {}
    for r in research:
        months[r["date"][:7]] = months.get(r["date"][:7], 0) + 1
    toc, cur = [], None
    for i, r in enumerate(research):
        ym = r["date"][:7]
        if ym != cur:
            cur = ym
            y, m = ym.split("-")
            toc.append(f'<div class="fascicle">{y} 年 {int(m)} 月 <span class="cnt">· {months[ym]} 篇</span></div>')
        delay = (i % 12) * 0.04
        toc.append(
            f'<a class="toc-item reveal" style="--d:{delay:.2f}s" href="reports/{r["file"]}">'
            f'<span class="toc-num">{len(research) - i:02d}</span>'
            f'<span class="toc-title">{html.escape(r["title"])}</span>'
            f'<span class="toc-dots"></span>'
            f'<span class="toc-date">{r["date_display"]}</span></a>'
        )
    year = reports[0]["date"][:4] if reports else str(datetime.now().year)
    return (_INDEX_TPL
            .replace("__FRONTMATTER__", frontmatter)
            .replace("__TOC__", "\n    ".join(toc))
            .replace("__TOTAL__", str(total))
            .replace("__YEAR__", year))


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
        date = date_match.group(1) if date_match else "0000-00-00"
        date_display = date[5:]
        # 提取标题
        content = f.read_text(encoding="utf-8")
        title_match = re.search(r"<title>(.+?)</title>", content)
        title = title_match.group(1) if title_match else name
        # 提取 tag（kicker）与副标题，用于卷首分流（META → 卷首）
        tag_match = re.search(r'<div class="kicker">([^<]*)</div>', content)
        tag = tag_match.group(1).strip() if tag_match else ""
        sub_match = re.search(r'<p class="subtitle">([^<]*)</p>', content)
        subtitle = sub_match.group(1).strip() if sub_match else ""
        result.append({"file": name, "title": title, "tag": tag, "subtitle": subtitle, "date": date, "date_display": date_display})
    return result


# ============================================================
# 按需组件注入（spec §5）：agent 写语义契约，server 检测并按篇注入资源
# 新增组件 = 本表加一条；agent 永不碰资源路径/版本/CDN
# ============================================================
COMPONENTS = {
    "mermaid": {
        "detect": lambda content: bool(re.search(
            r'<pre\b[^>]*\bclass=["\'][^"\']*\bmermaid\b', content, re.I)),
        "head": (
            '<script src="../assets/components/mermaid/mermaid-11.9.0.min.js" defer></script>',
            '<script src="../assets/components/mermaid/init.v1.js" defer></script>',
        ),
    },
}


def component_head(content: str) -> tuple:
    """返回 (head 注入片段, 命中的组件名列表)。"""
    hits = [name for name, comp in COMPONENTS.items() if comp["detect"](content)]
    head = "\n    ".join(tag for name in hits for tag in COMPONENTS[name]["head"])
    return head, hits


def validate_content(content: str) -> list:
    """表述规范门禁（skill/EXPRESSION-GRAMMAR.md）：只拦机器可判定的硬伤，返回错误列表"""
    errors = []
    # 1. 裸 <table>：模板无裸表格样式，渲染必裸奔。数据用 .data-table，选型用 .cmp-table
    for tag in re.findall(r"<table\b[^>]*>", content, re.I):
        m = re.search(r"class\s*=\s*[\"']([^\"']*)[\"']", tag)
        classes = set(m.group(1).split()) if m else set()
        if not classes & {"data-table", "cmp-table"}:
            errors.append("裸 <table> 没有样式：摆数据用 <table class=\"data-table\">，回答\"选谁\"用 .cmp-table（见 GET /api/guide「对比表三条硬规则」）")
            break
    # 2. 对比表必须有结论：没有 VERDICT 的对比不合格
    if "cmp-table" in content and "cmp-verdict" not in content:
        errors.append("cmp-table 缺少结论区：表尾必须接 <div class=\"cmp-verdict\">（带「怎么选 · VERDICT」）")
    # 3. 弃用组件：模板已删除其样式，用了就裸奔（weknora 的 .ladder-* 事故）
    deprecated = {"ladder-list": ".steps", "ladder-rung": ".step", "ladder-num": ".step-num", "ladder-content": ".step",
                  "quote-block": "blockquote", "concern-box": ".callout", "phase": ".steps"}
    used = set()
    for attr in re.findall(r"class\s*=\s*[\"']([^\"']*)[\"']", content):
        used |= set(attr.split())
    for c in sorted(used & deprecated.keys()):
        errors.append(f"已弃用组件 .{c}（模板已删除其样式）：改用 {deprecated[c]}")
    return errors


def create_report(title: str, slug: str, tag: str, content: str, subtitle: str = "") -> dict:
    """创建一篇新报告"""
    # 1. 读取模板
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # 2. 渲染
    today = datetime.now().strftime("%Y-%m-%d")
    filename = f"{today}-{slug}.html"
    comp_head, comp_hits = component_head(content)
    html = render(template,
        TITLE=title,
        HERO_TAG=tag,
        SUBTITLE=subtitle,
        DATE=today,
        CONTENT=content,
        COMPONENT_HEAD=comp_head,
    )

    # 3. 保存到 repo
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / filename
    report_path.write_text(html, encoding="utf-8")

    # 4. 重建索引
    reports = list_reports()
    index_html = build_index(reports)
    INDEX_PATH.write_text(index_html, encoding="utf-8")

    # 5. 部署到 Nginx（canonical：reports/ 直传 + assets 同步；平铺由 nginx 301）
    deployed = False
    try:
        subprocess.run(["sudo", "mkdir", "-p", str(NGINX_DIR / "reports"), str(NGINX_DIR / "assets")], check=True)
        subprocess.run(["sudo", "cp", str(report_path), str(NGINX_DIR / "reports" / filename)], check=True)
        subprocess.run(["sudo", "chmod", "644", str(NGINX_DIR / "reports" / filename)], check=True)
        subprocess.run(["sudo", "cp", str(INDEX_PATH), str(NGINX_DIR / "index.html")], check=True)
        subprocess.run(["sudo", "chmod", "644", str(NGINX_DIR / "index.html")], check=True)
        subprocess.run(["sudo", "cp", "-r", str(PUBLIC_DIR / "assets") + "/.", str(NGINX_DIR / "assets")], check=True)
        deployed = True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[warn] Nginx deploy failed: {e}", file=sys.stderr)

    return {
        "ok": True,
        "file": filename,
        "created": True,
        "components": comp_hits,
        "url": f"http://192.168.1.100:9090/research/reports/{filename}",
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

    def _serve_file(self, path: Path, content_type: str, download_name: str = None):
        """返回文件内容"""
        if not path.exists():
            self._json({"error": "not found"}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self):
        """Serve static files from PUBLIC_DIR (index + reports)"""
        # Normalize path
        req = self.path.split("?")[0].rstrip("/")
        if req == "" or req == "/":
            req = "/index.html"
        # Security: no path traversal
        target = (PUBLIC_DIR / req.lstrip("/")).resolve()
        if not str(target).startswith(str(PUBLIC_DIR.resolve())):
            self._json({"error": "forbidden"}, 403)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            self._json({"error": "not found"}, 404)
            return
        # MIME
        ext = target.suffix.lower()
        mime = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
                ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
                ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2"}.get(ext, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if ext in (".html", ".css", ".js", ".json") else mime)
        self.send_header("Content-Length", str(len(body)))
        no_cache = ext == ".html" or req.startswith("/assets")
        self.send_header("Cache-Control", "no-cache" if no_cache else "public, max-age=86400")
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
        elif self.path == "/api/guide":
            self._serve_file(GUIDE_PATH, "text/markdown; charset=utf-8")
        elif self.path == "/api/skill":
            self._serve_file(GUIDE_PATH, "text/markdown; charset=utf-8", "ai-report-skill.md")
        elif self.path == "/api/template":
            self._serve_file(TEMPLATE_PATH, "text/html; charset=utf-8")
        else:
            self._serve_static()

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
        subtitle = data.get("subtitle", "").strip()

        if not title or not slug or not content:
            self._json({"ok": False, "error": "title, slug, content 都是必填"}, 400)
            return

        # 表述规范门禁（EXPRESSION-GRAMMAR.md）：硬伤直接拒收，错误信息即写作指导
        violations = validate_content(content)
        if violations:
            self._json({"ok": False, "error": "内容不符合表述规范", "violations": violations}, 400)
            return

        # 清理 slug
        slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")

        try:
            result = create_report(title, slug, tag, content, subtitle)
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
    # ThreadingHTTPServer: 一个挂住的连接（慢客户端/未完成请求）不能把单线程 HTTPServer 堵死，经历过一次
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 shutting down")
        server.shutdown()