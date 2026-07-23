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
<style>
:root{
  --paper:#FBFAF7; --ink:#23272E; --sub:#6E7278;
  --accent:#0C4A6E; --seal:#A63A2E; --hairline:rgba(0,0,0,.08);
  --serif:'Noto Serif SC',serif; --sans:'Noto Sans SC',-apple-system,'PingFang SC',sans-serif;
  --mono:'JetBrains Mono','SF Mono',Menlo,monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{font-family:var(--sans);background:var(--paper);color:var(--ink);line-height:1.8;-webkit-font-smoothing:antialiased}
::selection{background:var(--accent);color:#fff}
#ribbon{position:fixed;top:0;left:0;height:3px;width:0;background:var(--seal);z-index:200}
.runninghead{position:sticky;top:0;z-index:100;background:rgba(251,250,247,.92);backdrop-filter:blur(10px);border-bottom:1px solid var(--hairline)}
.runninghead .inner{max-width:880px;margin:0 auto;padding:13px 32px;display:flex;justify-content:space-between;align-items:baseline}
.runninghead .book{font-family:var(--serif);font-weight:600;font-size:14px;letter-spacing:.06em}
.runninghead .chapter{font-family:var(--mono);font-size:11.5px;color:var(--sub)}
.page{max-width:880px;margin:0 auto;padding:0 32px}

/* 扉页（封面） */
.frontispiece{padding:100px 0 70px;position:relative}
.frontispiece .kicker{font-family:var(--mono);font-size:12.5px;color:var(--accent);letter-spacing:.24em;margin-bottom:30px;display:flex;align-items:center;gap:14px}
.frontispiece .kicker::after{content:'';flex:1;height:1px;background:var(--hairline)}
.titleblock{position:relative}
.frontispiece h1{font-family:var(--serif);font-weight:900;font-size:clamp(44px,7vw,68px);line-height:1.2;letter-spacing:.02em}
.frontispiece h1 .mark{color:var(--accent)}
.frontispiece .subtitle{font-size:18px;color:var(--sub);margin-top:20px;max-width:520px;line-height:1.7}
.seal{position:absolute;top:-10px;right:0;width:84px;height:84px;background:var(--seal);color:#FBFAF7;border-radius:10px;display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-weight:900;font-size:34px;transform:rotate(4deg);box-shadow:0 4px 16px rgba(166,58,46,.3),inset 0 0 0 2.5px rgba(251,250,247,.35);user-select:none}
@media(max-width:640px){.seal{width:56px;height:56px;font-size:22px}}
.volume{margin-top:44px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-family:var(--mono);font-size:12.5px;color:var(--sub);letter-spacing:.05em}
.volume .sep{color:var(--hairline)}
.volume .vtag{border:1px solid var(--accent);color:var(--accent);padding:2px 10px;border-radius:4px;font-size:11px}

/* 目录 */
.contents{padding:56px 0 40px;border-top:1px solid var(--hairline)}
.contents .chead{display:flex;align-items:baseline;gap:18px;margin-bottom:8px}
.contents h2{font-family:var(--serif);font-weight:900;font-size:30px}
.contents .chead::after{content:'';width:52px;height:3px;background:var(--accent);align-self:center}
.contents .csub{font-family:var(--mono);font-size:12px;color:var(--sub);margin-bottom:34px;letter-spacing:.05em}
.fascicle{font-family:var(--mono);font-size:12px;color:var(--accent);letter-spacing:.18em;margin:34px 0 6px;display:flex;align-items:center;gap:12px}
.fascicle::after{content:'';flex:1;height:1px;background:var(--hairline)}
.fascicle .cnt{color:var(--sub)}
.searchbox{display:flex;align-items:center;gap:14px;margin:8px 0 26px;background:#fff;border:1px solid rgba(0,0,0,.06);border-bottom:2px solid var(--accent);border-radius:10px 10px 0 0;padding:4px 18px 4px 6px;transition:box-shadow .25s}
.searchbox:focus-within{box-shadow:0 6px 20px rgba(12,74,110,.1)}
.search-ic{flex-shrink:0;width:34px;height:34px;background:var(--accent);color:#FBFAF7;border-radius:7px;display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-weight:900;font-size:16px}
.searchbox input{flex:1;border:none;background:none;font-family:var(--sans);font-size:15.5px;color:var(--ink);outline:none;padding:10px 0}
.searchbox input::placeholder{color:#a8aab0}
.search-hint{font-family:var(--mono);font-size:12px;color:var(--accent);white-space:nowrap}
.noresult{display:none;text-align:center;color:var(--sub);font-family:var(--serif);font-size:16px;padding:44px 0}
.toc-item{display:flex;align-items:baseline;gap:14px;padding:13px 10px;text-decoration:none;color:var(--ink);border-radius:8px;transition:background .2s,transform .2s}
.toc-item:hover{background:rgba(12,74,110,.045);transform:translateX(5px)}
.toc-item:hover .toc-title{color:var(--accent)}
.toc-item:hover .toc-dots{border-color:rgba(12,74,110,.4)}
.toc-num{font-family:var(--serif);font-weight:900;font-size:15px;color:var(--accent);width:30px;flex-shrink:0}
.toc-title{font-family:var(--serif);font-size:16.5px;font-weight:600;line-height:1.5;transition:color .2s}
.toc-title .en{display:block;font-family:var(--mono);font-size:11px;font-weight:400;color:var(--sub);margin-top:2px}
.toc-dots{flex:1;border-bottom:2px dotted rgba(0,0,0,.18);transform:translateY(-5px);transition:border-color .2s;min-width:24px}
.toc-date{font-family:var(--mono);font-size:12px;color:var(--sub);flex-shrink:0}
@media(max-width:560px){.toc-dots{display:none}}

/* Agent 接入（书签卡片） */
.agentpage{padding:20px 0 56px}
.acard{position:relative;background:#fff;border:1px solid rgba(0,0,0,.06);border-top:3px solid var(--accent);border-radius:10px;padding:38px 40px 34px;box-shadow:0 2px 10px rgba(0,0,0,.04)}
.aseal{position:absolute;top:-16px;right:26px;width:52px;height:52px;background:var(--seal);color:#FBFAF7;border-radius:8px;display:flex;align-items:center;justify-content:center;font-family:var(--serif);font-weight:900;font-size:22px;transform:rotate(4deg);box-shadow:0 4px 14px rgba(166,58,46,.28),inset 0 0 0 2px rgba(251,250,247,.35);user-select:none}
.akicker{font-family:var(--mono);font-size:12px;color:var(--accent);letter-spacing:.22em;margin-bottom:14px;display:flex;align-items:center;gap:12px}
.akicker::after{content:'';flex:1;height:1px;background:var(--hairline)}
.atitle{font-family:var(--serif);font-weight:900;font-size:26px;margin-bottom:12px}
.adesc{font-size:15.5px;color:var(--sub);line-height:1.8;max-width:640px;margin-bottom:26px}
.asteps{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:28px}
.astep{flex:1;min-width:170px;display:flex;gap:12px;align-items:flex-start;background:var(--paper);border:1px solid var(--hairline);border-radius:8px;padding:14px 16px;transition:transform .2s,box-shadow .2s}
.astep:hover{transform:translateY(-3px);box-shadow:0 6px 16px rgba(12,74,110,.08)}
.anum{font-family:var(--serif);font-weight:900;color:var(--accent);font-size:17px;line-height:1.4}
.astep b{display:block;font-size:14px;font-weight:700;margin-bottom:3px}
.astep code{font-family:var(--mono);font-size:11.5px;color:var(--accent);background:rgba(12,74,110,.06);padding:2px 6px;border-radius:4px}
.abtns{display:flex;gap:12px;flex-wrap:wrap}
.abtn{font-family:var(--sans);font-size:14.5px;font-weight:700;padding:11px 26px;border-radius:8px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:8px;transition:all .18s ease;border:1px solid transparent}
.abtn.primary{background:var(--accent);color:#FBFAF7}
.abtn.primary:hover{background:#0a3d5c;transform:translateY(-2px);box-shadow:0 6px 16px rgba(12,74,110,.25)}
.abtn.ghost{background:none;border-color:var(--accent);color:var(--accent)}
.abtn.ghost:hover{background:rgba(12,74,110,.06);transform:translateY(-2px)}
.atoast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%) translateY(90px);background:var(--ink);color:#FBFAF7;font-size:14px;padding:11px 26px;border-radius:8px;transition:transform .35s cubic-bezier(.16,1,.3,1);pointer-events:none;z-index:300;box-shadow:0 8px 24px rgba(0,0,0,.2)}
.atoast.show{transform:translateX(-50%) translateY(0)}
@media(max-width:640px){.acard{padding:28px 22px}.aseal{width:42px;height:42px;font-size:18px;top:-12px;right:16px}}

/* 跋 */
.colophon{border-top:1px solid var(--hairline);padding:48px 0 60px;text-align:center}
.colophon .book{font-family:var(--serif);font-weight:600;font-size:15px;letter-spacing:.08em}
.colophon .pg{font-family:var(--mono);font-size:12px;color:var(--sub);margin-top:10px}
.colophon a{color:var(--accent);text-decoration:none}

.reveal{opacity:0;transform:translateY(14px);transition:opacity .6s cubic-bezier(.16,1,.3,1),transform .6s cubic-bezier(.16,1,.3,1);transition-delay:var(--d,0s)}
.reveal.in{opacity:1;transform:none}
@media(prefers-reduced-motion:reduce){.reveal{opacity:1;transform:none;transition:none}}
</style>
<style>
/* 跨页过渡（文章 → 目录）—— 浏览器原生 View Transitions API，零 JS；
   不支持的浏览器（Safari/Firefox）自动降级为直接跳转。规范见 BOOK-STYLE §8 */
@view-transition{navigation:auto}
html{background:var(--paper)}
::view-transition-image-pair(root){isolation:isolate}
::view-transition-old(root),::view-transition-new(root){mix-blend-mode:normal;animation-duration:.45s;animation-timing-function:cubic-bezier(.4,0,.2,1)}
::view-transition-old(root){animation-name:vt-old}
::view-transition-new(root){animation-name:vt-new}
@keyframes vt-old{to{opacity:0;transform:translateX(20px)}}
@keyframes vt-new{from{opacity:0;transform:translateX(-20px)}}
@media(prefers-reduced-motion:reduce){::view-transition-old(root),::view-transition-new(root){animation:none}}
</style>
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
      <p class="subtitle">技术研究与方案归档 —— 开源项目、算法机制与工程实践的深度研究，由 AI 整理成册。</p>
    </div>
    <div class="volume">
      <span class="vtag">第一卷</span><span class="sep">·</span>
      <span>__YEAR__</span><span class="sep">·</span>
      <span>Hermes Agent 编</span><span class="sep">·</span>
      <span>共 __TOTAL__ 篇</span>
    </div>
  </div>

  <div class="contents">
    <div class="chead"><h2>目录</h2></div>
    <div class="csub">CONTENTS · 按时间倒序</div>

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
    """生成书风格索引页（目录从 reports 动态生成，含 Agent 接入入口）"""
    total = len(reports)
    months = {}
    for r in reports:
        months[r["date"][:7]] = months.get(r["date"][:7], 0) + 1
    toc, cur = [], None
    for i, r in enumerate(reports):
        ym = r["date"][:7]
        if ym != cur:
            cur = ym
            y, m = ym.split("-")
            toc.append(f'<div class="fascicle">{y} 年 {int(m)} 月 <span class="cnt">· {months[ym]} 篇</span></div>')
        delay = (i % 12) * 0.04
        toc.append(
            f'<a class="toc-item reveal" style="--d:{delay:.2f}s" href="reports/{r["file"]}">'
            f'<span class="toc-num">{total - i:02d}</span>'
            f'<span class="toc-title">{html.escape(r["title"])}</span>'
            f'<span class="toc-dots"></span>'
            f'<span class="toc-date">{r["date_display"]}</span></a>'
        )
    year = reports[0]["date"][:4] if reports else str(datetime.now().year)
    return (_INDEX_TPL
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
        result.append({"file": name, "title": title, "date": date, "date_display": date_display})
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