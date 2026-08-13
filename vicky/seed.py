"""内置种子内容：项目 README（为什么是这本书）作为「特性」随源码分发。

任何新实例启动时自举——reports 表若无 DESIGN_DOC_SLUG，即从源码种子
（vicky/seed/{slug}.html）创建该报告，保证空库部署后「序」也有一本 README。
幂等：已存在则跳过（不覆盖人工修订、不产生 rev 噪声）。
依赖方向：web → seed → l1_publish/store（单向）。
"""
from pathlib import Path

from . import config
from . import store

SEED_DIR = Path(__file__).parent / "seed"


def bootstrap() -> bool:
    """若 reports 表缺 README（DESIGN_DOC_SLUG），从源码种子创建。返回是否创建。"""
    slug = config.DESIGN_DOC_SLUG
    conn = store.get_db()
    try:
        exists = conn.execute("SELECT 1 FROM reports WHERE slug=?", (slug,)).fetchone()
    finally:
        conn.close()
    if exists:
        return False
    seed_file = SEED_DIR / f"{slug}.html"
    if not seed_file.exists():
        return False
    # 延迟导入避免 seed→l1_publish→… 的环（l1_publish 不 import seed）
    from . import l1_publish
    l1_publish.create_report(
        title="为什么是这本书",
        slug=slug,
        tag="META · 关于这本书本身",
        content=seed_file.read_text(encoding="utf-8"),
        subtitle="Vicky 的 README——它现在长什么样、每个决定背后的理由",
        category="brief",
    )
    return True
