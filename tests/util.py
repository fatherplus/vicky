"""测试公共：从 ai_report 包加载模块 + 临时目录环境。"""
import contextlib
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_server():
    """返回 ai_report.l1_publish 模块（兼容旧测试的 server.* 调用）。
    P0 包化：原 server.py 函数已在 l1_publish.py。同时注入 Handler 供 test_templates 用。"""
    import ai_report.l1_publish as mod
    # 注入 Handler（test_templates 通过 server.Handler 引用）
    from ai_report.web import Handler
    mod.Handler = Handler
    # 注入 _INDEX_TPL（test_assets 通过 server._INDEX_TPL 引用）
    # 已在 l1_publish 中定义，无需额外注入
    return mod


@contextlib.contextmanager
def tmp_env(server):
    """把 REPORTS_DIR/INDEX_PATH/TEMPLATES_DIR 指到临时目录。
    P0 包化：同时 patch ai_report.config 和 l1_publish 模块（两边绑定同步）。"""
    import ai_report.config as cfg
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "reports").mkdir()
        shutil.copytree(REPO / "templates", tmp / "templates")  # 预置 book，create_report 默认模板可用
        # 保存原始值（config 和 server 模块各一份）
        targets = [cfg, server]
        origs = [(t.REPORTS_DIR, t.INDEX_PATH, t.TEMPLATES_DIR) for t in targets]
        for t in targets:
            t.REPORTS_DIR = tmp / "reports"
            t.INDEX_PATH = tmp / "index.html"
            t.TEMPLATES_DIR = tmp / "templates"
        yield tmp
        for t, (rd, idx, td) in zip(targets, origs):
            t.REPORTS_DIR = rd
            t.INDEX_PATH = idx
            t.TEMPLATES_DIR = td
