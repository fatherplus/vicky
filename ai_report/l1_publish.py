"""
L1 表述层——快照 → 门禁 → 模板 → HTML+MD + 索引 + 丛书维护。
P0 包化：从 server.py 搬迁 render/build_index/门禁/丛书/模板校验全部代码。
行为零变化——仅代码搬迁 + import 路径更新，不改逻辑。
"""

import base64
import html as html_mod
import json
import re
from datetime import datetime
from pathlib import Path

from . import config
from . import store
from . import l0_ingest
from .html_to_md import html_to_md

# ============================================================
# 本地别名（便捷访问 config 常量）
# ============================================================
REPO_DIR = config.REPO_DIR
TEMPLATES_DIR = config.TEMPLATES_DIR
DEFAULT_TEMPLATE = config.DEFAULT_TEMPLATE
REPORTS_DIR = config.REPORTS_DIR
INDEX_PATH = config.INDEX_PATH
PUBLIC_DIR = config.PUBLIC_DIR
IMG_DIR = config.IMG_DIR
NARRATIVE_CONTRACTS = config.NARRATIVE_CONTRACTS
DOMAINS = config.DOMAINS
COMPONENTS = config.COMPONENTS
FIGURE_RE = config.FIGURE_RE
AI_WORDS = config.AI_WORDS
EMOJI_RE = config.EMOJI_RE
DEPRECATED_CLASSES = config.DEPRECATED_CLASSES
ROOT_TOKEN_RE = config.ROOT_TOKEN_RE
REQUIRED_PLACEHOLDERS = config.REQUIRED_PLACEHOLDERS
IMG_EXTENSIONS = config.IMG_EXTENSIONS
IMG_MAX_BYTES = config.IMG_MAX_BYTES

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
      <p class="adesc">本平台为 AI Agent 提供统一的研究报告发布入口。把提示词交给你的 Agent，或让它下载 Skill——它会先读写作规范，再按统一的"书"风格提交报告，自动套用主题色、版式与导航。</p>
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
var fTag=null,fSeries=null,fDomain=null;
function applyFilter(pop){
  var q=si.value.trim().toLowerCase(),shown=0,active=!!(q||fTag||fSeries||fDomain);
  items.forEach(function(it){
    var hit=(!q||it.textContent.toLowerCase().indexOf(q)>=0)
      &&(!fTag||it.getAttribute('data-tag')===fTag)
      &&(!fSeries||it.getAttribute('data-series')===fSeries)
      &&(!fDomain||it.getAttribute('data-domain')===fDomain);
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
  fDomain=c.getAttribute('data-type')==='domain'?c.getAttribute('data-f'):null;
  applyFilter(true);
});});
si.addEventListener('input',function(){applyFilter(false);});
/* 行内 tag / 丛书徽章点击 = 选中对应筹码 */
Array.prototype.forEach.call(document.querySelectorAll('.row-tag,.row-series,.row-domain'),function(b){
  b.addEventListener('click',function(e){
    e.preventDefault();e.stopPropagation();
    for(var i=0;i<chips.length;i++){var c=chips[i];
      if(c.getAttribute('data-type')===b.getAttribute('data-type')&&c.getAttribute('data-f')===b.getAttribute('data-f')){c.click();break;}}
  });
});
/* Agent 接入：API 与页面同源（Nginx 反代 /api/ → server.py）*/
var API=location.origin;
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
        f'<span class="fm-body"><span class="fm-title">{html_mod.escape(r["title"])}</span>'
        f'<span class="fm-desc">{html_mod.escape(r.get("subtitle") or "关于这个平台本身的设计说明。")}</span></span>'
        f'<span class="fm-arrow">→</span></a>'
        for r in front
    ]
    frontmatter = ""
    if fm:
        frontmatter = ('<div class="frontmatter">\n    <div class="fm-label">卷首 · 关于本书</div>\n    '
                       + "\n    ".join(fm) + "\n  </div>")
    # 时间流（新在上；list_reports 已按日期倒序）+ 类型筹码（tag / 丛书 / domain）
    DOMAIN_LABEL = {"tech": "技术", "design": "设计", "ephemeral": "工作"}
    tag_count, series_count, domain_count = {}, {}, {}
    for r in research:
        tag = (r.get("tag") or "研究报告").strip() or "研究报告"
        r["_tag"] = tag
        tag_count[tag] = tag_count.get(tag, 0) + 1
        sname = normalize_series(r["series"]) if r.get("series") else ""
        r["_series"] = sname
        if sname:
            series_count[sname] = series_count.get(sname, 0) + 1
        dom = r.get("domain") or "tech"
        r["_domain"] = dom
        domain_count[dom] = domain_count.get(dom, 0) + 1

    def toc_row(r, num):
        delay = (num % 12) * 0.04
        esc_tag = html_mod.escape(r["_tag"], quote=True)
        esc_series = html_mod.escape(r["_series"], quote=True)
        dom = r["_domain"]
        esc_dom = html_mod.escape(DOMAIN_LABEL.get(dom, dom), quote=True)
        badges = (f'<span class="row-domain {dom}" data-type="domain" data-f="{dom}">'
                  f'{esc_dom}</span> '
                  f'<span class="row-tag" data-type="tag" data-f="{esc_tag}">{esc_tag}</span>')
        if r["_series"]:
            badges += (f' <span class="row-series" data-type="series" data-f="{esc_series}">'
                       f'《{esc_series}》第 {r.get("series_order") or "?"} 卷</span>')
        sub = (f'<span class="toc-sub">{html_mod.escape(r["subtitle"])}</span>'
               if r.get("subtitle") else "")
        updated = (' <span class="toc-updated">订</span>' if r.get("updated") else "")
        return (f'<a class="toc-item reveal" style="--d:{delay:.2f}s" href="/research/reports/{r["file"]}"'
                f' data-tag="{esc_tag}" data-series="{esc_series}" data-domain="{dom}">'
                f'<span class="toc-num">{num:02d}</span>'
                f'<span class="toc-main"><span class="toc-line">'
                f'<span class="toc-title">{html_mod.escape(r["title"])}</span>{badges}</span>{sub}</span>'
                f'<span class="toc-dots"></span>'
                f'<span class="toc-date">{r["date_display"]}{updated}</span></a>')

    rows = [toc_row(r, i) for i, r in enumerate(research, 1)]

    # 筹码：全部 + tag（按数量降序）+ 丛书（按数量降序）；小 tag 不再合并——数量诚实展示
    chips = [f'<span class="chip on" data-type="all" data-f="">全部<span class="n">{len(research)}</span></span>']
    for dom in ("tech", "design", "ephemeral"):
        dn = domain_count.get(dom, 0)
        if dn:
            chips.append(f'<span class="chip chip-domain {dom}" data-type="domain" data-f="{dom}">'
                         f'{html_mod.escape(DOMAIN_LABEL.get(dom, dom))}<span class="n">{dn}</span></span>')
    for tag, n in sorted(tag_count.items(), key=lambda kv: (-kv[1], kv[0])):
        chips.append(f'<span class="chip" data-type="tag" data-f="{html_mod.escape(tag, quote=True)}">'
                     f'{html_mod.escape(tag)}<span class="n">{n}</span></span>')
    for sname, n in sorted(series_count.items(), key=lambda kv: (-kv[1], kv[0])):
        chips.append(f'<span class="chip chip-series" data-type="series" data-f="{html_mod.escape(sname, quote=True)}">'
                     f'《{html_mod.escape(sname)}》<span class="n">{n}</span></span>')

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
    """从 reports 表查全部报告，按日期倒序（P1：正则刮 HTML 退休）。
    DB 为空时回退扫描 public/reports/（backfill 运行前的过渡期兼容）。"""
    # ── 主路径：DB 查（P1 起的数据源）──
    try:
        conn = store.get_db()
        rows = store.list_reports_from_db(conn)
        conn.close()
        if rows:
            return rows
    except Exception:
        pass  # DB 不可用时回退文件扫描

    # ── 回退路径：文件扫描（backfill 前的过渡兼容，P2 移除）──
    result = []
    if not REPORTS_DIR.exists():
        return result
    for f in sorted(REPORTS_DIR.glob("*.html"), reverse=True):
        name = f.name
        date_match = re.match(r"(\d{4}-\d{2}-\d{2})", name)
        date = date_match.group(1) if date_match else "0000-00-00"
        date_display = date[5:]
        content = f.read_text(encoding="utf-8")
        title_match = re.search(r"<title>(.+?)</title>", content)
        title = title_match.group(1) if title_match else name
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
        domain_match = re.search(r'<meta name="domain" content="([^"]*)"', content)
        result.append({"file": name, "title": title, "tag": tag, "subtitle": subtitle,
                       "date": date, "date_display": date_display, "updated": updated,
                       "series": html_mod.unescape(series_match.group(1)) if series_match else "",
                       "series_order": int(order_match.group(1)) if order_match else 0,
                       "series_total": int(total_match.group(1)) if total_match else 0,
                       "template": tpl_match.group(1) if tpl_match else "book",
                       "domain": domain_match.group(1) if domain_match else "tech"})
    return result


# ============================================================
# 按需组件注入
# ============================================================
def component_head(content: str) -> tuple:
    """返回 (head 注入片段, 命中的组件名列表)。"""
    hits = [name for name, comp in COMPONENTS.items() if comp["detect"](content)]
    head = "\n    ".join(tag for name in hits for tag in COMPONENTS[name]["head"])
    return head, hits


# ============================================================
# 门禁
# ============================================================
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
    used = set()
    for attr in re.findall(r"class\s*=\s*[\"']([^\"']*)[\"']", content):
        used |= set(attr.split())
    for c in sorted(used & DEPRECATED_CLASSES.keys()):
        errors.append(f"已弃用组件 .{c}（模板已删除其样式）：改用 {DEPRECATED_CLASSES[c]}")

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


# ============================================================
# 丛书
# ============================================================
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
        links += f'<a class="vol prev" href="{prev_r["file"]}">← 上一卷 · {html_mod.escape(prev_r["title"])}</a>'
    if next_r:
        links += f'<a class="vol next" href="{next_r["file"]}">下一卷 · {html_mod.escape(next_r["title"])} →</a>'
    return f'<nav class="volume-nav" data-series="{html_mod.escape(normalize_series(series))}">{links}</nav>'


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


# ============================================================
# 创建/修订报告
# ============================================================
def create_report(title: str, slug: str, tag: str, content: str, subtitle: str = "",
                  series: str = "", order: int = 0, template: str = DEFAULT_TEMPLATE,
                  base_url: str = "", domain: str = "tech",
                  images: list | None = None, client_ip: str = "127.0.0.1") -> dict:
    """创建或修订报告（P1：L0 快照 → 渲染 → DB upsert）。
    同 slug 已存在 → 覆盖原文件、保留原日期、rev 递增。"""
    today = datetime.now().strftime("%Y-%m-%d")

    # ── 确定文件名与 created 标记 ──
    existing = _existing_for_slug(slug)
    warnings = []
    if existing:
        filename = existing[-1].name
        created = False
        if len(existing) > 1:
            warnings.append(f"同 slug 存在 {len(existing)} 份历史文件，覆盖最新 {filename}，其余建议人工清理")
    else:
        filename = f"{today}-{slug}.html"
        created = True

    # ── L0：不可变快照存档 ──
    payload = {
        "title": title, "slug": slug, "tag": tag, "content": content,
        "subtitle": subtitle, "series": series, "order": order,
        "template": template, "domain": domain,
    }
    if images:
        payload["images"] = [{"name": img.get("name", "")} for img in images]
    rev = l0_ingest.ingest_submission(slug, payload, client_ip=client_ip, provenance="api")

    # ── L0 图片原件保存 ──
    if images:
        l0_ingest.save_l0_images(slug, rev, images)

    # ── 渲染报告（模板 + 门禁 + 组件注入，逻辑不变）──
    tpl_path = template_path(template)
    tpl = tpl_path.read_text(encoding="utf-8")

    meta_tags = []
    meta_tags.append(f'<meta name="template" content="{template}">')
    meta_tags.append(f'<meta name="domain" content="{domain}">')
    if not created:
        meta_tags.append(f'<meta name="updated" content="{today}">')
    series = normalize_series(series)
    if series:
        meta_tags.append(f'<meta name="series" content="{html_mod.escape(series)}">')
        meta_tags.append(f'<meta name="series-order" content="{order}">')
        meta_tags.append(f'<meta name="series-total" content="1">')
    meta_html = "\n".join(meta_tags)

    series_badge = (f'<span class="series-badge">《{html_mod.escape(series)}》第 {order} 卷 · 共 1 卷</span>'
                    if series else "")
    volume_nav = f'<nav class="volume-nav" data-series="{html_mod.escape(series)}"></nav>' if series else ""

    comp_head, comp_hits = component_head(content)
    html_out = render(tpl,
        TITLE=title, HERO_TAG=tag, SUBTITLE=subtitle, DATE=today,
        CONTENT=content, COMPONENT_HEAD=comp_head, META=meta_html,
        SERIES_BADGE=series_badge, VOLUME_NAV=volume_nav,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / filename
    report_path.write_text(html_out, encoding="utf-8")
    (REPORTS_DIR / (filename[:-5] + ".md")).write_text(html_to_md(html_out), encoding="utf-8")

    # ── L1：DB upsert reports 表（P1：替代正则刮 HTML）──
    conn = store.get_db()
    try:
        # 获取 submission id（刚插入的那条）
        sub_row = conn.execute(
            "SELECT id FROM submissions WHERE slug=? AND rev=?", (slug, rev)).fetchone()
        sub_id = sub_row[0] if sub_row else 0
        created_date = filename[:10] if len(filename) >= 10 else today
        updated_date = today if not created else ""
        store.upsert_report(conn, slug, filename, title, tag, subtitle, domain,
                            template, series, order, created_date, updated_date, sub_id)
        conn.commit()
    finally:
        conn.close()

    # ── 重建索引 ──
    reports = list_reports()
    index_html = build_index(reports)
    INDEX_PATH.write_text(index_html, encoding="utf-8")

    if series:
        maintain_series_siblings(series)

    result = {
        "ok": True,
        "file": filename,
        "created": created,
        "components": comp_hits,
        "warnings": warnings,
        "url": f"{base_url}/research/reports/{filename}" if base_url else f"/research/reports/{filename}",
    }
    if not created:
        result["updated"] = today
    return result
