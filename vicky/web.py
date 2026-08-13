"""
Web 路由层——FastAPI 薄路由 + 静态自伺服（重构蓝图 2026-08-12 §05）。

换壳不换核心：l0-l3/store/curate 业务层不动；原 http.server Handler 的
路径与响应 JSON 形状全部保留，另按蓝图新增：
- GET  /api/narratives            叙事方式选型库（skill/NARRATIVES.md）
- GET  /api/projects              项目空间清单（store.list_projects）
- POST /api/reports/{slug}/hide   软下架/恢复（curate.hide_report）
- POST /api/reports/{slug}/delete 硬删除级联（curate.hard_delete_report）
- GET  /api/knowledge/audit       知识条目审核视图（curate.knowledge_audit）
- POST /api/knowledge/items/{id}/status  单条知识 active/hidden
- GET  /api/knowledge?q=…         FTS 三阶段检索（原 MCP knowledge_query 的 HTTP 化）
- POST /api/reports 增受 category / narrative / project 三字段（domain 语义已彻底删除，未传 category 默认 research）

MCP 已删除（2026-08-12 重构）：agent 交互走 skill/vicky-writer + 直接 HTTP。

静态自伺服行为与旧版一致：public/ 根级直出、/research/* 兼容前缀、
路径穿越 403、/ → home.html、目录 → index.html、HTML no-cache。
config.* 一律请求时读取（tests/tmp_env monkey-patch 依赖此约定）。

启动: python3 -m vicky.web [port] [host]
"""

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response

from . import config
from . import curate
from . import knowledge_query
from . import l1_publish
from . import l2_distill  # /api/knowledge 列表条目读 frontmatter 补 category/tags
from . import l3_feedback
from . import store
from . import ui  # D 阶段：project_slug 用于 POST /api/projects slug 生成
from . import arch  # B2 阶段：架构导航器 API（骨架/模块读写 + 搜索）
from . import seed  # 启动自举：空库部署从源码种子创建 README（序）
from .l0_ingest import (clean_slug, validate_slug_not_empty, save_images,
                        load_report_payload)

app = FastAPI(title="Vicky", version="2.0", docs_url="/docs", redoc_url=None)


# ============================================================
# 响应助手（与旧 Handler 同形状：ensure_ascii=False、ACAO *）
# ============================================================
def _json(data: dict, status: int = 200) -> Response:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(content=body, status_code=status,
                    media_type="application/json; charset=utf-8",
                    headers={"Access-Control-Allow-Origin": "*"})


def _serve_file(path: Path, content_type: str, download_name: str = None) -> Response:
    if not path.exists():
        return _json({"error": "not found"}, 404)
    body = path.read_bytes()
    headers = {"Access-Control-Allow-Origin": "*"}
    if download_name:
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
    return Response(content=body, status_code=200, media_type=content_type, headers=headers)


@app.middleware("http")
async def cors_preflight(request: Request, call_next):
    """CORS：旧 Handler 对 API 响应带 ACAO *；OPTIONS 预检直接 204。"""
    if request.method == "OPTIONS":
        return Response(status_code=204, headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"})
    resp = await call_next(request)
    resp.headers.setdefault("Access-Control-Allow-Origin", "*")
    return resp


# ============================================================
# GET /api/*
# ============================================================
@app.get("/api/health")
def api_health():
    return _json({"ok": True, "service": "vicky"})


@app.get("/api/reports")
def api_reports_list():
    return _json({"ok": True, "reports": l1_publish.list_reports()})


@app.get("/api/guide")
def api_guide():
    return _serve_file(config.GUIDE_PATH, "text/markdown; charset=utf-8")


@app.get("/api/skill")
def api_skill():
    """下载对外分发的规范 skill（vicky-writer/SKILL.md，含 name+description frontmatter）。
    区别于 /api/guide（详细写作参考 AGENT-GUIDE.md）。"""
    return _serve_file(config.SKILL_PATH, "text/markdown; charset=utf-8", "SKILL.md")


@app.get("/api/narratives")
def api_narratives():
    """叙事方式选型库（重构蓝图 §03）——agent 写前选叙事的依据。"""
    return _serve_file(config.REPO_DIR / "skill" / "NARRATIVES.md", "text/markdown; charset=utf-8")


@app.get("/api/template")
def api_template(name: str = ""):
    name = name or config.DEFAULT_TEMPLATE
    try:
        return _serve_file(l1_publish.template_path(name), "text/html; charset=utf-8")
    except KeyError as e:
        return _json({"ok": False, "error": str(e)}, 404)


@app.get("/api/templates")
def api_templates_list():
    return _json({"ok": True, "templates": l1_publish.list_templates()})


@app.get("/api/principles")
def api_principles():
    return _serve_file(config.REPO_DIR / "skill" / "NARRATIVE-PRINCIPLES.md",
                       "text/markdown; charset=utf-8")


@app.get("/api/projects")
def api_projects():
    """项目空间清单：已建项目元信息（projects 表）+ 报告聚合计数（reports 表）。
    合并逻辑：以 projects 表为主，补充 reports 聚合的 count/latest；
    仅有报告聚合、无元信息的项目也列出（count/latest 来自报告，其余字段空）。"""
    conn = store.get_db()
    try:
        metas = store.list_projects_meta(conn)  # 已建项目元信息
        agg_rows = store.list_projects(conn)     # 报告聚合计数
    finally:
        conn.close()
    # 报告聚合 → {project_slug: {count, latest}} 索引
    agg_map = {a["project"]: {"count": a["count"], "latest": a["latest"]} for a in agg_rows}
    # 以 projects 表为主干，补充报告计数
    result = []
    seen = set()
    for m in metas:
        slug = m["slug"]
        seen.add(slug)
        agg = agg_map.get(slug, {})
        result.append({
            "slug": slug,
            "name": m["name"],
            "description": m.get("description") or "",
            "count": agg.get("count", 0),
            "latest": agg.get("latest", ""),
            "created_at": m.get("created_at", ""),
        })
    # 仅有报告聚合、无 projects 元信息的也列出（向后兼容）
    for slug, agg in agg_map.items():
        if slug not in seen:
            result.append({
                "slug": slug,
                "name": slug,
                "description": "",
                "count": agg["count"],
                "latest": agg["latest"],
                "created_at": "",
            })
    return _json({"ok": True, "projects": result})


@app.get("/api/knowledge/feedback")
def api_feedback_list(topic: str = "", status: str = ""):
    """L3 账本可查。"""
    rows, err = l3_feedback.list_feedbacks_api(topic=topic, status=status)
    if err:
        return _json({"ok": False, "error": err}, 400)
    return _json({"ok": True, "feedbacks": rows})


@app.get("/api/knowledge/audit")
def api_knowledge_audit(topic: str = ""):
    """知识条目审核视图（重构蓝图 §04）：含 hidden，人工逐条把控质量。"""
    return _json({"ok": True, "items": curate.knowledge_audit(topic or None)})


@app.get("/api/knowledge")
def api_knowledge(topic: str = "", q: str = "",
                  budget: str = "", category: str = "", tag: str = ""):
    """知识库：q 非空 → FTS 三阶段检索（原 MCP knowledge_query 的 HTTP 化）；
    无参列全部页；topic 查单页。目录扁平 knowledge/{topic}/（domain 语义已彻底删除）。"""
    if q.strip():
        result = knowledge_query.query({"q": q, "budget": budget,
                                        "category": category, "tag": tag})
        return _json({"ok": True, **result})

    kdir = config.REPO_DIR / "knowledge"
    if not topic:
        pages = []
        if kdir.exists():
            for td in sorted(kdir.iterdir()):
                if not td.is_dir() or td.name.startswith("."):
                    continue
                ov = td / "overview.md"
                if ov.exists():
                    text = ov.read_text(encoding="utf-8")
                    parsed = l2_distill.parse_overview(text)
                    pages.append({"topic": td.name, "content": text,
                                  "category": parsed["category"],
                                  "category_label": parsed["category_label"],
                                  "tags": parsed["tags"]})
        return _json({"ok": True, "pages": pages})

    # 单页：topic 目录名全库唯一，直接定点查
    ov = kdir / topic / "overview.md"
    ov = ov if ov.exists() else None
    if ov is not None:
        stats = l3_feedback.feedback_stats(topic)
        return _json({"ok": True, "topic": topic,
                      "content": ov.read_text(encoding="utf-8"),
                      "feedback_count": stats["feedback_count"],
                      "feedback_last_used": stats["feedback_last_used"]})
    return _json({"ok": True, "topic": topic, "content": None})


@app.get("/api/design.css")
def api_design_css():
    """前端 CSS 资源包：单文件附件下载。"""
    return _serve_file(config.PUBLIC_DIR / "assets" / "book-style.css",
                       "text/css; charset=utf-8", "book-style.css")


@app.get("/api/design")
def api_design():
    """design.md token 总纲：稳定别名指向 DESIGN_DOC_SLUG 报告的 .md 孪生。"""
    conn = store.get_db()
    try:
        rep = store.get_report_by_slug(conn, config.DESIGN_DOC_SLUG)
    finally:
        conn.close()
    if not rep:
        return _json({"error": f"design 总纲文档（{config.DESIGN_DOC_SLUG}）尚未发布"}, 404)
    md_path = config.REPORTS_DIR / Path(rep["file"]).with_suffix(".md")
    if not md_path.exists():
        return _json({"error": f"design 总纲的 .md 孪生不存在: {md_path.name}"}, 404)
    return _serve_file(md_path, "text/markdown; charset=utf-8")


# ============================================================
# POST /api/*
# ============================================================
async def _read_json(request: Request):
    """读 POST body 并解析 JSON；失败返回 (None, error)。"""
    try:
        body = (await request.body()).decode("utf-8")
        return json.loads(body), None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "invalid JSON"


@app.post("/api/knowledge/feedback")
async def api_feedback_submit(request: Request):
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    fb, ferr = l3_feedback.submit_feedback(data)
    if ferr:
        return _json({"ok": False, "error": ferr}, 400)
    return _json({"ok": True, "feedback": fb}, 201)


@app.post("/api/knowledge/feedback/{fid}/judge")
async def api_feedback_judge(fid: int, request: Request):
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    # 人工裁决标识：body 自报 judge 字段，否则用来源 IP
    who = str((data.get("judge") or "")).strip() or (request.client.host if request.client else "unknown")
    fb, ferr, code = l3_feedback.judge_feedback(
        fid, data.get("verdict"), note=data.get("note", ""),
        judged_by=f"human:{who}")
    if ferr:
        return _json({"ok": False, "error": ferr}, code)
    return _json({"ok": True, "feedback": fb})


@app.post("/api/reports/{slug}/hide")
async def api_report_hide(slug: str, request: Request):
    """软下架/恢复（可逆）：body {"hidden": true|false}，缺省 true。"""
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    result = curate.hide_report(slug, hidden=bool((data or {}).get("hidden", True)))
    return _json(result, 200 if result.get("ok") else 404)


@app.post("/api/reports/{slug}/delete")
async def api_report_delete(slug: str):
    """硬删除（不可逆）：L0 快照 + 报告文件 + DB 行 + 关联知识条目级联清除。"""
    result = curate.hard_delete_report(slug)
    return _json(result, 200 if result.get("ok") else 404)


@app.post("/api/knowledge/items/{item_id}/status")
async def api_knowledge_item_status(item_id: str, request: Request):
    """单条知识状态切换：body {"status": "active"|"hidden"}。"""
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    result = curate.set_item_status(item_id, str((data or {}).get("status", "")).strip())
    return _json(result, 200 if result.get("ok") else 400)


@app.post("/api/templates")
async def api_template_register(request: Request):
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    name = (data.get("name") or "").strip()
    manifest = data.get("manifest") or {}
    tpl_html = data.get("template") or ""
    rationale = data.get("rationale") or ""
    violations = l1_publish.validate_template(name, manifest, tpl_html, rationale)
    if not violations and (config.TEMPLATES_DIR / name).exists():
        return _json({"ok": False, "error": f"模板 '{name}' 已存在（模板不经 API 覆盖；演进走 git）"}, 400)
    if violations:
        return _json({"ok": False, "violations": violations}, 400)
    tdir = config.TEMPLATES_DIR / name
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "template.html").write_text(tpl_html, encoding="utf-8")
    stored = {**manifest, "name": name, "default": False,
              "provisional": True, "rationale": rationale.strip()}
    (tdir / "manifest.json").write_text(
        json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    return _json({"ok": True, "name": name, "provisional": True,
                  "message": "已收录（provisional）。模板是叙事结构的执行点——大标题顺序须可从契约条目推出。"}, 201)


@app.post("/api/validate")
async def api_validate(request: Request):
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    title = data.get("title", "").strip()
    content = data.get("content", "")
    template = (data.get("template") or "").strip()
    category = (data.get("category") or "").strip()
    violations, warnings = l1_publish.validate_content(content, title, template, category)
    # 可选字段：给了就检
    slug = data.get("slug", "").strip()
    if slug:
        e = validate_slug_not_empty(slug)
        if e:
            violations.append(e)
    if category:
        ce = l1_publish.validate_category(category)
        if ce:
            violations.append(ce)
    _, hits = l1_publish.component_head(content)
    return _json({"ok": not violations, "violations": violations,
                  "warnings": warnings, "components": hits})


@app.post("/api/projects")
async def api_project_create(request: Request):
    """新建项目（决策3：先建项目 + .vicky 联动）。
    body: {name, description?}；slug 由 name 规范化生成（不接受显式覆盖）。
    重复 slug 返回 {"ok":false,"error":...}；成功返回 {"ok":true, project:{...}}。"""
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    name = (data.get("name") or "").strip()
    if not name:
        return _json({"ok": False, "error": "name 必填"}, 400)
    # slug 由 name 规范化生成（name→slug 关系定死：不接受显式覆盖，防重复/大小写分裂）
    slug = ui.project_slug(name)
    description = (data.get("description") or "").strip()
    try:
        store.create_project(slug, name, description)
    except Exception as e:
        # IntegrityError → 重复 slug
        err_msg = str(e).lower()
        if "unique" in err_msg or "primary key" in err_msg or "duplicate" in err_msg:
            return _json({"ok": False, "error": f"项目 '{slug}' 已存在"}, 409)
        return _json({"ok": False, "error": str(e)}, 500)
    conn = store.get_db()
    try:
        proj = store.get_project(slug, conn)
    finally:
        conn.close()
    return _json({"ok": True, "project": proj}, 201)


@app.delete("/api/projects/{slug}")
def api_project_delete(slug: str):
    """软删除 / 归档项目元信息（可逆，不动 reports.project 引用）。"""
    slug = ui.project_slug(slug)
    if not store.archive_project(slug):
        return _json({"ok": False, "error": f"项目 '{slug}' 不存在"}, 404)
    return _json({"ok": True, "slug": slug, "archived": True})


# ============================================================
# 架构导航器 API（骨架整体读写 / 模块单独读写 / 模块搜索）
# ============================================================
@app.get("/api/arch/{project}")
def api_arch_get(project: str):
    project = ui.project_slug(project)
    g = arch.get_graph(project)
    if g is None:
        return _json({"ok": False, "error": f"项目 '{project}' 暂无架构"}, 404)
    return _json({"ok": True, "graph": g})


@app.put("/api/arch/{project}")
async def api_arch_put(project: str, request: Request):
    project = ui.project_slug(project)
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    ok, verr = arch.put_graph(project, data)
    if not ok:
        return _json({"ok": False, "error": verr}, 400)
    return _json({"ok": True, "project": project})


@app.get("/api/arch/{project}/module/{node_id}")
def api_arch_module_get(project: str, node_id: str):
    project = ui.project_slug(project)
    m = arch.get_module(project, node_id)
    if m is None:
        return _json({"ok": False, "error": "模块不存在"}, 404)
    return _json({"ok": True, "kind": m["kind"], "body_md": m["body_md"],
                  "status": m["status"]})


@app.put("/api/arch/{project}/module/{node_id}")
async def api_arch_module_put(project: str, node_id: str, request: Request):
    project = ui.project_slug(project)
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    res = arch.put_module(project, node_id,
                          data.get("kind", "module"), data.get("body_md", ""))
    return _json(res)


@app.get("/api/arch/{project}/search")
def api_arch_search(project: str, q: str = ""):
    project = ui.project_slug(project)
    return _json({"ok": True, "items": arch.search(project, q)})


@app.post("/api/reports")
async def api_report_submit(request: Request):
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)

    title = data.get("title", "").strip()
    slug = data.get("slug", "").strip()
    tag = data.get("tag", "研究报告")
    content = data.get("content", "")
    subtitle = data.get("subtitle", "").strip()
    # category/narrative/project 显式指定；category 缺省由 create_report 落 research
    # （domain 语义已彻底删除，不再有 legacy 映射兜底）
    category = (data.get("category") or "").strip()
    narrative = (data.get("narrative") or "").strip()
    project = (data.get("project") or "").strip()

    if not title or not slug or not content:
        return _json({"ok": False, "error": "title, slug, content 都是必填"}, 400)

    # 表述规范门禁（EXPRESSION-GRAMMAR.md）：硬伤直接拒收，错误信息即写作指导
    template = (data.get("template") or config.DEFAULT_TEMPLATE).strip()
    violations, warnings = l1_publish.validate_content(content, title, template, category)
    if violations:
        return _json({"ok": False, "error": "内容不符合表述规范", "violations": violations}, 400)

    # category 门禁（非法拒收；缺省落 research）
    derived = category or "research"
    cat_err = l1_publish.validate_category(derived)
    if cat_err:
        return _json({"ok": False, "error": cat_err}, 400)

    # 清理 slug
    slug = clean_slug(slug)

    # D 阶段：project 字段校验——若传了 project，检查是否为已建项目（宽松匹配：先 slug 再 name）。
    # 未建项目不拒收，追加 warning 提示「建议先 POST /api/projects」。
    if project:
        conn_proj = store.get_db()
        try:
            p = store.get_project(project, conn_proj)  # 先按 slug 精确匹配
            if p is None:
                # 再按 name 宽松匹配
                for m in store.list_projects_meta(conn_proj):
                    if m["name"] == project:
                        p = m
                        break
            if p is None:
                warnings.append(f"项目 '{project}' 未注册，建议先 POST /api/projects")
        finally:
            conn_proj.close()

    # 图片落盘（设计报告截图等）：base64 只在传输瞬间存在，HTML 里只留链接
    images = data.get("images") or []
    saved_images, img_err = save_images(images, slug)
    if img_err:
        return _json({"ok": False, "error": img_err}, 400)

    try:
        host = request.headers.get("host", f"127.0.0.1:{config.PORT}")
        result = l1_publish.create_report(title, slug, tag, content, subtitle,
                                          template=template,
                                          base_url=f"http://{host}",
                                          category=category, narrative=narrative, project=project)
        result.setdefault("warnings", []).extend(warnings)
        if saved_images:
            result["images"] = saved_images
        return _json(result, 201)
    except KeyError as e:
        return _json({"ok": False, "error": e.args[0] if e.args else str(e)}, 400)
    except ValueError as e:
        # create_report 内门禁兜底（category 非法等）
        return _json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        return _json({"ok": False, "error": str(e)}, 500)


@app.get("/api/reports/{slug}/content")
def api_report_content(slug: str):
    """返回报告原始 content（L0 快照 payload.content）——修订 / 迁移 / 归项目的地基。
    报告列表 API 不返回 content（省 token），此端点按需取。"""
    slug = clean_slug(slug)
    payload = load_report_payload(slug)
    if not payload:
        return _json({"ok": False, "error": f"slug '{slug}' 不存在"}, 404)
    return _json({"ok": True, "slug": slug, **payload})


@app.patch("/api/reports/{slug}")
async def api_report_update_meta(slug: str, request: Request):
    """轻量更新报告元数据（title/subtitle/tag/category/narrative/project/template），
    不动 content、不触发「订」徽章。body 只含要改的字段。"""
    data, err = await _read_json(request)
    if err:
        return _json({"ok": False, "error": err}, 400)
    data = data or {}
    if not any(k in data for k in l1_publish.META_UPDATE_FIELDS):
        return _json({"ok": False, "error": f"无可更新字段：仅接受 {', '.join(l1_publish.META_UPDATE_FIELDS)}"}, 400)
    slug = clean_slug(slug)
    result = l1_publish.update_report_meta(slug, data)
    return _json(result, 200 if result.get("ok") else 404)
# ============================================================
# 静态自伺服（catch-all，必须在所有 API 路由之后声明）
# ============================================================
_MIME = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
         ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg",
         ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2",
         ".md": "text/markdown"}
_TEXT_EXTS = (".html", ".css", ".js", ".json", ".md")


@app.get("/{path:path}")
def serve_static(request: Request, path: str):
    """Serve static files from config.PUBLIC_DIR（home + index + reports + assets +
    projects + knowledge）。/research/* 兼容前缀 strip 后映射；/ → home.html；
    路径穿越 403。config.PUBLIC_DIR 请求时读取（tmp_env 依赖）。"""
    req = "/" + path
    req = req.rstrip("/") if req != "/" else req
    if req == "" or req == "/":
        req = "/home.html"
    # /research/* 兼容前缀——strip 后映射到 config.PUBLIC_DIR
    if req.startswith("/research/"):
        req = req[len("/research"):]
    elif req == "/research":
        req = "/index.html"
    # Security: no path traversal
    public_dir = config.PUBLIC_DIR
    target = (public_dir / req.lstrip("/")).resolve()
    if not str(target).startswith(str(public_dir.resolve())):
        return _json({"error": "forbidden"}, 403)
    if target.is_dir():
        target = target / "index.html"
    if not target.exists():
        return _json({"error": "not found"}, 404)
    ext = target.suffix.lower()
    mime = _MIME.get(ext, "application/octet-stream")
    body = target.read_bytes()
    no_cache = ext == ".html" or req.startswith("/assets")
    headers = {"Cache-Control": "no-cache" if no_cache else "public, max-age=86400"}
    media = f"{mime}; charset=utf-8" if ext in _TEXT_EXTS else mime
    return Response(content=body, status_code=200, media_type=media, headers=headers)


# ============================================================
# 启动
# ============================================================
def main():
    # 启动自举：空库部署也从源码种子创建 README（序），再重建索引
    seed.bootstrap()
    # 启动时重建索引（手动操作/迁移后索引可能过期）
    reports = l1_publish.list_reports()
    config.INDEX_PATH.write_text(l1_publish.build_index(reports), encoding="utf-8")
    l1_publish.refresh_home()
    print(f"📄 Vicky service starting on {config.HOST}:{config.PORT} (FastAPI)")
    print(f"   Templates: {config.TEMPLATES_DIR} (default: {config.DEFAULT_TEMPLATE})")
    print(f"   Reports:  {config.REPORTS_DIR} ({len(reports)} reports)")
    print(f"   Index:    {config.INDEX_PATH}")

    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
