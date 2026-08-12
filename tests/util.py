"""测试公共：从 vicky 包加载模块 + 临时目录环境。"""
import contextlib
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_server():
    """返回 vicky.l1_publish 模块（兼容旧测试的 server.* 调用）。
    2026-08-12 重构：Handler 已删（FastAPI 换壳），HTTP 层测试改用下方
    http_get/http_post（TestClient）或 live_server（真端口）。"""
    import vicky.l1_publish as mod
    return mod


def client():
    """FastAPI TestClient（进程内、无 socket）——旧 ThreadingHTTPServer+Handler 模式的替代。"""
    from fastapi.testclient import TestClient
    from vicky.web import app
    return TestClient(app)


def http_get(path: str):
    """GET → (status, body_bytes, headers)，与旧 _get 同形状。"""
    r = client().get(path)
    return r.status_code, r.content, r.headers


def http_post(path: str, body: dict):
    """POST JSON → (status, parsed_json)，与旧 _post 同形状。"""
    r = client().post(path, json=body)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"raw": r.text}


@contextlib.contextmanager
def live_server():
    """起真实 uvicorn 服务（随机空闲端口）——仅用于需要裸 socket 的场景
    （如路径穿越测试，httpx 客户端会归一化 ../）。yield 端口号。"""
    import socket
    import threading
    import time
    import uvicorn
    from vicky.web import app
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    try:
        yield port
    finally:
        srv.should_exit = True
        t.join(timeout=5)


@contextlib.contextmanager
def tmp_env(server):
    """把 REPORTS_DIR/INDEX_PATH/TEMPLATES_DIR/DATA_DIR/VIEWS_DIR 指到临时目录。
    P0 包化 + P1 DB + P3 前端抢救：patch config 全局路径；server 模块的本地别名同步更新。
    store._db_path() 延迟求值，patch config.DATA_DIR 后自动生效。"""
    import vicky.config as cfg
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
        try:
            yield tmp
        finally:
            # 恢复（无论断言成败都必须还原，否则会污染后续测试）
            cfg.REPORTS_DIR, cfg.INDEX_PATH, cfg.TEMPLATES_DIR, cfg.DATA_DIR, cfg.VIEWS_DIR = _rd, _idx, _td, _dd, _vd
            server.REPORTS_DIR, server.INDEX_PATH, server.TEMPLATES_DIR = _s_rd, _s_idx, _s_td
