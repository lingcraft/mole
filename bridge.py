import threading
import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PATCHED = {                   # 命中这些 URL 片段 -> 返回本地补丁文件
    "ClientCommonDLL.swf": str(Path(__file__).resolve().parent / "ClientCommonDLL.swf"),
}
INJECT_LISTEN = ("127.0.0.1", 10000)   # 本地注入服务：Flash 直连，不依赖系统代理
BRIDGE_LISTEN = ("127.0.0.1", 20000)   # 命令桥，SWF 直连，绕过系统代理
BRIDGE_BASE = "/_mole_bridge/"

UPSTREAM_BASE = "http://mole.61.com"  # 真实服务器基址，由 mole.py 按当前服/节点设置

# 复用 TCP 连接；trust_env=False 强制不走系统代理，避免回环到本代理自身
_SESSION = requests.Session()
_SESSION.trust_env = False

CMD_QUEUE: list[str] = []          # SWF 轮询命令队列（如 "alert|标题|内容"）


def push_cmd(text: str) -> None:
    """向 SWF 命令桥推入一条命令；SWF 每 ~500ms GET /_mole_bridge/poll 取走。"""
    CMD_QUEUE.append(text)


def set_upstream(base: str) -> None:
    """设置注入服务的真实服务器基址（如切换服/节点时调用）。"""
    global UPSTREAM_BASE
    UPSTREAM_BASE = base.rstrip("/")


def injector_url(path: str = "/Client.swf") -> str:
    """返回本地注入服务的完整 URL（Flash 的 LoadMovie 目标）。"""
    return f"http://{INJECT_LISTEN[0]}:{INJECT_LISTEN[1]}{path}"



# ---------------------------------------------------------------------------
# 注入服务：本地 HTTP 服务，Flash 直连；命中补丁则返回本地文件，否则转发上游
# ---------------------------------------------------------------------------
class _InjectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # 启用 keep-alive：Flash 复用连接，减少每个资源的 TCP 握手/线程开销

    def _handle(self):
        url = self.path
        for frag, local in PATCHED.items():    # 命中补丁：直接返回本地文件
            if frag in url:
                with open(local, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-shockwave-flash")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(data)
                return
        # 透传客户端请求头（去掉代理相关头、host）；保留 accept-encoding 让上游压缩返回，
        # 减小传输量。转发到真实服务器（UPSTREAM_BASE 由 set_upstream 按服/节点设置）
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("proxy-connection", "proxy-authorization", "host")}
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or None
        target = UPSTREAM_BASE + url
        try:
            resp = _SESSION.request(self.command, target, headers=headers, data=body,
                                    stream=True, timeout=30)
        except Exception:
            self.send_response(502)
            self.end_headers()
            return
        # 仅补丁 ClientCommonDLL.swf 不缓存（见上方 PATCHED 分支）；其余资源透传上游
        # 缓存头，让 Flash 正常缓存，避免每次加载都重新拉取全部资源。
        # （注入器只处理官服流量；官服无节点切换，无需为刷新配置而强制 no-cache）
        if "content-length" in resp.headers:
            # 上游给出长度：流式转发压缩字节(decode_content=False)，减少带宽且不必整包入内存
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                if k.lower() in ("transfer-encoding", "connection"):
                    continue
                self.send_header(k, v)
            self.end_headers()
            try:
                for chunk in resp.raw.stream(65536, decode_content=False):
                    self.wfile.write(chunk)
            finally:
                resp.close()
        else:
            # 上游分块传输(无 content-length)：退回读取解压后的内容，按实际长度发送
            data = resp.content
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                if k.lower() in ("transfer-encoding", "connection", "content-encoding",
                                 "content-length"):
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, *args):
        pass


def start_injector():
    """启动本地注入服务（守护线程），返回 ThreadingHTTPServer 实例。"""
    srv = ThreadingHTTPServer(INJECT_LISTEN, _InjectHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------------------
# 命令桥：localhost，SWF 直连，绕过系统代理
# ---------------------------------------------------------------------------
class _BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # 命令桥同样启用 keep-alive，Flash 轮询复用同一连接
    def _handle(self):
        url = self.path
        # 跨域策略文件：mole.61.com 的 SWF 访问 127.0.0.1 需要它
        if url.startswith("/crossdomain.xml"):
            policy = (
                b'<?xml version="1.0"?>\n'
                b'<!DOCTYPE cross-domain-policy SYSTEM '
                b'"http://www.adobe.com/xml/dtds/cross-domain-policy.dtd">\n'
                b'<cross-domain-policy>\n'
                b'<allow-access-from domain="*" to-ports="*"/>\n'
                b'</cross-domain-policy>\n'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(policy)))
            self.end_headers()
            self.wfile.write(policy)
            return
        # 命令轮询：返回队列首条命令并消费（无命令返回 "none"）
        if url.startswith(BRIDGE_BASE + "poll"):
            cmd = CMD_QUEUE.pop(0) if CMD_QUEUE else "none"
            body = cmd.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    do_GET = _handle
    do_POST = _handle

    def log_message(self, *args):
        pass


def start_bridge():
    """启动 localhost 命令桥（守护线程），返回 ThreadingHTTPServer 实例。"""
    srv = ThreadingHTTPServer(BRIDGE_LISTEN, _BridgeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
