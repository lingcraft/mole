from PySide6.QtCore import QTimer, QThread, Signal, QUrl, Qt, QTranslator
from PySide6.QtWidgets import QApplication, QHeaderView, QListWidgetItem, QTableWidgetItem, QTableWidget, QMessageBox, QMainWindow, QDialog
from PySide6.QtGui import QFont, QIcon, QDesktopServices, QAction
from ui_main import Ui_MainWindow
from ui_advance import Ui_AdvanceDialog
from struct import pack, pack_into, unpack_from
from threading import Lock, Thread
from cffi import FFI
from socket import socket, fromfd, AF_INET, SOCK_STREAM
from collections import Counter
from copy import deepcopy
from dict import *
from datetime import datetime
from time import sleep
from enum import IntEnum, IntFlag, StrEnum
from configparser import ConfigParser
from os import environ
from pathlib import Path
from tomllib import load, loads
from requests import get
from bisect import bisect_right
from math import floor, sqrt
from pypinyin import lazy_pinyin, Style
from packaging.version import parse
from pyamf import sol
from collections import deque
from client import Client

# 封包
secret_key = b"^FStx,wl6NquAVRF@f%6\x00"  # 封包算法密钥
login_socket_num, login_ip, login_port = 0, 0, 0  # 登录后的socket、IP、Port
user_id, serial_num, packet_index = 0, 0, 0  # 米米号、发送包序列号、封包序号索引
recv_buf = bytearray()  # 接收封包的数据缓冲区
buf_index = 0  # 数据索引
is_show_send, is_show_recv, is_write_recv = True, True, False  # 显示send包、recv包、写回recv包
lock = Lock()  # 发送锁
is_show_msg = False  # 是否显示过消息
pending_waits = []  # 等待中的请求
# 拉姆
can_get_lamu_info = True  # 能否获取拉姆信息
lamu_id, lamu_name, lamu_value, lamu_level, lamu_times = 0, "", 0, 0, 0  # 拉姆ID、名字、变身值、变身等级、变身获得物品成功次数
lamu_thresholds = [40, 180, 660, 1340, 2660, 4280, 6840, 9800, 14000, 18700]  # 拉姆变身值阈值
lamu_skill_types = ["火", "水", "木"]  # 拉姆技能类型
lamu_max_skill_level, lamu_last_skill_level, = 0, 0  # 拉姆最大技能等级、次大技能等级
lamu_last_item_level, lamu_max_item_level = 0, 0  # 拿取的物品等级
lamu_last_type_index, lamu_max_type_index = 0, 0  # 拿取的物品类型索引
lamu_last_item_index, lamu_max_item_index = 0, 0  # 拿取的物品索引
lamu_limit_item_dict, limit_data = {}, {}  # 已经拿到上限的物品
is_max_skill_success, is_last_skill_success = True, True  # 最大技能拿取物品是否成功、次大技能拿取物品是否成功
lamu_pick_result_dict = {}  # 拉姆拿取物品结果
super_lamu_value, super_lamu_level = 0, 0  # 超拉成长值、等级
# 摩摩怪
mmg_energy, mmg_vigour, mmg_level, mmg_card, mmg_game_id = 0, 0, 0, 0, ""  # 能量、活力、等级、摩摩挑战卡、游戏ID
mmg_type, mmg_times = 0, 0  # 摩摩怪挑战类型、执行次数
mmg_super_boss_times, mmg_lamu_boss_times, mmg_limit_boss_times = 0, 0, 0  # 超级Boss、超拉Boss、限时Boss的可挑战次数
mmg_boss_index1, mmg_boss_index2, mmg_boss_index3 = 0, 0, 0  # 3种Boss挑战次数索引
mmg_friends, mmg_friends_dict, mmg_students_dict, mmg_fight_friends = [], {}, {}, deque()  # 好友、好友字典（米米号：等级）、师徒、可挑战好友
mmg_friends_state_dict = {1: [], 2: [], 3: [], 4: []}  # 4种状态的好友字典
mmg_friends_num, mmg_query_size_max, mmg_query_page_max, mmg_query_page = 0, 14, 0, 0  # 好友数、最大可查询好友数、最大查询页码、查询页码
# 魔灵传说
mlcs_energy, mlcs_arena_times, mlcs_exp_times = 0, 0, 0  # 魔灵体力值、竞技场可挑战次数、经验之路可挑战次数
mlcs_fight_elves_dict, mlcs_elves_dict = {}, {}  # 出战魔灵、全部魔灵
# 元素骑士
ysqs_max_floor, ysqs_attack, ysqs_energy = 0, 0, 0  # 无尽深渊最高层数、最低攻击力、体力值
can_fight_wjsy, can_fight_ssmy, is_equip_card = False, False, True  # 能否挑战无尽深渊、莎士摩亚、是否装备卡牌
ysqs_cards_dict, ysqs_material_cards_dict, ysqs_max_level_cards_dict = {}, {}, {}  # 元素可升级卡牌、材料卡牌、最高等级卡牌
# 餐厅
ct_cooked_dishes_dict, ct_cooking_dishes_dict = {}, {}  # 餐台菜信息、灶台菜信息
# 游戏版本
server_dict = {
    "官服": "http://mole.61.com",
    "平行服": "http://$node",
    "骑士版": "http://$node/moleverse/20090626",
    "圣诞版": "http://$node/moleverse/20111225",
    "万圣版": "http://$node/moleverse/20190815",
    "新春版": "http://$node/moleverse/20120128",
    "火神版": "http://$node/moleverse/2025hsb",
    "桃源版": "http://$node/moleverse/taoyuan",
}
# 平行服节点
node_dict = {
    "主节点": "mole.61player.com",
    "备用节点": "mole-sub.61player.com",
    "亚洲节点": "mole-asia.61player.com",
    "国内节点": "175.178.55.57"
}
# 版本文件地址
version_url = "https://raw.githubusercontent.com/lingcraft/mole/master/pyproject.toml"
# 链接加速前缀
cdn_prefixs = [
    "https://v6.gh-proxy.org",
    "https://github.cnxiaobai.com"
]
# Hook文件
ffi = FFI()
ffi.cdef("""
typedef int (*SendCallBack)(ULONG64, PCHAR, INT);
typedef void (*RecvCallBack)(ULONG64, PCHAR, INT);
void SetSendCallBack(SendCallBack);
void SetRecvCallBack(RecvCallBack);
int WINAPI Send(ULONG64, PCHAR, INT);
void LoadFlash();
""")
# 路径
config = Path(environ["appdata"]) / "mole" / "config.ini"
base_dir = Path(__file__).resolve().parent
log = base_dir / "hook.log"
login_cache = next(
    (
        cache_dir / "mole.61.com" / "#mole" / "login.sol"
        for cache_dir in (Path(environ["appdata"]) / "Macromedia" / "Flash Player" / "#SharedObjects").glob("*")
    ),
    None
)
account_caches = [
    sol_file
    for cache_dir in (Path(environ["appdata"]) / "Macromedia" / "Flash Player" / "#SharedObjects").glob("*")
    for sol_file in (cache_dir / "mole.61.com" / "#mole").glob("*.sol")
    if sol_file.stem.isdigit()
]
is_window_init = False


class Interval(IntEnum):
    INSTANT = 0  # 无延迟模式，前台发送间隔，防止界面卡顿
    FAST = 1  # 快速模式，后台发送间隔，适用于刷点点豆、摩尔豆等
    NORMAL = 25  # 正常模式，后台通用发送间隔，适用于魔灵传说等
    SLOW = 50  # 慢速模式，后台发送间隔，适用于元素骑士
    IDLE = 200  # 最慢模式，后台发送间隔，适用于拉姆变身值


class Show(StrEnum):
    SEND = "S ==>"
    RECV = "R <=="


class Button(IntFlag):
    OK = QMessageBox.StandardButton.Ok
    CANCEL = QMessageBox.StandardButton.Cancel
    OK_CANCEL = OK | CANCEL


class MainWindow(QMainWindow, Ui_MainWindow):
    signal = Signal(str, int, int, str, str)

    def __init__(self):
        super().__init__()
        # 界面基础设置
        self.setupUi(self)
        # 界面额外设置
        # 读取配置
        self.config = ConfigParser()
        if config.exists():
            self.config.read(config, encoding="utf-8")
            self.server = self.config.get("Settings", "server", fallback="官服")
            self.node = self.config.get("Settings", "node", fallback="主节点")
            if self.server not in server_dict:
                self.server = "官服"
            if self.node not in node_dict:
                self.node = "主节点"
        else:
            self.server = "官服"
            self.node = "主节点"
        with open(path("pyproject.toml"), "rb") as file:  # 获取版本
            self.version = load(file)["project"]["version"]
        self.account_dict = {}
        if login_cache is not None:
            with open(login_cache, "rb") as file:  # 获取登录信息
                self.account_dict = {data["userID"]: get_password(data["pwd"]) for data in sol.decode(file.read())[1]["list"]}
        self.friend_dict = {}
        for account_cache in account_caches:  # 获取好友信息
            with open(account_cache, "rb") as file:
                self.friend_dict[int(account_cache.stem)] = [int(item["friend"]) for item in sol.decode(file.read())[1]["ServerFriendsList"]]
        # 界面主区域设置
        self.axWidget.dynamicCall("LoadMovie(long,string)", 0, self.url())
        self.axWidget.dynamicCall("SetScaleMode(int)", 0)
        self.tableWidget.setFont(QFont("Cascadia Code, Microsoft YaHei UI", 9))
        self.tableWidget.verticalHeader().setDefaultSectionSize(10)  # 行高
        self.tableWidget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # 禁止编辑单元格
        self.tableWidget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)  # 禁止选多行
        self.tableWidget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)  # 一次选一行
        self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # 允许手动调整列宽
        self.clear_table()
        self.tableWidget.setHorizontalHeaderLabels(["类型", "通信号", "命令号", "解析", "封包数据"])
        self.tableWidget.currentCellChanged.connect(self.change_row)
        # 界面菜单栏设置
        self.serverMenu = self.menubar.addMenu("切换版本")
        for server in server_dict:
            action = QAction(server, self, checkable=True)
            action.triggered.connect(self.change_server)
            self.serverMenu.addAction(action)
        self.nodeMenu = self.menubar.addMenu("切换节点")
        for node in node_dict:
            action = QAction(node, self, checkable=True)
            action.triggered.connect(self.change_node)
            self.nodeMenu.addAction(action)
        self.menubar.addAction("刷新游戏", self.refresh)
        self.menubar.addAction("检查更新", self.check_update)
        self.menubar.addAction(QIcon(path("github.ico")), "关于", self.open_github)
        self.check_menu()  # 节点勾选
        # 线程初始化
        self.send_thread = SendThread()
        self.send_ex_thread = SendExThread()
        self.send_to_server_thread = SendToServerThread()
        self.send_to_server_thread.result.connect(self.mmg_get_reward)
        self.update_thread = UpdateThread()
        self.update_thread.result.connect(self.update_result)
        self.advance_dialog = AdvanceDialog()
        self.signal.connect(self.add_data)
        self.client = None  # 独立进程客户端，懒启动时才创建
        # 单次运行功能
        self.sendButton.clicked.connect(self.send)
        self.sendClearButton.clicked.connect(self.send_clear)
        self.sendCheckBox.stateChanged.connect(self.change_show_send)
        self.recvCheckBox.stateChanged.connect(self.change_show_recv)
        self.socketCheckBox.stateChanged.connect(self.change_set_socket)
        self.clearButton.clicked.connect(self.clear_table)
        self.ysqsFightButton.clicked.connect(self.ysqs_start)
        self.ysqsUpgradeButton.clicked.connect(self.ysqs_upgrade_start)
        self.ysqsAdvanceButton.clicked.connect(self.ysqs_advance_start)
        self.mlcsFightButton.clicked.connect(self.mlcs_start)
        self.mlcsSellButton.clicked.connect(self.mlcs_sell_start)
        # 多次运行功能
        self.sendLoopButton.clicked.connect(lambda: self.start_task("循环发送", self.send, Interval.FAST, self.sendLoopButton))
        self.lamuGrowButton.clicked.connect(lambda: self.start_task("拉姆", self.lamu_run, Interval.IDLE, self.lamuGrowButton, self.lamu_start))
        self.dddGetButton.clicked.connect(lambda: self.start_task("点点豆", self.ddd_run, Interval.FAST, self.dddGetButton))
        self.medGetButton.clicked.connect(lambda: self.start_task("摩尔豆", self.med_run, Interval.FAST, self.medGetButton))
        self.bhOpenButton.clicked.connect(lambda: self.start_task("缤纷七彩宝盒", self.bh_run, Interval.SLOW, self.bhOpenButton, self.bh_start))
        # 摩摩怪功能
        self.timer_pool = {
            "摩摩怪": RunTimer(self.mmg_run, 1500),
            "餐厅": {pos: RunTimer() for pos in range(1, 8)}
        }
        self.mmgPVBButton.clicked.connect(lambda: self.mmg_start(1))
        self.mmgPVEButton.clicked.connect(lambda: self.mmg_start(2))
        self.mmgPVPButton.clicked.connect(lambda: self.mmg_start(3))
        # 餐厅功能
        self.ctSellButton.clicked.connect(lambda: self.start_task("餐厅卖菜", self.ct_sell_run, Interval.FAST, self.ctSellButton))
        self.ctHarvestButton.clicked.connect(self.ct_harvest_start)
        # 界面初始化完成
        global is_window_init
        is_window_init = True

    def closeEvent(self, event):
        if not self.config.has_section("Settings"):
            self.config.add_section("Settings")
        self.config.set("Settings", "server", self.server)
        self.config.set("Settings", "node", self.node)
        if not config.parent.exists():
            config.parent.mkdir()
        with open(config, "w", encoding="utf-8") as file:
            self.config.write(file)
        if log.exists():
            log.unlink()
        super(MainWindow, self).closeEvent(event)

    def stop_timer(self, name):
        if name in self.timer_pool:
            timer = self.timer_pool[name]
            if isinstance(timer, QTimer):
                if timer.isActive():
                    timer.stop()
            elif isinstance(timer, dict):
                for item in timer.values():
                    if item.isActive():
                        item.stop()
            elif isinstance(timer, tuple):
                for item in timer:
                    if isinstance(item, QTimer) and item.isActive():
                        item.stop()

    def url(self):
        return f"{server_dict.get(self.server, "").replace("$node", node_dict.get(self.node, ""))}/Client.swf"

    def change_show_send(self, state):
        global is_show_send
        is_show_send = state > 0

    def change_show_recv(self, state):
        global is_show_recv
        is_show_recv = state > 0

    def change_set_socket(self, state):
        self.socketLineEdit.setEnabled(state > 0)
        if state > 0 and len(self.socketLineEdit.text()) == 0 and login_socket_num != 0:
            self.socketLineEdit.setText(str(login_socket_num))

    def send(self):
        # 使用后台发送，防止添加自定义延迟后阻塞界面
        send_lines_back_ex(self.textEdit.toPlainText().split('\n'), Interval.FAST)

    def send_clear(self):
        self.textEdit.clear()

    def change_row(self, row, column):
        data = self.tableWidget.item(row, column if column < 2 else 4)
        if data is not None:
            self.textEdit.setPlainText(data.toolTip() if column == 0 else data.text())

    def change_server(self, checked):
        if checked:
            last_server = self.server
            self.server = self.sender().text()
            if self.server == "官服":
                self.node = "主节点"
            elif last_server == "官服":
                self.node = "国内节点"
            self.refresh()
        else:
            self.sender().setChecked(True)

    def change_node(self, checked):
        if checked:
            self.node = self.sender().text()
            self.refresh()
        else:
            self.sender().setChecked(True)

    def check_menu(self):
        for action in self.serverMenu.actions():
            action.setChecked(action.text() == self.server)
        for action in self.nodeMenu.actions():
            action.setChecked(action.text() == self.node)
            action.setEnabled(action.text() == "主节点" or self.server != "官服")

    def refresh(self):
        self.check_menu()
        self.axWidget.dynamicCall("LoadMovie(long, string)", 0, server_dict["官服"])
        self.axWidget.dynamicCall("LoadMovie(long, string)", 0, self.url())
        self.axWidget.dynamicCall("SetScaleMode(int)", 0)
        self.enable_all_buttons(False)

    def add_data(self, data_type, socket_num, cmd_id, cmd_analyse, data):
        self.tableWidget.blockSignals(True)
        global packet_index
        if packet_index >= 10000:  # 已有数据10000条，清空
            self.clear_table()
        if len(str(packet_index + 1)) > self.row_len:
            self.row_len += 1
            self.column_width -= 7
            self.tableWidget.setColumnWidth(4, self.column_width)
        if packet_index >= self.tableWidget.rowCount():
            self.tableWidget.setRowCount(packet_index + 1)
        self.tableWidget.setItem(packet_index, 0, QTableWidgetItem(data_type))
        self.tableWidget.setItem(packet_index, 1, QTableWidgetItem(str(socket_num)))
        self.tableWidget.setItem(packet_index, 2, QTableWidgetItem(str(cmd_id)))
        self.tableWidget.setItem(packet_index, 3, QTableWidgetItem(cmd_analyse))
        self.tableWidget.setItem(packet_index, 4, QTableWidgetItem(data))
        if socket_num == login_socket_num:
            tip = f"IP: {login_ip} Port: {login_port}"
        else:
            ip, port = get_ip_port(socket_num)
            tip = f"IP: {ip} Port: {port}"
        self.tableWidget.item(packet_index, 0).setToolTip(tip)
        self.tableWidget.item(packet_index, 1).setToolTip(str(socket_num))
        self.tableWidget.item(packet_index, 2).setToolTip(str(cmd_id))
        self.tableWidget.item(packet_index, 3).setToolTip(cmd_analyse)
        self.tableWidget.item(packet_index, 4).setToolTip(data)
        if packet_index >= 10:  # 已有10条数据后拖动到底部
            self.tableWidget.scrollToBottom()
        packet_index += 1  # 下一条要插入数据的索引
        self.tableWidget.blockSignals(False)

    def clear_table(self):
        self.tableWidget.blockSignals(True)
        global packet_index
        packet_index = 0
        self.row_len = 2  # 行数位数
        self.column_width = 224  # 封包数据列宽
        self.tableWidget.clearContents()  # 清空内容
        self.tableWidget.setRowCount(11)
        self.tableWidget.setColumnCount(5)
        self.tableWidget.setColumnWidth(0, 45)
        self.tableWidget.setColumnWidth(1, 45)
        self.tableWidget.setColumnWidth(2, 45)
        self.tableWidget.setColumnWidth(3, 100)
        self.tableWidget.setColumnWidth(4, self.column_width)
        self.tableWidget.setCurrentCell(-1, -1)  # 清除选中，避免恢复信号后触发 currentCellChanged
        self.tableWidget.scrollToTop()  # 拖动到顶部
        self.tableWidget.blockSignals(False)

    def enable_lamu_button(self, enable):
        self.lamuGrowButton.setEnabled(enable)

    def enable_mmg_button(self, enable):
        self.mmgPVBButton.setEnabled(enable)
        self.mmgPVEButton.setEnabled(enable)
        self.mmgPVPButton.setEnabled(enable)
        self.mmgLevelBox.setEnabled(enable)
        self.mmgBossBox.setEnabled(enable)

    def enable_ysqs_button(self, enable):
        self.ysqsFightButton.setEnabled(enable)
        self.ysqsUpgradeButton.setEnabled(enable)
        self.ysqsAdvanceButton.setEnabled(enable)
        self.ysqsLevelBox.setEnabled(enable)
        self.ysqsCardBox.setEnabled(enable)

    def enable_mlcs_button(self, enable):
        self.mlcsFightButton.setEnabled(enable)
        self.mlcsSellButton.setEnabled(enable)

    def enable_ct_button(self, enable):
        self.ctSellButton.setEnabled(enable)
        if not self.is_harvest_running():
            self.ctHarvestButton.setEnabled(enable)
            self.ctDishBox.setEnabled(enable)
        elif not enable:
            self.ctDishBox.setEnabled(enable)

    def enable_ddd_button(self, enable):
        self.dddGetButton.setEnabled(enable)

    def enable_med_button(self, enable):
        self.medGetButton.setEnabled(enable)

    def enable_bh_button(self, enable):
        self.bhOpenButton.setEnabled(enable)

    def enable_all_buttons(self, enable):
        self.enable_lamu_button(enable)
        self.enable_mmg_button(enable)
        self.enable_ysqs_button(enable)
        self.enable_mlcs_button(enable)
        self.enable_ddd_button(enable)
        self.enable_med_button(enable)
        self.enable_bh_button(enable)
        if not enable:  # 刷新游戏后的操作
            self.stop_timer("摩摩怪")
            self.stop_timer("拉姆")
            self.enable_ct_button(enable)

    # 简单的多次任务
    def start_task(self, name, func, interval, button=None, start_func=None, stop_text="停止"):
        if name in self.timer_pool:
            timer, text, button = self.timer_pool[name]
            if timer.isActive():  # 停止
                button.setText(text)
                if interval <= Interval.FAST:
                    self.recvCheckBox.setChecked(True)
                timer.stop()
                return
        else:  # 创建
            timer = RunTimer(func, interval)
            self.timer_pool[name] = timer, button.text(), button
        # 启动
        if start_func is not None:
            start_func()
        if button.isEnabled():
            button.setText(stop_text)
        if interval <= Interval.FAST:
            self.recvCheckBox.setChecked(False)
        timer.start()

    def stop_task(self, name):
        if name in self.timer_pool:
            timer, text, button = self.timer_pool[name]
            if timer.isActive():  # 停止
                button.setText(text)
                timer.stop()

    def check_update(self):
        if not self.update_thread.isRunning():
            self.update_thread.start()

    def update_result(self, res, msg, version):
        match res:
            case 1:
                info(self, "提示", msg)
            case 2:
                if info(self, "提示", msg, Button.OK_CANCEL) == Button.OK:
                    QDesktopServices.openUrl(QUrl(f"https://github.com/lingcraft/mole/releases/download/v{version}/mole.exe"))
            case 3:
                if info(self, "提示", msg, Button.OK_CANCEL) == Button.OK:
                    QDesktopServices.openUrl(QUrl(f"https://github.com/lingcraft/mole/releases"))

    def open_github(self):
        QDesktopServices.openUrl(QUrl("https://github.com/lingcraft/mole"))

    # =======================================上面是界面功能，下面是游戏功能============================================

    def lamu_get_info(self):
        send_lines([
            f"0000000000000000D40000000000000000{get_hex(user_id)}{get_hex(lamu_id)}00",  # 获取拉姆信息
            f"0000000000000000CC0000000000000000{get_hex(user_id)}"  # 获取超拉信息
        ])

    def lamu_gift(self):
        send_lines([
            "00000000000000277500000000000000003B9ACA16",  # 超拉每日礼包
            f"0000000000000027760000000000000000{get_hex(super_lamu_level + 22)}"
        ])

    def lamu_learn(self):
        send_lines([
            f"0000000000000004670000000000000000{get_hex(lamu_id)}00000001{get_hex(lamu_last_skill_level)}",  # 学习火系技能
            f"0000000000000004670000000000000000{get_hex(lamu_id)}00000002{get_hex(lamu_last_skill_level)}",  # 学习水系技能
            f"0000000000000004670000000000000000{get_hex(lamu_id)}00000003{get_hex(lamu_last_skill_level)}"  # 学习木系技能
        ])

    def lamu_feed(self):
        send_lines([
            "0000000000000001F500000000000000000002BF2600000002",  # 买十字架
            f"0000000000000001F90000000000000000{get_hex(user_id)}{get_hex(lamu_id)}0002BF26",  # 喂十字架
            f"0000000000000001F90000000000000000{get_hex(user_id)}{get_hex(lamu_id)}0002BF26"  # 喂十字架
        ])

    def lamu_get_vars(self):
        if lamu_times == 0:
            return is_last_skill_success, lamu_last_skill_level, lamu_last_item_level, lamu_last_type_index, lamu_last_item_index
        else:
            return is_max_skill_success, lamu_max_skill_level, lamu_max_item_level, lamu_max_type_index, lamu_max_item_index

    def lamu_set_vars(self, *args):
        global lamu_last_item_level, lamu_last_type_index, lamu_last_item_index, lamu_max_item_level, lamu_max_type_index, lamu_max_item_index
        if lamu_times == 0:
            lamu_last_item_level, lamu_last_type_index, lamu_last_item_index = args
        else:
            lamu_max_item_level, lamu_max_type_index, lamu_max_item_index = args

    def lamu_get_skill_info(self, skill_level, item_level, type_index):
        skill_type = lamu_skill_types[type_index]
        return skill_type, get_skill_id(skill_level, skill_type), list(
            lamu_dict[item_level][skill_type].items())

    def lamu_collect_result(self):
        is_skill_success, skill_level, item_level, type_index, item_index = self.lamu_get_vars()
        skill_type, skill_id, items = self.lamu_get_skill_info(skill_level, item_level, type_index)
        item_name = items[item_index][0]
        if is_skill_success:
            if item_name in lamu_pick_result_dict:
                lamu_pick_result_dict[item_name] += 1
            else:
                lamu_pick_result_dict[item_name] = 1

    def lamu_show_result(self):
        if len(lamu_pick_result_dict) > 0:
            text = ""
            for key, value in lamu_pick_result_dict.items():
                text += f"{key}：{value}，"
            text = text[:-1]
            info(self, "一键获取拉姆变身值结束", f"拉姆（{lamu_name}）成功采集以下物品：\n{text}")
        else:
            info(self, "一键获取拉姆变身值结束", f"拉姆（{lamu_name}）今天可采集物品已达上限")

    def lamu_start(self):
        global lamu_times, is_max_skill_success, is_last_skill_success, lamu_max_skill_level, lamu_last_skill_level, \
            lamu_max_item_level, lamu_last_item_level, lamu_max_type_index, lamu_last_type_index, lamu_max_item_index, \
            lamu_last_item_index, limit_data
        self.enable_lamu_button(False)
        lamu_max_skill_level = get_max_skill_level(lamu_level)
        lamu_last_skill_level = get_last_skill_level(lamu_level)
        self.lamu_gift()
        self.lamu_learn()
        self.lamu_feed()
        lamu_times = 0
        is_max_skill_success, is_last_skill_success = True, True
        lamu_max_item_level, lamu_last_item_level = lamu_max_skill_level, lamu_last_skill_level
        lamu_max_type_index, lamu_last_type_index = 0, 0
        lamu_max_item_index, lamu_last_item_index = 0, 0
        lamu_pick_result_dict.clear()
        now = datetime.now()
        refresh_time = datetime(now.year, now.month, now.day, 3)
        limit_data = lamu_limit_item_dict.setdefault(
            user_id, {"数据": {"火": {}, "水": {}, "木": {}}, "时间": now}
        )
        if limit_data["时间"] < refresh_time <= now:
            limit_data["数据"].clear()
            limit_data["时间"] = now

    def lamu_get_item(self, skill_level, item_level, type_index, item_index):
        skill_type, skill_id, items = self.lamu_get_skill_info(skill_level, item_level, type_index)
        item_id = items[item_index][1]
        while item_id in limit_data["数据"][skill_type]:
            type_index += 1
            if type_index >= len(lamu_skill_types):  # 技能类型都用过了
                item_index += 1
                type_index = 0
                if item_index >= len(items):  # 当前等级物品都拿过了
                    item_level -= 1
                    if item_level >= 1:
                        item_index = 0
                        type_index = 0
                    else:  # 全部等级物品都拿过了
                        return None, None, None
            self.lamu_set_vars(item_level, type_index, item_index)
            skill_type, skill_id, items = self.lamu_get_skill_info(skill_level, item_level, type_index)
            item_id = items[item_index][1]
        return item_id, skill_id, skill_type

    def lamu_run(self):
        is_skill_success, skill_level, item_level, type_index, item_index = self.lamu_get_vars()
        item_id, skill_id, skill_type = self.lamu_get_item(skill_level, item_level, type_index, item_index)
        if lamu_times < 11 or item_level == 6:  # 最高级物品全部拿到上限
            if not is_skill_success:  # 上次技能拿取失败
                limit_data["数据"][skill_type][item_id] = item_id
                limit_data["时间"] = datetime.now()
                item_id, skill_id, skill_type = self.lamu_get_item(skill_level, item_level, type_index, item_index)
            if item_id is None:
                self.lamu_stop()
                return
            send_lines([
                f"0000000000000004BC0000000000000000{get_hex(lamu_id)}{get_hex(skill_id)}",  # 变身
                f"0000000000000004B90000000000000000{get_hex(lamu_id)}{get_hex(skill_id)}{get_hex(item_id)}"  # 拿取物品
            ])
        else:
            self.lamu_stop()

    def lamu_stop(self):
        self.lamu_feed()
        self.enable_lamu_button(True)
        self.lamu_show_result()
        self.stop_timer("拉姆")

    def mmg_start(self, fight_type=0):
        def start():  # 开始执行
            global mmg_energy, mmg_type
            if "疯" in self.mmgLevelBox.currentText():
                mmg_energy /= 2
            send_lines([
                "0000000000000001910000000000000000000000E40000000000000000000000000000000000000000"  # 获取地图信息
            ])
            self.timer_pool["摩摩怪"].start()

        if fight_type == 0:  # 查询好友完毕
            start()
        else:
            global mmg_type, mmg_times
            self.enable_mmg_button(False)
            mmg_type, mmg_times = fight_type, 0
            send_lines(
                [
                    "0000000000000020200000000000000000"  # 查询Boss已挑战次数
                ] * (fight_type == 1)
                +
                [
                    f"0000000000000020080000000000000000{get_hex(user_id)}",  # 获取基础信息
                    "0000000000000020090000000000000000",  # 获取背包信息
                    "0000000000000001960000000000000000000000E400000000"  # 进入地图场景
                ]
            )
            if fight_type < 3:
                run_later(start)
            else:
                friends = self.friend_dict[user_id]
                ids = "".join([get_hex(friend) for friend in friends])
                send_lines([
                    f"0000000000000020220000000000000000{get_hex(user_id)}",  # 获取师徒信息
                    f"0000000000000020100000000000000000{get_hex(len(friends))}{ids}",  # 获取好友信息
                ])
                run_later(self.mmg_query_friends)

    def mmg_run(self):
        match mmg_type:
            case 1:  # 挑战Boss
                if self.mmgBossBox.currentText() == "独角萨摩":
                    match mmg_times:
                        case n if n < mmg_card:
                            level_id = get_level_info("独角萨摩", mmg_level)
                            self.mmg_fight(level_id, 1)
                        case _:
                            self.mmg_stop()
                else:
                    match mmg_times:
                        case n if n < mmg_boss_index1:
                            level_id = get_level_info("飞沙蝎")
                            self.mmg_fight(level_id, 1)
                        case n if mmg_boss_index1 <= n < mmg_boss_index2:
                            level_id = get_level_info(self.mmgBossBox.currentText())
                            self.mmg_fight(level_id, 1)
                        case n if mmg_boss_index2 <= n < mmg_boss_index3:
                            level_id = get_level_info("怪味糖蓝龙", mmg_level)
                            self.mmg_fight(level_id, 1)
                        case _:
                            self.mmg_stop()
            case 2:  # 挑战副本
                match mmg_times:
                    case n if n < mmg_energy // 10:
                        level_id = get_level_info(self.mmgLevelBox.currentText())
                        self.mmg_fight(level_id, 1)
                    case _:
                        self.mmg_stop()
            case 3:  # 挑战好友
                match mmg_times:
                    case n if n < mmg_vigour // 10 and len(mmg_fight_friends) > 0:
                        level_id, fight_type, _ = mmg_fight_friends.popleft()
                        self.mmg_fight(level_id, fight_type)
                    case _:
                        self.mmg_wish()
                        self.mmg_stop()

    def mmg_fight(self, level_id, fight_type):
        send_lines([
            "00000000000000019300000000000000000000000100000000"  # 进入游戏
        ])

        run_later(lambda: send_lines_to_server_back(
            ("123.206.131.63", 3001),
            [
                f"0000008101000075310000000000000000{mmg_game_id}",  # 进入游戏
                f"000000212000007724000000000000000000000004{get_hex(fight_type)}{get_hex(level_id)}00000000",  # 开始挑战
                "000000152000007724000000000000000000000040",  # 开始战斗
                "000000152000007724000000000000000000000080"  # 快速战斗
            ],
            [3, 1, 1, 2]
        ), 400)

    def mmg_get_reward(self, is_success):
        if is_success:
            run_later(lambda: send_lines([
                "0000000000000020140000000000000000",  # 校验能否翻牌
                "000000000000002015000000000000000000000000",  # 翻牌
                "000000000000000194000000000000000000"  # 离开游戏
            ]))

    def mmg_wish(self):
        send_lines_back([
            *[f"0000000000000020170000000000000000{get_hex(friend_id)}" for friend_id in mmg_friends_state_dict[1]],  # 祝福
            *[f"0000000000000020190000000000000000{get_hex(friend_id)}00000002" for friend_id in mmg_friends_state_dict[2]],  # 呼唤
            *[f"0000000000000020190000000000000000{get_hex(friend_id)}00000003" for friend_id in mmg_friends_state_dict[3]],  # 抱抱
            *[f"0000000000000020190000000000000000{get_hex(friend_id)}00000004" for friend_id in mmg_friends_state_dict[4]]  # 解救
        ])

    def mmg_query_friends(self):
        global mmg_query_page_max, mmg_query_page
        mmg_fight_friends.clear()
        mmg_friends_state_dict[1].clear()
        mmg_friends_state_dict[2].clear()
        mmg_friends_state_dict[3].clear()
        mmg_friends_state_dict[4].clear()
        mmg_query_page = 0
        max_size = mmg_query_size_max
        max_page = mmg_friends_num // max_size
        last_size = mmg_friends_num % max_size
        mmg_query_page_max = max_page + (last_size > 0)
        lines = []
        for page in range(max_page):
            friends = mmg_friends[page * max_size:(page + 1) * max_size]
            ids = "".join([get_hex(friend[0]) for friend in friends])
            lines.append(f"00000000000000201A0000000000000000{get_hex(max_size)}{ids}")
        if last_size > 0:
            friends = mmg_friends[-last_size:]
            ids = "".join([get_hex(friend[0]) for friend in friends])
            lines.append(f"00000000000000201A0000000000000000{get_hex(last_size)}{ids}")
        send_lines(lines)

    def mmg_stop(self):
        self.enable_mmg_button(True)
        self.stop_timer("摩摩怪")

    def ysqs_start(self):
        send_lines([
            "00000000000000231A0000000000000000",  # 领悟技能
            "00000000000000231E000000000000000000000000"  # 获取元素骑士信息
        ])
        run_later_expect(self.ysqs_run, {0x231E: 1})

    def ysqs_run(self):
        if (can_fight_wjsy and 10 <= datetime.now().hour < 13) or not (can_fight_wjsy and can_fight_ssmy):
            self.ysqs_fight((6, 0), (6, 0))
        else:
            send_lines([
                f"00000000000000231D0000000000000000{get_hex(get_level_info("无尽深渊")["ID"])}",
                f"00000000000000231D0000000000000000{get_hex(get_level_info("莎士摩亚")["ID"])}"
            ])
            run_later_expect(self.ysqs_fight, {0x231D: {"num": 2, "need_data": True, "offsets": (0, 28)}})

    def ysqs_fight(self, wjsy_info, ssmy_info):
        hour = datetime.now().hour
        level_info = get_level_info(self.ysqsLevelBox.currentText())
        # 无尽深渊、莎士摩亚挑战次数计算
        # state：0：可以挑战，2：挑战次数达到每日上限，3：体力不足，6：不在挑战时间内
        wjsy_state, wjsy_fighted_times = wjsy_info
        wjsy_fight_times = (70 - wjsy_fighted_times) if wjsy_state == 0 and can_fight_wjsy else 0
        ssmy_state, ssmy_fighted_times = ssmy_info
        ssmy_fight_times = (40 - ssmy_fighted_times) if ssmy_state == 0 and can_fight_ssmy else 0
        if ssmy_fight_times == 0:
            ssmy_fight_times_round1, ssmy_fight_times_round2 = 0, 0
        else:
            ssmy_fight_times_round1 = clamp((ysqs_energy - wjsy_fight_times) // 5, 0, 40)  # 第1管体力莎士摩亚挑战次数
            ssmy_fight_times_round2 = ssmy_fight_times - ssmy_fight_times_round1 + ssmy_fight_times // 4  # 第2管体力莎士摩亚挑战次数，加1/4容错包
        # 选定关卡挑战次数计算
        remain_times = ysqs_energy // level_info["体力消耗"]  # 当前体力可挑战次数
        if can_fight_wjsy and 13 <= hour < 21 and wjsy_fight_times > 0:
            fight_times = 170 // level_info["体力消耗"]  # 打完无尽深渊、莎士摩亚后的选定关卡挑战次数
        elif can_fight_ssmy and 10 <= hour < 21 and ssmy_fight_times > 0:
            fight_times = 20 // level_info["体力消耗"]  # 打完莎士摩亚后的选定关卡挑战次数
        elif (can_fight_wjsy and hour < 13) or (can_fight_ssmy and hour < 10):
            fight_times = 0  # 特殊关卡时段未到
        elif not (can_fight_wjsy or can_fight_ssmy or is_equip_card):
            fight_times = remain_times * 2  # 战力未达标且无卡牌挑战
        else:
            fight_times = remain_times
        # 挑战判断
        is_fight_wjsy = ysqs_energy > 0 and 13 <= hour < 21 and can_fight_wjsy and wjsy_fight_times > 0  # 是否挑战无尽深渊
        is_fight_ssmy = ysqs_energy > 0 and 10 <= hour < 21 and can_fight_ssmy and ssmy_fight_times > 0 and (is_fight_wjsy if can_fight_wjsy else True)  # 是否挑战莎士摩亚
        is_reward = is_fight_wjsy or is_fight_ssmy or fight_times >= 20  # 是否领取每日任务奖励
        is_fight = is_fight_wjsy or is_fight_ssmy or fight_times > 0  # 是否挑战
        send_lines_back(
            [
                f"00000000000000231D0000000000000000{get_hex(get_level_info("无尽深渊")["ID"])}",
            ] * wjsy_fight_times * is_fight_wjsy
            +
            [
                f"00000000000000231D0000000000000000{get_hex(get_level_info("莎士摩亚")["ID"])}",
            ] * ssmy_fight_times_round1 * is_fight_ssmy
            +
            [
                "000000000000002319000000000000000000000000"  # 恢复体力
            ] * is_fight_wjsy
            +
            [
                f"00000000000000231D0000000000000000{get_hex(get_level_info("莎士摩亚")["ID"])}",
            ] * ssmy_fight_times_round2 * is_fight_ssmy
            +
            [
                f"00000000000000{"231D" if is_equip_card else "2321"}0000000000000000{get_hex(level_info["ID"])}",  # 未装备卡牌时探索关卡
            ] * fight_times
            +
            [
                "000000000000002331000000000000000000000000",  # 每日任务奖励1
                "000000000000002331000000000000000000000001"  # 每日任务奖励2
            ] * is_reward
            +
            [
                "00000000000000231E000000000000000000000000"  # 获取元素骑士信息
            ] * is_fight,
            Interval.SLOW
        )

    def ysqs_upgrade_start(self):
        send_lines([
            "00000000000000231E000000000000000000000000"  # 获取元素骑士信息
        ])
        run_later(self.ysqs_upgrade_run)

    def ysqs_upgrade_run(self):
        card_data = ysqs_cards_dict[self.ysqsCardBox.currentData()]
        ysqs_material_cards_dict.pop(card_data["ID"], None)
        required_exp = get_card_max_exp(card_data["星级"]) - card_data["经验"]
        # 计算需要的材料卡牌
        material_ids = []
        for card_id, card_exp in ysqs_material_cards_dict.items():
            material_ids.append(card_id)
            required_exp -= card_exp
            if required_exp <= 0:
                break
        # 分包处理，每个包最多30张材料
        max_size = 30
        material_num = len(material_ids)
        max_page = material_num // max_size
        last_size = material_num % max_size
        lines = []
        for page in range(max_page):
            cards = material_ids[page * max_size: (page + 1) * max_size]
            ids = "".join([get_hex(card_id) for card_id in cards])
            lines.append(f"00000000000000231B0000000000000000{get_hex(card_data["ID"])}{get_hex(max_size)}{ids}")
        if last_size > 0:
            cards = material_ids[-last_size:]
            ids = "".join([get_hex(card_id) for card_id in cards])
            lines.append(f"00000000000000231B0000000000000000{get_hex(card_data["ID"])}{get_hex(last_size)}{ids}")
        if lines:
            lines.append("00000000000000231E000000000000000000000000")  # 获取元素骑士信息
        send_lines(lines)

    def ysqs_advance_start(self):
        self.advance_dialog.set_card_id(self.ysqsCardBox.currentData())
        self.advance_dialog.exec()

    def mlcs_start(self):
        send_lines([
            "000000000000002B20000000000000000000000001",  # 膜拜等级排行
            "000000000000002B20000000000000000000000002",  # 膜拜战力排行
            "000000000000002B20000000000000000000000003",  # 膜拜摩尔豆排行
            "000000000000002B20000000000000000000000004",  # 膜拜金豆排行
            f"000000000000002EE40000000000000000{get_hex(user_id)}",  # 获取体力信息
            "000000000000002B010000000000000000000000050000271E0000271F000027200000272100009C42",  # 获取竞技场剩余挑战次数
            "000000000000002B0100000000000000000000000100002722"  # 获取经验之路剩余挑战次数
        ])
        run_later(self.mlcs_run)

    def mlcs_run(self):
        now = datetime.now()
        weekday = now.weekday()
        is_fight_arena = mlcs_arena_times > 0  # 是否挑战竞技场
        if weekday < 5:
            double_start = datetime(now.year, now.month, now.day, 19)
        else:
            double_start = datetime(now.year, now.month, now.day, 13)
        if now < double_start:
            recoverable_energy = int((double_start - now).total_seconds()) // 420  # 到双倍时间时可恢复体力
            double_start_energy = mlcs_energy + recoverable_energy  # 双倍时间开始时的体力
            need_times = (double_start_energy - 60) // 10  # 保留经验之路体力后的可挑战次数
            remain_times = mlcs_energy // 10  # 当前体力可挑战次数
            fight_times = min(need_times, remain_times)
            send_lines_back(
                [
                    f"000000000000002EE70000000000000000{get_hex(get_level_info("希望之光5"))}",
                    *["000000000000002EF000000000000000000000F000F000F000F000F000F000F0"] * 5,
                    "000000000000002EEA0000000000000000"
                ] * fight_times
                +
                [
                    "000000000000002B3D000000000000000000000000"  # 消除冷却
                ] * is_fight_arena
                +
                [
                    f"0000000000000001FF0000000000000000{get_hex(user_id)}001A65E8001A65E902",  # 获取声望数量
                    "000000000000002B3000000000000000000000000300000001000000002621D1EF",  # 挑战玩家
                    "000000000000002B3D000000000000000000000000",  # 消除冷却
                ] * mlcs_arena_times  # 竞技场
            )
        else:
            fight_times = (mlcs_energy - mlcs_exp_times * 20) // 10
            send_lines_back(
                [
                    f"000000000000002EE70000000000000000{get_hex(get_level_info("经验之路"))}",
                    *["000000000000002EF000000000000000000000F000F000F000F000F000F000F0"] * 5,
                    "000000000000002EEA0000000000000000"
                ] * mlcs_exp_times
                +
                [
                    f"000000000000002EE70000000000000000{get_hex(get_level_info("希望之光5"))}",
                    *["000000000000002EF000000000000000000000F000F000F000F000F000F000F0"] * 5,
                    "000000000000002EEA0000000000000000"
                ] * fight_times
                +
                [
                    "000000000000002B3D000000000000000000000000"  # 消除冷却
                ] * is_fight_arena
                +
                [
                    f"0000000000000001FF0000000000000000{get_hex(user_id)}001A65E8001A65E902",  # 获取声望数量
                    "000000000000002B3000000000000000000000000300000001000000002621D1EF",  # 挑战玩家
                    "000000000000002B3D000000000000000000000000",  # 消除冷却
                ] * mlcs_arena_times  # 竞技场
            )

    def mlcs_sell_start(self):
        send_lines([
            f"000000000000002EE40000000000000000{get_hex(user_id)}",  # 魔灵用户信息
            "000000000000002EF2000000000000000000000000"  # 魔灵背包信息
        ])
        run_later(self.mlcs_sell_run)

    def mlcs_sell_run(self):
        elves = [get_hex(elf_id) for elf_id in mlcs_elves_dict.keys()]
        elves_num = len(mlcs_elves_dict)
        max_page = elves_num // 10
        last_size = elves_num % 10
        lines = []
        for page in range(max_page):
            elf_ids = "".join(elves[page * 10:(page + 1) * 10])
            lines.append(f"000000000000002F020000000000000000{get_hex(10)}{elf_ids}")
        if last_size > 0:
            elf_ids = "".join(elves[-last_size:])
            lines.append(f"000000000000002F020000000000000000{get_hex(last_size)}{elf_ids}")
        send_lines_back(lines)

    def ct_sell_run(self):
        send_lines([
            f"0000000000000003FA0000000000000000000027100000000000147293{get_hex(ct_cooked_dishes_dict[self.ctDishBox.currentText()]["ID"])}00000065"
        ])

    def is_harvest_running(self):
        return self.ctHarvestButton.text() == "停止"

    def ct_harvest_start(self):
        if not self.is_harvest_running():  # 启动
            self.harvest_button_text = self.ctHarvestButton.text()
            self.ctHarvestButton.setText("停止")
            self.ctDishBox.setEnabled(False)
            send_lines([
                f"0000000000000001910000000000000000{get_hex(user_id)}0000001F00000000000000000000000000000000",  # 获取地图信息
                f"0000000000000003F60000000000000000{get_hex(user_id)}0000001F"  # 获取餐厅信息
            ])
            run_later(self.ct_harvest_run)
        else:  # 停止
            self.ctHarvestButton.setText(self.harvest_button_text)
            self.ctDishBox.setEnabled(True)
            self.stop_timer("餐厅")
            if self.client is not None and self.client.is_alive():
                self.client.close()
                self.client = None

    def ct_harvest_run(self):
        cooked_info = ct_cooked_dishes_dict[self.ctDishBox.currentText()]
        need_time = cooked_info["完成时间"]
        expire_time = cooked_info["烧糊时间"]
        interval = need_time + 30  # 增加30秒登录账号时间
        timer_dict = self.timer_pool["餐厅"]
        for dish_pos, dish_info in ct_cooking_dishes_dict.items():
            timer = timer_dict[dish_pos]
            if dish_info.get("灶台为空", False):
                dish_info["跳过一次收菜"] = True
                timer.set_data(lambda pos=dish_pos: self.ct_harvest_func(pos), interval * 1000, 0).start()
            else:
                cook_time = dish_info["时间"]
                if cook_time < need_time:  # 未成熟的菜
                    timer.set_data(lambda pos=dish_pos: self.ct_harvest_func(pos), interval * 1000, (need_time - cook_time) * 1000).start()
                elif need_time <= cook_time < expire_time:  # 已成熟的菜
                    timer.set_data(lambda pos=dish_pos: self.ct_harvest_func(pos), interval * 1000, 0).start()
                else:  # 已糊的菜
                    dish_info["已糊"] = True
                    timer.set_data(lambda pos=dish_pos: self.ct_harvest_func(pos), interval * 1000, 0).start()

    def ct_harvest_func(self, pos):
        password = self.account_dict[user_id]
        cooked_info = ct_cooked_dishes_dict[self.ctDishBox.currentText()]
        dish_info = ct_cooking_dishes_dict[pos]
        now = datetime.now()
        # 首次登录包
        init_lines = [
            f"0000000000000001910000000000000000{get_hex(user_id)}0000001F00000000000000000000000000000000",  # 获取地图信息
            f"0000000000000003F60000000000000000{get_hex(user_id)}0000001F"  # 获取餐厅信息
        ]
        lines = []
        if not dish_info.pop("跳过一次收菜", False):
            if dish_info.pop("已糊", False):
                lines.append(f"0000000000000003FB0000000000000000{get_hex(dish_info["类型"])}{get_hex(dish_info["ID"])}{get_hex(pos)}")  # 处理糊菜
            else:
                lines.append(f"0000000000000003FD0000000000000000{get_hex(cooked_info["类型"])}{get_hex(dish_info["ID"])}{get_hex(pos)}{get_hex(cooked_info["位置"])}")  # 收菜
        if now.hour >= 6:
            lines.append(f"0000000000000003F90000000000000000{get_hex(dish_info["类型"])}{get_hex(pos)}")  # 做菜
        else:
            dish_info["跳过一次收菜"] = True
            cook_start = datetime(now.year, now.month, now.day, 6)
            self.timer_pool["餐厅"][pos].restart((cook_start - now).total_seconds() * 1000)
        send_lines_by_client((user_id, password), init_lines, lines)

    def ct_cook_after(self, dish_id, dish_type, step, is_refresh=False):
        # 自动完成做菜后续步骤
        lines = [f"0000000000000003FC0000000000000000{get_hex(dish_type)}{get_hex(dish_id)}"]
        if is_refresh:  # 刷新餐厅信息时触发的
            run_later(lambda: send_lines(lines))  # 等待默认时间，否则显示有问题
        else:  # 做菜时触发的
            if step == 1:
                run_later(lambda: send_lines(lines), 2000)  # 首次做菜时，等待2秒动画，否则显示有问题
            else:
                send_lines(lines)  # 后续设置菜状态时，不用等待动画

    def ddd_run(self):
        send_lines([
            "0000000000000001F500000000000000000002737200000001",
            "0000000000000004DB0000000000000000000000790000000100000001",
            *["0000000000000017850000000000000000000000010002E96400000001"] * 5
        ])

    def med_run(self):
        send_lines_back([
            f"000000000000002B1A0000000000000000{get_hex(num)}" for num in range(1, 11)
        ], Interval.FAST)

    def bh_start(self):
        global is_show_msg
        is_show_msg = False

    def bh_run(self):
        send_lines_back([
            "0000000000000022F9000000000000000000003E95"
        ])


class AdvanceDialog(QDialog, Ui_AdvanceDialog):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        for key in card_advance_dict.keys():
            item = QListWidgetItem(key)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.listWidget.addItem(item)
        self.lineEdit.textChanged.connect(self.on_filter)
        self.pushButton.clicked.connect(self.advance)

    def on_filter(self, text: str):
        for i in range(self.listWidget.count()):
            item = self.listWidget.item(i)
            item_text = item.text()
            # 部分匹配
            if text in item_text:
                item.setHidden(False)
                continue
            # 全拼匹配
            full_pinyin = "".join(lazy_pinyin(item_text, style=Style.NORMAL))
            if text in full_pinyin:
                item.setHidden(False)
                continue
            # 首字母匹配
            first_letters = "".join(lazy_pinyin(item_text, style=Style.FIRST_LETTER))
            if text in first_letters:
                item.setHidden(False)
                continue
            item.setHidden(True)

    def set_card_id(self, card_id: int):
        self.card_id = card_id
        self.card_name = ysqs_cards_dict[card_id]["名称"]
        self.lineEdit.clear()

    def advance(self):
        card_name = self.listWidget.currentItem().text()
        self.target_card_name = f"{card_name} Lv.1"
        card_info = get_card_info(get_card_type(card_name))
        need_card_types = card_info["进阶材料"]
        card_type = card_info["上一星级"]
        owned_cards_dict = deepcopy(ysqs_max_level_cards_dict)
        unequip_cards = []
        consume_cards = []
        can_advance = True
        for need_card_type in need_card_types:
            if need_card_type in owned_cards_dict:
                owned_cards = owned_cards_dict[need_card_type]
                card_data = owned_cards.popleft()
                if card_data["已装备"]:
                    unequip_cards.append(card_data["ID"])
                consume_cards.append(card_data["名称"])
                if not owned_cards:
                    owned_cards_dict.pop(need_card_type)
            else:
                can_advance = False
                break
        if can_advance:
            consume_count = Counter(consume_cards)
            consume_text = "\n".join(
                f"{card_name} 共计 {consume_count[card_name]} 张"
                for card_name in consume_count
            )
            if info(self, "提示", f"{self.card_name} 进阶到 {self.target_card_name} 将消耗：\n{consume_text}", Button.OK_CANCEL) == Button.OK:
                self.accept()
                send_lines([
                    *[f"00000000000000231F000000000000000000000000{get_hex(card_id)}" for card_id in unequip_cards],  # 卸载卡牌
                    f"00000000000000231C0000000000000000{get_hex(self.card_id)}{get_hex(card_type)}",  # 进阶卡牌
                    "00000000000000231E000000000000000000000000"  # 获取元素骑士信息
                ])
                info(window, "成功", f"{self.card_name} 进阶到 {self.target_card_name} 成功")
        else:
            need_count = Counter(need_card_types)
            owned_count = {card_type: len(ysqs_max_level_cards_dict.get(card_type, deque())) for card_type in need_count}
            need_text = "\n".join(
                f"{get_card_info(card_type)["名称"]} Lv.{get_card_max_level(get_card_info(card_type)["星级"])} 需要 {need_count[card_type]} 张，拥有 {owned_count[card_type]} 张"
                for card_type in need_count
            )
            info(self, "提示", f"{self.card_name} 进阶到 {self.target_card_name} 材料不足：\n{need_text}")


class SendThread(QThread):
    def set_data(self, lines: list, interval: int):
        self.lines = lines
        self.interval = interval

    def run(self):
        send_lines(self.lines, self.interval)


class SendExThread(SendThread):
    def run(self):
        if not window.socketCheckBox.isChecked():
            send_lines(self.lines, self.interval)
        else:
            send_lines_to_socket(self.lines, self.interval)


class SendToServerThread(QThread):
    result = Signal(bool)

    def set_data(self, address: tuple[str, int], lines: list, wait_recv_nums: list | None):
        self.address = address
        self.lines = lines
        self.wait_recv_nums = wait_recv_nums

    def run(self):
        is_success = send_lines_to_server(self.address, self.lines, self.wait_recv_nums)
        self.result.emit(is_success)


class UpdateThread(QThread):
    result = Signal(int, str, str)

    def run(self):
        version, description = "", ""
        for cdn_prefix in cdn_prefixs:
            url = f"{cdn_prefix}/{version_url}"
            try:
                res = get(url, timeout=(3, 5))
                res.raise_for_status()
            except:
                continue
            else:
                version, description = [loads(res.text)["project"][key] for key in ("version", "description")]
                break
        if version:
            if parse(window.version) >= parse(version):
                self.result.emit(1, f"当前版本 v{window.version} 已是最新！", version)
            else:
                self.result.emit(2, f"发现新版本：v{version}，更新信息：\n{description}", version)
        else:
            self.result.emit(3, "检查更新失败，是否前往下载页？", version)


class RunTimer(QTimer):
    signal = Signal()

    def __init__(self, func=None, interval: int = 1000, delay: int = 300):
        super().__init__()
        super().timeout.connect(self.on_timeout)
        self.set_data(func, interval, delay)

    def set_data(self, func, interval: int, delay: int):
        if func is not None:
            self.signal.connect(func)
        self.interval = interval
        self.delay = delay
        self.is_restart = False
        return self

    def start(self):
        self.is_first = True
        super().start(self.delay)

    def restart(self, delay):
        self.stop()
        self.delay = delay
        self.is_restart = True
        self.start()

    def on_timeout(self):
        self.is_restart = False
        self.signal.emit()
        if self.is_first and not self.is_restart:
            self.is_first = False
            super().setInterval(self.interval)


class Packet:
    def __init__(self, packet: str | bytearray | bytes | None = None, cmd_id: int | None = None, body: str | bytearray | bytes | None = None):
        self.length = self.serial_num = self.cmd_id = self.user_id = self.version = 0
        self.body = bytearray()
        if packet is not None:
            packet = self.to_bytearray(packet)
            if len(packet) >= 17:
                self.length, self.serial_num, self.cmd_id, self.user_id, self.version = unpack_from("!IBIII", packet)
                self.body = packet[17:]
        elif cmd_id is not None:
            self.cmd_id = cmd_id
            self.body = self.to_bytearray(body)

    def data(self):
        head = pack("!IBIII", self.length, self.serial_num, self.cmd_id, self.user_id, self.version)
        return head + self.body

    @staticmethod
    def to_bytearray(data: str | bytearray | bytes | None):
        if data is None:
            return bytearray()
        if isinstance(data, str):
            return bytearray.fromhex(data)
        return bytearray(data)


    @staticmethod
    def from_hex(packet: str):
        packet = bytearray.fromhex(packet)
        if packet.startswith(b"\x00\x00"):
            set_int(packet, user_id, 9)
        return packet

    def get_serial_num(self):
        global serial_num
        self.length, self.user_id, self.version = len(self.body) + 18, user_id, 0
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


def path(file: str):
    return str(base_dir / file)


def show_data(data_type: str, socket_num: int, packet: Packet):
    if is_window_init:
        if QThread.currentThread() is QApplication.instance().thread():
            window.add_data(data_type, socket_num, packet.cmd_id, analyse(packet.cmd_id), packet.data().hex().upper())
        else:
            window.signal.emit(data_type, socket_num, packet.cmd_id, analyse(packet.cmd_id), packet.data().hex().upper())


def info(parent, title: str, msg: str, buttons: int = Button.OK):
    return QMessageBox.information(parent, title, msg, QMessageBox.StandardButton(buttons))


def warn(parent, title: str, msg: str, buttons: int = Button.OK):
    return QMessageBox.warning(parent, title, msg, QMessageBox.StandardButton(buttons))


def run_later(func, delay: int = 350):
    QTimer.singleShot(delay, func)


def run_later_expect(func, expect: dict):
    # 等待到期望包之后运行
    # expect：{cmd_id：{"num"：数量, "offsets"：[offset, ...], "need_data"：是否获取数据}}
    # expect：{cmd_id：数量} 仅等待收齐指定数量的包
    pending_waits.append({
        "expect": expect,
        "counts": {cmd_id: 0 for cmd_id in expect},
        "data": {cmd_id: [] for cmd_id in expect},
        "func": func,
    })


def check_waiting_packets(packet):
    # 检查待匹配包
    for index in range(len(pending_waits) - 1, -1, -1):
        wait_info = pending_waits[index]
        expect = wait_info.get("expect", {})
        if packet.cmd_id in expect:
            counts = wait_info.get("counts", {})
            counts[packet.cmd_id] = counts.get(packet.cmd_id, 0) + 1
            spec = expect[packet.cmd_id]
            data = wait_info.get("data", {})
            if isinstance(spec, dict) and spec.get("need_data", False):
                offsets = spec.get("offsets", ())
                data[packet.cmd_id].append(
                    tuple(get_int(packet.body, offset) for offset in offsets) if offsets else get_int(packet.body)
                )
            # 检查是否所有 cmd_id 都集齐
            if all(counts.get(cid, 0) >= (spec["num"] if isinstance(spec, dict) else spec)
                   for cid, spec in expect.items()):
                func = wait_info["func"]
                if func:
                    if len(expect) == 1:
                        run_later(lambda args=data.get(next(iter(expect)), []): func(*args), 0)
                    else:
                        run_later(lambda args=data: func(args), 0)
                pending_waits.pop(index)


def get_lamu_level(value: int):
    return bisect_right(lamu_thresholds, value) + 1


def get_max_skill_level(level: int):
    return (level + 1) // 2


def get_last_skill_level(level: int):
    if level < 3:
        return 1
    else:
        return get_max_skill_level(level) - 1


def get_skill_id(skill_level: int, skill_type):
    match skill_type:
        case "火":
            return 3 * skill_level - 2
        case "水":
            return 3 * skill_level - 1
        case "木":
            return 3 * skill_level
        case _:
            return 1


def get_card_max_exp(star):
    # n星卡牌经验上限
    star = min(star, 6)
    return 120 * star ** 2 + 28 * star - 4


def get_card_max_level(star):
    # n星卡牌等级上限
    star = min(star, 6)
    return 10 * star


def get_card_provided_exp(star):
    # n星1级卡牌提供的经验值
    star = min(star, 6)
    return 5 * star - 2


def get_card_level(star, exp):
    # n星卡牌根据总经验计算等级
    star = min(star, 6)
    base = 2 * star + 5
    return floor((-base + sqrt(base ** 2 + 4 * exp)) / 2) + 1


def clamp(value, lower, upper):
    return min(max(int(value), lower), upper)


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


def get_name(buf: bytes, offset: int = 0):
    return unpack_from("16s", buf, offset)[0].rstrip(b"\x00").decode()


def get_password(pwd: str):
    return f"{pwd[8:16]}{pwd[0:8]}{pwd[24:32]}{pwd[16:24]}".encode().hex()


def send_lines(lines: list, interval: int = Interval.INSTANT):
    for data in lines:
        if len(data) < 17:
            if 0 < len(data) < 5:
                if (delay := int(data)) > 0:
                    sleep(delay / 1000)
            continue
        packet = Packet(data)
        with lock:
            packet.encrypt()
        send(login_socket_num, packet.data(), packet.length)
        packet.decrypt()
        if is_show_send:
            show_data(Show.SEND, login_socket_num, packet)
        if interval > 0:
            sleep(interval / 1000)


def send_lines_back(lines: list, interval: int = Interval.NORMAL):
    if not window.send_thread.isRunning():
        window.send_thread.set_data(lines, interval)
        window.send_thread.start()


def send_lines_back_ex(lines: list, interval: int = Interval.NORMAL):
    if not window.send_ex_thread.isRunning():
        window.send_ex_thread.set_data(lines, interval)
        window.send_ex_thread.start()


def send_lines_to_server(address: tuple[str, int], lines: list, wait_recv_nums: list | None = None):
    need_wait_recv = wait_recv_nums is not None
    with socket(AF_INET, SOCK_STREAM) as s:
        s.connect(address)
        for index, data in enumerate(lines):
            s.send(Packet.from_hex(data))
            if need_wait_recv:
                for _ in range(wait_recv_nums[index]):
                    packet = Packet(s.recv(17))
                    if packet.version != 0:
                        return False
                    try:
                        s.recv(packet.length - 17)
                    except:
                        return False
    return True


def send_lines_to_server_back(address: tuple[str, int], lines: list, wait_recv_nums: list | None = None):
    if not window.send_to_server_thread.isRunning():
        window.send_to_server_thread.set_data(address, lines, wait_recv_nums)
        window.send_to_server_thread.start()


def send_lines_to_socket(lines: list, interval: int = Interval.INSTANT):
    socket_num = window.socketLineEdit.text()
    if socket_num.isdigit():
        socket_num = int(socket_num)
        try:
            with fromfd(socket_num, AF_INET, SOCK_STREAM) as s:
                for data in lines:
                    if len(data) < 17:
                        continue
                    s.send(Packet.from_hex(data))
                    if interval > 0:
                        sleep(interval / 1000)
        except:
            pass


def send_lines_by_client(account: tuple[int, str], init_lines: list, lines: list):
    if window.client is None or not window.client.is_alive():
        window.client = Client(account, init_lines)
        window.client.put_data(lines)
        window.client.start()
        Thread(target=update_cooking_info, args=(window.client,), daemon=True).start()
    else:
        window.client.put_data(lines)


def update_cooking_info(client):
    while client.is_alive():
        try:
            dish_id, dish_pos = client.recv_queue.get(timeout=1)
        except:
            continue
        ct_cooking_dishes_dict[dish_pos]["ID"] = dish_id


def is_not_running(name: str):
    return not window.timer_pool[name].isActive()


def is_not_sending():
    return not window.send_thread.isRunning()


def get_ip_port(socket_num: int):
    try:
        with fromfd(socket_num, AF_INET, SOCK_STREAM) as s:
            ip, port = s.getpeername()
    except:
        return None, None
    else:
        return ip, port


def get_remote_info(socket_num: int):
    ip, port = get_ip_port(socket_num)
    if ip is None or ip != "123.206.131.236":
        return 0
    else:
        if port in (1965, 1865, 1201, 1239):
            return 2
        else:
            return 1


def send(socket_num, buf, length):
    return hook.Send(socket_num, ffi.from_buffer(buf), length)


@ffi.callback("int(ULONG64, PCHAR, INT)")
def process_send_packet(socket_num, buf, length):
    global login_socket_num, login_ip, login_port, user_id, can_get_lamu_info
    sock_type = get_remote_info(socket_num)
    raw_buf = ffi.buffer(buf, length)
    # 摩尔主服务器包
    if sock_type > 0 and raw_buf[:2] == b"\x00\x00" and len(raw_buf) > 17:
        packet = Packet(raw_buf)
        if packet.cmd_id == 201:  # 登录包
            login_socket_num = socket_num
            login_ip, login_port = get_ip_port(socket_num)
            user_id = packet.user_id
            can_get_lamu_info = True
            window.enable_all_buttons(True)
        if socket_num == login_socket_num:
            packet.decrypt()
            if is_show_send:
                show_data(Show.SEND, socket_num, packet)  # 界面显示send数据
            with lock:
                packet.encrypt()
        else:
            if is_show_send:
                show_data(Show.SEND, socket_num, packet)  # 界面显示send数据
        return send(socket_num, packet.data(), length)
    else:
        return send(socket_num, raw_buf, length)


@ffi.callback("void(ULONG64, PCHAR, INT)")
def process_recv_packet(socket_num, buf, length):
    global recv_buf, buf_index, can_get_lamu_info, lamu_id, lamu_name, lamu_value, lamu_level, lamu_times, is_last_skill_success, is_max_skill_success, \
        super_lamu_value, super_lamu_level, mmg_game_id, mmg_energy, mmg_vigour, mmg_level, mmg_card, mmg_times, mmg_friends, mmg_fight_friends, mmg_friends_num, \
        mmg_friends_dict, mmg_query_page, mmg_super_boss_times, mmg_lamu_boss_times, mmg_limit_boss_times, mmg_boss_index1, mmg_boss_index2, \
        mmg_boss_index3, mlcs_energy, mlcs_arena_times, mlcs_exp_times, ysqs_max_floor, ysqs_attack, ysqs_energy, is_show_msg, ysqs_cards_dict, \
        ysqs_material_cards_dict, can_fight_wjsy, can_fight_ssmy, is_equip_card
    raw_buf = ffi.buffer(buf, length)
    recv_buf.extend(raw_buf)
    if raw_buf[:2] == b"\x00\x00":  # 新包
        buf_index = 0
    # 摩尔主服务器包
    if socket_num == login_socket_num:
        while True:
            if len(recv_buf) >= 4:
                packet_len = get_int(recv_buf)
                if len(recv_buf) >= packet_len:
                    # 不是断包
                    cipher = recv_buf[:packet_len]
                    packet = Packet(cipher)
                    packet.decrypt()
                    if is_show_recv:
                        show_data(Show.RECV, socket_num, packet)  # 界面显示recv数据
                    if packet.version == 0:  # 正确包
                        match packet.cmd_id:
                            case 228 if can_get_lamu_info:  # 第1次进入游戏时获取拉姆ID
                                can_get_lamu_info = False
                                lamu_id = get_int(packet.body)
                                window.lamu_get_info()
                            case 212 if get_int(packet.body, 4) == 1:  # 获取拉姆信息
                                lamu_id = get_int(packet.body, 8)
                                lamu_name = get_name(packet.body, 24)
                                lamu_value = get_int(packet.body, 79)
                                lamu_level = get_lamu_level(lamu_value)
                            case 204 if get_int(packet.body) == user_id:  # 获取超拉信息
                                super_lamu_level = get_int(packet.body, 92)
                                super_lamu_value = get_int(packet.body, 100)
                            case 1209:  # 拉姆变身获得物品
                                if lamu_times == 0:
                                    is_last_skill_success = True
                                else:
                                    is_max_skill_success = True
                                window.lamu_collect_result()
                                lamu_times += 1
                            case 8200 if is_not_running("摩摩怪"):  # 获取摩摩怪能量和活力值
                                mmg_energy = get_int(packet.body, 40)
                                mmg_vigour = get_int(packet.body, 48)
                                mmg_level = get_int(packet.body, 12)
                            case 8201 if is_not_running("摩摩怪"):  # 获取摩摩挑战卡数量
                                mmg_card = 0
                                items_num = len(packet.body) // 4
                                size = 1 * 4
                                for page in range(items_num):
                                    item_id = get_int(packet.body, page * size)
                                    if item_id == 0x13DA23:
                                        mmg_card = get_int(packet.body, page * size + 4)
                                        break
                            case 8224 if is_not_running("摩摩怪"):  # 获取摩摩怪Boss已挑战次数
                                mmg_super_boss_times = 10 - get_int(packet.body)
                                mmg_lamu_boss_times = 10 - get_int(packet.body, 4)
                                if datetime.now().hour == 13:
                                    mmg_limit_boss_times = 10 - get_int(packet.body, 8)
                                else:
                                    mmg_limit_boss_times = 0
                                mmg_boss_index1 = mmg_limit_boss_times
                                mmg_boss_index2 = mmg_boss_index1 + mmg_super_boss_times
                                mmg_boss_index3 = mmg_boss_index2 + mmg_lamu_boss_times
                            case 10007:  # 获取摩摩怪游戏ID
                                mmg_game_id = packet.body[18:130].hex()
                            case 8212:  # 翻牌成功
                                mmg_times += 1
                            case 8226:  # 获取师徒ID
                                mmg_students_dict.clear()
                                students_num = get_int(packet.body, 40)
                                start = 44
                                size = 3 * 4
                                for page in range(students_num):
                                    student_id = get_int(packet.body, start + page * size)
                                    mmg_students_dict[student_id] = 100  # 小小
                                teacher_num = get_int(packet.body, 12)
                                if teacher_num > 0:
                                    teacher_id = get_int(packet.body, 16)
                                    mmg_students_dict[teacher_id] = 200  # 大大
                            case 8208:  # 获取好友ID
                                mmg_friends_dict.clear()
                                friends_num = get_int(packet.body)
                                start = 4
                                size = 3 * 4
                                for page in range(friends_num):
                                    friend_id = get_int(packet.body, start + page * size)
                                    friend_level = get_int(packet.body, start + page * size + 8)
                                    mmg_friends_dict[friend_id] = friend_level
                                for student_id, student_level in mmg_students_dict.items():
                                    mmg_friends_dict[student_id] = student_level
                                # 师徒放前面，后面好友等级从高到低
                                mmg_friends = sorted(mmg_friends_dict.items(), key=lambda item: item[1], reverse=True)
                                mmg_friends_num = len(mmg_friends)
                            case 8218 if is_not_running("摩摩怪") \
                                         and get_int(packet.body) in (mmg_query_size_max, mmg_friends_num % mmg_query_size_max):
                                # 查询好友能否对战
                                query_size = get_int(packet.body)
                                start = 4
                                size1 = 3 * 4
                                size2 = 1 * 4
                                for _ in range(query_size):
                                    friend_id = get_int(packet.body, start)
                                    fight_state = get_int(packet.body, start + 4)
                                    other_state_num = get_int(packet.body, start + 8)
                                    if fight_state == 0:  # 未挑战过的
                                        friend_level = mmg_friends_dict[friend_id]
                                        if friend_level == 200:
                                            fight_type = 5  # 大大
                                        elif friend_level == 100:
                                            fight_type = 4  # 小小
                                        else:
                                            fight_type = 0  # 好友
                                        mmg_fight_friends.append((friend_id, fight_type, friend_level))
                                    for page in range(other_state_num):
                                        state = get_int(packet.body, start + size1 + page * size2)
                                        mmg_friends_state_dict[state].append(friend_id)
                                    start += size1 + other_state_num * size2
                                mmg_query_page += 1
                                if mmg_query_page == mmg_query_page_max:  # 查询完毕
                                    # 重新排序，因为返回的好友挑战信息和查询时的好友ID顺序可能不一样
                                    mmg_fight_friends = deque(sorted(mmg_fight_friends, key=lambda item: item[2], reverse=True))
                                    window.mmg_start()
                            case 12004:  # 魔灵用户信息
                                mlcs_energy = get_int(packet.body, 13, 2)  # 剩余体力值
                                mlcs_fight_elves_dict.clear()
                                start = 24
                                size = 1 * 4
                                for page in range(15):  # 出战魔灵信息
                                    elf_id = get_int(packet.body, start + page * size)
                                    if elf_id != 0:
                                        mlcs_fight_elves_dict[elf_id] = elf_id
                            case 12018 if is_not_sending():  # 魔灵背包信息
                                mlcs_elves_dict.clear()
                                elves_num = get_int(packet.body)
                                start = 4
                                size = 7 * 4
                                for page in range(elves_num):
                                    elf_id = get_int(packet.body, start + page * size)
                                    elf_type = get_int(packet.body, start + page * size + 4)
                                    elf_level = get_int(packet.body, start + page * size + 9, 1)
                                    # 非出战魔灵、烈焰剑齿虎且等级为1的可删除
                                    if elf_id not in mlcs_fight_elves_dict and elf_type != 0x1A3F6A and elf_level == 1:
                                        mlcs_elves_dict[elf_id] = elf_id
                            case 11009:  # 魔灵竞技场信息
                                info_type = get_int(packet.body)
                                if info_type == 5:  # 竞技场信息
                                    remain_times = 10 - get_int(packet.body, 4)  # 剩余挑战次数
                                    purchase_times = get_int(packet.body, 8)  # 金豆购买挑战次数
                                    mlcs_arena_times = remain_times + purchase_times
                                elif info_type == 1:  # 经验之路信息
                                    mlcs_exp_times = 3 - get_int(packet.body, 4)  # 剩余挑战次数
                            case 8990 if get_int(packet.body) == 0:  # 元素骑士信息
                                ysqs_cards_dict.clear()
                                ysqs_material_cards_dict.clear()
                                ysqs_energy = get_int(packet.body, 28)
                                ysqs_attack = get_int(packet.body, 44)
                                ysqs_max_floor = get_int(packet.body, 68)
                                can_fight_wjsy = ysqs_max_floor >= 50 or ysqs_attack >= 7000  # 无尽深渊战力达标
                                can_fight_ssmy = ysqs_attack >= 2000  # 莎士摩亚战力达标
                                is_equip_card = ysqs_attack > 0  # 是否装备卡牌
                                cards_num = get_int(packet.body, 76)
                                start = 80
                                size = 4 * 4
                                for page in range(cards_num):
                                    card_id = get_int(packet.body, start + page * size)  # 卡牌ID
                                    card_type = get_int(packet.body, start + page * size + 4)  # 卡牌类型
                                    card_exp = get_int(packet.body, start + page * size + 8)  # 卡牌经验
                                    card_is_equip = get_int(packet.body, start + page * size + 12) > 0  # 卡牌是否已装备
                                    card_info = get_card_info(card_type)
                                    card_star = card_info["星级"]
                                    card_level = get_card_level(card_star, card_exp)
                                    ysqs_cards_dict[card_id] = {
                                        "ID": card_id,
                                        "类型": card_type,
                                        "名称": f"{card_info["名称"]} Lv.{card_level}",
                                        "星级": card_star,
                                        "经验": card_exp,
                                        "已装备": card_is_equip
                                    }
                                    # 6星蛋蛋或者6星以下不是奥丁、汉青和洛基的0经验卡牌可为升级材料
                                    if (card_star < 6 and card_type not in (0x1962A0, 0x196277, 0x19628E, 0x19628F, 0x196290) or card_type == 0x19627A) and card_exp == 0:
                                        ysqs_material_cards_dict[card_id] = get_card_provided_exp(card_star)
                                ysqs_cards_dict = dict(
                                    sorted(
                                        ysqs_cards_dict.items(),
                                        key=lambda item: (
                                            item[1]["星级"],
                                            item[1]["类型"],
                                            item[1]["经验"]
                                        ),
                                        reverse=True
                                    )
                                )
                                # 更新数据并重新选中之前的卡牌
                                window.ysqsCardBox.blockSignals(True)
                                old_card_id = window.ysqsCardBox.currentData()
                                window.ysqsCardBox.clear()
                                ysqs_max_level_cards_dict.clear()
                                for card_id, card_data in ysqs_cards_dict.items():
                                    # 只显示非满级的卡牌
                                    if card_data["经验"] < get_card_max_exp(card_data["星级"]):
                                        window.ysqsCardBox.addItem(card_data["名称"], card_id)
                                    # 满级卡牌信息
                                    else:
                                        ysqs_max_level_cards_dict.setdefault(card_data["类型"], deque()).append(card_data)
                                # 未装备卡牌放前面
                                for card_type, card_list in ysqs_max_level_cards_dict.items():
                                    ysqs_max_level_cards_dict[card_type] = deque(sorted(card_list, key=lambda item: item["已装备"]))
                                if old_card_id is not None:
                                    index = window.ysqsCardBox.findData(old_card_id)
                                    if index != -1:
                                        window.ysqsCardBox.setCurrentIndex(index)
                                window.ysqsCardBox.blockSignals(False)
                            case 1014:  # 餐厅信息
                                ct_cooked_dishes_dict.clear()
                                ct_cooking_dishes_dict.clear()
                                house_type = get_int(packet.body, 36)  # 内部装潢类型
                                stove_num = get_stove_num(house_type)  # 餐厅灶台数
                                dishes_num = get_int(packet.body, 68)
                                start = 72
                                size = 6 * 4
                                for page in range(dishes_num):
                                    dish_pos = get_int(packet.body, start + page * size)  # 菜位置
                                    dish_type = get_int(packet.body, start + page * size + 4)  # 菜类型
                                    dish_id = get_int(packet.body, start + page * size + 8)  # 菜ID
                                    dish_num = get_int(packet.body, start + page * size + 12)  # 菜数量
                                    dish_step = get_int(packet.body, start + page * size + 16)  # 菜步骤
                                    dish_time = get_int(packet.body, start + page * size + 20)  # 菜已制作时间
                                    dish_info = get_dish_info(dish_type)
                                    if dish_step == 6:  # 已熟菜信息
                                        ct_cooked_dishes_dict[dish_info["名称"]] = {
                                            "ID": dish_id,
                                            "类型": dish_type,
                                            "位置": dish_pos,
                                            "完成时间": dish_info["完成时间"],
                                            "烧糊时间": dish_info["烧糊时间"],
                                            "数量": dish_num
                                        }
                                    elif dish_step == 3 and dish_info["名称"] in ("酱爆雪顶菇", "阳光酥油肉松"):  # 正在做的菜信息
                                        ct_cooking_dishes_dict[dish_pos] = {
                                            "ID": dish_id,
                                            "类型": dish_type,
                                            "位置": dish_pos,
                                            "时间": dish_time,
                                        }
                                    elif dish_step < 3:
                                        window.ct_cook_after(dish_id, dish_type, dish_step, True)
                                        if dish_info["名称"] in ("酱爆雪顶菇", "阳光酥油肉松"):
                                            ct_cooking_dishes_dict[dish_pos] = {
                                                "ID": dish_id,
                                                "类型": dish_type,
                                                "位置": dish_pos,
                                                "时间": -5,
                                            }
                                for dish_pos in range(1, stove_num + 1):
                                    if dish_pos not in ct_cooking_dishes_dict:
                                        ct_cooking_dishes_dict[dish_pos] = {
                                            "类型": 0x147267,
                                            "位置": dish_pos,
                                            "灶台为空": True
                                        }
                                window.ctDishBox.clear()
                                window.ctDishBox.addItems(ct_cooked_dishes_dict.keys())
                                window.enable_ct_button(len(ct_cooked_dishes_dict) > 0)
                            case 1017:  # 餐厅做菜信息
                                dish_type = get_int(packet.body)
                                dish_id = get_int(packet.body, 4)
                                dish_pos = get_int(packet.body, 8)
                                dish_step = get_int(packet.body, 12)
                                if dish_step < 3:
                                    window.ct_cook_after(dish_id, dish_type, dish_step)
                                elif dish_step == 3:  # 做菜步骤完成后，更新灶台信息
                                    ct_cooking_dishes_dict[dish_pos] = {
                                        "ID": dish_id,
                                        "类型": dish_type,
                                        "位置": dish_pos,
                                        "时间": 0,
                                    }
                            case 1021:  # 餐厅收菜信息
                                dish_type = get_int(packet.body)
                                dish_id = get_int(packet.body, 4)
                                dish_pos = get_int(packet.body, 12)
                                dish_num = get_int(packet.body, 16)
                                dish_info = get_dish_info(dish_type)
                                if dish_info["名称"] not in ct_cooked_dishes_dict:  # 新收的菜
                                    ct_cooked_dishes_dict[dish_info["名称"]] = {
                                        "ID": dish_id,
                                        "类型": dish_type,
                                        "位置": dish_pos,
                                        "完成时间": dish_info["完成时间"],
                                        "烧糊时间": dish_info["烧糊时间"],
                                        "数量": dish_num
                                    }
                                    window.ctDishBox.addItem(dish_info["名称"])
                                    window.enable_ct_button(True)
                            case 8953:  # 开启七彩缤纷宝盒
                                item_id = get_int(packet.body)
                                if item_id == 0x31CE:  # 火龙珠
                                    window.stop_task("缤纷七彩宝盒")
                                    info(window, "缤纷七彩宝盒", "恭喜你获得火龙珠")
                                elif item_id == 0 and not is_show_msg:
                                    is_show_msg = True
                                window.stop_task("缤纷七彩宝盒")
                                info(window, "缤纷七彩宝盒", "宝盒已开完，暂未获得火龙珠")
                        check_waiting_packets(packet)  # 检查待匹配包，放到结尾确保包数据已处理过
                        if is_write_recv:  # 修改原始数据模式
                            raw_buf[buf_index:buf_index + packet_len] = packet.encrypt(False).data()
                    else:  # 错误包
                        if packet.cmd_id == 1209:  # 拉姆变身获得物品
                            if lamu_times == 0:
                                is_last_skill_success = False
                            else:
                                is_max_skill_success = False
                    # 处理后面的包
                    recv_buf = recv_buf[packet_len:]
                    buf_index += packet_len
                else:
                    break
            else:
                break
    # 其他包
    else:
        while True:
            if recv_buf.startswith(b"\x00\x00"):
                if len(recv_buf) >= 4:
                    packet_len = get_int(recv_buf)
                    if len(recv_buf) >= packet_len:
                        # 不是断包
                        cipher = recv_buf[:packet_len]
                        if is_show_recv:
                            show_data(Show.RECV, socket_num, Packet(cipher))  # 界面显示recv数据
                        recv_buf = recv_buf[packet_len:]
                    else:
                        break
                else:
                    break
            else:
                index = recv_buf.find(b"\x00\x00")
                if index == -1:
                    recv_buf.clear()
                else:
                    recv_buf = recv_buf[index:]  # 跳过非摩尔包
                break


if __name__ == "__main__":
    hook = ffi.dlopen("hook.dll")
    hook.SetSendCallBack(process_send_packet)
    hook.SetRecvCallBack(process_recv_packet)
    hook.LoadFlash()
    app = QApplication([])
    trans = QTranslator()
    trans.load(path("zh_CN.qm"))
    app.installTranslator(trans)
    window = MainWindow()
    window.show()
    app.exec()
