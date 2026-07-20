from os import environ
from re import match
from socket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR, timeout
from threading import Thread
from requests import Session
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 根目录下的 *.swf 注入 ext.xml 并就地提供。
# 注意：只放自定义 mod，勿放游戏官方 SWF（如 Client.swf），否则会覆盖上游。
base_dir = Path(__file__).resolve().parent


def list_mod_swfs() -> list[Path]:
    """列出根目录下所有 *.swf（按文件名排序，保证加载顺序稳定）。"""
    if not base_dir.is_dir():
        return []
    return sorted((p for p in base_dir.glob("*.swf") if p.is_file()),
                  key=lambda p: p.name.lower())


injecter_address = ("127.0.0.1", 10000)  # 注入服务：Flash 直连，不走系统代理
upstream_base = "http://mole.61.com"  # 真实服务器基址，由 mole.py 按服/节点设置

# 复用 TCP 连接；trust_env=False 强制不走系统代理，避免回环到本代理自身
session = Session()
session.trust_env = False

cmd_queue: list[str] = []  # SWF 命令队列（如 "alert|标题|内容"）


def push_cmd(text: str) -> None:
    """向命令队列推入一条命令；socket 桥逐条下发给 SWF（统一加 send_prefix 前缀）。"""
    cmd_queue.append(f"{send_prefix}{text}")


def set_upstream(base: str) -> None:
    """设置注入服务的真实服务器基址（切换服/节点时调用）。"""
    global upstream_base
    upstream_base = base.rstrip("/")


def injector_url(path: str = "/Client.swf") -> str:
    """返回本地注入服务的完整 URL（Flash 的 LoadMovie 目标）。"""
    return f"http://{injecter_address[0]}:{injecter_address[1]}{path}"


def clear_ext_xml_cache() -> None:
    """清除 WinINet 缓存里的 ext.xml，避免客户端命中旧版（未注入 mod 的）配置。
    注入器已对 ext.xml 发 no-store，此函数只清历史残留。"""
    # 1) 按 URL 删除 WinINet 索引条目（索引+文件一并清理）
    try:
        import ctypes
        from ctypes import wintypes
        wininet = ctypes.WinDLL("wininet", use_last_error=True)
        delete_url_cache_entry_w = wininet.DeleteUrlCacheEntryW
        delete_url_cache_entry_w.argtypes = [wintypes.LPCWSTR]  # 必须显式声明，否则 64 位下指针被截断
        delete_url_cache_entry_w.restype = wintypes.BOOL
        urls = {
            "http://mole.61.com/resource/xml/ext.xml",
            f"{upstream_base}/resource/xml/ext.xml",
            f"http://{injecter_address[0]}:{injecter_address[1]}/resource/xml/ext.xml",
        }
        for url in urls:
            try:
                delete_url_cache_entry_w(url)
            except Exception:
                pass
    except Exception:
        pass
    # 2) 兜底：直接删除 INetCache\IE 下所有 ext*.xml 文件
    try:
        cache_root = Path(environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "INetCache" / "IE"
        if cache_root.is_dir():
            for f in cache_root.glob("**/ext*.xml"):
                try:
                    f.unlink()
                except Exception:
                    pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 注入服务：本地 HTTP，Flash 直连；命中 mod 则返回本地文件，否则转发上游
# ---------------------------------------------------------------------------
class InjectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive：Flash 复用连接

    def serve_local(self, data: bytes, content_type: str):
        """以 no-store 方式返回一段本地字节。"""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            # 客户端中途断开：静默结束
            pass

    def dispatch(self):
        url = self.path
        # 官服无前缀直接透传；其他服用 /server<索引>/ 前缀隔离缓存，这里剥离前缀再按原逻辑处理
        m = match(r"^/server\d+(/.*)$", url)
        if m:
            url = m.group(1)
        # ext.xml：动态注入根目录下的 *.swf，无额外 SWF 时原样透传
        if self.command == "GET" and "ext.xml" in url:
            if self.serve_ext_xml(url):
                return
        # 额外 SWF：游戏按 ext.xml 追加的 path 请求，就地提供
        name = url.split("?", 1)[0].rsplit("/", 1)[-1]
        if name.lower().endswith(".swf"):
            local = base_dir / name
            if local.is_file():
                self.serve_local(local.read_bytes(), "application/x-shockwave-flash")
                return
        # 其余请求透传上游（保留缓存头，流式转发压缩字节）
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("proxy-connection", "proxy-authorization", "host")}
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or None
        target = upstream_base + url
        try:
            resp = session.request(self.command, target, headers=headers, data=body,
                                   stream=True, timeout=30)
        except Exception:
            self.send_response(502)
            self.end_headers()
            return
        if "content-length" in resp.headers:
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                if k.lower() in ("transfer-encoding", "connection"):
                    continue
                self.send_header(k, v)
            self.end_headers()
            try:
                for chunk in resp.raw.stream(65536, decode_content=False):
                    self.wfile.write(chunk)
            except OSError:
                # 客户端中途断开（如 Flash 刷新时取消下载）：静默结束，不打 traceback
                pass
            finally:
                resp.close()
        else:
            # 上游分块传输：读取解压后内容，按实际长度发送
            data = resp.content
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                if k.lower() in ("transfer-encoding", "connection", "content-encoding",
                                 "content-length"):
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                # 客户端中途断开：静默结束
                pass

    def serve_ext_xml(self, url: str) -> bool:
        """取上游原版 ext.xml，把根目录下所有 *.swf 追加为 <item> 后返回。
        返回 True 表示已处理；False 表示放弃（如上游取回失败），交回 dispatch 走透传。"""
        mods = list_mod_swfs()
        try:
            resp = session.get(upstream_base + url, timeout=30)
        except Exception:
            return False
        if resp.status_code != 200:
            return False
        text = resp.text
        if mods and "</ext>" in text:
            items = "".join(
                f'\t\t<item name="摩尔拓展....." path="{p.name}" ver="081224"/>\n'
                for p in mods
            )
            text = text.replace("</ext>", items + "\t</ext>", 1)
        self.serve_local(text.encode("utf-8"), "application/xml")
        return True

    do_GET = dispatch
    do_POST = dispatch

    def log_message(self, *args):
        pass


def start_bridge():
    """启动本地桥服务（守护线程）：注入服务(10000) + socket 命令桥(10001)。"""
    clear_ext_xml_cache()  # 清旧版 ext.xml 缓存，保证拉到最新（含 mod）
    srv = ThreadingHTTPServer(injecter_address, InjectHandler)
    Thread(target=srv.serve_forever, daemon=True).start()
    start_socket_bridge()
    return srv


# ---------------------------------------------------------------------------
# socket 命令桥：127.0.0.1:10001，SWF 用 flash.net.Socket 连接，替代 HTTP 轮询
# ---------------------------------------------------------------------------
bridge_address = ("127.0.0.1", 10001)

# SWF↔本地命令方向前缀（与 mole.py 的 Show.SEND/Show.RECV 一致）
send_prefix = "S ==>"
recv_prefix = "R <=="

# Flash socket 策略文件：允许任意域连接任意端口
sock_policy = (
    b'<?xml version="1.0"?>\r\n'
    b'<!DOCTYPE cross-domain-policy SYSTEM '
    b'"http://www.adobe.com/xml/dtds/cross-domain-policy.dtd">\r\n'
    b'<cross-domain-policy>\r\n'
    b'<allow-access-from domain="*" to-ports="*"/>\r\n'
    b'</cross-domain-policy>\r\n'
)


def sock_serve(conn):
    # Flash 连接后先发 <policy-file-request/> 请求策略文件
    conn.settimeout(5.0)
    try:
        data = conn.recv(4096)
    except Exception:
        conn.close()
        return
    if b"<policy-file-request" in data:
        try:
            conn.sendall(sock_policy + b"\x00")
        except Exception:
            conn.close()
            return

    # 数据通道主循环：recv 设 0.25s 超时，超时则回到顶部下发命令
    conn.settimeout(0.25)
    while True:
        # 下行：队列有命令则全部推送
        while cmd_queue:
            cmd = cmd_queue.pop(0)
            try:
                conn.sendall((cmd + "\n").encode("utf-8"))
            except Exception:
                conn.close()
                return
        # 上行：读取 SWF 回传（READY / PING / ECHO 等）
        try:
            data = conn.recv(4096)
        except timeout:
            continue
        except Exception:
            break
        if not data:
            break
        for line in data.decode("utf-8", "ignore").split("\n"):
            line = line.rstrip("\r")
            if not line:
                continue
    conn.close()


def start_socket_bridge():
    """启动 socket 命令桥（守护线程），返回监听 socket。"""
    srv = socket(AF_INET, SOCK_STREAM)
    srv.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    srv.bind(bridge_address)
    srv.listen(8)

    def loop():
        while True:
            try:
                conn, addr = srv.accept()
            except Exception:
                continue
            Thread(target=sock_serve, args=(conn,), daemon=True).start()

    Thread(target=loop, daemon=True).start()
    return srv
