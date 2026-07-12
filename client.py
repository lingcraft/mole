from collections import deque
from socket import socket, AF_INET, SOCK_STREAM
from struct import pack, pack_into, unpack_from
from threading import Lock, Thread
from multiprocessing import Process, Queue
from queue import Empty
from random import randint
from hashlib import md5
from time import sleep

secret_key = b"^FStx,wl6NquAVRF@f%6\x00"  # 封包算法密钥
user_id, serial_num = 0, 0  # 米米号、发送包序列号
recv_buf = bytearray()  # 接收封包的数据缓冲区
lock = Lock()  # 发送锁


class Client(Process):
    def __init__(self, account: tuple[int, str], init_lines: list[str]):
        super().__init__(daemon=True)
        self.login_socket = socket(AF_INET, SOCK_STREAM)
        self.main_socket = socket(AF_INET, SOCK_STREAM)
        self.is_connect = False
        self.send_queue = Queue()
        self.recv_queue = Queue()
        self.user_id, self.password = account
        self.init_lines = init_lines

    def put_data(self, lines: list):
        self.send_queue.put(("send", lines))

    def run(self):
        global user_id
        user_id = self.user_id
        while True:
            try:
                cmd, lines = self.send_queue.get(timeout=60)
            except Empty:
                break
            if cmd == "stop":
                break
            elif cmd == "send":
                self.send_lines(deque(lines))

    def login(self):
        try:
            # 获取账户认证信息
            self.login_socket.settimeout(10)
            self.login_socket.connect(("123.206.131.236", 1863))
            self.login_socket.send(Packet.parse_data(
                f"0000009301000000670000000000000000{self.password}0000000000000001{"00" * 90}"
            ))
            self.login_socket.settimeout(1.2)
            res = read_packet(self.login_socket)
            if len(res.body) < 20:
                return False
            session = res.body[4:20]

            # 连接主服务器
            server_id = randint(1, 100)
            if server_id == 1:
                port = 1965
            elif 2 <= server_id <= 30:
                port = 1865
            else:
                port = 1201
            self.main_socket.settimeout(10)
            self.main_socket.connect(("123.206.131.236", port))

            # 登录
            token = get_login_token(session)
            self.main_socket.send(Packet(
                f"0000000000000000C90000000000000000{get_hex(server_id, 2)}{token.hex()}00000010{session.hex()}0000000030{"00" * 63}"
            ).encrypt().data())
            res = read_packet(self.main_socket)
            if res.version != 0:
                return False
            self.is_connect = True
            self.main_socket.settimeout(None)
            Thread(target=self.recv_loop, daemon=True).start()
        except:
            return False
        else:
            return True

    def send_line(self, data: str):
        if len(data) < 17:
            return True
        try:
            packet = Packet(data)
            with lock:
                packet.encrypt()
            self.main_socket.send(packet.data())
        except:
            self.is_connect = False
            return False
        else:
            return True

    def send_lines(self, lines: deque[str]):
        while lines:
            if not self.is_connect:
                if not self.login():
                    sleep(1)
                    continue
                for line in self.init_lines:  # 登录成功后发送初始化包
                    if not self.send_line(line):
                        break
                if not self.is_connect:  # 初始化包发送失败，重新登录后重发
                    continue
            data = lines.popleft()
            if not self.send_line(data):
                lines.appendleft(data)  # 发送失败，放回队首待重连后重发
                sleep(1)

    def recv_loop(self):
        global recv_buf
        while self.is_connect:
            try:
                data = self.main_socket.recv(4096)
                if not data:
                    self.is_connect = False
                    break
                recv_buf.extend(data)
                while len(recv_buf) >= 4:
                    packet_len = get_int(recv_buf)
                    if len(recv_buf) >= packet_len:
                        # 不是断包
                        cipher = recv_buf[:packet_len]
                        packet = Packet(cipher)
                        packet.decrypt()
                        if packet.version == 0:  # 正确包
                            match packet.cmd_id:
                                case 1017:  # 餐厅做菜信息
                                    dish_type = get_int(packet.body)
                                    dish_id = get_int(packet.body, 4)
                                    dish_pos = get_int(packet.body, 8)
                                    dish_step = get_int(packet.body, 12)
                                    if dish_step < 3:  # 做菜后续步骤
                                        self.put_data([
                                            f"0000000000000003FC0000000000000000{get_hex(dish_type)}{get_hex(dish_id)}"
                                        ])
                                    elif dish_step == 3:
                                        self.recv_queue.put((dish_id, dish_pos))  # 传回主进程刷新菜ID
                        recv_buf = recv_buf[packet_len:]
                    else:
                        break
            except:
                self.is_connect = False
                break

    def close(self):
        try:
            while True:
                self.send_queue.get_nowait()
        except:
            pass
        try:
            self.send_queue.put(("stop", None))
        except:
            pass
        if self.is_alive():
            self.terminate()


class Packet:
    def __init__(self, packet):
        if isinstance(packet, str):
            packet = bytearray.fromhex(packet)
        packet_len = len(packet)
        self.length, self.serial_num, self.cmd_id, self.user_id, self.version = unpack_from("!IBIII", packet) if packet_len >= 17 else (0, 0, 0, 0, 0)
        self.body = packet[17:] if packet_len > 17 else bytearray()

    def data(self):
        head = pack("!IBIII", self.length, self.serial_num, self.cmd_id, self.user_id, self.version)
        return head + self.body

    @staticmethod
    def parse_data(data: str):
        packet = bytearray.fromhex(data)
        if packet.startswith(b"\x00\x00"):
            set_int(packet, user_id, 9)
        return packet

    def get_serial_num(self):
        global serial_num
        self.length = len(self.body) + 18
        self.user_id = user_id
        self.version = 0
        if self.cmd_id == 201:
            serial_num = 65
        else:
            crc = 0
            for byte in self.body:
                crc ^= byte
            # 计算发送包序列号
            serial_num = (serial_num - serial_num // 7 + 147 + (self.length - 1) % 21 + self.cmd_id % 13 + crc) % 256
        self.serial_num = serial_num

    def encrypt(self, is_get_serial_num=True):
        if is_get_serial_num:
            self.get_serial_num()
        res = bytearray(len(self.body) + 1)
        key_index = 0
        for index in range(len(self.body)):
            res[index] = self.body[index] ^ secret_key[key_index % 21]
            key_index += 1
            if key_index == 22:
                key_index = 0
        for index in range(len(res) - 1, 0, -1):
            res[index] |= res[index - 1] >> 3
            res[index - 1] = (res[index - 1] << 5) % 256
        res[0] |= 3
        self.body = res
        return self

    def decrypt(self):
        res = bytearray(len(self.body) - 1)
        key_index = 0
        for index in range(len(res)):
            res[index] = (self.body[index] >> 5) | (self.body[index + 1] << 3) % 256
            res[index] ^= secret_key[key_index % 21]
            key_index += 1
            if key_index == 22:
                key_index = 0
        self.body = res
        return self


def get_int(buf: bytes, offset: int = 0, bytes_num: int = 4):
    match bytes_num:
        case 4:
            return unpack_from("!I", buf, offset)[0]
        case 2:
            return unpack_from("!H", buf, offset)[0]
        case 1:
            return unpack_from("!B", buf, offset)[0]
        case 8:
            return unpack_from("!Q", buf, offset)[0]
        case _:
            return unpack_from("!I", buf, offset)[0]


def set_int(buf: bytes, value: int, offset: int = 0, bytes_num: int = 4):
    match bytes_num:
        case 4:
            pack_into("!I", buf, offset, value)
        case 2:
            pack_into("!H", buf, offset, value)
        case 1:
            pack_into("!B", buf, offset, value)
        case 8:
            pack_into("!Q", buf, offset, value)
        case _:
            pack_into("!I", buf, offset, value)


def get_hex(value: int, bytes_num: int = 4):
    return f"{value:0{2 * bytes_num}X}"


def get_md5(text: str):
    return md5(text.encode()).hexdigest()


def get_login_token(session: bytes):
    return get_md5(f"{get_int(session, 10)}hAo crAzy B{get_int(session, 3)}")[6:22].encode()


def read_packet(s: socket):
    packet = Packet(s.recv(17))
    body_len = packet.length - 17
    while len(packet.body) < body_len:
        chunk = s.recv(body_len - len(packet.body))
        if not chunk:
            break
        packet.body.extend(chunk)
    return packet
