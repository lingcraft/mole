#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import hashlib
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from multiprocessing import Process
from pathlib import Path
from struct import pack, unpack

SECRET_KEY = b"^FStx,wl6NquAVRF@f%6\x00"
BEIJING_TZ = timezone(timedelta(hours=8))
MLCS_WINDOW_START_MINUTES = 13 * 60
MLCS_WINDOW_END_MINUTES = 19 * 60

serial_num = 0
user_id = 0
session_bytes = bytes()


def md5_hash(text):
    return hashlib.md5(text.encode()).hexdigest()


def build_login_token(session, server_id):
    start1 = int.from_bytes(session[3:7], "big")
    start2 = int.from_bytes(session[10:14], "big")
    fixed_str = "fREd hAo crAzy BAby in Our ProgRAm?"
    src = str(start2) + fixed_str[5:16] + str(start1)
    token_str = md5_hash(src)[5:22]
    return token_str.encode("ascii")


def get_int(data):
    if isinstance(data, bytes) and len(data) >= 4:
        return int.from_bytes(data[:4], "big")
    return 0


def get_hex(num):
    return f"{num:08X}"


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


def _normalize_hex8(value, default="00000000"):
    s = str(value or "").strip().upper()
    s = "".join(ch for ch in s if ch in "0123456789ABCDEF")
    if not s:
        return default
    return s[-8:].rjust(8, "0")


def _normalize_user_id_hex(value, default="00000000"):
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return f"{int(value) & 0xFFFFFFFF:08X}"

    text = str(value).strip()
    if not text:
        return default
    if text.isdigit():
        return f"{int(text) & 0xFFFFFFFF:08X}"

    clean_hex = text.upper().replace("0X", "")
    clean_hex = "".join(ch for ch in clean_hex if ch in "0123456789ABCDEF")
    if not clean_hex:
        return default
    try:
        return f"{int(clean_hex, 16) & 0xFFFFFFFF:08X}"
    except Exception:
        return default


LAMU_LEVEL_GROUP = {
    "1-2": {"max": 1, "last": 1},
    "3-4": {"max": 2, "last": 1},
    "5-6": {"max": 3, "last": 2},
    "7-8": {"max": 4, "last": 3},
    "9-10": {"max": 5, "last": 4},
    "11": {"max": 6, "last": 5},
}


def _normalize_lamu_attr(value, default="木"):
    text = str(value or "").strip()
    return text if text in ("火", "水", "木") else default


def _get_lamu_skill_id(skill_level, attr):
    offsets = {"火": -2, "水": -1, "木": 0}
    return 3 * int(skill_level) + offsets.get(attr, 0)


class Packet:
    def __init__(self, data=None):
        if data is None:
            self.length = 0
            self.serial_num = 0
            self.cmd_id = 0
            self.user_id = 0
            self.version = 0
            self.body = bytes()
        else:
            if isinstance(data, str):
                data = bytes.fromhex(data)
            if len(data) >= 17:
                self.length, self.serial_num, self.cmd_id, self.user_id, self.version = unpack("!IBIII", data[:17])
                self.body = data[17:]
            else:
                self.length, self.serial_num, self.cmd_id, self.user_id, self.version = 0, 0, 0, 0, 0
                self.body = bytes()

    def data(self):
        head = pack("!IBIII", self.length, self.serial_num, self.cmd_id, self.user_id, self.version)
        return head + self.body

    def get_serial_num(self):
        global serial_num, user_id
        self.length = len(self.body) + 18
        self.user_id = user_id
        self.version = 0
        if self.cmd_id == 201:
            serial_num = 65
        else:
            crc = 0
            for value in self.body:
                crc ^= value
            serial_num = (
                serial_num
                - int(serial_num / 7)
                + 147
                + (self.length - 1) % 21
                + self.cmd_id % 13
                + crc
            ) % 256
        self.serial_num = serial_num

    def encrypt(self):
        self.get_serial_num()
        res = bytearray(len(self.body) + 1)
        key_index = 0
        for idx in range(len(self.body)):
            res[idx] = self.body[idx] ^ SECRET_KEY[key_index % 21]
            key_index += 1
            if key_index == 22:
                key_index = 0
        for idx in range(len(res) - 1, 0, -1):
            res[idx] |= res[idx - 1] >> 3
            res[idx - 1] = (res[idx - 1] << 5) % 256
        res[0] |= 3
        self.body = res
        return self

    def decrypt(self):
        if len(self.body) == 0:
            return
        res = bytearray(len(self.body) - 1)
        key_index = 0
        for idx in range(len(res)):
            res[idx] = (self.body[idx] >> 5) | (self.body[idx + 1] << 3) % 256
            res[idx] ^= SECRET_KEY[key_index % 21]
            key_index += 1
            if key_index == 22:
                key_index = 0
        self.body = res


class Client:
    def __init__(self):
        self.login_socket = None
        self.main_socket = None
        self.connected = False
        self.recv_buffer = bytearray()
        self.heartbeat_thread = None
        self.heartbeat_running = False
        self.send_lock = threading.Lock()
        self.ranch_fish_ids = []
        self.ranch_fish_lock = threading.Lock()
        self.ranch_fish_event = threading.Event()
        self.map_info_event = threading.Event()
        self.last_ranch_fish_diag = None
        self.ysqs_energy = 0
        self.ysqs_attack = 0
        self.ysqs_max_floor = 0
        self.ysqs_info_lock = threading.Lock()
        self.ysqs_info_event = threading.Event()
        self.recv_cmd_history = []
        self.recv_cmd_history_lock = threading.Lock()

    def connect_login_server(self):
        try:
            self.login_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.login_socket.settimeout(10)
            self.login_socket.connect(("123.206.131.236", 1863))
            print("[+] 登录服连接成功")
            return True
        except Exception as exc:
            print(f"[-] 登录服连接失败: {exc}")
            return False

    def login_server_auth(self, username, password, server_id):
        global user_id, session_bytes
        try:
            pwd_hash = md5_hash(md5_hash(password))

            first_packet = bytearray([0x00, 0x00, 0x00, 0x93, 0x01, 0x00, 0x00, 0x00, 0x67])
            first_packet.extend(int(username).to_bytes(4, "big"))
            first_packet.extend(bytes([0x00, 0x00, 0x00, 0x00]))
            first_packet.extend(pwd_hash.encode("ascii"))
            first_packet.extend(pack("!III", 0, 1, 0))
            first_packet.extend(bytes(22))
            first_packet.extend(bytes(64))
            self.login_socket.send(bytes(first_packet))

            self.login_socket.settimeout(1.2)
            resp_data = bytearray()
            try:
                while True:
                    chunk = self.login_socket.recv(4096)
                    if not chunk:
                        break
                    resp_data.extend(chunk)
            except socket.timeout:
                pass

            if len(resp_data) < 37:
                print("[-] 登录服响应异常")
                return False

            session_16 = resp_data[21:37]

            verify_packet = bytearray()
            verify_packet.extend(pack("!I", 37))
            verify_packet.append(1)
            verify_packet.extend(pack("!I", 105))
            verify_packet.extend(int(username).to_bytes(4, "big"))
            verify_packet.extend(pack("!I", 0))
            verify_packet.extend(session_16)
            verify_packet.extend(bytes(4))
            self.login_socket.send(bytes(verify_packet))

            server_select_packet = bytearray()
            server_select_packet.extend(pack("!I", 205))
            server_select_packet.append(1)
            server_select_packet.extend(pack("!I", 106))
            server_select_packet.extend(int(username).to_bytes(4, "big"))
            server_select_packet.extend(pack("!I", 0))
            server_select_packet.extend(pack("!I", server_id))
            server_select_packet.extend(pack("!I", server_id))
            server_select_packet.extend(pack("!I", 44))
            server_select_packet.extend(bytes(205 - len(server_select_packet)))
            self.login_socket.send(bytes(server_select_packet))

            self.login_socket.settimeout(5.0)
            final_resp = bytearray()
            try:
                while True:
                    chunk = self.login_socket.recv(4096)
                    if not chunk:
                        break
                    final_resp.extend(chunk)
            except socket.timeout:
                pass

            if len(final_resp) == 0:
                print("[-] 登录验证失败")
                return False

            session_bytes = session_16 + bytes(96)
            user_id = int(username)
            print(f"[+] 登录验证成功 (服务器{server_id})")
            return True

        except Exception as exc:
            print(f"[-] 登录验证异常: {exc}")
            return False

    def connect_main_server(self, server_id):
        if server_id == 1:
            port = 1965
        elif 2 <= server_id <= 30:
            port = 1865
        elif 31 <= server_id <= 100:
            port = 1201
        else:
            print(f"[-] 服务器范围错误: {server_id}")
            return False

        try:
            self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.main_socket.settimeout(10)
            self.main_socket.connect(("123.206.131.236", port))
            print("[+] 主服连接成功")
            return True
        except Exception as exc:
            print(f"[-] 主服连接失败: {exc}")
            return False

    def main_server_login(self, server_id):
        global user_id, session_bytes
        try:
            token = build_login_token(session_bytes, server_id)
            token_modified = bytearray(token)
            token_modified[0] = server_id

            body = bytearray()
            body.append(0x00)
            body.extend(token_modified)
            body.extend(pack("!I", 16))
            body.extend(session_bytes[:16])
            body.extend(pack("!I", 0))
            body.append(0x30)
            body.extend(bytes(63))

            packet = Packet()
            packet.cmd_id = 201
            packet.user_id = user_id
            packet.body = bytes(body)
            packet.encrypt()
            self.main_socket.send(packet.data())

            header = self.main_socket.recv(17)
            if len(header) < 17:
                print(f"[-] 主服包头异常: {len(header)}")
                return False

            packet_len = int.from_bytes(header[:4], "big")
            body_len = packet_len - 17
            recv_body = b""
            while len(recv_body) < body_len:
                chunk = self.main_socket.recv(body_len - len(recv_body))
                if not chunk:
                    break
                recv_body += chunk

            response = header + recv_body
            if len(response) < packet_len:
                print("[-] 主服返回不完整")
                return False

            resp_packet = Packet(response)
            resp_packet.decrypt()
            if resp_packet.version != 0:
                print(f"[-] 主服登录失败: {resp_packet.version}")
                return False

            self.connected = True
            self.main_socket.settimeout(None)
            threading.Thread(target=self.recv_loop, daemon=True).start()
            self.start_heartbeat()
            print("[+] 主服登录成功")
            return True

        except Exception as exc:
            print(f"[-] 主服登录异常: {exc}")
            return False

    def recv_loop(self):
        while self.connected:
            try:
                data = self.main_socket.recv(4096)
                if not data:
                    self.connected = False
                    break
                self.recv_buffer.extend(data)
                while len(self.recv_buffer) >= 4:
                    packet_len = int.from_bytes(self.recv_buffer[:4], "big")
                    if packet_len <= len(self.recv_buffer):
                        packet_data = self.recv_buffer[:packet_len]
                        self.recv_buffer = self.recv_buffer[packet_len:]
                        packet = Packet(packet_data)
                        packet.decrypt()
                        now_ts = time.time()
                        with self.recv_cmd_history_lock:
                            self.recv_cmd_history.append((now_ts, packet.cmd_id, packet.version, packet.body))
                            # 仅保留最近120秒，避免历史无限增长
                            self.recv_cmd_history = [item for item in self.recv_cmd_history if now_ts - item[0] <= 120]
                        if packet.cmd_id == 401:
                            self.map_info_event.set()
                        if packet.cmd_id == 1366:
                            fish_ids, diag = self._parse_ranch_fish_ids(packet.body, return_diag=True)
                            with self.ranch_fish_lock:
                                self.ranch_fish_ids = fish_ids
                            self.last_ranch_fish_diag = diag
                            self.ranch_fish_event.set()
                        if packet.cmd_id == 3001 and len(packet.body) >= 72:
                            with self.ysqs_info_lock:
                                self.ysqs_energy = get_int(packet.body[28:32])
                                self.ysqs_attack = get_int(packet.body[44:48])
                                self.ysqs_max_floor = get_int(packet.body[68:72])
                            self.ysqs_info_event.set()
                    else:
                        break
            except Exception:
                self.connected = False
                break

    @staticmethod
    def _parse_ranch_fish_ids(body, return_diag=False):
        fish_ids = []
        body_hex = body.hex().upper()
        fish_count = 0
        if len(body_hex) >= 16:
            fish_count = int(body_hex[14:16], 16)
            offset = 16
            for _ in range(fish_count):
                if offset + 8 <= len(body_hex):
                    fish_ids.append(int(body_hex[offset:offset + 8], 16))
                offset += 160
        diag = {
            "body_len": len(body),
            "fish_count": fish_count,
            "parsed_count": len(fish_ids),
            "head_hex": body_hex[:64],
        }
        if return_diag:
            return fish_ids, diag
        return fish_ids

    def get_cmd_ids_in_window(self, start_ts, end_ts):
        with self.recv_cmd_history_lock:
            return [cmd_id for ts, cmd_id, _version, _body in self.recv_cmd_history if start_ts <= ts <= end_ts]

    def get_cmd_packets_in_window(self, start_ts, end_ts, cmd_id=None):
        with self.recv_cmd_history_lock:
            rows = [item for item in self.recv_cmd_history if start_ts <= item[0] <= end_ts]
        if cmd_id is None:
            return rows
        return [item for item in rows if item[1] == cmd_id]

    def start_heartbeat(self):
        self.heartbeat_running = True
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

    def _heartbeat_loop(self):
        while self.heartbeat_running and self.connected:
            try:
                time.sleep(30)
                if not self.connected:
                    break
                packet = Packet()
                packet.cmd_id = 40
                packet.user_id = user_id
                packet.body = bytes([0x00])
                with self.send_lock:
                    packet.encrypt()
                    self.main_socket.send(packet.data())
            except Exception:
                break

    def stop_heartbeat(self):
        self.heartbeat_running = False
        if self.heartbeat_thread:
            self.heartbeat_thread.join(timeout=1)

    def send_packet(self, packet):
        if not self.connected or not self.main_socket:
            return False
        try:
            with self.send_lock:
                packet.encrypt()
                self.main_socket.send(packet.data())
            return True
        except Exception:
            self.connected = False
            return False

    def close(self):
        self.connected = False
        self.stop_heartbeat()
        if self.login_socket:
            try:
                self.login_socket.close()
            except Exception:
                pass
        if self.main_socket:
            try:
                self.main_socket.close()
            except Exception:
                pass


def load_daily_packets():
    import os

    packets_data = None
    for env_key in ("PACKETS_DATA", "MOLE_PACKETS_DATA"):
        packets_data = os.environ.get(env_key)
        if packets_data:
            break

    if not packets_data:
        for file_name in ("封包.txt", "packet.txt"):
            path = Path(__file__).parent / file_name
            if path.exists():
                packets_data = path.read_text(encoding="utf-8")
                break

    if not packets_data:
        return {}

    lines = packets_data.split("\n")
    items = {}
    current_name = None
    current_count = 1
    current_packets = []

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("#") or not line:
            if current_name and current_packets:
                items[current_name] = {
                    "count": current_count,
                    "packets": current_packets.copy(),
                }
            current_name = None
            current_count = 1
            current_packets = []
            continue

        if "（" in line and "）" in line:
            if current_name and current_packets:
                items[current_name] = {
                    "count": current_count,
                    "packets": current_packets.copy(),
                }
                current_packets = []
            try:
                name_part = line.split("（")[0].strip()
                count_part = line.split("（")[1].split("）")[0]
                current_name = name_part
                if current_name in items:
                    index = 2
                    while f"{current_name}_{index}" in items:
                        index += 1
                    current_name = f"{current_name}_{index}"
                current_count = _to_int(count_part, 1)
            except Exception:
                current_name = None
                current_count = 1
            continue

        if current_name and len(line) >= 17:
            clean_line = line.replace("{", "0").replace("}", "0")
            if all(ch in "0123456789ABCDEFabcdef" for ch in clean_line):
                current_packets.append(line)

    if current_name and current_packets:
        items[current_name] = {
            "count": current_count,
            "packets": current_packets.copy(),
        }

    return items


def _normalize_daily_feature_cfg(feature_cfg):
    feature_cfg = feature_cfg if isinstance(feature_cfg, dict) else {}
    return {
        "enabled": _to_bool(feature_cfg.get("enabled", True), True),
        "interval_ms": 50,
    }


def _normalize_online_feature_cfg(feature_cfg, account):
    feature_cfg = feature_cfg if isinstance(feature_cfg, dict) else {}
    base_minutes = account.get("online_minutes", 0)
    return {
        "enabled": _to_bool(feature_cfg.get("enabled", True), True),
        "minutes": max(0, _to_int(feature_cfg.get("minutes", base_minutes), base_minutes)),
    }


def _normalize_online_gift_feature_cfg(feature_cfg):
    feature_cfg = feature_cfg if isinstance(feature_cfg, dict) else {}
    return {
        "enabled": _to_bool(feature_cfg.get("enabled", True), True),
        "min_minutes": max(0, _to_int(feature_cfg.get("min_minutes", 100), 100)),
    }


def _normalize_lamu_daily_feature_cfg(feature_cfg):
    feature_cfg = feature_cfg if isinstance(feature_cfg, dict) else {}
    lamus = feature_cfg.get("lamus", [])
    if not isinstance(lamus, list):
        lamus = []

    normalized_lamus = []
    for item in lamus:
        if not isinstance(item, dict):
            continue
        level_group = str(item.get("level_group", "11")).strip()
        if level_group not in LAMU_LEVEL_GROUP:
            level_group = "11"
        normalized_lamus.append(
            {
                "lamu_id": _normalize_hex8(item.get("lamu_id", "00000000"), "00000000"),
                "level_group": level_group,
                "prev_attr": _normalize_lamu_attr(item.get("prev_attr", "木"), "木"),
                "prev_item": _normalize_hex8(item.get("prev_item", "0002E8C0"), "0002E8C0"),
                "prev_count": max(0, _to_int(item.get("prev_count", 1), 1)),
                "curr_attr": _normalize_lamu_attr(item.get("curr_attr", "水"), "水"),
                "curr_item": _normalize_hex8(item.get("curr_item", "0012C4C6"), "0012C4C6"),
                "curr_count": max(0, _to_int(item.get("curr_count", 10), 10)),
                "feed_after": _to_bool(item.get("feed_after", True), True),
            }
        )

    return {
        "enabled": _to_bool(feature_cfg.get("enabled", False), False),
        "interval_ms": 50,
        "lamus": normalized_lamus,
    }


def _normalize_ranch_fish_feature_cfg(feature_cfg):
    feature_cfg = feature_cfg if isinstance(feature_cfg, dict) else {}
    bait_count = _to_int(feature_cfg.get("bait_count", feature_cfg.get("target_capacity", 30)), 30)
    bait_type = str(feature_cfg.get("bait_type", "krill")).strip().lower() or "krill"
    if bait_type not in ("krill", "crayfish"):
        bait_type = "krill"
    return {
        "enabled": _to_bool(feature_cfg.get("enabled", False), False),
        "jump_first": True,
        "bait_count": max(1, bait_count),
        "bait_type": bait_type,
        "interval_ms": 50,
    }


def _normalize_ranch_feature_cfg(feature_cfg):
    feature_cfg = feature_cfg if isinstance(feature_cfg, dict) else {}
    return {
        "enabled": _to_bool(feature_cfg.get("enabled", False), False),
        "jump_before_all": True,
        "interval_ms": 50,
    }


def _normalize_ranch_egg_feature_cfg(feature_cfg):
    feature_cfg = feature_cfg if isinstance(feature_cfg, dict) else {}
    mode = str(feature_cfg.get("mode", "turkey3")).strip().lower()
    if mode not in ("turkey3", "turkey2_phoenix1"):
        mode = "turkey3"
    return {
        "enabled": _to_bool(feature_cfg.get("enabled", False), False),
        "mode": mode,
        "hatch_after_place": True,
        "interval_ms": 50,
    }


def _normalize_mlcs_feature_cfg(feature_cfg):
    feature_cfg = feature_cfg if isinstance(feature_cfg, dict) else {}
    level = str(feature_cfg.get("level", "")).strip()
    # 允许的关卡：激战蛋蛋、沉睡奥丁、莎士摩亚
    if level not in ("激战蛋蛋", "沉睡奥丁", "莎士摩亚"):
        level = ""
    return {
        "enabled": _to_bool(feature_cfg.get("enabled", False), False),
        "level": level,
    }


def _normalize_wish_feature_cfg(feature_cfg):
    feature_cfg = feature_cfg if isinstance(feature_cfg, dict) else {}
    item = str(feature_cfg.get("item", "")).strip()
    allowed_items = (
        "组合蘑菇壁灯",
        "古典落地灯",
        "雪花",
        "绿色蘑菇壁灯",
        "绿茵壁纸",
        "小杠铃",
        "拉姆跳跳杆",
        "红色小鼓",
    )
    if item not in allowed_items:
        item = ""
    return {
        "target_user_id": _normalize_user_id_hex(feature_cfg.get("target_user_id", ""), "00000000"),
        "item": item,
    }


def _normalize_super_lamu_level(value):
    level = _to_int(value, 0)
    if 1 <= level <= 8:
        return level
    return 0


def _build_super_lamu_packets(level):
    level = _normalize_super_lamu_level(level)
    if level == 0:
        return []
    hex_level = f"{level + 22:08X}"
    return [
        "00000000000000277500000000000000003B9ACA16",
        f"0000000000000027760000000000000000{hex_level}",
    ]


def normalize_account_config(account):
    features = account.get("features", {}) if isinstance(account, dict) else {}
    normalized = {
        "username": str(account.get("username", "")).strip(),
        "password": str(account.get("password", "")),
        "server": _to_int(account.get("server", 100), 100),
        "enabled": _to_bool(account.get("enabled", True), True),
        "features": {
            "daily": _normalize_daily_feature_cfg(features.get("daily", {})),
            "online": _normalize_online_feature_cfg(features.get("online", {}), account),
            "online_gift": _normalize_online_gift_feature_cfg(features.get("online_gift", {})),
            "lamu_daily": _normalize_lamu_daily_feature_cfg(features.get("lamu_daily", {})),
            "ranch": _normalize_ranch_feature_cfg(features.get("ranch", {})),
            "ranch_fish": _normalize_ranch_fish_feature_cfg(features.get("ranch_fish", {})),
            "ranch_egg": _normalize_ranch_egg_feature_cfg(features.get("ranch_egg", {})),
            "mlcs": _normalize_mlcs_feature_cfg(features.get("mlcs", {})),
            "wish": _normalize_wish_feature_cfg(features.get("wish", {})),
        },
        "super_lamu_level": _normalize_super_lamu_level(account.get("super_lamu_level", 0)),
        "super_lamu_packets": account.get("super_lamu_packets", []),
    }

    if "online_minutes" in account:
        normalized["features"]["online"]["minutes"] = max(0, _to_int(account.get("online_minutes"), 0))

    return normalized


def select_daily_items_for_account(daily_items, daily_cfg):
    selected = {}
    for item_name, item_data in daily_items.items():
        base_count = _to_int(item_data.get("count", 1), 1)
        selected[item_name] = {
            "count": base_count,
            "packets": item_data.get("packets", []),
        }
    return selected


def _expand_custom_packets(custom_packets):
    def parse_named_packet_text(text):
        lines = str(text or "").splitlines()
        current_count = 1
        current_packets = []
        output = []

        def flush_group():
            nonlocal current_count, current_packets, output
            if not current_packets:
                return
            if len(current_packets) == 1 and current_count > 1:
                output.append(f"{current_packets[0]}*{current_count}")
            elif len(current_packets) > 1 and current_count > 1:
                output.append([*current_packets, f"*{current_count}"])
            else:
                output.extend(current_packets)
            current_count = 1
            current_packets = []

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                flush_group()
                continue

            if "（" in line and "）" in line:
                flush_group()
                try:
                    count_part = line.split("（", 1)[1].split("）", 1)[0]
                    current_count = max(1, _to_int(count_part, 1))
                except Exception:
                    current_count = 1
                continue

            clean = line.replace("{", "0").replace("}", "0")
            if len(clean) >= 17 and all(ch in "0123456789ABCDEFabcdef" for ch in clean):
                current_packets.append(line)

        flush_group()
        return output

    result = []
    if isinstance(custom_packets, str):
        parsed = parse_named_packet_text(custom_packets)
        if parsed:
            custom_packets = parsed
        else:
            custom_packets = [custom_packets] if custom_packets.strip() else []

    if not isinstance(custom_packets, list):
        return result

    for packet in custom_packets:
        if isinstance(packet, list):
            group = []
            repeat = 1
            for part in packet:
                if isinstance(part, str) and part.startswith("*") and part[1:].isdigit():
                    repeat = int(part[1:])
                elif isinstance(part, str):
                    group.append(part)
            for _ in range(max(0, repeat)):
                result.extend(group)
        elif isinstance(packet, str):
            repeat = 1
            raw_packet = packet
            if "*" in raw_packet:
                head, tail = raw_packet.rsplit("*", 1)
                if tail.isdigit():
                    raw_packet = head
                    repeat = int(tail)
            for _ in range(max(0, repeat)):
                result.append(raw_packet)

    return result


def build_packet_queue(daily_items, daily_cfg, custom_packets):
    queue = []
    for item_data in daily_items.values():
        count = max(0, _to_int(item_data.get("count", 1), 1))
        packets = item_data.get("packets", [])
        for _ in range(count):
            queue.extend(packets)
    queue.extend(_expand_custom_packets(custom_packets))
    return queue


def _send_packet_queue_common(
    client,
    packet_queue,
    interval_ms,
    server_id,
    username,
    password,
    lamu_id_hex="00000000",
    jump_to_ranch_on_reconnect=False,
    fail_log_label=None,
):
    success_count = 0
    fail_count = 0

    for index, packet_hex in enumerate(packet_queue, start=1):
        retry_count = 0
        sent = False
        while retry_count < 3 and not sent:
            attempt_no = retry_count + 1
            if not client.connected:
                print("[!] 连接中断，重连中")
                client.close()
                time.sleep(2)
                relogin_ok = (
                    client.connect_login_server()
                    and client.login_server_auth(username, password, server_id)
                    and client.connect_main_server(server_id)
                    and client.main_server_login(server_id)
                )
                if not relogin_ok:
                    retry_count += 1
                    continue
                if jump_to_ranch_on_reconnect:
                    if not run_ranch_jump_task(client, interval_ms, server_id, username, password):
                        retry_count += 1
                        continue
                time.sleep(1.0)

            try:
                final_hex = packet_hex.replace("{user_id}", get_hex(user_id))
                final_hex = final_hex.replace("{super_lamu_level}", "00000016")
                final_hex = final_hex.replace("{lamu_id}", lamu_id_hex)
                packet = Packet(final_hex)
                if client.send_packet(packet):
                    success_count += 1
                    sent = True
                else:
                    if fail_log_label:
                        print(
                            f"[!] {fail_log_label} 发送返回失败, 重试 {attempt_no}/3, "
                            f"connected={client.connected}"
                        )
                    fail_count += 1
                    retry_count += 1
                    time.sleep(0.1)
            except Exception as exc:
                if fail_log_label:
                    print(f"[!] {fail_log_label} 发送异常, 重试 {attempt_no}/3: {type(exc).__name__}: {exc}")
                fail_count += 1
                retry_count += 1
                time.sleep(0.1)

        if not sent:
            if fail_log_label:
                print(f"[!] {fail_log_label} 发送失败 {index}/{len(packet_queue)}")
            else:
                print(f"[!] 发送失败 {index}/{len(packet_queue)}")

        if interval_ms > 0:
            time.sleep(interval_ms / 1000.0)

    return success_count, fail_count


def execute_packet_queue(client, packet_queue, interval_ms, server_id, username, password, lamu_id_hex="00000000"):
    if not packet_queue:
        return True

    print(f"[*] 每日封包: {len(packet_queue)}")
    success_count, fail_count = _send_packet_queue_common(
        client,
        packet_queue,
        interval_ms,
        server_id,
        username,
        password,
        lamu_id_hex=lamu_id_hex,
        jump_to_ranch_on_reconnect=False,
        fail_log_label=None,
    )

    print(f"[*] 每日封包完成: 成功 {success_count} / 总 {len(packet_queue)} / 失败 {fail_count}")
    time.sleep(5)
    return True


def _run_packet_batch(
    client,
    packet_queue,
    interval_ms,
    server_id,
    username,
    password,
    label,
    lamu_id_hex="00000000",
    jump_to_ranch_on_reconnect=False,
    require_all_success=False,
):
    if not packet_queue:
        return True

    success_count, fail_count = _send_packet_queue_common(
        client,
        packet_queue,
        interval_ms,
        server_id,
        username,
        password,
        lamu_id_hex=lamu_id_hex,
        jump_to_ranch_on_reconnect=jump_to_ranch_on_reconnect,
        fail_log_label=label,
    )

    print(f"[*] {label} 完成: 成功 {success_count} / 总 {len(packet_queue)} / 失败 {fail_count}")
    if require_all_success and success_count < len(packet_queue):
        return False
    return True


def run_ranch_jump_task(client, interval_ms, server_id, username, password):
    jump_packets = [
        "000000127200000192{user_id}00000000",
        "0000002A4300000191{user_id}00000000{user_id}0000000200000000000000000000000000000000",
        "000000160300000551{user_id}00000000{user_id}",
    ]
    return _run_packet_batch(client, jump_packets, interval_ms, server_id, username, password, "牧场跳转")


def run_ranch_fish_task(client, ranch_fish_cfg, server_id, username, password, pre_jumped=False):
    if not _to_bool(ranch_fish_cfg.get("enabled", False), False):
        return True

    fish_interval = max(0, _to_int(ranch_fish_cfg.get("interval_ms", 80), 80))
    jump_first = _to_bool(ranch_fish_cfg.get("jump_first", True), True)
    bait_type = str(ranch_fish_cfg.get("bait_type", "krill")).strip().lower() or "krill"
    bait_count = max(1, _to_int(ranch_fish_cfg.get("bait_count", ranch_fish_cfg.get("target_capacity", 30)), 30))

    if jump_first and not pre_jumped:
        if not run_ranch_jump_task(client, fish_interval, server_id, username, password):
            return False

    fish_packets = []
    for _ in range(10):
        fish_packets.append("00000012620000076C{user_id}00000000")
        fish_packets.append("00000012E40000076E{user_id}00000000")
    if not _run_packet_batch(
        client,
        fish_packets,
        fish_interval,
        server_id,
        username,
        password,
        "渔网捕捞",
        jump_to_ranch_on_reconnect=True,
    ):
        return False

    if bait_type == "crayfish":
        bait_packet = "000000161000000555{user_id}0000000000136105"
    else:
        bait_type = "krill"
        buy_krill_packets = ["0000001AEC000001F5{user_id}00000000001361170000001E"]
        if not _run_packet_batch(
            client,
            buy_krill_packets,
            fish_interval,
            server_id,
            username,
            password,
            "购买磷虾",
            jump_to_ranch_on_reconnect=True,
        ):
            return False
        bait_packet = "00000016B900000555{user_id}0000000000136117"

    bait_packets = [bait_packet for _ in range(bait_count)]
    bait_label = "放磷虾" if bait_type == "krill" else "放小龙虾"
    if not _run_packet_batch(
        client,
        bait_packets,
        fish_interval,
        server_id,
        username,
        password,
        bait_label,
        jump_to_ranch_on_reconnect=True,
    ):
        return False

    return True


def run_mlcs_task(client, mlcs_cfg, server_id, username, password):
    if not _to_bool(mlcs_cfg.get("enabled", False), False):
        return True

    beijing_now = datetime.now(timezone.utc).astimezone(BEIJING_TZ)
    now_minutes = beijing_now.hour * 60 + beijing_now.minute
    if now_minutes < MLCS_WINDOW_START_MINUTES or now_minutes > MLCS_WINDOW_END_MINUTES:
        return True

    level_id_map = {
        "无尽深渊": "00000007",
        "激战蛋蛋": "00000010",
        "沉睡奥丁": "00000017",
        "莎士摩亚": "00000009",
    }
    packet_queue = [
        "00000000000000231A0000000000000000",
    ]

    def append_fight_packets(level_name, times):
        level_hex = level_id_map[level_name]
        for _ in range(max(0, int(times))):
            packet_queue.append(f"00000000000000231D0000000000000000{level_hex}")
            packet_queue.append(f"0000000000000023210000000000000000{level_hex}")

    append_fight_packets("无尽深渊", 70)
    append_fight_packets("莎士摩亚", 40)
    packet_queue.append("000000000000002319000000000000000000000000")
    packet_queue.extend(
        [
            "000000000000002331000000000000000000000000",
            "000000000000002331000000000000000000000001",
        ]
    )

    selected_level = str(mlcs_cfg.get("level", "")).strip()
    if selected_level in ("激战蛋蛋", "沉睡奥丁", "莎士摩亚"):
        append_fight_packets(selected_level, 44)

    print(f"[*] 元素骑士固定流程，总封包 {len(packet_queue)}")
    return _run_packet_batch(client, packet_queue, 50, server_id, username, password, "元素骑士-固定流程")


def run_wish_task(client, wish_cfg, server_id, username, password):
    wish_item = str(wish_cfg.get("item", "")).strip()
    if not wish_item:
        return True

    target_user_id = _normalize_user_id_hex(wish_cfg.get("target_user_id", ""), "00000000")
    if target_user_id == "00000000":
        return True

    wish_packet_map = {
        "组合蘑菇壁灯": "0000003C85000002EF{user_id}00000000{target_user_id}00027114E7BB84E59088E89891E88F87E5A381E781AF00000000000000000000000000000063",
        "古典落地灯": "0000003C43000002EF{user_id}00000000{target_user_id}00027109E58FA4E585B8E890BDE59CB0E781AF00000000000000000000000000000000000063",
        "雪花": "0000003C05000002EF{user_id}00000000{target_user_id}0002719DE99BAAE88AB100000000000000000000000000000000000000000000000000000063",
        "绿色蘑菇壁灯": "0000003CE0000002EF{user_id}00000000{target_user_id}0002710CE7BBBFE889B2E89891E88F87E5A381E781AF00000000000000000000000000000063",
        "绿茵壁纸": "0000003C7D000002EF{user_id}00000000{target_user_id}00027149E7BBBFE88CB5E5A381E7BAB800000000000000000000000000000000000000000063",
        "小杠铃": "0000003C23000002EF{user_id}00000000{target_user_id}000271CFE5B08FE69DA0E9938300000000000000000000000000000000000000000000000063",
        "拉姆跳跳杆": "0000003CA4000002EF{user_id}00000000{target_user_id}000271D1E68B89E5A786E8B7B3E8B7B3E69D8600000000000000000000000000000000000063",
        "红色小鼓": "0000003CF6000002EF{user_id}00000000{target_user_id}0002711CE7BAA2E889B2E5B08FE9BC9300000000000000000000000000000000000000000063",
    }

    packet_hex = wish_packet_map.get(wish_item, "")
    if not packet_hex:
        return True

    packet_hex = packet_hex.replace("{target_user_id}", target_user_id)
    # 发送前快速校验，避免模板问题在重试里被吞掉。
    preview_hex = packet_hex.replace("{user_id}", get_hex(user_id))
    if len(preview_hex) % 2 != 0:
        print(f"[!] 许愿-{wish_item} 模板长度异常: {len(preview_hex)}(需为偶数)")
        return False
    try:
        bytes.fromhex(preview_hex)
    except Exception as exc:
        print(f"[!] 许愿-{wish_item} 模板解析失败: {type(exc).__name__}: {exc}")
        return False

    label = f"许愿-{wish_item}"
    success_count = 0
    fail_count = 0

    for attempt_no in range(1, 4):
        if not client.connected:
            print("[!] 连接中断，重连中")
            client.close()
            time.sleep(2)
            relogin_ok = (
                client.connect_login_server()
                and client.login_server_auth(username, password, server_id)
                and client.connect_main_server(server_id)
                and client.main_server_login(server_id)
            )
            if not relogin_ok:
                fail_count += 1
                continue
            time.sleep(1.0)

        try:
            final_hex = packet_hex.replace("{user_id}", get_hex(user_id))
            packet = Packet(final_hex)
            if not client.send_packet(packet):
                print(f"[!] {label} 发送返回失败, 重试 {attempt_no}/3, connected={client.connected}")
                fail_count += 1
                time.sleep(0.1)
                continue
            success_count = 1
            break

        except Exception as exc:
            print(f"[!] {label} 发送异常, 重试 {attempt_no}/3: {type(exc).__name__}: {exc}")
            fail_count += 1
            time.sleep(0.1)

    print(f"[*] {label} 完成: 成功 {success_count} / 总 1 / 失败 {fail_count}")
    return success_count == 1


def is_mlcs_window_now():
    beijing_now = datetime.now(timezone.utc).astimezone(BEIJING_TZ)
    now_minutes = beijing_now.hour * 60 + beijing_now.minute
    return MLCS_WINDOW_START_MINUTES <= now_minutes <= MLCS_WINDOW_END_MINUTES, beijing_now


def run_ranch_egg_task(client, ranch_egg_cfg, server_id, username, password):
    if not _to_bool(ranch_egg_cfg.get("enabled", False), False):
        return True

    egg_interval = max(0, _to_int(ranch_egg_cfg.get("interval_ms", 80), 80))
    mode = str(ranch_egg_cfg.get("mode", "turkey3")).strip().lower()
    hatch_after_place = _to_bool(ranch_egg_cfg.get("hatch_after_place", False), False)

    # 孵蛋前先跳转牧场确认场景
    if not run_ranch_jump_task(client, egg_interval, server_id, username, password):
        return False

    collect_packets = [
        "00000016A000000788{user_id}0000000000000000",
        "00000016A000000788{user_id}0000000000000001",
        "00000016A000000788{user_id}0000000000000002",
    ]
    turkey_place_packets = [
        "0000001A5A0000077E{user_id}000000000000000000136102",
        "0000001AC90000077E{user_id}000000000000000100136102",
        "0000001A330000077E{user_id}000000000000000200136102",
    ]
    phoenix_claim_packet = "0000001A81000001F5{user_id}000000000013610D00000001"
    phoenix_place_packet = "0000001AE10000077E{user_id}00000000000000020013610D"
    hatch_packets = [
        "0000001AF00000077F{user_id}00000000{user_id}00000000",
        "0000001A440000077F{user_id}00000000{user_id}00000001",
        "0000001AB40000077F{user_id}00000000{user_id}00000002",
    ]

    packet_queue = []
    packet_queue.extend(collect_packets)

    if mode == "turkey2_phoenix1":
        packet_queue.append(turkey_place_packets[0])
        packet_queue.append(turkey_place_packets[1])
        packet_queue.append(phoenix_claim_packet)
        packet_queue.append(phoenix_place_packet)
    else:
        packet_queue.extend(turkey_place_packets)

    if hatch_after_place:
        packet_queue.extend(hatch_packets)

    return _run_packet_batch(
        client,
        packet_queue,
        egg_interval,
        server_id,
        username,
        password,
        "孵蛋收蛋放蛋",
        jump_to_ranch_on_reconnect=True,
    )


def run_lamu_daily_task(client, lamu_cfg, server_id, username, password):
    if not _to_bool(lamu_cfg.get("enabled", False), False):
        return True

    interval_ms = max(0, _to_int(lamu_cfg.get("interval_ms", 50), 50))
    lamu_entries = lamu_cfg.get("lamus", [])

    # 兼容旧配置：只有单个lamu_id时构造默认规则
    if not lamu_entries:
        lamu_id_hex = _normalize_hex8(lamu_cfg.get("lamu_id", "00000000"), "00000000")
        if lamu_id_hex != "00000000":
            lamu_entries = [
                {
                    "lamu_id": lamu_id_hex,
                    "level_group": "11",
                    "prev_attr": "木",
                    "prev_item": "0002E8C0",
                    "prev_count": 1,
                    "curr_attr": "水",
                    "curr_item": "0012C4C6",
                    "curr_count": 10,
                    "feed_after": True,
                }
            ]

    if not lamu_entries:
        print("[!] 拉姆每日已开启但未配置拉姆列表，已跳过")
        return True

    valid_lamus = []
    for item in lamu_entries:
        if not isinstance(item, dict):
            continue
        lamu_id_hex = _normalize_hex8(item.get("lamu_id", "00000000"), "00000000")
        if lamu_id_hex == "00000000":
            continue

        level_group = str(item.get("level_group", "11")).strip()
        level_cfg = LAMU_LEVEL_GROUP.get(level_group, LAMU_LEVEL_GROUP["11"])
        prev_attr = _normalize_lamu_attr(item.get("prev_attr", "木"), "木")
        curr_attr = _normalize_lamu_attr(item.get("curr_attr", "水"), "水")
        prev_item = _normalize_hex8(item.get("prev_item", "0002E8C0"), "0002E8C0")
        curr_item = _normalize_hex8(item.get("curr_item", "0012C4C6"), "0012C4C6")
        prev_count = max(0, _to_int(item.get("prev_count", 1), 1))
        curr_count = max(0, _to_int(item.get("curr_count", 10), 10))
        feed_after = _to_bool(item.get("feed_after", True), True)

        valid_lamus.append(
            {
                "lamu_id_hex": lamu_id_hex,
                "level_cfg": level_cfg,
                "prev_attr": prev_attr,
                "curr_attr": curr_attr,
                "prev_item": prev_item,
                "curr_item": curr_item,
                "prev_count": prev_count,
                "curr_count": curr_count,
                "feed_after": feed_after,
            }
        )

    valid_count = len(valid_lamus)
    if valid_count == 0:
        print("[!] 拉姆列表没有有效拉姆ID，已跳过")
        return True

    all_packets = []
    feed_lamu_ids = []
    for idx, item in enumerate(valid_lamus):
        lamu_id_hex = item["lamu_id_hex"]
        level_cfg = item["level_cfg"]
        prev_attr = item["prev_attr"]
        curr_attr = item["curr_attr"]
        prev_item = item["prev_item"]
        curr_item = item["curr_item"]
        prev_count = item["prev_count"]
        curr_count = item["curr_count"]
        feed_after = item["feed_after"]

        prev_skill_id = _get_lamu_skill_id(level_cfg["last"], prev_attr)
        curr_skill_id = _get_lamu_skill_id(level_cfg["max"], curr_attr)
        prev_skill_hex = f"{prev_skill_id:08X}"
        curr_skill_hex = f"{curr_skill_id:08X}"

        for _ in range(prev_count):
            all_packets.append(f"0000000000000004BC0000000000000000{lamu_id_hex}{prev_skill_hex}")
            all_packets.append(f"0000000000000004B90000000000000000{lamu_id_hex}{prev_skill_hex}{prev_item}")

        for _ in range(curr_count):
            all_packets.append(f"0000000000000004BC0000000000000000{lamu_id_hex}{curr_skill_hex}")
            all_packets.append(f"0000000000000004B90000000000000000{lamu_id_hex}{curr_skill_hex}{curr_item}")

        if feed_after:
            feed_lamu_ids.append(lamu_id_hex)

        if idx + 1 < valid_count:
            next_lamu_id_hex = valid_lamus[idx + 1]["lamu_id_hex"]
            all_packets.append(f"0000001A66000000D7{{user_id}}0000000000{next_lamu_id_hex}00000001")

    if feed_lamu_ids:
        all_packets.append("0000001EE800000200{user_id}00000000000000010002BF2600000063")
        for feed_lamu_id in feed_lamu_ids:
            all_packets.append(f"0000001E25000001F9{{user_id}}00000000{{user_id}}{feed_lamu_id}0002BF26")
            all_packets.append(f"0000001E25000001F9{{user_id}}00000000{{user_id}}{feed_lamu_id}0002BF26")

    return _run_packet_batch(
        client,
        all_packets,
        interval_ms,
        server_id,
        username,
        password,
        f"拉姆每日变身值与喂养({valid_count}只拉姆)",
    )


def send_online_gift_packets(client):
    packets = [
        "0000001EB0000004DB03E4F72C000000000000003D0000000100000001",
        "0000001E12000004DB03E4F72C000000000000003E0000000100000001",
        "0000001EF2000004DB03E4F72C000000000000003F0000000100000001",
        "0000001E7A000004DB03E4F72C00000000000000400000000100000001",
        "0000001E8D000004DB03E4F72C00000000000000410000000100000001",
    ]
    success = 0
    fail = 0
    for packet_hex in packets:
        try:
            packet = Packet(packet_hex)
            if client.send_packet(packet):
                success += 1
            else:
                fail += 1
        except Exception:
            fail += 1
        time.sleep(0.05)
    print(f"[*] 在线礼包发送: 成功 {success} / 总 {len(packets)} / 失败 {fail}")


def load_accounts():
    import os

    def normalize_accounts(raw_accounts):
        result = []
        for raw in raw_accounts:
            if not isinstance(raw, dict):
                continue
            item = normalize_account_config(raw)
            if item["enabled"] and item["username"] and item["password"]:
                result.append(item)
        return result

    for env_key in ("MOLE_ACCOUNTS_JSON", "ACCOUNTS_CONFIG"):
        accounts_json = os.environ.get(env_key)
        if accounts_json:
            try:
                parsed = json.loads(accounts_json)
                if isinstance(parsed, dict):
                    parsed = [parsed]
                result = normalize_accounts(parsed if isinstance(parsed, list) else [])
                print(f"[+] 从 {env_key} 加载账号: {len(result)}")
                return result
            except Exception as exc:
                print(f"[-] 解析 {env_key} 失败: {exc}")

    username = os.environ.get("MOLE_USERNAME")
    password = os.environ.get("MOLE_PASSWORD")
    server = os.environ.get("MOLE_SERVER")
    if username and password:
        return normalize_accounts(
            [
                {
                    "username": username,
                    "password": password,
                    "server": _to_int(server, 100),
                    "enabled": True,
                    "online_minutes": 30,
                }
            ]
        )

    for file_name in ("accounts_config.json", "account.json", "accounts.json"):
        path = Path(__file__).parent / file_name
        if not path.exists():
            continue
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and "accounts" in parsed and isinstance(parsed["accounts"], dict):
                # 兼容 {"accounts": {"uid": "pwd"}} 旧结构
                parsed = [
                    {
                        "username": uid,
                        "password": pwd,
                        "server": 100,
                        "enabled": True,
                    }
                    for uid, pwd in parsed["accounts"].items()
                ]
            if isinstance(parsed, dict):
                parsed = [parsed]
            result = normalize_accounts(parsed if isinstance(parsed, list) else [])
            print(f"[+] 从文件 {file_name} 加载账号: {len(result)}")
            return result
        except Exception as exc:
            print(f"[-] 读取 {file_name} 失败: {exc}")

    return []


def _account_task_items(account, in_mlcs_window):
    features = account.get("features", {}) if isinstance(account, dict) else {}
    online_cfg = features.get("online", {})
    gift_cfg = features.get("online_gift", {})
    daily_cfg = features.get("daily", {})
    lamu_cfg = features.get("lamu_daily", {})
    ranch_cfg = features.get("ranch", {})
    ranch_fish_cfg = features.get("ranch_fish", {})
    ranch_egg_cfg = features.get("ranch_egg", {})
    mlcs_cfg = features.get("mlcs", {})
    wish_cfg = features.get("wish", {})

    mlcs_enabled = _to_bool(mlcs_cfg.get("enabled", False), False)
    if in_mlcs_window:
        if mlcs_enabled:
            return ["元素骑士"]
        return ["跳过"]

    items = []

    online_enabled = _to_bool(online_cfg.get("enabled", True), True)
    online_minutes = max(0, _to_int(online_cfg.get("minutes", 0), 0))
    if online_enabled and online_minutes > 0:
        items.append(f"挂机{online_minutes}m")
        if (
            _to_bool(gift_cfg.get("enabled", True), True)
            and online_minutes >= _to_int(gift_cfg.get("min_minutes", 100), 100)
        ):
            items.append("在线礼包")

    if _to_bool(daily_cfg.get("enabled", True), True):
        items.append("每日任务")

    if _to_bool(lamu_cfg.get("enabled", False), False):
        items.append("拉姆变身值")
        items.append("拉姆喂养")

    if _to_bool(ranch_cfg.get("enabled", False), False):
        if _to_bool(ranch_fish_cfg.get("enabled", False), False):
            items.append("渔网补饵")
        if _to_bool(ranch_egg_cfg.get("enabled", False), False):
            items.append("孵蛋")

    wish_item = str(wish_cfg.get("item", "")).strip()
    wish_target = _normalize_user_id_hex(wish_cfg.get("target_user_id", ""), "00000000")
    if wish_item and wish_target != "00000000":
        items.append(f"许愿:{wish_item}")

    if mlcs_enabled:
        items.append("元素骑士")

    if not items:
        items.append("无")
    return items


def process_account(account, daily_items):
    username = account["username"]
    password = account["password"]
    server = account.get("server", 100)

    features = account.get("features", {})
    daily_cfg = features.get("daily", {})
    online_cfg = features.get("online", {})
    gift_cfg = features.get("online_gift", {})
    lamu_daily_cfg = features.get("lamu_daily", {})
    ranch_cfg = features.get("ranch", {})
    ranch_fish_cfg = features.get("ranch_fish", {})
    ranch_egg_cfg = features.get("ranch_egg", {})
    mlcs_cfg = features.get("mlcs", {})
    wish_cfg = features.get("wish", {})
    super_lamu_level = _normalize_super_lamu_level(account.get("super_lamu_level", 0))
    custom_packets = account.get("super_lamu_packets", [])
    custom_packets = _build_super_lamu_packets(super_lamu_level) + (custom_packets if isinstance(custom_packets, list) else [])

    online_enabled = _to_bool(online_cfg.get("enabled", True), True)
    online_minutes = max(0, _to_int(online_cfg.get("minutes", 0), 0))

    print(f"\n[*] 账号 {username} / 服{server}")

    client = Client()

    try:
        login_ok = (
            client.connect_login_server()
            and client.login_server_auth(username, password, server)
            and client.connect_main_server(server)
            and client.main_server_login(server)
        )
        if not login_ok:
            return False

        mlcs_enabled = _to_bool(mlcs_cfg.get("enabled", False), False)
        in_mlcs_window, beijing_now = is_mlcs_window_now()
        if mlcs_enabled and in_mlcs_window:
            print(f"[*] 元素骑士专用时段 {beijing_now.strftime('%H:%M')}")
            if not run_mlcs_task(client, mlcs_cfg, server, username, password):
                return False
            print(f"[+] {username} 完成")
            return True

        if online_enabled and online_minutes > 0:
            print(f"[*] 挂机 {online_minutes} 分钟")
            end_ts = time.time() + int(online_minutes * 60)
            while time.time() < end_ts:
                if not client.connected:
                    print("[!] 挂机掉线，重连中")
                    client.close()
                    relogin_ok = (
                        client.connect_login_server()
                        and client.login_server_auth(username, password, server)
                        and client.connect_main_server(server)
                        and client.main_server_login(server)
                    )
                    if not relogin_ok:
                        time.sleep(5)
                        continue
                time.sleep(1)
        if (
            _to_bool(gift_cfg.get("enabled", True), True)
            and online_enabled
            and online_minutes >= _to_int(gift_cfg.get("min_minutes", 100), 100)
        ):
            send_online_gift_packets(client)

        if _to_bool(daily_cfg.get("enabled", True), True):
            selected_items = select_daily_items_for_account(daily_items, daily_cfg)
            packet_queue = build_packet_queue(selected_items, daily_cfg, custom_packets)
            interval_ms = max(0, _to_int(daily_cfg.get("interval_ms", 50), 50))
            lamu_id_hex = _normalize_hex8(lamu_daily_cfg.get("lamu_id", "00000000"), "00000000")
            if not execute_packet_queue(client, packet_queue, interval_ms, server, username, password, lamu_id_hex=lamu_id_hex):
                return False
        if not run_lamu_daily_task(client, lamu_daily_cfg, server, username, password):
            return False

        ranch_enabled = _to_bool(ranch_cfg.get("enabled", False), False)
        if ranch_enabled:
            ranch_interval = max(0, _to_int(ranch_cfg.get("interval_ms", 80), 80))
            jump_before_all = _to_bool(ranch_cfg.get("jump_before_all", True), True)
            pre_jumped = False
            if jump_before_all:
                if not run_ranch_jump_task(client, ranch_interval, server, username, password):
                    return False
                pre_jumped = True

            if not run_ranch_fish_task(client, ranch_fish_cfg, server, username, password, pre_jumped=pre_jumped):
                return False

            if not run_ranch_egg_task(client, ranch_egg_cfg, server, username, password):
                return False
        if not run_wish_task(client, wish_cfg, server, username, password):
            return False

        if not run_mlcs_task(client, mlcs_cfg, server, username, password):
            return False

        print(f"[+] {username} 执行完成")
        return True

    except Exception as exc:
        print(f"[-] 账号 {username} 执行失败: {exc}")
        return False
    finally:
        client.close()
        time.sleep(2)


def process_account_entry(index, total, account, daily_items):
    print(f"\n[{index}/{total}]")
    success = process_account(account, daily_items)
    if not success:
        raise SystemExit(1)


def main():
    accounts = load_accounts()
    if not accounts:
        print("[-] 未找到可用账号配置")
        return 1

    daily_items = load_daily_packets()
    if not daily_items:
        daily_items = {}

    in_mlcs_window, beijing_now = is_mlcs_window_now()
    run_accounts = accounts
    skipped_accounts = []
    if in_mlcs_window:
        run_accounts = []
        for account in accounts:
            features = account.get("features", {}) if isinstance(account, dict) else {}
            mlcs_cfg = features.get("mlcs", {}) if isinstance(features, dict) else {}
            if _to_bool(mlcs_cfg.get("enabled", False), False):
                run_accounts.append(account)
            else:
                skipped_accounts.append(account)

    if in_mlcs_window:
        print(f"[*] 元素骑士时段 {beijing_now.strftime('%H:%M')} | 执行 {len(run_accounts)} | 跳过 {len(skipped_accounts)}")

    account_items = [_account_task_items(account, in_mlcs_window) for account in accounts]
    status_by_index = ["待执行" for _ in accounts]
    if in_mlcs_window:
        for idx, account in enumerate(accounts):
            features = account.get("features", {}) if isinstance(account, dict) else {}
            mlcs_cfg = features.get("mlcs", {}) if isinstance(features, dict) else {}
            if not _to_bool(mlcs_cfg.get("enabled", False), False):
                status_by_index[idx] = "跳过"

    if not run_accounts:
        print(f"汇总: 总账号 {len(accounts)} | 执行 0 | 跳过 {len(skipped_accounts)} | 成功 0 | 失败 0")
        for idx, account in enumerate(accounts, 1):
            username = account.get("username", "")
            item_text = "、".join(account_items[idx - 1])
            print(f"{idx}. {username} | {status_by_index[idx - 1]} | {item_text}")
        return 0

    success_accounts = []
    failed_accounts = []
    processes = []
    total = len(run_accounts)
    run_entries = []
    run_ids = {id(account) for account in run_accounts}
    for idx, account in enumerate(accounts):
        if id(account) in run_ids:
            run_entries.append((idx, account))

    for i, (idx, account) in enumerate(run_entries, 1):
        p = Process(target=process_account_entry, args=(i, total, account, daily_items))
        p.start()
        processes.append((p, idx, account.get("username", "")))

    for p, idx, username in processes:
        p.join()
        if p.exitcode == 0:
            success_accounts.append(username)
            status_by_index[idx] = "成功"
        else:
            failed_accounts.append(username)
            status_by_index[idx] = "失败"

    print(
        f"汇总: 总账号 {len(accounts)} | 执行 {len(run_accounts)} | 跳过 {len(skipped_accounts)} "
        f"| 成功 {len(success_accounts)} | 失败 {len(failed_accounts)}"
    )
    if failed_accounts:
        print("失败账号: " + "、".join(failed_accounts))

    for idx, account in enumerate(accounts, 1):
        username = account.get("username", "")
        item_text = "、".join(account_items[idx - 1])
        print(f"{idx}. {username} | {status_by_index[idx - 1]} | {item_text}")

    return 0 if len(failed_accounts) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
