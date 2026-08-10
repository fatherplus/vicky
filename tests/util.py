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
    # P3 前端抢救：_INDEX_TPL 已迁出，不在模块级保存
    return mod


@contextlib.contextmanager
def tmp_env(server):
    """把 REPORTS_DIR/INDEX_PATH/TEMPLATES_DIR/DATA_DIR/VIEWS_DIR 指到临时目录。
    P0 包化 + P1 DB + P3 前端抢救：patch config 全局路径；server 模块的本地别名同步更新。
    store._db_path() 延迟求值，patch config.DATA_DIR 后自动生效。"""
    import ai_report.config as cfg
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "reports").mkdir()
        (tmp / "data").mkdir()  # P1: 隔离 sqlite DB
        shutil.copytree(REPO / "templates", tmp / "templates")  # 预置 book，create_report 默认模板可用
        shutil.copytree(REPO / "views", tmp / "views")  # P3: 视图模板也复制进去
        # 保存 config 原始值
        _rd, _idx, _td, _dd, _vd = cfg.REPORTS_DIR, cfg.INDEX_PATH, cfg.TEMPLATES_DIR, cfg.DATA_DIR, cfg.VIEWS_DIR
        # 保存 server 模块本地别名（独立于 config 的引用）
        _s_rd, _s_idx, _s_td = server.REPORTS_DIR, server.INDEX_PATH, server.TEMPLATES_DIR
        # patch config
        cfg.REPORTS_DIR = tmp / "reports"
        cfg.INDEX_PATH = tmp / "index.html"
        cfg.TEMPLATES_DIR = tmp / "templates"
        cfg.DATA_DIR = tmp / "data"  # P1: 隔离 DB
        cfg.VIEWS_DIR = tmp / "views"  # P3: 视图模板
        # patch server 本地别名
        server.REPORTS_DIR = tmp / "reports"
        server.INDEX_PATH = tmp / "index.html"
        server.TEMPLATES_DIR = tmp / "templates"
        yield tmp
        # 恢复
        cfg.REPORTS_DIR, cfg.INDEX_PATH, cfg.TEMPLATES_DIR, cfg.DATA_DIR, cfg.VIEWS_DIR = _rd, _idx, _td, _dd, _vd
        server.REPORTS_DIR, server.INDEX_PATH, server.TEMPLATES_DIR = _s_rd, _s_idx, _s_td
