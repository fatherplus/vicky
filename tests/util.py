"""测试公共：从文件加载 server 模块 + 临时目录环境。"""
import contextlib
import importlib.util
import tempfile
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent


def load_server():
    spec = importlib.util.spec_from_file_location("aireport_server", REPO / "server.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # __main__ 守卫保证不起服务
    return mod


@contextlib.contextmanager
def tmp_env(server):
    """把 REPORTS_DIR/INDEX_PATH/NGINX_DIR 指到临时目录，subprocess.run 打桩为记录器。"""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "reports").mkdir()
        orig = (server.REPORTS_DIR, server.INDEX_PATH, server.NGINX_DIR)
        server.REPORTS_DIR = tmp / "reports"
        server.INDEX_PATH = tmp / "index.html"
        server.NGINX_DIR = tmp / "nginx"
        with mock.patch.object(server.subprocess, "run") as run:
            yield tmp, run
        server.REPORTS_DIR, server.INDEX_PATH, server.NGINX_DIR = orig
