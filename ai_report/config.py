"""
ai_report 全局配置——路径、常量、端口、组件注册表。
P0 包化：从 server.py / distill.py 提取所有配置常量。
"""

import re
import sys
from pathlib import Path

# ============================================================
# 路径（由 REPO_DIR 派生；tests 通过 monkey-patch 覆盖）
# ============================================================
REPO_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_DIR / "templates"
DEFAULT_TEMPLATE = "book"
REPORTS_DIR = REPO_DIR / "public" / "reports"
INDEX_PATH = REPO_DIR / "public" / "index.html"
PUBLIC_DIR = REPO_DIR / "public"
GUIDE_PATH = REPO_DIR / "skill" / "AGENT-GUIDE.md"
IMG_DIR = PUBLIC_DIR / "assets" / "img"
KNOWLEDGE_DIR = REPO_DIR / "knowledge"

# ============================================================
# 端口（server.py 位置参数；-m ai_report.web 同款）
# ============================================================
def _parse_port() -> int:
    try:
        return int(sys.argv[1])
    except (IndexError, ValueError):
        return 9091

PORT = _parse_port()

# ============================================================
# 契约与领域常量
# ============================================================
# 契约条目单一真相（与 NARRATIVE-PRINCIPLES.md §3 逐字一致）
NARRATIVE_CONTRACTS = {
    "type-determines-narrative", "why-first", "conclusion-first",
    "three-questions", "evidence-for-claims", "scenario-exercise",
    "verdict-on-comparison", "figure-caption", "mece-structure",
}

DOMAINS = {"tech", "design", "ephemeral"}

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
