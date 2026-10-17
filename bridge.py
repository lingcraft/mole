from os import environ, walk
import copy
import re
import time
import sys
import xml.etree.ElementTree as ET
from socket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, timeout
from threading import Thread, Lock
from requests import Session
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from ctypes import wintypes, WinDLL, Structure, c_ulong, c_char_p, byref, sizeof, windll, get_last_error
from urllib.parse import urlparse, parse_qs
from json import loads
from loguru import logger

# swf/append 下的 *.swf 注入 ext.xml 让客户端额外加载；*.xml 拉上游原始 xml 并合并后返回；
# swf/replace 下的同名 SWF/XML 在客户端请求时就地替换为本地文件（覆盖上游官方资源）。
# 两个目录统一命名规则：「【官服】xxx」去掉前缀匹配 xxx，且仅官服生效；无前缀文件所有服生效
# （replace 兼容旧规则：无前缀且以 DLL.swf 结尾的仅官服生效；append 无此特例，BridgeDLL.swf 等两服都要）。
# 注意：replace 仅放要覆盖的官方资源，append 仅放自定义 mod，勿混用。
base_dir = Path(__file__).resolve().parent
OFFICIAL_PREFIX = "【官服】"  # 文件名前缀：去掉后匹配资源名，且仅官服生效（append/replace 通用）
append_dir = base_dir / "swf" / "append"    # 追加 SWF
replace_dir = base_dir / "swf" / "replace"  # 替换 SWF
cache_dir = Path(environ["appdata"]) / "mole" / "cache"  # SWF 缓存


def list_append_swfs() -> list[tuple[Path, str]]:
    """列出 swf/append 下当前服生效的 *.swf → [(本地文件, 注入名)]（按文件名排序，保证加载顺序稳定）。

    命名规则与 replace 一致：「【官服】xxx.swf」仅官服生效，注入名去前缀（xxx.swf）；
    无前缀所有服生效；官服下同时存在前缀版与无前缀版时前缀版优先（同名只注入一份）。"""
    if not append_dir.is_dir():
        return []
    entries = sorted((p for p in append_dir.glob("*.swf") if p.is_file()), key=lambda p: p.name.lower())
    out: dict[str, Path] = {}  # 注入名 → 本地文件
    for p in entries:
        if p.name.startswith(OFFICIAL_PREFIX):
            if not is_official_server():
                continue
            out[p.name[len(OFFICIAL_PREFIX):]] = p  # 前缀版直接占位（官服下优先于同名无前缀版）
        else:
            out.setdefault(p.name, p)
    return [(p, n) for n, p in out.items()]


def merge_append(orig: ET.Element, append: ET.Element) -> None:
    """将 append 子树合并进 orig：
    - 同名/同 id 的元素：用 append 的属性覆盖 orig 的对应属性（orig 独有属性保留），再递归其子节点；
    - 仅 append 独有的元素（容器或 item）：整棵子树追加；
    - <remove> 标记：按 id 从当前层级删除 item；支持 <remove ids="a,b,c"/> 紧凑写法，
      也兼容其下 <item id="..."/> 子元素写法；<remove> 节点本身不并入结果；
    - 匹配规则：容器按 tag 名匹配，item 按 id 匹配。
    例如原始 <shop info="原始info"> 与补充 <shop info="新info"> 合并后，info 被替换为「新info」。"""
    # 用 append 的属性覆盖当前层匹配元素的属性（不删除 orig 独有属性）
    for k, v in append.attrib.items():
        orig.set(k, v)
    for ac in list(append):
        if not isinstance(ac.tag, str):
            continue  # 跳过注释等非元素节点
        if ac.tag == "remove":  # 删除标记：按 id 从 orig 当前层级删除 item，<remove> 本身不并入
            # 兼容 ids="a,b,c" 紧凑写法 与 子 <item id="..."/> 写法（两者可混用）
            ids = [x.strip() for x in (ac.get("ids") or "").split(",") if x.strip()]
            for di in ac:
                if isinstance(di.tag, str) and di.tag == "item":
                    did = di.get("id")
                    if did:
                        ids.append(did)
            for did in ids:
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


def merge_parallel_add(orig: ET.Element, src: ET.Element) -> None:
    """并入 src（平行服）节点到 orig（官服）基底：
    - 两服共有的元素（容器按 tag、item 按 id 匹配）：用 src 的属性覆盖 orig 对应属性
      （orig 独有属性保留），再递归其子节点；
    - 仅 src 独有的元素整棵子树追加；orig 独有（即平行服删除的）保留不动。"""
    for k, v in src.attrib.items():
        orig.set(k, v)
    for sc in list(src):
        if not isinstance(sc.tag, str):
            continue  # 跳过注释等非元素节点
        if sc.tag == "item":  # item 按 id 匹配
            oc = next((c for c in orig if isinstance(c.tag, str) and c.tag == "item" and c.get("id") == sc.get("id")), None)
        else:  # 容器按 tag 名匹配
            oc = next((c for c in orig if isinstance(c.tag, str) and c.tag == sc.tag), None)
        if oc is None:
            orig.append(copy.deepcopy(sc))  # 平行服新增节点：整棵追加
        else:
            merge_parallel_add(oc, sc)  # 共有节点：平行服属性覆盖 + 递归子节点


injecter_port: int = 10000  # 本实例注入服务实际监听端口（10000/10002/10004…成对递增，多客户端隔离）
official_base = "http://mole.61.com"  # 官服基址
parallel_base = "http://mole.61player.com"  # 平行服基址：官服资源上游 0 字节时回退取此
upstream_base = official_base  # 真实服务器基址，由 mole.py 按服/节点设置
official_host = urlparse(official_base).netloc  # 官服可见域名（Flash 的身份：sol 归属 / WinINet 缓存键都靠它）
parallel_host = urlparse(parallel_base).netloc  # 平行服/版本服可见域名（固定为主节点域名 ⇒ 切节点不改 URL、共享缓存）
chunk_size: int = 4096  # 流式收发块大小（本地 swf 读取与官服透传共用，对齐官服原生加载的进度平滑）
replace_resources = {"JDGoodsXmlData.xml"}  # 官服替换为平行服的资源
merge_resources = {"MoleShop.xml"}  # 需额外并入平行服「新增」节点的 xml（官服/平行服内容不同，如 MoleShop.xml）；其余 append xml 仅在官服原始资源上应用 append 的增删改规则
login_gate_host = "login.mole.61.com"  # 官服 Server.xml 的 MOUrl 指向的死域（80 端口秒拒）：登录的跨域策略与 ip.txt 都发往这里，由 dispatch 登录闸门本地秒回（内容复用 sock_policy）


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


session = Session()  # 上游请求会话
session.trust_env = False  # 上游必须直连：不读注册表/环境变量代理（本机 Clash 等系统代理不会劫持上游转发）
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


def resolve_replace_file(name: str) -> Path | None:
    """解析 swf/replace 中该用哪个本地文件替换请求的资源（入参为请求文件名，如 home.swf）。

    规则（文件名前缀决定生效范围）：
    - 「【官服】xxx」：去掉前缀匹配 xxx，且仅官服替换（平行服不替换）；
    - 无前缀的同名文件：所有服都替换；
    - 兼容旧规则：无前缀且以 DLL.swf 结尾的 SWF（如 ClientAppDLL.swf）仅官服替换；
    - 官服下若同时存在「【官服】xxx」与无前缀 xxx，优先取前者；
    - 未命中返回 None。
    """
    lower = name.lower()
    if is_official_server():
        pref = replace_dir / f"{OFFICIAL_PREFIX}{name}"
        if pref.is_file():
            return pref
        plain = replace_dir / name
        if plain.is_file():
            return plain
        return None
    # 平行服：不替换以「【官服】」前缀标记的文件；无前缀的 DLL 结尾文件沿用旧规则（不替换）
    if lower.endswith("dll.swf"):
        return None
    plain = replace_dir / name
    if plain.is_file():
        return plain
    return None


def resolve_append_file(name: str) -> Path | None:
    """解析 swf/append 中该用哪个本地文件（入参为请求文件名，如 Server.xml）。

    命名规则与 replace 一致：
    - 「【官服】xxx」：去掉前缀匹配 xxx，且仅官服生效（平行服不加载/不合并）；
    - 无前缀的同名文件：所有服都生效；
    - 官服下若同时存在「【官服】xxx」与无前缀 xxx，优先取前者；
    - 未命中返回 None（append 无 DLL.swf 旧规则特例：BridgeDLL.swf 等两服都要）。"""
    if is_official_server():
        pref = append_dir / f"{OFFICIAL_PREFIX}{name}"
        if pref.is_file():
            return pref
        plain = append_dir / name
        return plain if plain.is_file() else None
    plain = append_dir / name
    return plain if plain.is_file() else None


def visible_host() -> str:
    """Flash 看到的域名（决定 sol 归属与 WinINet 缓存键，随服切换）：
    官服 → mole.61.com（与官方客户端共享 Flash 缓存与账号数据）；
    平行服/版本服 → 固定 mole.61player.com（主节点域名：URL 不含节点 ⇒ 切换节点不改变缓存键）。"""
    return official_host if is_official_server() else parallel_host


def injector_url(path: str = "/Client.swf") -> str:
    """返回 Flash 的 LoadMovie 目标：**可见域名、不带端口**（身份 / 缓存键所在）。
    官服 → mole.61.com、平行服/版本服 → mole.61player.com，与官方客户端/浏览器同域名同路径形态
    ⇒ sol 归属一致（共享账号数据）、WinINet 缓存键一致（命中官方 Flash 缓存）；
    端口不进 URL ⇒ 缓存键稳定；实际连接由进程级代理（set_proxy）落到本服务。"""
    return f"http://{visible_host()}{path}"


class INTERNET_PROXY_INFO(Structure):
    """WinINet 代理配置结构（InternetSetOptionA 的 INTERNET_OPTION_PROXY(38) 参数；A 版=窄字符串）。"""
    _fields_ = [("dwAccessType", c_ulong),   # 3 = INTERNET_OPEN_TYPE_PROXY
                ("lpszProxy", c_char_p),
                ("lpszProxyBypass", c_char_p)]


def set_proxy(port: int, host: str = "127.0.0.1") -> None:
    """把**本进程**的 WinINet HTTP 代理指向本地桥接 —— 只影响本进程，不改系统代理设置。

    ⚠ 实测要点：
    · NULL 句柄 + INTERNET_OPTION_PROXY(38) 是**进程内存级**设置：注册表分毫不动、进程退出即失效、
      其它进程不受影响、多开互不干扰（无需备份/还原）；
    · 必须用 **A 版**（InternetSetOptionA + 窄字符串）——W 版在 NULL 句柄下字符串会乱码、不生效；
    · 只代理 http（https 直连，不经过本服务）；勿用 INTERNET_OPTION_PER_CONNECTION_OPTION(75)——它写注册表全局值。
    URL 域名/路径不变 ⇒ sol 归属与 WinINet 缓存键不受影响。"""
    try:
        info = INTERNET_PROXY_INFO(3, f"http={host}:{port}".encode(), b"")
        if windll.wininet.InternetSetOptionA(None, 38, byref(info), sizeof(info)):
            logger.info(f"[bridge] 进程代理已启动")
        else:
            logger.warning(f"[bridge] 进程代理设置失败（err={get_last_error()}）")
    except Exception as e:
        logger.warning(f"[bridge] 进程代理设置异常：{e}")


def clear_ext_xml_cache() -> None:
    """清除 WinINet 缓存里的 ext.xml，避免客户端命中旧版（未注入 mod 的）配置。
    注入器已对 ext.xml 发 no-store，此函数只清历史残留（按 Flash 请求的可见 URL 删）。"""
    # 1) 按 URL 删除 WinINet 索引条目（索引+文件一并清理）
    try:
        wininet = WinDLL("wininet", use_last_error=True)
        delete_url_cache_entry_w = wininet.DeleteUrlCacheEntryW
        delete_url_cache_entry_w.argtypes = [wintypes.LPCWSTR]  # 必须显式声明，否则 64 位下指针被截断
        delete_url_cache_entry_w.restype = wintypes.BOOL
        urls = {
            f"http://{official_host}/resource/xml/ext.xml",  # 官服可见 URL
            f"http://{parallel_host}/resource/xml/ext.xml",  # 平行服可见 URL
            f"http://{parallel_host}{urlparse(upstream_base).path}/resource/xml/ext.xml",  # 版本服可见 URL（当前版本）
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
        cache_root = Path(environ["localappdata"]) / "Microsoft" / "Windows" / "INetCache" / "IE"
        if cache_root.is_dir():
            for f in cache_root.glob("**/ext*.xml"):
                try:
                    f.unlink()
                except Exception:
                    pass
    except Exception:
        pass


def collect_mod_resource_names(only_xml: bool = False) -> set[str]:
    """收集 swf/append 与 swf/replace 下需清理缓存的资源名（去掉「【官服】」前缀）。

    only_xml=True 只收集 xml（启动时用：动态合并类资源如 Server.xml 必须每次重新请求）。"""
    names: set[str] = set()
    for d in (append_dir, replace_dir):
        if not d.is_dir():
            continue
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if not p.is_file():
                continue
            n = p.name[len(OFFICIAL_PREFIX):] if p.name.startswith(OFFICIAL_PREFIX) else p.name
            low = n.lower()
            if not (low.endswith(".swf") or low.endswith(".xml")):
                continue
            if only_xml and not low.endswith(".xml"):
                continue
            names.add(n)
    return names


def clear_mod_resource_caches(only_xml: bool = False) -> None:
    """清除 WinINet 缓存中与 swf/append、swf/replace 下文件同名的 swf/xml 条目。

    用途：更新本地 mod / 合并 xml（如「【官服】Server.xml」对应的 Server.xml）后，
    避免 Flash 命中旧缓存导致改动不生效（读到的还是旧版资源）。
    only_xml=True 只清 xml（启动时调用；swf 留给用户手动「清除缓存」）。

    双保险：
    ① DeleteUrlCacheEntryW 删缓存索引条目（URL 路径未知，用通配形态尽力尝试）；
    ② 兜底扫描 INetCache\\IE 按文件名删除（含 [n] 重名变体，同 clear_ext_xml_cache 的做法）。"""
    names = collect_mod_resource_names(only_xml)
    if not names:
        return
    # ① 删 WinINet 索引条目（索引+文件一并清理；通配不支持时返回 FALSE，无副作用）
    try:
        wininet = WinDLL("wininet", use_last_error=True)
        delete_url_cache_entry_w = wininet.DeleteUrlCacheEntryW
        delete_url_cache_entry_w.argtypes = [wintypes.LPCWSTR]  # 必须显式声明，否则 64 位下指针被截断
        delete_url_cache_entry_w.restype = wintypes.BOOL
        for n in names:
            for host in {official_host, parallel_host}:
                for url in (f"http://{host}/*/{n}", f"http://{host}/{n}"):
                    try:
                        delete_url_cache_entry_w(url)
                    except Exception:
                        pass
    except Exception:
        pass
    # ② 兜底：按文件名删 INetCache\IE 下的缓存文件（含 Server[1].xml 这类重名变体）
    try:
        cache_root = Path(environ["localappdata"]) / "Microsoft" / "Windows" / "INetCache" / "IE"
        if cache_root.is_dir():
            targets = {n.lower() for n in names}
            for root, _dirs, files in walk(cache_root):
                for fn in files:
                    m = re.fullmatch(r"(.+?)(\[\d+\])?(\.[a-z0-9]+)", fn.lower())
                    if m and f"{m.group(1)}{m.group(3)}" in targets:
                        try:
                            (Path(root) / fn).unlink()
                        except Exception:
                            pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 注入服务：本地 HTTP，Flash 经进程级代理过来（绝对 URI 形态）；命中 mod 则返回本地文件，否则转发上游
# ---------------------------------------------------------------------------
class InjectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive：Flash 复用连接
    timeout = 15  # 空闲 keep-alive 连接 15s 无请求则断开并回收线程，避免刷新后僵尸线程堆积

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

    def serve_local_stream(self, path: Path, content_type: str, delay: float = 0.0):
        """像官服透传（relay_stream）那样分块流式返回本地文件（带可缓存头），
        边从文件读取边写出，避免大 swf 整块 read_bytes 读入内存。
        delay>0 时每块间隔 delay 秒，使客户端加载进度渐进而非瞬间跳变。"""
        try:
            size = path.stat().st_size
        except OSError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "max-age=2592000")
        self.end_headers()
        try:
            with path.open("rb") as fp:
                while True:
                    chunk = fp.read(chunk_size)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    if delay > 0:
                        time.sleep(delay)
        except OSError:
            # 客户端中途断开：静默结束
            pass

    def dispatch(self):
        # 代理请求行为绝对 URI（http://host/path?query）→ 拆出目标域名与路径
        url = self.path
        proxy_host = None
        if url[:7].lower() == "http://":
            rest = url[7:]
            slash = rest.find("/")
            proxy_host, url = (rest, "/") if slash < 0 else (rest[:slash], rest[slash:])
        # 命令桥端口发现：SWF 从 loaderInfo.url 解析出注入服务器基址（parseBase 只取域名 ⇒ 请求恒打在根路径），
        # GET /cmd-port 取真实 socket 端口（不依赖 ext.xml 的 ?port= 查询串，兼容 new 实例化 / loadBytes 等拿不到参数的场景）
        if url.split("?", 1)[0] == "/cmd-port":
            self.serve_local(str(bridge_port).encode("utf-8"), "text/plain; charset=utf-8")
            return
        # BridgeDLL 诊断回传：把 SWF 内部状态打印到控制台，便于排查连桥问题
        if url.split("?", 1)[0] == "/log":
            try:
                q = parse_qs(urlparse(url).query)
                logger.info(f"[bridgedll] {q.get("m", [""])[0]}")
            except Exception:
                pass
            self.serve_local(b"ok", "text/plain; charset=utf-8")
            return
        # 仅「本方案请求」（可见域名）应用本地 mod 与路径归一；其他域名（代理卷进来的、原先直连的）按原目标透传
        is_own = proxy_host is None or proxy_host.lower() == visible_host()
        if is_own:
            # 版本服把路径里已含的版本前缀（如 /moleverse/20090626）拨正
            # ⇒ 恢复「真实上游 URL = upstream_base + url」不变式（相对 / 根路径两种请求形态都归一到同一上游）
            version_path = urlparse(upstream_base).path
            if version_path and url.startswith(version_path + "/"):
                url = url[len(version_path):]
        # ext.xml：动态注入根目录下的 *.swf，无额外 SWF 时原样透传
        if is_own and self.command == "GET" and url.split("?", 1)[0].endswith("/ext.xml"):
            if self.serve_ext_xml(url):
                return
        # 额外资源（仅本方案请求）：
        # 1) swf/replace 中的同名 SWF/XML → 就地替换为本地文件，覆盖上游官方文件
        #    （注：「【官服】」前缀的仅官服替换；无前缀的所有服替换；以 DLL 结尾的 SWF 旧规则仅官服替换）
        # 2) swf/append 中的 .swf → 直接返回本地 mod 文件（「【官服】」前缀的仅官服生效）
        # 3) swf/append 中的 .xml → 拉取上游原始 xml 并合并新增/删除/修改节点后返回（同样支持【官服】前缀）
        name = url.split("?", 1)[0].rsplit("/", 1)[-1]
        lower = name.lower()
        if is_own and (lower.endswith(".swf") or lower.endswith(".xml")):
            replace_local = resolve_replace_file(name)  # 优先 replace：同名覆盖官方 SWF/XML
            if replace_local is not None:
                ctype = "application/x-shockwave-flash" if lower.endswith(".swf") else "application/xml"
                self.serve_local_stream(replace_local, ctype)
                return
            append_local = resolve_append_file(name)  # append：同一套「【官服】」前缀规则
            if append_local is not None:
                if lower.endswith(".swf"):
                    self.serve_local_stream(append_local, "application/x-shockwave-flash")
                else:
                    # 所有 append xml 都在「请求的原始资源（官服内容）」上应用 append 的新增/删除/修改规则；
                    # 仅 merge_resources 内的（如 MoleShop.xml）官服/平行服内容不同，需额外并入平行服新增节点
                    self.serve_merged_xml(url, append_local, include_parallel=name in merge_resources)
                return
            # 官服：replace_list 命中的资源强制替换为平行服对应资源并允许缓存
            if is_official_server() and name in replace_resources:
                self.serve_parallel_replace(url, name)
                return
            # 官服：上游返回 0 字节的资源改用平行服资源（交由 Flash 本地缓存）
            if is_official_server():
                self.serve_fallback(url, name)
                return
        # 登录闸门（仅官服）：官服 Server.xml 的 MOUrl 指向死域 login.mole.61.com，登录时 Flash 要
        # 跨域请求它的 crossdomain.xml（策略）与 ip.txt（登录服地址），任何真实往返都是 5s 白等
        # （连接拒绝 + WinINet 重试）。平行服域名是活的、有自己的正常流程，不走此闸门。
        # 两个应答在本地等价复刻：
        # · /crossdomain.xml → 复用 sock_policy 原字节（domain="*"，HTTP 策略检查忽略 to-ports；
        #   与本地命令桥「信任所有域」的立场一致）。带 2022 年 Last-Modified 让 WinINet
        #   启发式长缓存，与旧透传行为一致（共享缓存里那条对摩尔江江等仍生效）
        # · /ip.txt → 本地 404：onGetIpPort 对失败统一走 Server.xml DirSer 兜底，语义零变化，
        #   纯省 ~200ms 往返（也无「写死 IP 过期」风险）
        if is_official_server() and proxy_host is not None and proxy_host.lower() == login_gate_host:
            gate_path = url.split("?", 1)[0]
            if gate_path == "/crossdomain.xml":
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.send_header("Content-Length", str(len(sock_policy)))
                self.send_header("Last-Modified", "Mon, 26 Dec 2022 08:48:51 GMT")
                self.end_headers()
                try:
                    self.wfile.write(sock_policy)
                except OSError:
                    pass  # 客户端中途断开：静默结束
                logger.debug("[gate] crossdomain.xml 本地秒回（官服闸门，复用 sock_policy）")
                return
            if gate_path == "/ip.txt":
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                logger.debug("[gate] ip.txt 本地 404 快速失败（官服闸门）")
                return
        # 其余请求透传上游（保留缓存头，流式转发压缩字节）：
        # · 本方案请求（可见域名）→ 当前服/节点的真实服务器（URL 里只有可见域名，真实节点在这里映射
        #   ⇒ 切换节点不改变 Flash 侧 URL、缓存命中不受影响）
        # · 其他域名（原先直连的）→ 按原目标域名转发（通用代理行为）
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("proxy-connection", "proxy-authorization", "connection", "host")}
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or None
        if proxy_host is not None and not is_own:
            target = f"http://{proxy_host}{url}"
        else:
            target = upstream_base + url
        try:
            resp = session.request(self.command, target, headers=headers, data=body, stream=True, timeout=5)
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
                for chunk in resp.raw.stream(chunk_size, decode_content=False):
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
        """取上游原版 ext.xml，把 swf/append 下当前服生效的 *.swf 追加为 <item> 后返回
        （「【官服】xxx.swf」仅官服注入，注入 path 去前缀 = xxx.swf）。
        返回 True 表示已处理；False 表示放弃（如上游取回失败），交回 dispatch 走透传。"""
        mods = list_append_swfs()
        try:
            resp = session.get(upstream_base + url, timeout=5)
        except Exception:
            return False
        if resp.status_code != 200:
            return False
        text = resp.text
        if mods and "</ext>" in text:
            items = "".join(
                f"\t<item name=\"摩尔拓展.....\" path=\"{inject_name}\" ver=\"081224\"/>\n"
                for _, inject_name in mods
            )
            text = text.replace("</ext>", items + "\t</ext>", 1)
            logger.info(f"[ext.xml] 注入: {"，".join(inject_name for _, inject_name in mods)}")
        elif mods:
            logger.info(f"[ext.xml] 注入失败，ext.xml 中未找到 <ext> 节点")
        self.serve_local(text.encode("utf-8"), "application/xml")
        return True

    def serve_merged_xml(self, url: str, append_path: Path, include_parallel: bool = True) -> None:
        """把 swf/append 下的补充 xml 应用到官服原始资源后返回：
        - 始终以「请求的原始资源」为基底，通过 merge_append 应用 append xml 的新增/删除/修改规则（含 <remove>）；
        - include_parallel=False（MoleShop.xml 外的其他 xml）：只取「当前请求所属服（官服或平行服）」的原始 xml 应用规则，不两服都取；
        - include_parallel=True（仅 MoleShop.xml 等官服/平行服内容不同的资源）：同时取官服+平行服，官服为基底并入平行服新增（平行服删除的不管）；官服取不到以平行服为基底；两服均失败回退本地。"""
        try:
            append_root = ET.parse(append_path).getroot()
        except Exception as e:
            logger.warning(f"[resource] 解析补充 xml 失败（{e}），回退返回本地补充文件")
            self.serve_local(append_path.read_bytes(), "application/xml")
            return
        if include_parallel:
            # MoleShop.xml 等：同时取官服与平行服，以官服为基底并入平行服新增
            bases = (("官服", official_base), ("平行服", parallel_base))
        else:
            # 其他：只在「当前请求所属服」的原始 xml 上应用 append 规则，不两服都取
            bases = (("当前服", upstream_base),)
        roots = {}
        for label, base in bases:
            try:
                resp = session.get(base + url, timeout=5)
                if resp.status_code == 200 and resp.content:
                    roots[label] = ET.fromstring(resp.content.decode("utf-8-sig"))
            except Exception as e:
                logger.warning(f"[resource] 取{label} xml 失败（{e}）: {url}")
        if include_parallel:
            orig = roots.get("官服")
            if orig is None:
                # 官服取不到：以平行服内容为基底（跳过平行服并入）
                orig = roots.get("平行服")
                if orig is None:
                    logger.warning(f"[resource] 官服与平行服均取回失败，回退返回本地补充文件: {url}")
                    self.serve_local(append_path.read_bytes(), "application/xml")
                    return
            elif "平行服" in roots:
                # 官服为基底：并入平行服「新增」节点（仅 MoleShop.xml 等需要）
                merge_parallel_add(orig, roots["平行服"])
        else:
            orig = next(iter(roots.values()), None)
            if orig is None:
                # 当前服原始 xml 取不到：回退返回本地补充文件
                logger.warning(f"[resource] 原始 xml 取回失败，回退返回本地补充文件: {url}")
                self.serve_local(append_path.read_bytes(), "application/xml")
                return
        merge_append(orig, append_root)  # 第 3 层：应用 append xml 的自定义新增/删除规则
        merged = ET.tostring(orig, encoding="utf-8")
        self.serve_local(merged, "application/xml")
        logger.info(f"[resource] 修改: {append_path.name}")

    def relay_cacheable(self, resp, name=None, t0=None) -> None:
        """转发上游响应（全量），用于官服 0 字节兜底等场景。
        剔除 hop-by-hop 头（transfer-encoding/connection/content-encoding/content-length，长度按解压后字节重算）。
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
        if name is not None and t0 is not None:
            dt = (time.perf_counter() - t0) * 1000
            logger.info(f"[resource] 转发 {name} {len(data)//1024}KB {dt:.0f}ms threads={len(sys._current_frames())}")

    def relay_stream(self, resp, name=None, t0=None, cache_path=None) -> int:
        """保留上游原始字节（含 gzip）与缓存头，分块流式转发；支持 304 条件响应。
        与 dispatch 透传分支一致：透传 content-encoding（压缩体）与 content-length（压缩后长度），
        raw.stream(decode_content=False) 保留压缩字节，不再二次解压；上游返回明文时则透传明文。
        cache_path 指定时，边流式边写唯一临时文件，整段流完才原子改名到 cache_path
        （中断/并发不会留下半截或交错缓存；对客户端字节流与加载进度无任何影响）。
        直接对标原生 Flash/WinINet 的流式 + 压缩 + 缓存行为。返回已发送字节数。"""
        self.send_response(resp.status_code)
        has_cache = False
        for k, v in resp.headers.items():
            lk = k.lower()
            if lk in ("transfer-encoding", "connection"):
                continue
            # 保留 content-encoding 与 content-length：若上游压缩则透传压缩体，定长压缩传输
            if lk in ("cache-control", "pragma", "expires"):
                has_cache = True
            self.send_header(k, v)
        if not has_cache:
            self.send_header("Cache-Control", "max-age=2592000")
        self.end_headers()
        sent = 0
        f = None
        tmp_path = None
        completed = False
        try:
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = cache_path.with_name(f"{cache_path.name}.{id(self)}.part")  # 唯一临时名：并发请求不互踩
                try:
                    f = tmp_path.open("wb")
                except OSError as e:
                    logger.warning(f"[resource] 打开本地缓存失败: {e}")
                    f = None
                    tmp_path = None
            if resp.status_code != 304:
                for chunk in resp.raw.stream(chunk_size, decode_content=False):
                    if chunk:
                        self.wfile.write(chunk)
                        if f is not None:
                            f.write(chunk)
                        sent += len(chunk)
                completed = True  # 整段流完才算完整缓存
        except OSError:
            pass
        finally:
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
            if f is not None and tmp_path is not None:
                if completed:
                    try:
                        tmp_path.replace(cache_path)  # 完整才原子改名生效
                    except OSError as e:
                        logger.warning(f"[resource] 缓存改名失败: {e}")
                else:
                    try:
                        tmp_path.unlink()  # 中断/失败：丢弃半截缓存
                    except OSError:
                        pass
            resp.close()
        if name is not None and t0 is not None:
            dt = (time.perf_counter() - t0) * 1000
            logger.info(f"[resource] 转发 {name} {sent//1024}KB {dt:.0f}ms threads={len(sys._current_frames())}")
        return sent

    def serve_resource(self, url: str, name: str, prefer_parallel: bool) -> None:
        """官服/平行服资源统一获取与缓存（serve_fallback 与 serve_parallel_replace 的公共实现）。
        - prefer_parallel=False (fallback)：官服优先；官服为空/失败再回退平行服。采用官服时不缓存（便于官服恢复即时生效）；
          仅当采用平行服时写本地缓存。两服皆空时退回官服响应（哪怕 0 字节），否则 502。
        - prefer_parallel=True (replace)：平行服优先，强制替换官服；采用平行服时写本地缓存并以可缓存方式返回；
          平行服取不到才回退官服透传，否则 502。
        本地缓存命中时直接可缓存返回，跳过网络。"""
        t0 = time.perf_counter()

        def done(tag: str, size: int) -> None:
            dt = (time.perf_counter() - t0) * 1000
            logger.info(f"[resource] {tag} {name} {size // 1024}KB {dt:.0f}ms threads={len(sys._current_frames())}")

        cache_path = fallback_cache_path(url)
        if cache_path.is_file():
            self.serve_local_stream(cache_path, content_type_for(name))
            done("加载", cache_path.stat().st_size)
            return
        # 透传客户端条件请求头：让上游能回 304（刷新时直接走 Flash 缓存，对标浏览器秒开）
        cond_headers = {k: v for k, v in self.headers.items()
                        if k.lower() in ("if-none-match", "if-modified-since")}
        primary, secondary = (parallel_base, upstream_base) if prefer_parallel else (upstream_base, parallel_base)
        last_official = None  # 官服响应（含 0 字节），仅 fallback 双空兜底用
        resp = source = None
        for base in (primary, secondary):
            try:
                r = session.get(base + url, stream=True, timeout=5, headers=cond_headers)
            except Exception:
                r = None
            if r is None:
                continue
            if r.status_code == 304:
                # 官服可用（用缓存）：直接转发明文/压缩条件响应，供 Flash 验证缓存
                self.relay_stream(r, name, t0)
                return
            cl = r.headers.get("content-length")
            if r.status_code == 200 and (cl is None or cl != "0"):
                resp, source = r, base
                break
            if base is upstream_base:
                last_official = r
            else:
                r.close()  # 平行服此路径不可用，释放连接
        else:
            # 官服与平行服都无有效内容
            if not prefer_parallel and last_official is not None:
                self.relay_cacheable(last_official, name, t0)  # 退回官服响应（哪怕 0 字节）
            else:
                self.send_response(502)
                self.end_headers()
                done("上游失败", 0)
            return
        if source is parallel_base:
            if last_official is not None:
                last_official.close()  # 官服空响应已不再使用，释放其连接
            # 采用平行服：分块流式转发（保留 content-encoding 原样），同时落本地缓存
            sent = self.relay_stream(resp, name, t0, cache_path)
            done("缓存", sent)
        else:
            # 采用官服：保留 content-encoding 原样流式转发，不写本地缓存
            self.relay_stream(resp, name, t0)

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


class ExclusiveHTTPServer(ThreadingHTTPServer):
    # 关闭地址复用：HTTPServer 默认 allow_reuse_address=1，而 Windows 下 SO_REUSEADDR
    # 允许不同进程同时 bind 同一端口 → 多实例会串端口。设为 0 后，端口被其他实例占用时
    # bind 真正失败 → 触发 start_bridge 的成对 +2 递增重试，实现多实例隔离。
    allow_reuse_address = 0
    daemon_threads = True  # 连接线程随主线程退出；配合 InjectHandler.timeout 回收空闲 keep-alive 连接

    def handle_error(self, request, client_address):
        # socketserver 在此调用服务器自身的 handle_error（注意：不是 InjectHandler 的方法）。
        # 切节点等场景 Flash/BridgeDLL 会直接 RST/中止 keep-alive 连接，读请求行时抛
        # ConnectionResetError(10054)/ConnectionAbortedError(10053)/BrokenPipeError 等 OSError 子类，
        # 属正常客户端行为，压掉默认打印的整段 traceback 噪声。
        if isinstance(sys.exc_info()[1], OSError):
            return
        super().handle_error(request, client_address)


def start_bridge():
    """启动本地桥服务（守护线程）：注入服务(默认端口 10000) + socket 命令桥(默认端口 10001)，
    并把本进程 WinINet 代理指向注入服务（set_proxy，内存级、只影响本进程）。
    端口对被占用时整对 +2 递增重试（10002/10003、10004/10005…），避免 OS 动态分配(port 0) 的慢速探测，
    保证多客户端实例各用独立端口、互不干扰。"""
    global injecter_port
    inject = 10000
    while True:
        http_srv = None
        srv = None
        try:
            http_srv = ExclusiveHTTPServer(("127.0.0.1", inject), InjectHandler)
            srv = bind_exclusive_socket(inject + 1)
            break
        except OSError:  # 端口对被占用 → 释放已绑定资源，整对 +2 重试
            if http_srv is not None:
                http_srv.server_close()
            if srv is not None:
                srv.close()
            inject += 2
            if inject > 65534:
                raise OSError("无法找到可用的注入/命令桥端口对") from None
    injecter_port = http_srv.server_address[1]
    logger.info(f"[bridge] 注入服务端口: {injecter_port}")
    set_proxy(injecter_port)  # ★ 主通道：本进程 WinINet 代理 → 本地服务（内存级，退出即失效；不改系统设置）
    clear_ext_xml_cache()  # 此时 injecter_port 已知，清对应本地 ext.xml 缓存
    Thread(target=http_srv.serve_forever, daemon=True).start()
    start_socket_bridge(srv)
    return http_srv


def bind_exclusive_socket(port: int):
    """创建命令桥 socket 并独占绑定指定端口（SO_EXCLUSIVEADDRUSE，Windows 防多实例串口）。"""
    srv = socket(AF_INET, SOCK_STREAM)
    excl = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if excl is not None:
        try:
            srv.setsockopt(SOL_SOCKET, excl, 1)
        except OSError:
            pass
    srv.bind(("127.0.0.1", port))
    return srv


# ---------------------------------------------------------------------------
# socket 命令桥：127.0.0.1:10001，SWF 用 flash.net.Socket 连接，替代 HTTP 轮询
# ---------------------------------------------------------------------------
bridge_port: int = 10001  # 本实例 socket 命令桥实际监听端口（与注入端口成对，10001/10003/10005…递增）

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


def start_socket_bridge(srv=None):
    """启动 socket 命令桥（守护线程），返回监听 socket。
    srv 由 start_bridge 成对分配后传入（已独占绑定）；传入 None 时回退固定 10001。"""
    global bridge_port
    if srv is None:
        srv = bind_exclusive_socket(10001)
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
