from os import environ
from re import match
import copy
import xml.etree.ElementTree as ET
from socket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR, timeout
from threading import Thread, Lock
from requests import Session
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from ctypes import wintypes, WinDLL
from urllib.parse import urlparse, parse_qs
from json import loads
from loguru import logger

# swf/append 下的 *.swf 注入 ext.xml 让客户端额外加载；
# swf/replace 下的同名 SWF 在客户端请求时就地替换为本地文件（覆盖上游官方 SWF）。
# 注意：replace 仅放要覆盖的官方 SWF，append 仅放自定义 mod，勿混用。
base_dir = Path(__file__).resolve().parent
append_dir = base_dir / "swf" / "append"    # 追加 SWF
replace_dir = base_dir / "swf" / "replace"  # 替换 SWF
cache_dir = Path(environ["appdata"]) / "mole" / "cache"  # SWF 缓存


def list_append_swfs() -> list[Path]:
    """列出 swf/append 下所有 *.swf（按文件名排序，保证加载顺序稳定）。"""
    if not append_dir.is_dir():
        return []
    return sorted((p for p in append_dir.glob("*.swf") if p.is_file()), key=lambda p: p.name.lower())


def merge_append(orig: ET.Element, append: ET.Element) -> None:
    """将 append 子树合并进 orig：
    - 同名/同 id 的元素：用 append 的属性覆盖 orig 的对应属性（orig 独有属性保留），再递归其子节点；
    - 仅 append 独有的元素（容器或 item）：整棵子树追加；
    - <remove> 标记：其下的 <item> 按 id 从当前层级删除，<remove> 节点本身不并入结果；
    - 匹配规则：容器按 tag 名匹配，item 按 id 匹配。
    例如原始 <shop info="原始info"> 与补充 <shop info="新info"> 合并后，info 被替换为「新info」。"""
    # 用 append 的属性覆盖当前层匹配元素的属性（不删除 orig 独有属性）
    for k, v in append.attrib.items():
        orig.set(k, v)
    for ac in list(append):
        if not isinstance(ac.tag, str):
            continue  # 跳过注释等非元素节点
        if ac.tag == "remove":  # 删除标记：其下 item 按 id 从 orig 当前层级删除，<remove> 本身不并入
            for di in ac:
                if not isinstance(di.tag, str) or di.tag != "item":
                    continue
                did = di.get("id")
                target = next(
                    (c for c in orig if isinstance(c.tag, str) and c.tag == "item" and c.get("id") == did),
                    None,
                )
                if target is not None:
                    orig.remove(target)
            continue
        if ac.tag == "item":  # item 按 id 匹配
            oc = next((c for c in orig if isinstance(c.tag, str) and c.tag == "item" and c.get("id") == ac.get("id")), None)
        else:  # 容器按 tag 名匹配
            oc = next((c for c in orig if isinstance(c.tag, str) and c.tag == ac.tag), None)
        if oc is None:
            orig.append(copy.deepcopy(ac))
        else:
            merge_append(oc, ac)


injecter_port: int = 10000  # 本实例注入服务实际监听端口（动态分配，多客户端隔离）
upstream_base = "http://mole.61.com"  # 真实服务器基址，由 mole.py 按服/节点设置
parallel_base = "http://mole.61player.com"  # 平行服基址：官服资源上游 0 字节时回退取此
replace_list = ["JDGoodsXmlData.xml"]  # 官服替换为平行服的资源


def fallback_cache_path(url: str) -> Path:
    """官服 URL 路径 → 本地缓存文件绝对路径（镜像 URL 路径结构）。"""
    rel = url.split("?", 1)[0].lstrip("/")
    return cache_dir / rel


def content_type_for(name: str) -> str:
    """按文件后缀推断回传的 Content-Type。"""
    lower = name.lower()
    if lower.endswith(".swf"):
        return "application/x-shockwave-flash"
    if lower.endswith(".xml"):
        return "application/xml"
    return "application/octet-stream"

# 复用 TCP 连接；trust_env=False 强制不走系统代理，避免回环到本代理自身
session = Session()
session.trust_env = False

cmd_queue: list[str] = []  # SWF 命令队列（如 "alert|标题|内容"）


def push_cmd(text: str) -> None:
    """向命令队列推入一条命令；socket 桥逐条下发给 SWF（统一加 send_prefix 前缀）。"""
    cmd_queue.append(f"{send_prefix}{text}")


response_handler = None  # 结果回调函数


def set_response_handler(func) -> None:
    """注册 SWF 回传处理函数；收到 SWF 响应时以 (cmd, payload) 调用之。"""
    global response_handler
    response_handler = func


def set_upstream(base: str) -> None:
    """设置注入服务的真实服务器基址（切换服/节点时调用）。"""
    global upstream_base
    upstream_base = base.rstrip("/")


def is_official_server() -> bool:
    """当前上游是否为官服（mole.61.com）；非官服不启用平行服回退。"""
    return urlparse(upstream_base).netloc == "mole.61.com"


def injector_url(path: str = "/Client.swf") -> str:
    """返回本地注入服务的完整 URL（Flash 的 LoadMovie 目标）。"""
    return f"http://127.0.0.1:{injecter_port}{path}"


def clear_ext_xml_cache() -> None:
    """清除 WinINet 缓存里的 ext.xml，避免客户端命中旧版（未注入 mod 的）配置。
    注入器已对 ext.xml 发 no-store，此函数只清历史残留。"""
    # 1) 按 URL 删除 WinINet 索引条目（索引+文件一并清理）
    try:
        wininet = WinDLL("wininet", use_last_error=True)
        delete_url_cache_entry_w = wininet.DeleteUrlCacheEntryW
        delete_url_cache_entry_w.argtypes = [wintypes.LPCWSTR]  # 必须显式声明，否则 64 位下指针被截断
        delete_url_cache_entry_w.restype = wintypes.BOOL
        urls = {
            "http://mole.61.com/resource/xml/ext.xml",
            f"{upstream_base}/resource/xml/ext.xml",
            f"http://127.0.0.1:{injecter_port}/resource/xml/ext.xml",
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

    def serve_local_cacheable(self, data: bytes, content_type: str):
        """以可缓存方式返回一段本地字节（带较长过期时间，不带 no-store/no-cache），
        交由 Flash 存入本地 SWF 缓存目录，进一步减少重复加载。"""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=2592000")
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            # 客户端中途断开：静默结束
            pass

    def dispatch(self):
        url = self.path
        # 命令桥端口发现：SWF 从 loaderInfo.url 解析出注入服务器后，GET /cmd-port 取真实 socket 端口
        # （不依赖 ext.xml 的 ?port= 查询串，兼容 new 实例化 / loadBytes 等拿不到参数的场景）
        if url.split("?", 1)[0] == "/cmd-port":
            self.serve_local(str(bridge_port).encode("utf-8"), "text/plain; charset=utf-8")
            return
        # BridgeDLL 诊断回传：把 SWF 内部状态打印到控制台，便于排查连桥问题
        if url.split("?", 1)[0] == "/log":
            try:
                q = parse_qs(urlparse(self.path).query)
                logger.info(f"[bridgedll] {q.get("m", [""])[0]}")
            except Exception:
                pass
            self.serve_local(b"ok", "text/plain; charset=utf-8")
            return
        # 官服无前缀直接透传；其他服用 /server<索引>/ 前缀隔离缓存，这里剥离前缀再按原逻辑处理
        m = match(r"^/server\d+(/.*)$", url)
        if m:
            url = m.group(1)
        # ext.xml：动态注入根目录下的 *.swf，无额外 SWF 时原样透传
        if self.command == "GET" and "ext.xml" in url:
            if self.serve_ext_xml(url):
                return
        # 额外资源：
        # 1) swf/replace 中的同名 SWF/XML → 就地替换为本地文件，覆盖上游官方文件
        # 2) swf/append 中的 .swf → 直接返回本地 mod 文件
        # 3) swf/append 中的 .xml → 视为「新增内容」：拉取上游原始 xml 并合并新增节点后返回
        name = url.split("?", 1)[0].rsplit("/", 1)[-1]
        lower = name.lower()
        if lower.endswith(".swf") or lower.endswith(".xml"):
            replace_local = replace_dir / name  # 优先 replace：同名覆盖官方 SWF/XML
            if replace_local.is_file():
                ctype = "application/x-shockwave-flash" if lower.endswith(".swf") else "application/xml"
                self.serve_local(replace_local.read_bytes(), ctype)
                return
            append_local = append_dir / name
            if append_local.is_file():
                if lower.endswith(".swf"):
                    self.serve_local(append_local.read_bytes(), "application/x-shockwave-flash")
                else:
                    self.serve_merged_xml(url, append_local)
                return
            # 官服：replace_list 命中的资源强制替换为平行服对应资源并允许缓存
            if is_official_server() and name in replace_list:
                self.serve_parallel_replace(url, name)
                return
            # 官服：上游返回 0 字节的资源改用平行服资源（交由 Flash 本地缓存）
            if is_official_server():
                self.serve_fallback(url, name)
                return
        # 其余请求透传上游（保留缓存头，流式转发压缩字节）
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("proxy-connection", "proxy-authorization", "host")}
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or None
        target = upstream_base + url
        try:
            resp = session.request(self.command, target, headers=headers, data=body, stream=True, timeout=30)
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
                if k.lower() in ("transfer-encoding", "connection", "content-encoding", "content-length"):
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
        """取上游原版 ext.xml，把 swf/append 下所有 *.swf 追加为 <item> 后返回。
        返回 True 表示已处理；False 表示放弃（如上游取回失败），交回 dispatch 走透传。"""
        mods = list_append_swfs()
        try:
            resp = session.get(upstream_base + url, timeout=30)
        except Exception:
            return False
        if resp.status_code != 200:
            return False
        text = resp.text
        if mods and "</ext>" in text:
            items = "".join(
                f"\t\t<item name=\"摩尔拓展.....\" path=\"{p.name}\" ver=\"081224\"/>\n"
                for p in mods
            )
            text = text.replace("</ext>", items + "\t</ext>", 1)
            logger.info(f"[ext.xml] 注入: {"，".join(p.name for p in mods)}")
        else:
            logger.info(f"[ext.xml] 注入失败，ext.xml 中未找到 <ext> 节点")
        self.serve_local(text.encode("utf-8"), "application/xml")
        return True

    def serve_merged_xml(self, url: str, append_path: Path) -> None:
        """把 swf/append 下的「补充 xml」合并进上游原始 xml 后返回。
        append xml 仅含新增节点（同根/同层级结构）；先取上游原版 xml，
        再把补充 xml 中的节点按 id 去重后并入对应容器，最后返回合并结果。
        若上游取回 / 解析失败，则回退为直接返回本地补充文件。"""
        try:
            resp = session.get(upstream_base + url, timeout=30)
        except Exception:
            logger.warning(f"[resource] 取上游原始 xml 失败，回退返回本地补充文件: {url}")
            self.serve_local(append_path.read_bytes(), "application/xml")
            return
        if resp.status_code != 200:
            logger.warning(f"[resource] 上游返回 {resp.status_code}，回退返回本地补充文件: {url}")
            self.serve_local(append_path.read_bytes(), "application/xml")
            return
        try:
            orig_root = ET.fromstring(resp.content.decode("utf-8-sig"))
            append_root = ET.parse(append_path).getroot()
        except Exception as e:
            logger.warning(f"[resource] 解析 xml 失败（{e}），回退返回本地补充文件")
            self.serve_local(append_path.read_bytes(), "application/xml")
            return
        merge_append(orig_root, append_root)
        merged = ET.tostring(orig_root, encoding="utf-8")
        self.serve_local(merged, "application/xml")
        logger.info(f"[resource] 修改: {append_path.name}")

    def relay_cacheable(self, resp) -> None:
        """转发上游响应，剔除 hop-by-hop 头（transfer-encoding/connection/
        content-encoding/content-length，长度由本方法按真实解压后字节重算）。
        缓存相关头（cache-control/pragma/expires）原样保留——若上游本就带
        no-store/no-cache，则遵循上游、不强行改为可缓存；仅当上游完全没有
        任何缓存指令时，补一个 max-age=2592000 促使 Flash 缓存。"""
        self.send_response(resp.status_code)
        has_cache = False
        for k, v in resp.headers.items():
            lk = k.lower()
            if lk in ("transfer-encoding", "connection", "content-encoding", "content-length"):
                continue
            if lk in ("cache-control", "pragma", "expires"):
                has_cache = True  # 上游自带缓存指令（含 no-store/no-cache），原样遵循
            self.send_header(k, v)
        # 上游完全没有缓存指令时，补一个较长过期时间促使 Flash 缓存
        if not has_cache:
            self.send_header("Cache-Control", "max-age=2592000")
        data = resp.content
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            pass

    def serve_resource(self, url: str, name: str, prefer_parallel: bool) -> None:
        """官服/平行服资源统一获取与缓存（serve_fallback 与 serve_parallel_replace 的公共实现）。
        - prefer_parallel=False (fallback)：官服优先；官服为空/失败再回退平行服。采用官服时不缓存（便于官服恢复即时生效）；
          仅当采用平行服时写本地缓存。两服皆空时退回官服响应（哪怕 0 字节），否则 502。
        - prefer_parallel=True (replace)：平行服优先，强制替换官服；采用平行服时写本地缓存并以可缓存方式返回；
          平行服取不到才回退官服透传，否则 502。
        本地缓存命中时直接可缓存返回，跳过网络。"""
        cache_path = fallback_cache_path(url)
        if cache_path.is_file():
            data = cache_path.read_bytes()
            logger.info(f"[resource] 加载: {name}")
            self.serve_local_cacheable(data, content_type_for(name))
            return
        primary, secondary = (parallel_base, upstream_base) if prefer_parallel else (upstream_base, parallel_base)
        last_official = None  # 官服响应（含 0 字节），仅 fallback 双空兜底用
        resp = source = None
        for base in (primary, secondary):
            try:
                r = session.get(base + url, timeout=30)
            except Exception:
                r = None
            if r is not None and r.status_code == 200 and len(r.content) > 0:
                resp, source = r, base
                break
            if base is upstream_base:
                last_official = r
        else:
            # 官服与平行服都无有效内容
            if not prefer_parallel and last_official is not None:
                self.relay_cacheable(last_official)  # 退回官服响应（哪怕 0 字节）
            else:
                self.send_response(502)
                self.end_headers()
            return
        if source is parallel_base:
            # 采用平行服：写本地缓存并以可缓存方式返回
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(resp.content)
            except Exception as e:
                logger.warning(f"[resource] 写入本地缓存失败: {e}")
            logger.info(f"[resource] 缓存: {name}")
            self.serve_local_cacheable(resp.content, content_type_for(name))
        else:
            # 采用官服：透传上游缓存头，不写本地缓存
            self.relay_cacheable(resp)

    def serve_fallback(self, url: str, name: str) -> None:
        """官服资源上游返回 0 字节（或取回失败）时，改用平行服同路径资源（详见 _serve_resource）。"""
        self.serve_resource(url, name, False)

    def serve_parallel_replace(self, url: str, name: str) -> None:
        """replace_list 命中：官服资源强制替换为平行服同路径资源并允许缓存（详见 _serve_resource）。"""
        self.serve_resource(url, name, True)

    do_GET = dispatch
    do_POST = dispatch

    def log_message(self, *args):
        pass


def start_bridge():
    """启动本地桥服务（守护线程）：注入服务(动态端口) + socket 命令桥(动态端口)。
    两个端口均由 OS 动态分配，保证多客户端实例各用独立端口、互不干扰。"""
    global injecter_port
    http_srv = ThreadingHTTPServer(("127.0.0.1", 0), InjectHandler)
    injecter_port = http_srv.server_address[1]
    logger.info(f"[bridge] 注入服务端口: {injecter_port}")
    clear_ext_xml_cache()  # 此时 injecter_port 已知，清对应本地 ext.xml 缓存
    Thread(target=http_srv.serve_forever, daemon=True).start()
    start_socket_bridge()
    return http_srv


# ---------------------------------------------------------------------------
# socket 命令桥：127.0.0.1:10001，SWF 用 flash.net.Socket 连接，替代 HTTP 轮询
# ---------------------------------------------------------------------------
bridge_port: int = 10001  # 本实例 socket 命令桥实际监听端口（由 start_socket_bridge 动态分配）

# 当前唯一生效的 SWF 连接：刷新重载后旧连接必须被淘汰，否则多个连接共享 cmd_queue
# 会随机分流命令、旧半开连接吞掉命令。新连接到来即取代旧的。
conn_lock = Lock()
active_conn = None


def set_active(conn):
    """把 conn 设为当前唯一生效的命令目标；关闭并淘汰上一个连接（如刷新后的旧 SWF 实例）。"""
    global active_conn
    with conn_lock:
        old = active_conn
        active_conn = conn
    if old is not None and old is not conn:
        try:
            old.close()
            logger.info("[bridge] 新连接已取代旧连接，旧连接已关闭")
        except Exception:
            pass


def release_active(conn):
    """若 conn 仍是当前生效连接，则清空，避免命令继续发往已死的 socket。"""
    global active_conn
    with conn_lock:
        if active_conn is conn:
            active_conn = None


# SWF↔本地命令方向前缀（与 mole.py 的 Show.SEND/Show.RECV 一致）
send_prefix = "S ==>"
recv_prefix = "R <=="

# Flash socket 策略文件：允许任意域连接任意端口
sock_policy = (
    b"<?xml version=\"1.0\"?>\r\n"
    b"<!DOCTYPE cross-domain-policy SYSTEM "
    b"\"http://www.adobe.com/xml/dtds/cross-domain-policy.dtd\">\r\n"
    b"<cross-domain-policy>\r\n"
    b"<allow-access-from domain=\"*\" to-ports=\"*\"/>\r\n"
    b"</cross-domain-policy>\r\n"
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

    # 标记为当前生效连接：刷新重载后新连接取代旧连接，旧连接被关闭、其线程随后退出，
    # 从而避免多个 SWF 实例的连接共存、共享 cmd_queue 互相抢命令。
    set_active(conn)

    # 数据通道主循环：recv 设 0.25s 超时，超时则回到顶部下发命令
    conn.settimeout(0.25)
    sock_buf = ""  # 跨 recv 的行缓冲，保证大 JSON 不被 TCP 分段切断
    while True:
        # 若已被更新的连接取代（如再次刷新），立即退出，不再服务于命令
        with conn_lock:
            if conn is not active_conn:
                break
        # 下行：队列有命令则全部推送
        while cmd_queue:
            cmd = cmd_queue.pop(0)
            try:
                conn.sendall((cmd + "\x01").encode("utf-8"))
            except Exception:
                release_active(conn)
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
        # 跨 recv 累积缓冲，只处理以 \n 结尾的完整行：
        # 大 JSON 响应会被 TCP 分段，若逐次 split 会把半截 JSON 当完整行解析失败。
        sock_buf += data.decode("utf-8", "ignore")
        while "\x01" in sock_buf:
            line, sock_buf = sock_buf.split("\x01", 1)
            if not line:
                continue
            # SWF 回传统一带 "R <==" 前缀，去掉后再解析
            if line.startswith(recv_prefix):
                line = line[len(recv_prefix):]
            # 拆分为 "cmd|payload"
            if "|" in line:
                cmd, payload = line.split("|", 1)
            else:
                cmd, payload = line, ""
            # getItemInfo 回传是 JSON 字符串，解析成 dict 便于使用
            if cmd == "getItemInfo":
                try:
                    payload = loads(payload)
                except Exception:
                    pass
            # 交给 mole.py 注册的回调；未注册则对关键回传打印到控制台
            if response_handler is not None:
                try:
                    response_handler(cmd, payload)
                except Exception:
                    pass
    release_active(conn)
    conn.close()


def start_socket_bridge():
    """启动 socket 命令桥（守护线程），返回监听 socket。
    端口由 OS 动态分配（bind 0），保证多客户端实例各用独立端口、互不干扰。"""
    global bridge_port
    srv = socket(AF_INET, SOCK_STREAM)
    srv.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))  # 0 = 由 OS 分配空闲端口
    bridge_port = srv.getsockname()[1]
    logger.info(f"[bridge] 命令桥端口: {bridge_port}")
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
