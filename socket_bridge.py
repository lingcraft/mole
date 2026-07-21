"""
socket_bridge.py — 命令桥的 socket 版（替代 ClientCommonDLL.swf 里的 HTTP 轮询）

协议：
  1) SWF 用 flash.net.Socket 连 127.0.0.1:20001。
  2) Flash 连接后自动发 <policy-file-request/>\\0，本服务在同一端口回策略文件(\\0 结尾)。
     策略允许任意域连任意端口，故 mole.61.com(或 127.0.0.1:10000) 加载的 SWF 都能连。
  3) 策略通过后 Event.CONNECT 触发，SWF 发 "READY\\n"。
  4) 本服务把 bridge.CMD_QUEUE 里的命令逐条以 "cmd|arg1|arg2\\n" 推下去；
     SWF 按行读取并分发（alertMsg / enterMap / alertReward …）。
  5) SWF 上行数据(READY / PING / ECHO 等)打印为 [swf] ... 便于调试。

运行：
  终端1: uv run python socket_bridge.py        # 起 socket 桥（默认也起原 HTTP 桥保持兼容）
  终端2: uv run python mole.py                  # 正常启动游戏，注入 ClientCommonDLL.swf
  然后调用 bridge.push_cmd("alertMsg|你好") 即可经 socket 下发。
"""
import socket as _sock
import threading

import bridge

HOST = "127.0.0.1"
PORT = 20001

# Flash socket 策略文件：允许任意域连接任意端口
POLICY = (
    b'<?xml version="1.0"?>\r\n'
    b'<!DOCTYPE cross-domain-policy SYSTEM '
    b'"http://www.adobe.com/xml/dtds/cross-domain-policy.dtd">\r\n'
    b'<cross-domain-policy>\r\n'
    b'<allow-access-from domain="*" to-ports="*"/>\r\n'
    b'</cross-domain-policy>\r\n'
)


def _serve(conn, addr):
    # Flash 连接后首先发 <policy-file-request/>\0 请求策略文件
    conn.settimeout(5.0)
    try:
        data = conn.recv(4096)
    except Exception:
        conn.close()
        return
    if b"<policy-file-request" in data:
        try:
            conn.sendall(POLICY + b"\x00")
        except Exception:
            conn.close()
            return
        # 同一连接即成为数据通道，Event.CONNECT 随后触发

    # 数据通道主循环
    conn.settimeout(0.25)
    while True:
        # 下行：队列中有命令则推送
        if bridge.CMD_QUEUE:
            cmd = bridge.CMD_QUEUE.pop(0)
            try:
                conn.sendall((cmd + "\n").encode("utf-8"))
                print("[push]", cmd, flush=True)
            except Exception:
                break
        # 上行：读取 SWF 回传（READY / PING / ECHO 等，便于调试）
        try:
            data = conn.recv(4096)
        except _sock.timeout:
            continue
        except Exception:
            break
        if not data:
            break
        text = data.decode("utf-8", "ignore").rstrip("\r\n")
        if text:
            print("[swf]", text, flush=True)
    conn.close()
    print("[disconnect]", addr, flush=True)


def start_socket_bridge():
    """启动 socket 命令桥（守护线程），返回监听 socket。"""
    srv = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    srv.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(8)
    print(f"[socket-bridge] listening {HOST}:{PORT}", flush=True)

    def _loop():
        while True:
            try:
                conn, addr = srv.accept()
            except Exception:
                continue
            print("[connect]", addr, flush=True)
            threading.Thread(target=_serve, args=(conn, addr), daemon=True).start()

    threading.Thread(target=_loop, daemon=True).start()
    return srv


if __name__ == "__main__":
    # 同时起原 HTTP 桥，保持 crossdomain.xml / push_cmd 等入口兼容
    bridge.start_bridge()
    start_socket_bridge()
    print("[socket-bridge] 运行中，Ctrl+C 退出", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
