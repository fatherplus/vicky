#!/usr/bin/env python3
"""
AI Report Service — 轻量 HTTP API
=================================
接受 agent 提交的 HTML 内容，用统一模板渲染，保存并部署。

启动: python3 server.py [--port 9091]
API:
  POST /api/reports   — 创建报告
  POST /api/templates — 创建模板（门禁通过即收录，provisional）
  GET  /api/reports   — 列出所有报告
  GET  /api/templates — 模板目录
  GET  /api/principles— 叙事宪法（markdown）
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
import subprocess
from datetime import datetime
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ============================================================
# 配置
# ============================================================
REPO_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = REPO_DIR / "templates"
DEFAULT_TEMPLATE = "book"
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

# 契约条目单一真相（与 NARRATIVE-PRINCIPLES.md §3 逐字一致）
NARRATIVE_CONTRACTS = {
    "type-determines-narrative", "why-first", "conclusion-first",
    "three-questions", "evidence-for-claims", "scenario-exercise",
    "verdict-on-comparison", "figure-caption", "mece-structure",
}

REQUIRED_PLACEHOLDERS = ("{{TITLE}}", "{{CONTENT}}", "{{HERO_TAG}}", "{{SUBTITLE}}",
                         "{{DATE}}", "{{META}}", "{{COMPONENT_HEAD}}",
                         "{{SERIES_BADGE}}", "{{VOLUME_NAV}}")

# ============================================================
# 模板渲染
# ============================================================
def template_path(name: str) -> Path:
    """解析模板文件；未知模板抛 KeyError（handler 层转 400）"""
    p = TEMPLATES_DIR / name / "template.html"
    if not p.exists():
        raise KeyError(f"模板 '{name}' 不存在（GET /api/templates 查看可用模板）")
    return p


def list_templates() -> list:
    """模板目录：manifest 列表，default 排首"""
    out = []
    if TEMPLATES_DIR.exists():
        for m in sorted(TEMPLATES_DIR.glob("*/manifest.json")):
            out.append(json.loads(m.read_text(encoding="utf-8")))
    return sorted(out, key=lambda t: not t.get("default"))

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
<link rel="stylesheet" href="/research/assets/index.css">
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
    <div class="csub">CONTENTS · 按时间倒序 · 点类型筹码筛选，可与搜索叠加</div>

    <div class="searchbox reveal">
      <span class="search-ic">检</span>
      <input type="text" id="tocSearch" placeholder="输入关键词，模糊匹配报告标题……" autocomplete="off">
      <span class="search-hint" id="searchHint"></span>
    </div>
    <div class="noresult" id="noresult">没有匹配的报告</div>

    <div class="chips reveal" id="chips">__CHIPS__</div>

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
/* 目录筛选：类型筹码 × 关键词搜索叠加生效 */
var si=document.getElementById('tocSearch'),hint=document.getElementById('searchHint'),nores=document.getElementById('noresult');
var items=Array.prototype.slice.call(document.querySelectorAll('.toc-item'));
var chips=Array.prototype.slice.call(document.querySelectorAll('.chip'));
var fTag=null,fSeries=null;
function applyFilter(pop){
  var q=si.value.trim().toLowerCase(),shown=0,active=!!(q||fTag||fSeries);
  items.forEach(function(it){
    var hit=(!q||it.textContent.toLowerCase().indexOf(q)>=0)
      &&(!fTag||it.getAttribute('data-tag')===fTag)
      &&(!fSeries||it.getAttribute('data-series')===fSeries);
    it.style.display=hit?'':'none';
    if(hit){shown++;if(pop){it.classList.remove('pop');void it.offsetWidth;it.classList.add('pop');}}
  });
  hint.textContent=active?shown+' 篇匹配':'';
  nores.style.display=(active&&shown===0)?'block':'none';
}
chips.forEach(function(c){c.addEventListener('click',function(){
  chips.forEach(function(x){x.classList.remove('on');});c.classList.add('on');
  fTag=c.getAttribute('data-type')==='tag'?c.getAttribute('data-f'):null;
  fSeries=c.getAttribute('data-type')==='series'?c.getAttribute('data-f'):null;
  applyFilter(true);
});});
si.addEventListener('input',function(){applyFilter(false);});
/* 行内 tag / 丛书徽章点击 = 选中对应筹码 */
Array.prototype.forEach.call(document.querySelectorAll('.row-tag,.row-series'),function(b){
  b.addEventListener('click',function(e){
    e.preventDefault();e.stopPropagation();
    for(var i=0;i<chips.length;i++){var c=chips[i];
      if(c.getAttribute('data-type')===b.getAttribute('data-type')&&c.getAttribute('data-f')===b.getAttribute('data-f')){c.click();break;}}
  });
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
    """生成书风格索引页。tag 以 META 开头的文档钉住「卷首」（关于本书），
    其余按时间倒序进目录流，类型筹码（tag / 丛书）前端筛选。"""
    total = len(reports)
    front = [r for r in reports if r.get("tag", "").upper().startswith("META")]
    research = [r for r in reports if not r.get("tag", "").upper().startswith("META")]
    # 卷首区（关于本书）
    fm = [
        f'<a class="fm-item reveal" href="/research/reports/{r["file"]}">'
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
    # 时间流（新在上；list_reports 已按日期倒序）+ 类型筹码（tag / 丛书）
    tag_count, series_count = {}, {}
    for r in research:
        tag = (r.get("tag") or "研究报告").strip() or "研究报告"
        r["_tag"] = tag
        tag_count[tag] = tag_count.get(tag, 0) + 1
        sname = normalize_series(r["series"]) if r.get("series") else ""
        r["_series"] = sname
        if sname:
            series_count[sname] = series_count.get(sname, 0) + 1

    def toc_row(r, num):
        delay = (num % 12) * 0.04
        esc_tag = html.escape(r["_tag"], quote=True)
        esc_series = html.escape(r["_series"], quote=True)
        badges = f'<span class="row-tag" data-type="tag" data-f="{esc_tag}">{esc_tag}</span>'
        if r["_series"]:
            badges += (f' <span class="row-series" data-type="series" data-f="{esc_series}">'
                       f'《{esc_series}》第 {r.get("series_order") or "?"} 卷</span>')
        sub = (f'<span class="toc-sub">{html.escape(r["subtitle"])}</span>'
               if r.get("subtitle") else "")
        updated = (' <span class="toc-updated">订</span>' if r.get("updated") else "")
        return (f'<a class="toc-item reveal" style="--d:{delay:.2f}s" href="reports/{r["file"]}"'
        return (f'<a class="toc-item reveal" style="--d:{delay:.2f}s" href="/research/reports/{r["file"]}"'
                f'<span class="toc-num">{num:02d}</span>'
                f'<span class="toc-main"><span class="toc-line">'
                f'<span class="toc-title">{html.escape(r["title"])}</span>{badges}</span>{sub}</span>'
                f'<span class="toc-dots"></span>'
                f'<span class="toc-date">{r["date_display"]}{updated}</span></a>')

    rows = [toc_row(r, i) for i, r in enumerate(research, 1)]

    # 筹码：全部 + tag（按数量降序）+ 丛书（按数量降序）；小 tag 不再合并——数量诚实展示
    chips = [f'<span class="chip on" data-type="all" data-f="">全部<span class="n">{len(research)}</span></span>']
    for tag, n in sorted(tag_count.items(), key=lambda kv: (-kv[1], kv[0])):
        chips.append(f'<span class="chip" data-type="tag" data-f="{html.escape(tag, quote=True)}">'
                     f'{html.escape(tag)}<span class="n">{n}</span></span>')
    for sname, n in sorted(series_count.items(), key=lambda kv: (-kv[1], kv[0])):
        chips.append(f'<span class="chip chip-series" data-type="series" data-f="{html.escape(sname, quote=True)}">'
                     f'《{html.escape(sname)}》<span class="n">{n}</span></span>')

    year = reports[0]["date"][:4] if reports else str(datetime.now().year)
    return (_INDEX_TPL
            .replace("__FRONTMATTER__", frontmatter)
            .replace("__CHIPS__", "\n    ".join(chips))
            .replace("__TOC__", "\n    ".join(rows))
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
        updated_match = re.search(r'<meta name="updated" content="([^"]*)"', content)
        updated = updated_match.group(1) if updated_match else ""
        series_match = re.search(r'<meta name="series" content="([^"]*)"', content)
        order_match = re.search(r'<meta name="series-order" content="(\d+)"', content)
        total_match = re.search(r'<meta name="series-total" content="(\d+)"', content)
        tpl_match = re.search(r'<meta name="template" content="([^"]*)"', content)
        result.append({"file": name, "title": title, "tag": tag, "subtitle": subtitle, "date": date, "date_display": date_display, "updated": updated,
                       "series": html.unescape(series_match.group(1)) if series_match else "",  # 烙入用了 html.escape，刮回需还原
                       "series_order": int(order_match.group(1)) if order_match else 0,
                       "series_total": int(total_match.group(1)) if total_match else 0,
                       "template": tpl_match.group(1) if tpl_match else "book"})  # 存量无 meta → book
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


FIGURE_RE = re.compile(r'<figure\b[^>]*>([\s\S]*?)</figure>', re.I)
AI_WORDS = ("赋能", "闭环", "打通", "一站式", "全方位", "引领")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")

# 门禁（validate 之前，常量区附近）
ROOT_TOKEN_RE = re.compile(
    r':root[^}]*--(?:paper|ink|sub|accent|seal|dark|hair|serif|sans|mono)\s*:', re.I)


def validate_template(name: str, manifest: dict, tpl_html: str, rationale: str) -> list:
    """模板创建门禁（机器可判定）：占位符齐全 / 不重定义视觉 token / 契约条目合法"""
    violations = []
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", name or ""):
        violations.append("模板名须为小写字母数字连字符（≤40 字符）")
    missing = [ph for ph in REQUIRED_PLACEHOLDERS if ph not in (tpl_html or "")]
    if missing:
        violations.append(f"模板缺少必需占位符：{' '.join(missing)}")
    if ROOT_TOKEN_RE.search(tpl_html or ""):
        violations.append("模板不得重定义 :root 视觉 token（调色板/字体由平台 book-style.css 拥有）")
    unknown = sorted(set(manifest.get("narrative_contract") or []) - NARRATIVE_CONTRACTS)
    if unknown:
        violations.append(f"未知契约条目：{unknown}（合法条目见 GET /api/principles §3）")
    if not (manifest.get("purpose") or "").strip():
        violations.append("manifest.purpose 必填：这个模板为哪类文档的什么目的而生")
    if not manifest.get("document_types"):
        violations.append("manifest.document_types 必填：至少一种文档类型")
    if not (rationale or "").strip():
        violations.append("rationale 必填：论证现有模板为何承载不了这个目的")
    return violations


def validate_content(content: str, title: str = "") -> tuple:
    """表述规范门禁 + 软提醒（spec §7）。返回 (errors, warnings)：
    errors 触发 400 拒收；warnings 只随响应返回，agent 自觉修订。"""
    errors = []
    # --- errors：机器可判定的硬伤（原三条保留）---
    for tag in re.findall(r"<table\b[^>]*>", content, re.I):
        m = re.search(r"class\s*=\s*[\"']([^\"']*)[\"']", tag)
        classes = set(m.group(1).split()) if m else set()
        if not classes & {"data-table", "cmp-table"}:
            errors.append("裸 <table> 没有样式：摆数据用 <table class=\"data-table\">，回答\"选谁\"用 .cmp-table（见 GET /api/guide「对比表三条硬规则」）")
            break
    if "cmp-table" in content and "cmp-verdict" not in content:
        errors.append("cmp-table 缺少结论区：表尾必须接 <div class=\"cmp-verdict\">（带「怎么选 · VERDICT」）")
    deprecated = {"ladder-list": ".steps", "ladder-rung": ".step", "ladder-num": ".step-num", "ladder-content": ".step",
                  "quote-block": "blockquote", "concern-box": ".callout", "phase": ".steps"}
    used = set()
    for attr in re.findall(r"class\s*=\s*[\"']([^\"']*)[\"']", content):
        used |= set(attr.split())
    for c in sorted(used & deprecated.keys()):
        errors.append(f"已弃用组件 .{c}（模板已删除其样式）：改用 {deprecated[c]}")

    # --- warnings：零误伤取向的提醒（宁可漏报不误报）---
    warnings = []
    for i, fig in enumerate(FIGURE_RE.findall(content), 1):
        if "fig-cap" not in fig:
            warnings.append(f"第 {i} 个 figure 缺图题（图 N · 标题）")
        if "fig-note" not in fig:
            warnings.append(f"第 {i} 个 figure 缺图注（所以呢）")
    text = title + content
    hit = [w for w in AI_WORDS if w in text]
    if hit:
        warnings.append(f"AI 腔词 ×{sum(text.count(w) for w in hit)}：{'、'.join(hit)}（禁止清单）")
    emoji = EMOJI_RE.findall(text)
    if emoji:
        warnings.append(f"标题/正文含 emoji ×{len(emoji)}")
    if COMPONENTS["mermaid"]["detect"](content) and 'class="figure"' not in content:
        warnings.append("检测到 mermaid 但无任何 figure 装裱")
    return errors, warnings


def normalize_series(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def check_series_conflict(series: str, order: int, exclude_file, reports: list) -> str | None:
    """同丛书同卷号已被其他文件占用 → 返回错误文案；否则 None。"""
    series = normalize_series(series)
    for r in reports:
        if (r.get("series") and normalize_series(r["series"]) == series
                and r.get("series_order") == order and r["file"] != exclude_file):
            return f"《{series}》第 {order} 卷已被 {r['file']} 占用"
    return None


def _series_siblings(series: str, reports: list) -> list:
    series = normalize_series(series)
    sibs = [r for r in reports if r.get("series") and normalize_series(r["series"]) == series]
    return sorted(sibs, key=lambda r: r["series_order"])


def volume_nav_html(series: str, order: int, siblings: list) -> str:
    prev_r = next((r for r in siblings if r["series_order"] == order - 1), None)
    next_r = next((r for r in siblings if r["series_order"] == order + 1), None)
    links = ""
    if prev_r:
        links += f'<a class="vol prev" href="{prev_r["file"]}">← 上一卷 · {html.escape(prev_r["title"])}</a>'
    if next_r:
        links += f'<a class="vol next" href="{next_r["file"]}">下一卷 · {html.escape(next_r["title"])} →</a>'
    return f'<nav class="volume-nav" data-series="{html.escape(normalize_series(series))}">{links}</nav>'


NAV_RE = re.compile(r'<nav class="volume-nav"[\s\S]*?</nav>')
TOTAL_META_RE = re.compile(r'(<meta name="series-total" content=")\d+(")')
BADGE_TOTAL_RE = re.compile(r'(第 \d+ 卷 · 共 )\d+( 卷)')


def maintain_series_siblings(series: str):
    """重算同丛书所有卷的导航/总数/徽章片段（定向替换，不碰正文与 head 资源）。"""
    reports = list_reports()
    siblings = _series_siblings(series, reports)
    total = len(siblings)
    for r in siblings:
        path = REPORTS_DIR / r["file"]
        text = path.read_text(encoding="utf-8")
        nav = volume_nav_html(series, r["series_order"], siblings)
        new = NAV_RE.sub(nav, text)
        new = TOTAL_META_RE.sub(rf"\g<1>{total}\g<2>", new)
        new = BADGE_TOTAL_RE.sub(rf"\g<1>{total}\g<2>", new)
        if new != text:
            path.write_text(new, encoding="utf-8")


def _existing_for_slug(slug: str) -> list:
    """按文件名格式精确匹配同 slug 报告（杜绝后缀误命中）"""
    pat = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}\.html$")
    return sorted(f for f in REPORTS_DIR.glob("*.html") if pat.match(f.name))


def create_report(title: str, slug: str, tag: str, content: str, subtitle: str = "",
                  series: str = "", order: int = 0, template: str = DEFAULT_TEMPLATE) -> dict:
    """创建或修订报告（同 slug 已存在 → 覆盖原文件、保留原日期）"""
    tpl_path = template_path(template)          # 未知模板在此抛 KeyError
    tpl = tpl_path.read_text(encoding="utf-8")
    today = datetime.now().strftime("%Y-%m-%d")

    existing = _existing_for_slug(slug)
    warnings = []
    if existing:
        filename = existing[-1].name                 # 保留原文件名（原日期）
        created = False
        if len(existing) > 1:
            warnings.append(f"同 slug 存在 {len(existing)} 份历史文件，覆盖最新 {filename}，其余建议人工清理")
    else:
        filename = f"{today}-{slug}.html"
        created = True

    meta_tags = []
    meta_tags.append(f'<meta name="template" content="{template}">')   # 恒烙，保证可重渲染
    if not created:
        meta_tags.append(f'<meta name="updated" content="{today}">')
    series = normalize_series(series)
    if series:
        meta_tags.append(f'<meta name="series" content="{html.escape(series)}">')
        meta_tags.append(f'<meta name="series-order" content="{order}">')
        meta_tags.append(f'<meta name="series-total" content="1">')  # 占位，maintain 会重算
    meta_html = "\n".join(meta_tags)

    series_badge = (f'<span class="series-badge">《{html.escape(series)}》第 {order} 卷 · 共 1 卷</span>'
                    if series else "")
    # 导航先烙空锚（maintain 统一重算，含本卷）
    volume_nav = f'<nav class="volume-nav" data-series="{html.escape(series)}"></nav>' if series else ""

    comp_head, comp_hits = component_head(content)
    html_out = render(tpl,
        TITLE=title, HERO_TAG=tag, SUBTITLE=subtitle, DATE=today,
        CONTENT=content, COMPONENT_HEAD=comp_head, META=meta_html,
        SERIES_BADGE=series_badge, VOLUME_NAV=volume_nav,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / filename
    report_path.write_text(html_out, encoding="utf-8")

    # 4. 重建索引
    reports = list_reports()
    index_html = build_index(reports)
    INDEX_PATH.write_text(index_html, encoding="utf-8")

    if series:
        maintain_series_siblings(series)

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

    result = {
        "ok": True,
        "file": filename,
        "created": created,
        "components": comp_hits,
        "warnings": warnings,
        "url": f"http://192.168.1.100:9090/research/reports/{filename}",
        "deployed": deployed,
    }
    if not created:
        result["updated"] = today
    return result


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
        elif self.path.split("?")[0] == "/api/template":
            from urllib.parse import urlparse, parse_qs
            name = parse_qs(urlparse(self.path).query).get("name", [DEFAULT_TEMPLATE])[0]
            try:
                self._serve_file(template_path(name), "text/html; charset=utf-8")
            except KeyError as e:
                self._json({"ok": False, "error": str(e)}, 404)
        elif self.path == "/api/templates":
            self._json({"ok": True, "templates": list_templates()})
        elif self.path == "/api/principles":
            self._serve_file(REPO_DIR / "skill" / "NARRATIVE-PRINCIPLES.md",
                             "text/markdown; charset=utf-8")
        else:
            self._serve_static()

    def do_POST(self):
        if self.path not in ("/api/reports", "/api/validate", "/api/templates"):
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

        if self.path == "/api/templates":
            name = (data.get("name") or "").strip()
            manifest = data.get("manifest") or {}
            tpl_html = data.get("template") or ""
            rationale = data.get("rationale") or ""
            violations = validate_template(name, manifest, tpl_html, rationale)
            if not violations and (TEMPLATES_DIR / name).exists():
                self._json({"ok": False, "error": f"模板 '{name}' 已存在（模板不经 API 覆盖；演进走 git）"}, 400)
                return
            if violations:
                self._json({"ok": False, "violations": violations}, 400)
                return
            tdir = TEMPLATES_DIR / name
            tdir.mkdir(parents=True, exist_ok=True)
            (tdir / "template.html").write_text(tpl_html, encoding="utf-8")
            stored = {**manifest, "name": name, "default": False,
                      "provisional": True, "rationale": rationale.strip()}
            (tdir / "manifest.json").write_text(
                json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
            self._json({"ok": True, "name": name, "provisional": True,
                        "message": "已收录（provisional）。模板是叙事结构的执行点——大标题顺序须可从契约条目推出。"}, 201)
            return

        title = data.get("title", "").strip()
        slug = data.get("slug", "").strip()
        tag = data.get("tag", "研究报告")
        content = data.get("content", "")
        subtitle = data.get("subtitle", "").strip()

        if self.path == "/api/validate":
            violations, warnings = validate_content(content, title)
            # 可选字段：给了就检
            slug = data.get("slug", "").strip()
            if slug and not re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-"):
                violations.append("slug 清理后为空：至少包含一个字母或数字")
            series, order = data.get("series"), data.get("order")
            if bool(series) != (order is not None):
                violations.append("series 与 order 必须同时提供")
            elif series:
                try:
                    order = int(order)
                    assert order >= 1
                except (TypeError, ValueError, AssertionError):
                    violations.append("order 必须是 ≥1 的整数")
                else:
                    # upsert 本卷自己占自己的卷号不算冲突（spec §2.6）：slug 给了就按同款逻辑算 exclude
                    clean_slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
                    existing = _existing_for_slug(clean_slug) if clean_slug else []
                    exclude_file = existing[-1].name if existing else None
                    conflict = check_series_conflict(series, order, exclude_file=exclude_file,
                                                     reports=list_reports())
                    if conflict:
                        violations.append(conflict)
            _, hits = component_head(content)
            self._json({"ok": not violations, "violations": violations,
                        "warnings": warnings, "components": hits})
            return

        if not title or not slug or not content:
            self._json({"ok": False, "error": "title, slug, content 都是必填"}, 400)
            return

        # 表述规范门禁（EXPRESSION-GRAMMAR.md）：硬伤直接拒收，错误信息即写作指导
        violations, warnings = validate_content(content, title)
        if violations:
            self._json({"ok": False, "error": "内容不符合表述规范", "violations": violations}, 400)
            return

        # 清理 slug（提前到丛书校验之前：校验要用清理后的 slug 匹配 upsert 本卷文件名）
        slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")

        series = (data.get("series") or "").strip()
        order = data.get("order")
        if bool(series) != (order is not None):
            self._json({"ok": False, "error": "series 与 order 必须同时提供"}, 400)
            return
        if series:
            try:
                order = int(order)
                assert order >= 1
            except (TypeError, ValueError, AssertionError):
                self._json({"ok": False, "error": "order 必须是 ≥1 的整数"}, 400)
                return
            # upsert 本卷自己占自己的卷号不算冲突（spec §2.6：同 slug upsert 且 order 不变 → 允许）
            existing = _existing_for_slug(slug)
            exclude_file = existing[-1].name if existing else None
            conflict = check_series_conflict(series, order, exclude_file=exclude_file,
                                             reports=list_reports())
            if conflict:
                self._json({"ok": False, "error": conflict}, 400)
                return

        template = data.get("template") or DEFAULT_TEMPLATE

        try:
            result = create_report(title, slug, tag, content, subtitle,
                                   series=series, order=order or 0, template=template)
            result.setdefault("warnings", []).extend(warnings)
            self._json(result, 201)
        except KeyError as e:
            self._json({"ok": False, "error": e.args[0] if e.args else str(e)}, 400)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    print(f"📄 ai-report service starting on :{PORT}")
    print(f"   Templates: {TEMPLATES_DIR} (default: {DEFAULT_TEMPLATE})")
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