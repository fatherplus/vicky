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
from . import ui
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
REPORT_CATEGORIES = config.REPORT_CATEGORIES
NARRATIVES = config.NARRATIVES
COMPONENTS = config.COMPONENTS
FIGURE_RE = config.FIGURE_RE
AI_WORDS = config.AI_WORDS
CLOSED_LOOP_OK_RE = config.CLOSED_LOOP_OK_RE
EMOJI_RE = config.EMOJI_RE
EMOJI_WHITELIST = config.EMOJI_WHITELIST
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


# _INDEX_TPL 已迁出到 views/index.html，通过 ui.load_view("index.html") 加载
# 保留模块级别名供测试兼容（tests/util.py 注入 _INDEX_TPL 属性）
_INDEX_TPL = None  # P3 前端抢救：启动时由 _init_index_tpl() 填充


def _annotate_rows(rows: list, default_tag: str) -> None:
    """给目录行打 _tag/_category/_project 供 ui 构建器使用。"""
    for r in rows:
        r["_tag"] = (r.get("tag") or default_tag).strip() or default_tag
        r["_category"] = r.get("category") or "research"
        r["_project"] = r.get("project") or ""


def build_index(reports: list[dict]) -> str:
    """生成四区书风格索引页（重构蓝图 §04）——技术文库 / 项目空间 / 简报·知识库。
    - hidden=1 与 legacy design（category=design）不进入任何区；
    - 卷首（关于本书）确定性地 = 项目 README（config.DESIGN_DOC_SLUG），不再由 META tag 聚合（防多本挂顶）；
    - 技术文库（research）与简报（brief）时间倒序；项目空间（tech-solution 带 project）
      按项目聚合，链到 /projects/{slug}.html；
    - Alpine 前端筛选：分类 / 项目 / 标签 + 关键词，默认时间倒序（行序即 server 时间倒序）。"""
    visible = [r for r in reports if not r.get("hidden")]
    front = [r for r in visible if r["slug"] == config.DESIGN_DOC_SLUG]
    research = [r for r in visible if r.get("category") == "research"]
    briefs = [r for r in visible if r.get("category") == "brief"]
    # 项目区聚合 tech-solution 且带 project（蓝图 §04-B：项目空间 = 方案归档；arch-doc 已退场）
    project_docs = [r for r in visible
                    if r.get("project") and r.get("category") == "tech-solution"]
    _annotate_rows(research, "研究报告")
    _annotate_rows(briefs, "简报")
    for docs in _group_projects(project_docs).values():
        _annotate_rows(docs, "方案")

    # 标签筹码计数（技术文库 + 简报，按计数倒序）
    tag_counts = {}
    for r in research + briefs:
        tag = r["_tag"]
        tag_counts[tag] = tag_counts.get(tag, 0) + 1
    tag_list = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))

    # 项目卡片 + 项目筹码（按最新日期倒序）
    proj_map = _group_projects(project_docs)
    proj_sorted = sorted(proj_map.items(),
                         key=lambda kv: (kv[1][0]["date"] if kv[1] else ""), reverse=True)
    cards = [ui.project_card(name, docs) for name, docs in proj_sorted]
    proj_chips = [(name, len(docs)) for name, docs in proj_sorted]

    zone_total = len(research) + len(briefs) + len(project_docs)
    cat_chips = ui.category_chips_html(zone_total, len(research), len(briefs), len(proj_map))
    filter_chips = ui.filter_chips_html(tag_list, proj_chips)
    frontmatter = ui.frontmatter_html(front)
    research_rows = [ui.toc_row(r, i) for i, r in enumerate(research, 1)]
    brief_rows = [ui.toc_row(r, i) for i, r in enumerate(briefs, 1)]
    year = (research + briefs + project_docs)[0]["date"][:4] \
        if (research + briefs + project_docs) else str(datetime.now().year)

    tpl = ui.load_view("index.html")
    return (tpl
            .replace("__FRONTMATTER__", frontmatter)
            .replace("__CAT_CHIPS__", "\n    ".join(cat_chips))
            .replace("__FILTER_CHIPS__", "\n    ".join(filter_chips))
            .replace("__RESEARCH_ROWS__", "\n    ".join(research_rows))
            .replace("__BRIEF_ROWS__", "\n    ".join(brief_rows))
            .replace("__PROJECT_CARDS__", "\n    ".join(cards))
            .replace("__RESEARCH_N__", str(len(research)))
            .replace("__BRIEF_N__", str(len(briefs)))
            .replace("__PROJECT_N__", str(len(proj_map)))
            .replace("__TOPICS_N__", str(count_knowledge_topics()))
            .replace("__TOTAL__", str(zone_total))
            .replace("__YEAR__", year))


def _group_projects(project_docs: list) -> dict:
    """按 project 字段分组（保持每组内时间倒序），空 project 不入组。"""
    out = {}
    for r in project_docs:
        name = (r.get("project") or "").strip()
        if not name:
            continue
        out.setdefault(name, []).append(r)
    return out


# ============================================================
# 核心操作
# ============================================================
def list_reports() -> list[dict]:
    """从 reports 表查全部报告，按日期倒序（P1：12 个正则刮 HTML 退休）。"""
    conn = store.get_db()
    try:
        return store.list_reports_from_db(conn)
    finally:
        conn.close()


# ============================================================
# 按需组件注入
# ============================================================
def component_head(content: str) -> tuple:
    """返回 (head 注入片段, 命中的组件名列表)。"""
    hits = [name for name, comp in COMPONENTS.items() if comp["detect"](content)]
    head = "\n    ".join(tag for name in hits for tag in COMPONENTS[name]["head"])
    return head, hits


# ============================================================
# 骨架分类门禁 + tech-solution 代码块红线（重构蓝图 2026-08-12 §03）
# ============================================================
def validate_category(category: str) -> str | None:
    """骨架分类门禁：category 必须是四大分类之一（domain 语义已彻底删除，
    不再有 legacy 映射兼容）。非法返回错误文案，合法返回 None。"""
    category = (category or "").strip() or "research"
    if category in REPORT_CATEGORIES:
        return None
    return f"category 必须是 {REPORT_CATEGORIES} 之一"


# tech-solution 代码块红线：方案止步于架构与表结构示意，不出现大段实施代码
CODE_BLOCK_RE = re.compile(r"<pre>\s*<code[^>]*>([\s\S]*?)</code>\s*</pre>", re.I)
CODE_LINE_LIMIT = 15  # 超过约 15 行 → 疑似实施代码


def _code_block_line_count(content: str) -> int:
    """全部 <pre><code> 代码块中最大行数（去空行）；无代码块返回 0。"""
    max_lines = 0
    for m in CODE_BLOCK_RE.findall(content or ""):
        lines = [ln for ln in m.split("\n") if ln.strip()]
        max_lines = max(max_lines, len(lines))
    return max_lines


def code_block_warning(content: str, category: str) -> str | None:
    """tech-solution 软提醒：内容中出现 <pre><code> 且代码块超过约 15 行 →
    「技术方案不应包含实施代码（止步于架构与表结构示意）」。非 tech-solution 不告警。"""
    if category != "tech-solution":
        return None
    lines = _code_block_line_count(content)
    if lines > CODE_LINE_LIMIT:
        return (f"tech-solution 不应包含实施代码：检测到 {lines} 行代码块"
                f"（方案止步于架构与表结构示意）")
    return None


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


def _ai_word_stats(text: str) -> tuple[list, int]:
    """AI 腔词命中统计（「闭环」做正当技术语境豁免：生产-消费闭环等不算）。
    返回 (命中词列表, 命中总次数)。"""
    hits, total = [], 0
    for w in AI_WORDS:
        cnt = text.count(w)
        if cnt == 0:
            continue
        if w == "闭环":
            cnt -= len(CLOSED_LOOP_OK_RE.findall(text))  # 豁免正当技术语境
            if cnt <= 0:
                continue
        hits.append(w)
        total += cnt
    return hits, total


def validate_content(content: str, title: str = "", template: str = "",
                     category: str = "") -> tuple:
    """表述规范门禁 + 软提醒（spec §7）。返回 (errors, warnings)：
    errors 触发 400 拒收；warnings 只随响应返回，agent 自觉修订。
    category="tech-solution" 时追加实施代码软提醒（代码块超过约 15 行）。
    重构蓝图：category 参数可选（不传 = 不检分类相关提醒），签名向后兼容。"""
    errors = []
    # --- errors：机器可判定的硬伤 ---
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
    hit, ai_total = _ai_word_stats(text)
    if hit:
        warnings.append(f"AI 腔词 ×{ai_total}：{'、'.join(hit)}（禁止清单）")
    emoji = [e for e in EMOJI_RE.findall(text) if e not in EMOJI_WHITELIST]
    if emoji:
        warnings.append(f"标题/正文含 emoji ×{len(emoji)}")
    if COMPONENTS["mermaid"]["detect"](content) and 'class="figure"' not in content:
        warnings.append("检测到 mermaid 但无任何 figure 装裱")
    bare = [m for m in SECTION_RE.findall(content) if _section_lacks_wrap(m[1])]
    if bare:
        warnings.append(f"{len(bare)} 个 section 缺 .wrap 版心（server 已自动补；提交时请包 <div class=\"wrap\">）")
    cw = code_block_warning(content, category)
    if cw:
        warnings.append(cw)
    return errors, warnings


SECTION_RE = re.compile(r"(<section\b[^>]*>)([\s\S]*?)</section>", re.I)


def _section_lacks_wrap(inner: str) -> bool:
    return not re.search(r'class\s*=\s*["\'][^"\']*\bwrap\b', inner)


def normalize_wrap(content: str) -> str:
    """section 缺 .wrap 版心时 server 自动补——版心宽/内边距全挂 .wrap，缺了整页裸奔。"""
    def fix(m):
        head, inner = m.group(1), m.group(2)
        if not _section_lacks_wrap(inner):
            return m.group(0)
        return f'{head}<div class="wrap">{inner}</div></section>'
    return SECTION_RE.sub(fix, content)


def _existing_for_slug(slug: str) -> list:
    """按文件名格式精确匹配同 slug 报告（杜绝后缀误命中）"""
    pat = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(slug)}\.html$")
    return sorted(f for f in REPORTS_DIR.glob("*.html") if pat.match(f.name))


# ============================================================
# 创建/修订报告
# ============================================================
def create_report(title: str, slug: str, tag: str, content: str, subtitle: str = "",
                  template: str = DEFAULT_TEMPLATE,
                  base_url: str = "",
                  images: list | None = None, client_ip: str = "127.0.0.1",
                  category: str = "", narrative: str = "", project: str = "",
                  mark_updated: bool = True, skip_content_gate: bool = False) -> dict:
    """创建或修订报告（P1：L0 快照 → 渲染 → DB upsert）。
    category（三分类骨架）/ narrative（叙事方式）/ project（归档维度）三字段显式指定，
    与模板正交；category 非法直接拒收（validate_category，domain 语义已彻底删除），
    tech-solution 内容含大段实施代码给 warning。同 slug 已存在 → 覆盖原文件、保留原日期、rev 递增。
    mark_updated=False 用于元数据更新（PATCH）：不追加 updated meta、不触发「订」徽章。
    skip_content_gate=True（PATCH 元数据）：content 原样保留，跳过 content 硬门禁重校验
    （旧报告可能有历史遗留裸 table，当初已发布；元数据更新不该因 content 旧内容被拒）。"""
    today = datetime.now().strftime("%Y-%m-%d")

    # ── 骨架分类门禁（重构蓝图 §02）：未指定 category 时默认 research；
    # web.py 预检后可传 category；此处兜底直调方，防绕门禁 ──
    category = (category or "").strip() or "research"
    cat_err = validate_category(category)
    if cat_err:
        raise ValueError(cat_err)

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

    # ── 模板级硬契约门禁 ──
    # web.py 已预检过（400），此处兜底直调方（cli/测试），防止绕门禁
    violations, _ = validate_content(content, title, template, category)
    if violations and not skip_content_gate:
        raise ValueError("内容不符合表述规范：" + "；".join(violations))

    # ── tech-solution 实施代码软提醒（方案止步于架构与表结构示意）──
    cw = code_block_warning(content, category)
    if cw:
        warnings.append(cw)

    # ── L0：不可变快照存档 ──
    payload = {
        "title": title, "slug": slug, "tag": tag, "content": content,
        "subtitle": subtitle,
        "template": template,
        "category": category, "narrative": narrative, "project": project,
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
    if not created and mark_updated:
        meta_tags.append(f'<meta name="updated" content="{today}">')
    meta_html = "\n".join(meta_tags)

    content = normalize_wrap(content)
    comp_head, comp_hits = component_head(content)
    html_out = render(tpl,
        TITLE=title, HERO_TAG=tag, SUBTITLE=subtitle, DATE=today,
        CONTENT=content, COMPONENT_HEAD=comp_head, META=meta_html,
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
        if not created and not mark_updated:
            # 元数据更新不改 updated_date：不触发「订」徽章，保留原修订痕迹
            prev = store.get_report_by_slug(conn, slug)
            updated_date = (prev or {}).get("updated_date") or ""
        else:
            updated_date = today if not created else ""
        store.upsert_report(conn, slug, filename, title, tag, subtitle,
                            template=template,
                            created_date=created_date, updated_date=updated_date,
                            current_rev=sub_id,
                            category=category, narrative=narrative, project=project)
        conn.commit()
    finally:
        conn.close()

    # ── 重建索引 ──
    reports = list_reports()
    index_html = build_index(reports)
    INDEX_PATH.write_text(index_html, encoding="utf-8")
    refresh_home()
    refresh_projects()

    result = {
        "ok": True,
        "file": filename,
        "created": created,
        "components": comp_hits,
        "warnings": warnings,
        "url": f"{base_url}/reports/{filename}" if base_url else f"/reports/{filename}",
    }
    if not created:
        result["updated"] = today
    return result


# 可经 PATCH 更新的元数据字段（不含 content——正文修订走 POST /api/reports）
META_UPDATE_FIELDS = ("title", "subtitle", "tag", "category", "narrative",
                      "project", "template")


def update_report_meta(slug: str, updates: dict) -> dict:
    """轻量更新报告元数据（不动 content、不触发「订」徽章）。
    读 L0 快照拿原 payload（含 content），合并新元数据后复用 create_report 渲染管线
    （mark_updated=False 保持 updated_date 不变）。返回 create_report 结果 + updated_fields。
    slug 不存在返回 {"ok": False, "error"}。"""
    payload = l0_ingest.load_report_payload(slug)
    if not payload:
        return {"ok": False, "error": f"slug '{slug}' 不存在"}
    changed = {k: updates[k] for k in META_UPDATE_FIELDS if k in updates}
    if not changed:
        return {"ok": False, "error": f"无可更新字段：仅接受 {', '.join(META_UPDATE_FIELDS)}"}
    merged = {**payload, **changed}
    result = create_report(
        title=merged.get("title", ""), slug=slug, tag=merged.get("tag", ""),
        content=merged.get("content", ""), subtitle=merged.get("subtitle", ""),
        template=merged.get("template") or DEFAULT_TEMPLATE,
        category=merged.get("category", ""), narrative=merged.get("narrative", ""),
        project=merged.get("project", ""), mark_updated=False, skip_content_gate=True)
    result["updated_fields"] = sorted(changed.keys())
    return result

# ============================================================
# 从 L0 快照重渲染（render --all / --slug，P5 实现）
# 不创建新快照——仅从已有 L0 数据再生 L1 产物。
# ============================================================
def render_from_l0(slug: str) -> dict:
    """从 L0 快照再生单份报告的 HTML + MD，不创建新快照。
    返回 {"ok": bool, "file": str, "error": str | None}。"""
    conn = store.get_db()
    try:
        # 查 reports 表获取当前文件名与 current_rev
        rep = conn.execute(
            "SELECT file, title, tag, subtitle, template, "
            "current_rev FROM reports WHERE slug=?", (slug,)).fetchone()
        if not rep:
            return {"ok": False, "error": f"slug '{slug}' 不在 reports 表中——先 backfill"}

        filename, title, tag, subtitle, template, cur_rev = rep

        # 从 submissions 表取快照路径
        sub = conn.execute(
            "SELECT payload_path FROM submissions WHERE id=?", (cur_rev,)).fetchone()
        if not sub:
            return {"ok": False, "error": f"submission id={cur_rev} 不存在"}

        payload_path = Path(sub[0])
        if not payload_path.exists():
            return {"ok": False, "error": f"快照文件不存在: {payload_path}"}
    finally:
        conn.close()

    snap = json.loads(payload_path.read_text(encoding="utf-8"))
    data = snap["payload"]
    content = data["content"]
    date_str = filename[:10]  # 从文件名取原始日期，不再用今天

    # ── 渲染模板（复用 create_report 的渲染逻辑，但不写 L0 快照）──
    tpl_path = template_path(template)
    tpl = tpl_path.read_text(encoding="utf-8")

    meta_tags = [
        f'<meta name="template" content="{template}">',
    ]
    meta_html = "\n".join(meta_tags)

    content = normalize_wrap(content)
    comp_head, comp_hits = component_head(content)
    html_out = render(tpl,
        TITLE=title, HERO_TAG=tag, SUBTITLE=subtitle, DATE=date_str,
        CONTENT=content, COMPONENT_HEAD=comp_head, META=meta_html,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / filename
    report_path.write_text(html_out, encoding="utf-8")
    (REPORTS_DIR / (filename[:-5] + ".md")).write_text(html_to_md(html_out), encoding="utf-8")

    return {"ok": True, "file": filename, "components": comp_hits}


def rebuild_index():
    """重建索引页 + 首页 + 项目页（render --all 后调用）。
    审核治理（curate 软下架/硬删除）也走此入口——项目页随之重算，hidden 文档自动消失。"""
    reports = list_reports()
    INDEX_PATH.write_text(build_index(reports), encoding="utf-8")
    refresh_home()
    refresh_projects()


# ============================================================
# 项目空间（重构蓝图 §04-B）——public/projects/{slug}.html
# 每项目一页：项目名 + 文档时间线（倒序、tech-solution 类型徽章）+ 页间互链。
# 聚合口径与索引页项目空间区一致：tech-solution 且带 project。
# ============================================================
def build_project_page(project: dict, docs: list[dict], all_projects: list[dict]) -> str:
    """单项目页组装：文档时间线（倒序）+ 页间互链（其他项目）。
    docs 已按时间倒序且限定 tech-solution；空文档给占位提示。"""
    rows_html = "\n    ".join(ui.project_doc_row(r, i) for i, r in enumerate(docs, 1))
    if not docs:
        rows_html = '<div class="zone-empty">暂无已归档文档（tech-solution）</div>'
    year = docs[0]["date"][:4] if docs else str(datetime.now().year)
    pname = project["project"]
    has_arch = store.get_arch_graph(pname) is not None
    tpl = ui.load_view("project.html")
    return (tpl
            .replace("__PROJECT_NAME__", html_mod.escape(pname))
            .replace("__COUNT__", str(len(docs)))
            .replace("__YEAR__", year)
            .replace("__ARCH_ENTRY__", ui.arch_entry_html(pname, has_arch))
            .replace("__DOCS__", rows_html)
            .replace("__PROJECT_NAV__", ui.project_nav(all_projects, pname)))


def build_project_pages() -> int:
    """全量重建 public/projects/{slug}.html——每项目一页，返回生成页数。
    随发布（create_report）与全量重渲染（rebuild_index）触发；
    审核治理（curate 软下架/硬删除）经 rebuild_index 一并生效。"""
    conn = store.get_db()
    try:
        projects = store.list_projects(conn)  # 已排除 hidden 与空 project
        docs_by = {p["project"]: store.list_reports(conn, project=p["project"])
                   for p in projects}
    finally:
        conn.close()
    proj_dir = PUBLIC_DIR / "projects"
    proj_dir.mkdir(parents=True, exist_ok=True)
    for p in projects:
        docs = [d for d in docs_by.get(p["project"], [])
                if d.get("category") == "tech-solution"]
        _annotate_rows(docs, "方案")
        page = build_project_page(p, docs, projects)
        (proj_dir / f"{ui.project_slug(p['project'])}.html").write_text(
            page, encoding="utf-8")
    # 清理孤儿页：项目最后一篇被下架/删除后，对应项目页一并移除
    expected = {f"{ui.project_slug(p['project'])}.html" for p in projects}
    for f in proj_dir.glob("*.html"):
        if f.name not in expected:
            f.unlink()
    return len(projects)


def refresh_projects():
    """刷新 public/projects/ 全部项目页（与索引/首页同触发点）。"""
    build_project_pages()


# ============================================================
# 首页门户（P2）——public/home.html，与索引页同目录
# 占位符：__RESEARCH_N__ / __PROJECT_N__ / __BRIEF_N__ / __TOTAL_TOPICS__ / __YEAR__
# ============================================================
def count_knowledge_topics() -> int:
    """knowledge/ 主题目录数：有 overview.md 的才算（与 GET /api/knowledge 列表口径一致）。
    目录扁平 knowledge/{topic}/（B 阶段重构，domain 语义已彻底删除）。"""
    kdir = config.KNOWLEDGE_DIR
    total = 0
    if kdir.exists():
        for td in sorted(kdir.iterdir()):
            if not td.is_dir() or td.name.startswith("."):
                continue
            if (td / "overview.md").exists():
                total += 1
    return total


def build_home() -> str:
    """生成首页门户：四区计数（文库篇数 / 项目数 / 简报数）+ 知识主题数 + 总篇数，
    填 views/home.html。计数一律排除 hidden（store.list_reports / list_projects 默认过滤）。"""
    conn = store.get_db()
    try:
        reports = store.list_reports(conn)
        research_n = sum(1 for r in reports if r.get("category") == "research")
        brief_n = sum(1 for r in reports if r.get("category") == "brief")
        project_n = len(store.list_projects(conn))
    finally:
        conn.close()
    tpl = ui.load_view("home.html")
    return (tpl
            .replace("__RESEARCH_N__", str(research_n))
            .replace("__BRIEF_N__", str(brief_n))
            .replace("__PROJECT_N__", str(project_n))
            .replace("__TOTAL_REPORTS__", str(len(reports)))
            .replace("__TOTAL_TOPICS__", str(count_knowledge_topics()))
            .replace("__YEAR__", str(datetime.now().year)))


def refresh_home():
    """刷新 public/home.html（与索引页同目录；随发布与 cli render 重渲染调用）。"""
    home = config.INDEX_PATH.parent / "home.html"
    home.write_text(build_home(), encoding="utf-8")
