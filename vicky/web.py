"""
Web 路由层——薄路由 + 静态自伺服（/research/*）。
P0 包化：从 server.py 搬迁 Handler + 启动逻辑。
行为零变化——API 契约不变；补全 /research/ 前缀处理（P4 部署切换前置能力）。

启动: python3 -m vicky.web [port] [host]
"""

import json
import re
import sys
from datetime import datetime
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import config
from . import l1_publish
from . import l2_distill  # P2 分类规格 §3: /api/knowledge 列表条目读 frontmatter 补 category/tags
from . import l3_feedback
from . import store
from .l0_ingest import clean_slug, validate_slug_not_empty, validate_domain, save_images, validate_series_params

# P0: 不创建 config 路径的本地别名——tests/tmp_env 通过 monkey-patch config.* 工作，
# 本地别名在 import 时即绑定，patch 后不更新。Handler 方法内统一用 config.XXX 访问。


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
        """Serve static files from config.PUBLIC_DIR (home + index + reports + assets + knowledge)。
        P0: 处理 /research/ 前缀（P4 Nginx 纯反代时 app 直接收到带前缀的 URL）。
        P2: 根路径 `/` = 首页门户 home.html；reports/assets/design.html/knowledge 根级直出。"""
        req = self.path.split("?")[0].rstrip("/")
        if req == "" or req == "/":
            req = "/home.html"
        # P0: 自伺服 /research/* 前缀——strip 后映射到 config.PUBLIC_DIR
        if req.startswith("/research/"):
            req = req[len("/research"):]
        elif req == "/research":
            req = "/index.html"
        # Security: no path traversal
        public_dir = config.PUBLIC_DIR
        target = (public_dir / req.lstrip("/")).resolve()
        if not str(target).startswith(str(public_dir.resolve())):
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
                ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2",
                ".md": "text/markdown"}.get(ext, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if ext in (".html", ".css", ".js", ".json", ".md") else mime)
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
            self._json({"ok": True, "service": "vicky"})
        elif self.path == "/api/reports":
            self._json({"ok": True, "reports": l1_publish.list_reports()})
        elif self.path == "/api/guide":
            self._serve_file(config.GUIDE_PATH, "text/markdown; charset=utf-8")
        elif self.path == "/api/skill":
            self._serve_file(config.GUIDE_PATH, "text/markdown; charset=utf-8", "vicky-skill.md")
        elif self.path.split("?")[0] == "/api/template":
            name = parse_qs(urlparse(self.path).query).get("name", [config.DEFAULT_TEMPLATE])[0]
            try:
                self._serve_file(l1_publish.template_path(name), "text/html; charset=utf-8")
            except KeyError as e:
                self._json({"ok": False, "error": str(e)}, 404)
        elif self.path == "/api/templates":
            self._json({"ok": True, "templates": l1_publish.list_templates()})
        elif self.path == "/api/principles":
            self._serve_file(config.REPO_DIR / "skill" / "NARRATIVE-PRINCIPLES.md",
                             "text/markdown; charset=utf-8")
        elif self.path.split("?")[0] == "/api/knowledge/feedback":
            # P2: L3 账本可查（路由必须在 /api/knowledge 前判定）
            qs = parse_qs(urlparse(self.path).query)
            rows, err = l3_feedback.list_feedbacks_api(
                topic=qs.get("topic", [""])[0], status=qs.get("status", [""])[0])
            if err:
                self._json({"ok": False, "error": err}, 400)
            else:
                self._json({"ok": True, "feedbacks": rows})
        elif self.path.split("?")[0] == "/api/knowledge":
            qs = parse_qs(urlparse(self.path).query)
            domain = qs.get("domain", [""])[0]
            topic = qs.get("topic", [""])[0]
            kdir = config.REPO_DIR / "knowledge"
            if not domain and not topic:
                pages = []
                if kdir.exists():
                    for dd in sorted(kdir.iterdir()):
                        if not dd.is_dir() or dd.name.startswith("."):
                            continue
                        for td in sorted(dd.iterdir()):
                            ov = td / "overview.md"
                            if ov.exists():
                                # 分类规格 §3: 列表条目补 category / category_label / tags（parse_overview
                                # 已做枚举校验+兜底 ai、tags 截断，与藏书楼页同一出处）
                                text = ov.read_text(encoding="utf-8")
                                parsed = l2_distill.parse_overview(text)
                                pages.append({"domain": dd.name, "topic": td.name,
                                              "content": text,
                                              "category": parsed["category"],
                                              "category_label": parsed["category_label"],
                                              "tags": parsed["tags"]})
                self._json({"ok": True, "pages": pages})
            else:
                # P2: 支持只给 topic（目录名是全库唯一 id）——扫各 domain 定位
                if domain and topic:
                    ov = kdir / domain / topic / "overview.md"
                    ov = ov if ov.exists() else None
                else:
                    ov = None
                    if kdir.exists():
                        for dd in sorted(kdir.iterdir()):
                            cand = kdir / dd.name / topic / "overview.md"
                            if cand.exists():
                                domain, ov = dd.name, cand
                                break
                if ov is not None:
                    # P2: 响应增加写回次数/最近使用（循环可见，规格 §6④）
                    stats = l3_feedback.feedback_stats(topic)
                    self._json({"ok": True, "domain": domain, "topic": topic,
                                "content": ov.read_text(encoding="utf-8"),
                                "feedback_count": stats["feedback_count"],
                                "feedback_last_used": stats["feedback_last_used"]})
                else:
                    self._json({"ok": True, "domain": domain, "topic": topic, "content": None})
        elif self.path == "/api/design.css":
            # 前端 CSS 资源包：单文件附件下载（spec §3）
            self._serve_file(config.PUBLIC_DIR / "assets" / "book-style.css",
                             "text/css; charset=utf-8", "book-style.css")
        elif self.path == "/api/design":
            # design.md token 总纲：稳定别名指向 DESIGN_DOC_SLUG 报告的 .md 孪生
            conn = store.get_db()
            try:
                rep = store.get_report_by_slug(conn, config.DESIGN_DOC_SLUG)
            finally:
                conn.close()
            if not rep:
                self._json({"error": f"design 总纲文档（{config.DESIGN_DOC_SLUG}）尚未发布"}, 404)
                return
            md_path = config.REPORTS_DIR / Path(rep["file"]).with_suffix(".md")
            if not md_path.exists():
                self._json({"error": f"design 总纲的 .md 孪生不存在: {md_path.name}"}, 404)
                return
            self._serve_file(md_path, "text/markdown; charset=utf-8")
        else:
            self._serve_static()

    def _read_json_body(self):
        """读 POST body 并解析 JSON；失败返回 (None, error)。"""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(body), None
        except json.JSONDecodeError:
            return None, "invalid JSON"

    def do_POST(self):
        path = self.path.split("?")[0]

        # P2: L3 写回 / 人工裁决（规格 §6）
        if path == "/api/knowledge/feedback":
            data, err = self._read_json_body()
            if err:
                self._json({"ok": False, "error": err}, 400)
                return
            fb, ferr = l3_feedback.submit_feedback(data)
            if ferr:
                self._json({"ok": False, "error": ferr}, 400)
            else:
                self._json({"ok": True, "feedback": fb}, 201)
            return
        m = re.fullmatch(r"/api/knowledge/feedback/(\d+)/judge", path)
        if m:
            data, err = self._read_json_body()
            if err:
                self._json({"ok": False, "error": err}, 400)
                return
            # 人工裁决标识：body 自报 judge 字段，否则用来源 IP
            who = str((data.get("judge") or "")).strip() or self.client_address[0]
            fb, ferr, code = l3_feedback.judge_feedback(
                int(m.group(1)), data.get("verdict"), note=data.get("note", ""),
                judged_by=f"human:{who}")
            if ferr:
                self._json({"ok": False, "error": ferr}, code)
            else:
                self._json({"ok": True, "feedback": fb})
            return

        if path not in ("/api/reports", "/api/validate", "/api/templates"):
            self._json({"error": "not found"}, 404)
            return

        data, err = self._read_json_body()
        if err:
            self._json({"ok": False, "error": err}, 400)
            return

        if self.path == "/api/templates":
            name = (data.get("name") or "").strip()
            manifest = data.get("manifest") or {}
            tpl_html = data.get("template") or ""
            rationale = data.get("rationale") or ""
            violations = l1_publish.validate_template(name, manifest, tpl_html, rationale)
            if not violations and (config.TEMPLATES_DIR / name).exists():
                self._json({"ok": False, "error": f"模板 '{name}' 已存在（模板不经 API 覆盖；演进走 git）"}, 400)
                return
            if violations:
                self._json({"ok": False, "violations": violations}, 400)
                return
            tdir = config.TEMPLATES_DIR / name
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
            template = (data.get("template") or "").strip()
            violations, warnings = l1_publish.validate_content(content, title, template)
            # 可选字段：给了就检
            slug = data.get("slug", "").strip()
            if slug:
                err = validate_slug_not_empty(slug)
                if err:
                    violations.append(err)
            domain = (data.get("domain") or "tech").strip()
            err = validate_domain(domain)
            if err:
                violations.append(err)
            series, order = data.get("series"), data.get("order")
            _, series_err = validate_series_params(series, order)
            if series_err:
                violations.append(series_err)
            elif series:
                order_int = int(order)
                clean_s = clean_slug(slug) if slug else ""
                existing = l1_publish._existing_for_slug(clean_s) if clean_s else []
                exclude_file = existing[-1].name if existing else None
                conflict = l1_publish.check_series_conflict(series, order_int, exclude_file=exclude_file,
                                                            reports=l1_publish.list_reports())
                if conflict:
                    violations.append(conflict)
            _, hits = l1_publish.component_head(content)
            self._json({"ok": not violations, "violations": violations,
                        "warnings": warnings, "components": hits})
            return

        if not title or not slug or not content:
            self._json({"ok": False, "error": "title, slug, content 都是必填"}, 400)
            return

        # 表述规范门禁（EXPRESSION-GRAMMAR.md）：硬伤直接拒收，错误信息即写作指导
        template = (data.get("template") or config.DEFAULT_TEMPLATE).strip()
        violations, warnings = l1_publish.validate_content(content, title, template)
        if violations:
            self._json({"ok": False, "error": "内容不符合表述规范", "violations": violations}, 400)
            return

        # 清理 slug（提前到丛书校验之前：校验要用清理后的 slug 匹配 upsert 本卷文件名）
        slug = clean_slug(slug)

        series = (data.get("series") or "").strip()
        order = data.get("order")
        order_int, series_err = validate_series_params(series, order)
        if series_err:
            self._json({"ok": False, "error": series_err}, 400)
            return

        if series:
            # upsert 本卷自己占自己的卷号不算冲突（spec §2.6：同 slug upsert 且 order 不变 → 允许）
            existing = l1_publish._existing_for_slug(slug)
            exclude_file = existing[-1].name if existing else None
            conflict = l1_publish.check_series_conflict(series, order_int, exclude_file=exclude_file,
                                                        reports=l1_publish.list_reports())
            if conflict:
                self._json({"ok": False, "error": conflict}, 400)
                return

        domain = (data.get("domain") or "tech").strip()
        err = validate_domain(domain)
        if err:
            self._json({"ok": False, "error": err}, 400)
            return

        # 图片落盘（设计报告截图等）：base64 只在传输瞬间存在，HTML 里只留链接
        images = data.get("images") or []
        saved_images, img_err = save_images(images, slug)
        if img_err:
            self._json({"ok": False, "error": img_err}, 400)
            return

        try:
            host = self.headers.get("Host", f"127.0.0.1:{config.PORT}")
            result = l1_publish.create_report(title, slug, tag, content, subtitle,
                                              series=series, order=order_int or 0, template=template,
                                              base_url=f"http://{host}", domain=domain)
            result.setdefault("warnings", []).extend(warnings)
            if saved_images:
                result["images"] = saved_images
            self._json(result, 201)
        except KeyError as e:
            self._json({"ok": False, "error": e.args[0] if e.args else str(e)}, 400)
        except ValueError as e:
            # create_report 内模板级门禁兜底（arch-node 三段等）
            self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)


# ============================================================
# 启动
# ============================================================
def main():
    # 启动时重建索引（手动操作/迁移后索引可能过期）
    reports = l1_publish.list_reports()
    config.INDEX_PATH.write_text(l1_publish.build_index(reports), encoding="utf-8")
    l1_publish.refresh_home()
    print(f"📄 Vicky service starting on {config.HOST}:{config.PORT}")
    print(f"   Templates: {config.TEMPLATES_DIR} (default: {config.DEFAULT_TEMPLATE})")
    print(f"   Reports:  {config.REPORTS_DIR} ({len(reports)} reports)")
    print(f"   Index:    {config.INDEX_PATH}")
    # ThreadingHTTPServer: 一个挂住的连接（慢客户端/未完成请求）不能把单线程 HTTPServer 堵死，经历过一次
    # 绑定 config.HOST：生产环境由 Nginx 反代；9093 直连传 0.0.0.0 对外暴露
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
