"""
vicky 全局配置——路径、常量、端口、组件注册表。
P0 包化：从 server.py / distill.py 提取所有配置常量。
"""

import re
import sys
from pathlib import Path

# ============================================================
# 路径（由 REPO_DIR 派生；tests 通过 monkey-patch 覆盖）
# ============================================================
REPO_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_DIR / "data"           # L0 快照 + sqlite DB（git-ignore）
TEMPLATES_DIR = REPO_DIR / "templates"
VIEWS_DIR = REPO_DIR / "views"         # P3 前端抢救：整页模板，纯 HTML + __占位符__
DEFAULT_TEMPLATE = "book"
REPORTS_DIR = REPO_DIR / "public" / "reports"
INDEX_PATH = REPO_DIR / "public" / "index.html"
PUBLIC_DIR = REPO_DIR / "public"
GUIDE_PATH = REPO_DIR / "skill" / "AGENT-GUIDE.md"
IMG_DIR = PUBLIC_DIR / "assets" / "img"
KNOWLEDGE_DIR = REPO_DIR / "knowledge"

# ============================================================
# 端口 / 绑定地址（server.py 位置参数；-m vicky.web 同款）
# ============================================================
def _parse_port() -> int:
    try:
        return int(sys.argv[1])
    except (IndexError, ValueError):
        return 9091

def _parse_host() -> str:
    """绑定地址：argv[2]，默认 127.0.0.1（生产由 Nginx 反代；9093 直连传 0.0.0.0）。"""
    try:
        return sys.argv[2]
    except IndexError:
        return "127.0.0.1"

PORT = _parse_port()
HOST = _parse_host()

# ============================================================
# 契约与领域常量
# ============================================================
# 契约条目单一真相（与 NARRATIVE-PRINCIPLES.md §3 逐字一致）
NARRATIVE_CONTRACTS = {
    "type-determines-narrative", "why-first", "conclusion-first",
    "three-questions", "evidence-for-claims", "scenario-exercise",
    "verdict-on-comparison", "figure-caption", "mece-structure",
}

# 存量 domain 枚举（重构蓝图 2026-08-12-vicky-reshape-product-design 起已废弃，仅向后兼容保留）：
# 新模型改为 category 骨架（REPORT_CATEGORIES），存量 domain 经 LEGACY_DOMAIN_TO_CATEGORY 迁移。
DOMAINS = {"tech", "design", "ephemeral", "arch"}

# ============================================================
# 报告分类骨架（重构蓝图 2026-08-12 §03「四大分类」）
# category = 骨架（平台强制）：决定进不进知识库 / 门禁红线 / 归档去向，
# 与叙事方式（NARRATIVES）、模板（CATEGORY_DEFAULT_TEMPLATE）正交。
# 命名说明：与下方知识库专栏 CATEGORIES（dict）同名冲突，故用 REPORT_CATEGORIES；
# 专栏是 L2 蒸馏产物的归档维度，骨架是 L1 报告的路由维度，二者正交。
# ============================================================
REPORT_CATEGORIES = ["research", "brief", "tech-solution", "arch-doc"]

# 存量 domain → 新 category 迁移映射（schema 迁移回填用；design 为 legacy，不再开放提交）
LEGACY_DOMAIN_TO_CATEGORY = {
    "tech": "research",
    "ephemeral": "brief",
    "arch": "arch-doc",
    "design": "design",
}

# 各分类默认模板（agent 提交未显式指定 template 时兜底；骨架与模板正交，分类内可换模板）
CATEGORY_DEFAULT_TEMPLATE = {
    "research": "book",
    "brief": "brief",
    "tech-solution": "book",
    "arch-doc": "arch-overview",
}

# 叙事方式库（跨骨架通用，agent 按内容自选；骨架决定「去哪/怎么管」，叙事决定「怎么讲」）
NARRATIVES = [
    "金字塔/结论先行", "对比擂台", "问题拆解", "场景演练",
    "时间线/演进", "总分总/地图", "黄金五章",
]

# 知识库专栏枚举（spec 2026-08-10-knowledge-taxonomy-design §1）——蒸馏时每主题必归其一（MECE），
# key → 中文名。分类校验失败兜底 'ai'（宁可默认也不留无分类主题）。
# 注意：这是 L2 蒸馏产物的「知识库专栏」维度，与报告分类骨架 REPORT_CATEGORIES（4 大分类）
# 正交勿混用——专栏在蒸馏产物上，骨架在 L1 报告上。
CATEGORIES = {
    "ai": "AI 专栏",
    "infra": "后端与基础设施专栏",
    "eng": "工程效能专栏",
    "ops": "成本与治理专栏",
    "design": "产品与设计专栏",
}

# 各专栏收什么（spec 2026-08-10-knowledge-taxonomy-design §1）——classify/编译 prompt 注入，
# 引导 LLM 按内容归栏，避免盲猜。key 与 CATEGORIES 严格同键。
CATEGORY_SCOPES = {
    "ai": "Agent、RAG、模型、记忆、提示工程、开源项目介绍",
    "infra": "数据库、架构、分布式、图存储",
    "eng": "开发工具、agent 工程方法、工作流",
    "ops": "用量分析、费用治理、监控",
    "design": "前端、设计 token、产品分析",
}

# 前端卡片 token 总纲（design.md）指向的稳定别名文档 slug（端点由 P2 实现）
DESIGN_DOC_SLUG = "why-this-book"

# ============================================================
# 图片上传约束
# ============================================================
IMG_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
IMG_MAX_BYTES = 10 * 1024 * 1024  # 10MB per image

# ============================================================
# 模板门禁常量
# ============================================================
REQUIRED_PLACEHOLDERS = ("{{TITLE}}", "{{CONTENT}}", "{{HERO_TAG}}", "{{SUBTITLE}}",
                         "{{DATE}}", "{{META}}", "{{COMPONENT_HEAD}}",
                         "{{SERIES_BADGE}}", "{{VOLUME_NAV}}")

ROOT_TOKEN_RE = re.compile(
    r':root[^}]*--(?:paper|ink|sub|accent|seal|dark|hair|serif|sans|mono)\s*:', re.I)

# ============================================================
# 按需组件注入（spec §5）
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
    "arch-flow": {
        "detect": lambda content: bool(re.search(
            r'<div\b[^>]*\bclass=["\'][^"\']*\barch-flow\b', content, re.I)),
        "head": (
            '<link rel="stylesheet" href="../assets/components/arch-flow/flow.css">',
            '<script src="../assets/components/arch-flow/flow.js" defer></script>',
        ),
    },
}

# ============================================================
# 门禁正则与词表
# ============================================================
FIGURE_RE = re.compile(r'<figure\b[^>]*>([\s\S]*?)</figure>', re.I)
AI_WORDS = ("赋能", "闭环", "打通", "一站式", "全方位", "引领")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]")

# 弃用类名映射（spec §7）
DEPRECATED_CLASSES = {
    "ladder-list": ".steps", "ladder-rung": ".step", "ladder-num": ".step-num",
    "ladder-content": ".step", "quote-block": "blockquote", "concern-box": ".callout",
    "phase": ".steps",
}
