"""MCP 协议层——stdlib JSON-RPC 2.0 over HTTP（stateless 形态）。

MCP streamable HTTP 的简化实现：POST /mcp 单请求单响应，无会话、无批处理、无 SSE 流。
规范要点（MCP 2024-11-05 / JSON-RPC 2.0）：
  - 请求:  {"jsonrpc":"2.0","method":...,"params":?,"id":?}
  - 响应:  {"jsonrpc":"2.0","result":...,"id":...}  或 {"jsonrpc":"2.0","error":{...},"id":...}
  - 通知:  无 id 的请求——服务端执行但不回响应体（web 层回 HTTP 202 空体）
  - 错误码: -32700 解析错误 / -32600 非法请求 / -32601 方法不存在 / -32602 参数非法 / -32603 内部错误

工具注册（P2 起使用）：
    router.tool_schemas["search_knowledge"] = {
        "name": "search_knowledge", "description": "...",
        "inputSchema": {"type": "object", "properties": {...}, "required": [...]}}
    router.register("search_knowledge", handler)   # handler(params) -> result dict

仅依赖 stdlib json，无第三方依赖。
"""

import json

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "vicky"
SERVER_VERSION = "0.1.0"

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RPCError(Exception):
    """JSON-RPC 错误：code/message 会进响应 error 对象。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class MCPRouter:
    """JSON-RPC 2.0 分发器。

    - register(name, handler): 注册 JSON-RPC 方法 / 工具执行器，handler(params) -> dict
    - dispatch(method, params): 核心分发，返回 result dict；失败抛 RPCError
    - handle_request(method, params, id): 完整信封，返回响应 dict；通知返回 None
    - tool_schemas: 工具注册表，key=工具名，value={name, description, inputSchema}
    """

    def __init__(self):
        self._handlers = {}
        self.tool_schemas = {}

    def register(self, name: str, handler):
        """注册方法处理器：handler(params) -> dict（即响应的 result）。"""
        self._handlers[name] = handler

    def dispatch(self, method, params):
        """核心分发：method -> result dict。错误抛 RPCError，由调用方组装信封。"""
        if method == "initialize":
            return {
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "capabilities": {"tools": {}},
                "protocolVersion": PROTOCOL_VERSION,
            }
        if method == "tools/list":
            return {"tools": list(self.tool_schemas.values())}
        if method == "tools/call":
            return self._call_tool(params)
        if method == "ping":
            return {}
        handler = self._handlers.get(method)
        if handler is None:
            raise RPCError(METHOD_NOT_FOUND, f"Method not found: {method}")
        try:
            return handler(params or {})
        except RPCError:
            raise
        except Exception as e:
            raise RPCError(INTERNAL_ERROR, str(e) or "Internal error") from e

    def _call_tool(self, params):
        """tools/call：按 name 分发到已注册的 tool handler（当前注册表为空，P2 填充）。"""
        params = params or {}
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise RPCError(INVALID_PARAMS, "tools/call 需要 name 参数")
        if name not in self.tool_schemas:
            raise RPCError(INVALID_PARAMS, f"Unknown tool: {name}")
        handler = self._handlers.get(name)
        if handler is None:
            raise RPCError(INTERNAL_ERROR, f"Tool '{name}' 已登记 schema 但未注册 handler")
        result = handler(params.get("arguments") or {})
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}

    def handle_request(self, method, params, request_id):
        """完整 JSON-RPC 信封。

        返回响应 dict（result 或 error 二选一）；通知（request_id is None）返回 None——
        服务端对通知永不回响应（JSON-RPC 2.0 §2.2）。
        """
        if request_id is None:
            try:
                self.dispatch(method, params)
            except RPCError:
                pass
            except Exception:
                pass
            return None
        try:
            result = self.dispatch(method, params)
            return {"jsonrpc": "2.0", "result": result, "id": request_id}
        except RPCError as e:
            return {"jsonrpc": "2.0",
                    "error": {"code": e.code, "message": e.message},
                    "id": request_id}
        except Exception as e:
            return {"jsonrpc": "2.0",
                    "error": {"code": INTERNAL_ERROR, "message": str(e) or "Internal error"},
                    "id": request_id}


# 模块级单例：web 层与测试共用同一个路由实例（工具注册在启动期/导入期完成）
router = MCPRouter()


# ============================================================
# P2 写入线工具（submit_report / submit_feedback / register_template / authoring_guide）
# 每个 handler 直接调用后端逻辑（l0_ingest / l1_publish / l3_feedback），不经 HTTP。
#
# 注册是显式的（register_default_tools()），不是 import 期自动填充：
# P1 协议测试（test_mcp_protocol::test_tools_list）断言 tools/list 为空——
# 注册表保持惰性，由 web.main() 启动时调用；测试按需显式调用。
# 路径类配置一律在 handler 内经 config.XXX 取（tmp_env 只 patch config.*，
# import 期本地别名不会随测试环境更新，见 web.py 顶部注释）。
# ============================================================

from . import config
from . import l0_ingest
from . import l1_publish
from . import l3_feedback
from . import knowledge_query  # P4 读线：知识 Wiki 查询（三阶段管线）

# domain 路由表：与 AGENT-GUIDE.md「domain 路由」表格一致（key 取自 config.DOMAINS）
DOMAIN_DESCRIPTIONS = {
    "tech": "技术文章（默认）：进知识库蒸馏",
    "design": "前端卡片：一产品一卡，不进蒸馏（token 人工维护）",
    "ephemeral": "临时报告：给人/领导看，跳过蒸馏",
    "arch": "项目架构多页站：总览卷 + 节点卷，跳过蒸馏",
}


# ============================================================
# Tool 1: submit_report（映射 POST /api/reports + /api/validate）
# ============================================================
def _submit_report(params: dict) -> dict:
    """提交/预检报告。
    - dry_run=true → 预检分支：门禁 + slug/domain/series 校验，不落盘；
    - 正式提交 → L0 快照 + L1 发布（l1_publish.create_report 内部完成 ingest → 渲染 → DB upsert）。
    - 表述规范 violations 以 result content 返回（不抛错），agent 可据此修订；
    - 参数格式错误（缺必填 / 非法 domain / series 与 order 不配对）抛 -32602。
    """
    title = str(params.get("title") or "").strip()
    slug = str(params.get("slug") or "").strip()
    content = params.get("content") or ""
    if not isinstance(content, str):
        raise RPCError(INVALID_PARAMS, "content 必须是字符串")
    if not title or not slug or not content.strip():
        raise RPCError(INVALID_PARAMS, "title, slug, content 都是必填")

    template = str(params.get("template") or config.DEFAULT_TEMPLATE).strip() \
        or config.DEFAULT_TEMPLATE
    domain = str(params.get("domain") or "tech").strip() or "tech"
    tag = str(params.get("tag") or "研究报告").strip() or "研究报告"
    subtitle = str(params.get("subtitle") or "").strip()
    series = str(params.get("series") or "").strip()
    order = params.get("order")
    dry_run = bool(params.get("dry_run", False))

    # ── 参数格式校验（-32602 invalid params）──
    err = l0_ingest.validate_slug_not_empty(slug)
    if err:
        raise RPCError(INVALID_PARAMS, err)
    err = l0_ingest.validate_domain(domain)
    if err:
        raise RPCError(INVALID_PARAMS, err)
    order_int, series_err = l0_ingest.validate_series_params(series, order)
    if series_err:
        raise RPCError(INVALID_PARAMS, series_err)

    # ── 表述规范门禁（violations 走 result，不抛错）──
    violations, warnings = l1_publish.validate_content(content, title, template)
    _, hits = l1_publish.component_head(content)

    if dry_run:
        if series:
            clean_s = l0_ingest.clean_slug(slug)
            existing = l1_publish._existing_for_slug(clean_s) if clean_s else []
            exclude = existing[-1].name if existing else None
            conflict = l1_publish.check_series_conflict(
                series, order_int, exclude_file=exclude, reports=l1_publish.list_reports())
            if conflict:
                violations.append(conflict)
        return {"ok": not violations, "dry_run": True,
                "violations": violations, "warnings": warnings, "components": hits}

    if violations:
        return {"ok": False, "submitted": False,
                "violations": violations, "warnings": warnings, "components": hits}

    # 正式提交：清理 slug 后做丛书冲突预检（同 slug upsert 本卷不占自己的号）
    slug = l0_ingest.clean_slug(slug)
    if series:
        existing = l1_publish._existing_for_slug(slug)
        exclude = existing[-1].name if existing else None
        conflict = l1_publish.check_series_conflict(
            series, order_int, exclude_file=exclude, reports=l1_publish.list_reports())
        if conflict:
            return {"ok": False, "submitted": False, "violations": [conflict], "warnings": warnings}

    # 图片落盘（镜像 web.py：base64 只在传输瞬间存在，HTML 里只留链接）
    images = params.get("images") or []
    saved_images = []
    if images:
        if not isinstance(images, list):
            raise RPCError(INVALID_PARAMS, "images 必须是数组")
        saved_images, img_err = l0_ingest.save_images(images, slug)
        if img_err:
            raise RPCError(INVALID_PARAMS, img_err)

    try:
        result = l1_publish.create_report(
            title, slug, tag, content, subtitle,
            series=series, order=order_int or 0, template=template, domain=domain)
        result.setdefault("warnings", []).extend(warnings)
        if saved_images:
            result["images"] = saved_images
        url = result.get("url") or ""
        md_url = url[:-5] + ".md" if url.endswith(".html") else ""
        return {"ok": True, "submitted": True, "url": url, "md_url": md_url,
                "file": result.get("file"), "created": result.get("created"),
                "components": result.get("components") or [],
                "warnings": result.get("warnings") or []}
    except KeyError as e:
        # 未知模板（template_path 抛 KeyError）
        raise RPCError(INVALID_PARAMS, e.args[0] if e.args else str(e))
    except ValueError as e:
        # create_report 内模板级门禁兜底（arch-node 三段等）
        raise RPCError(INVALID_PARAMS, str(e))


# ============================================================
# Tool 2: submit_feedback（映射 POST /api/knowledge/feedback，L3 写回）
# ============================================================
def _submit_feedback(params: dict) -> dict:
    """L3 使用反馈写回：带证据的陈述入账本（pending），topic 必须已蒸馏存在。
    校验沿用 l3_feedback.submit_feedback（evidence 必填；agent/opinion 缺失后端拒收）。"""
    topic = str(params.get("topic") or "").strip()
    domain = str(params.get("domain") or "").strip()
    agent = str(params.get("agent") or "").strip()
    evidence = str(params.get("evidence") or "").strip()
    opinion = str(params.get("opinion") or "").strip()
    cited = params.get("cited") or []
    if isinstance(cited, list):
        cited_str = ",".join(str(c) for c in cited if str(c).strip())
    else:
        cited_str = str(cited or "").strip()

    if not topic:
        raise RPCError(INVALID_PARAMS, "topic 必填")
    if not domain:
        raise RPCError(INVALID_PARAMS, "domain 必填")
    if not evidence:
        raise RPCError(INVALID_PARAMS, "evidence 必填——没有真实证据的意见不进循环")

    fb, err = l3_feedback.submit_feedback({
        "topic": topic, "domain": domain, "agent": agent,
        "evidence": evidence, "opinion": opinion, "cited": cited_str})
    if err:
        raise RPCError(INVALID_PARAMS, err)
    return {"id": fb["id"], "status": fb["status"],
            "topic": fb["topic"], "domain": fb["domain"],
            "agent": fb["agent"], "created_at": fb["created_at"]}


# ============================================================
# Tool 3: register_template（映射 POST /api/templates）
# ============================================================
def _register_template(params: dict) -> dict:
    """注册模板（provisional）。门禁与落盘镜像 web.py /api/templates：
    validate_template（占位符 / :root token / 契约条目 / purpose / rationale）+ 同名防覆盖。
    说明：store 无 create_template 函数（模板文件不进 DB），落盘逻辑与 HTTP 端一致。"""
    name = str(params.get("name") or "").strip()
    manifest = params.get("manifest") or {}
    tpl_html = params.get("template") or ""
    rationale = str(params.get("rationale") or "").strip()
    if not name:
        raise RPCError(INVALID_PARAMS, "name 必填")
    if not isinstance(manifest, dict):
        raise RPCError(INVALID_PARAMS, "manifest 必须是对象")
    if not isinstance(tpl_html, str) or not tpl_html.strip():
        raise RPCError(INVALID_PARAMS, "template 必填")

    violations = l1_publish.validate_template(name, manifest, tpl_html, rationale)
    if not violations and (config.TEMPLATES_DIR / name).exists():
        raise RPCError(INVALID_PARAMS, f"模板 '{name}' 已存在（模板不经 API 覆盖；演进走 git）")
    if violations:
        raise RPCError(INVALID_PARAMS, "模板不符合门禁：" + "；".join(violations))

    tdir = config.TEMPLATES_DIR / name
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "template.html").write_text(tpl_html, encoding="utf-8")
    stored = {**manifest, "name": name, "default": False,
              "provisional": True, "rationale": rationale.strip()}
    (tdir / "manifest.json").write_text(
        json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "name": name, "provisional": True,
            "message": "已收录（provisional）。模板是叙事结构的执行点——大标题顺序须可从契约条目推出。"}


# ============================================================
# Tool 4: authoring_guide（聚合写作工具包，一次返回）
# ============================================================
def _authoring_guide(params: dict) -> dict:
    """聚合：写作指南正文 + 模板目录 + domain 路由表 + 叙事宪法，一次返回。"""
    guide = ""
    if config.GUIDE_PATH.exists():
        guide = config.GUIDE_PATH.read_text(encoding="utf-8")

    templates = []
    if config.TEMPLATES_DIR.exists():
        for m in sorted(config.TEMPLATES_DIR.glob("*/manifest.json")):
            try:
                data = json.loads(m.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            templates.append({"name": data.get("name") or m.parent.name,
                              "description": data.get("purpose") or ""})

    principles = ""
    principles_path = config.REPO_DIR / "skill" / "NARRATIVE-PRINCIPLES.md"
    if principles_path.exists():
        principles = principles_path.read_text(encoding="utf-8")

    return {"guide": guide,
            "templates": templates,
            "domains": {d: DOMAIN_DESCRIPTIONS.get(d, "") for d in sorted(config.DOMAINS)},
            "principles": principles}


# ============================================================
# Tool 5: knowledge_query（P4 读线——知识 Wiki 查询，MCP 服务的 READ line）
# ============================================================
def _knowledge_query(params: dict) -> dict:
    """知识 Wiki 读线：FTS5 召回 → 相关度打分 → token 预算装包，返回带引文的条目片段。
    q 为空 → 目录模式（按专栏列出主题与计数）。参数由 knowledge_query.query 容错归一
    （类型非法取默认值），内部错误由 router 兜底 -32603。"""
    try:
        return knowledge_query.query(params or {})
    except RPCError:
        raise
    except Exception as e:
        raise RPCError(INTERNAL_ERROR, f"knowledge_query 内部错误: {e}") from e


# ============================================================
# 注册入口
# ============================================================
_default_tools_registered = False


SUBMIT_REPORT_SCHEMA = {
    "name": "submit_report",
    "description": "提交或预检一份报告（映射 POST /api/reports + /api/validate）。"
                   "dry_run=true 只预检不落盘，返回 violations/warnings；正式提交返回 url + md_url。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "报告标题（必填）"},
            "slug": {"type": "string", "description": "URL slug：小写字母数字连字符（必填）"},
            "content": {"type": "string", "description": "HTML 内容（必填），遵循 /api/guide 表述规范"},
            "tag": {"type": "string", "description": "分类标签，默认 研究报告"},
            "domain": {"type": "string", "default": "tech",
                        "description": "内容域：tech/design/ephemeral/arch"},
            "template": {"type": "string", "default": "book",
                          "description": "模板名（authoring_guide 可查目录）"},
            "series": {"type": "string", "description": "丛书名（与 order 同生共死）"},
            "order": {"type": "integer", "description": "丛书卷号（≥1）"},
            "subtitle": {"type": "string", "description": "一行副标题（可选）"},
            "images": {"type": "array", "items": {"type": "object"},
                        "description": "截图：[{name, b64}]"},
            "dry_run": {"type": "boolean", "default": False,
                         "description": "true 只预检不落盘"},
        },
        "required": ["title", "slug", "content"],
    },
}

SUBMIT_FEEDBACK_SCHEMA = {
    "name": "submit_feedback",
    "description": "L3 使用反馈写回（映射 POST /api/knowledge/feedback）：带证据的陈述入账本，"
                   "等待裁决。topic 必须是已蒸馏存在的知识主题，evidence 必填。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "知识主题（必填，须已蒸馏存在）"},
            "domain": {"type": "string", "description": "主题所在 domain（必填）"},
            "agent": {"type": "string", "description": "提交方身份（后端要求，账本可追溯）"},
            "evidence": {"type": "string", "description": "证据（必填）——没有真实证据的意见不进循环"},
            "opinion": {"type": "string", "description": "意见（后端要求）"},
            "cited": {"type": "array", "items": {"type": "string"},
                       "description": "引用条目/来源列表"},
        },
        "required": ["topic", "domain", "evidence"],
    },
}

REGISTER_TEMPLATE_SCHEMA = {
    "name": "register_template",
    "description": "注册新模板（provisional，映射 POST /api/templates）。门禁：必需占位符齐全、"
                   "不重定义 :root 视觉 token、manifest 契约条目合法、purpose/rationale 必填。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "模板名：小写字母数字连字符（必填）"},
            "manifest": {"type": "object",
                          "description": "manifest：purpose/document_types/narrative_contract（必填）"},
            "template": {"type": "string", "description": "template.html 内容（必填），含 {{TITLE}} 等占位符"},
            "rationale": {"type": "string", "description": "论证现有模板为何承载不了这个目的（必填）"},
        },
        "required": ["name", "manifest", "template"],
    },
}

AUTHORING_GUIDE_SCHEMA = {
    "name": "authoring_guide",
    "description": "一次取回完整写作工具包：写作指南正文 + 模板目录 + domain 路由表 + 叙事宪法。",
    "inputSchema": {"type": "object", "properties": {}},
}

KNOWLEDGE_QUERY_SCHEMA = {
    "name": "knowledge_query",
    "description": "查询知识 Wiki（读线）：FTS5 召回 → 相关度打分（结论×1.5/陷阱×1.2/数据×1.0）→ "
                   "token 预算装包（默认 2000，硬顶 6000），返回带引文（来源报告 .md 链接）的条目片段。"
                   "q 为空返回目录：按专栏列出全部主题与条目数。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "检索词（≤200 字符，超长截断）"},
            "budget": {"type": "integer", "default": 2000,
                        "description": "返回条目的 token 预算（1-6000，默认 2000，绝对上限 6000）"},
            "category": {"type": "string",
                          "description": "专栏过滤：ai/infra/eng/ops/design（overview category）"},
            "tag": {"type": "string", "description": "标签子串过滤（overview frontmatter tags）"},
        },
    },
}


# 工具名 → (handler, schema) 注册表
_DEFAULT_TOOLS = [
    ("submit_report", _submit_report, SUBMIT_REPORT_SCHEMA),
    ("submit_feedback", _submit_feedback, SUBMIT_FEEDBACK_SCHEMA),
    ("register_template", _register_template, REGISTER_TEMPLATE_SCHEMA),
    ("authoring_guide", _authoring_guide, AUTHORING_GUIDE_SCHEMA),
    ("knowledge_query", _knowledge_query, KNOWLEDGE_QUERY_SCHEMA),
]


def register_default_tools() -> None:
    """注册 P2 写入线 4 工具 + P4 读线 knowledge_query（幂等）。
    由 web.main() 启动时调用（运行中服务对 MCP 客户端可用）；测试按需显式调用。
    不在模块 import 期自动注册——P1 协议测试断言 tools/list 为空，注册表保持惰性填充。"""
    global _default_tools_registered
    if _default_tools_registered:
        return
    _default_tools_registered = True
    for name, handler, schema in _DEFAULT_TOOLS:
        router.tool_schemas[name] = schema
        router.register(name, handler)
