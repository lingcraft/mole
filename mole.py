from PySide6.QtCore import QTimer, QThread, Signal, QUrl, Qt, QTranslator, QRect
from PySide6.QtWidgets import QApplication, QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QHeaderView, QListWidgetItem, QMainWindow, QMessageBox, \
    QPushButton, QRadioButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtGui import QFont, QIcon, QDesktopServices, QAction, QCloseEvent
from _cffi_backend import buffer
from ui_main import Ui_MainWindow
from ui_advance import Ui_AdvanceDialog
from struct import pack, pack_into, unpack_from
from threading import Lock, Thread
from cffi import FFI
from socket import socket, fromfd, AF_INET, SOCK_STREAM
from collections import Counter
from copy import deepcopy
from dict import *
from datetime import datetime, timedelta
from queue import Empty
from time import sleep, monotonic, time
from enum import IntEnum, IntFlag, StrEnum
from configparser import ConfigParser
from os import environ
from pathlib import Path
from shutil import rmtree
from tomllib import load, loads
from requests import get
from bisect import bisect_right
from itertools import accumulate
from math import floor, sqrt
from pypinyin import lazy_pinyin, Style
from packaging.version import parse
from pyamf import sol
from collections import deque
from collections.abc import Callable
from client import Client
from bridge import start_bridge, set_upstream, injector_url, push_cmd, set_response_handler
from ctypes import windll, c_void_p
from re import sub
from loguru import logger
from ppl import Bot

# 封包
secret_key = b"^FStx,wl6NquAVRF@f%6\x00"  # 封包算法密钥
login_socket_num, game_socket_num, login_ip, login_port = 0, 0, 0, 0  # 摩尔主服务器通信号、游戏服务器通信号、IP、Port
user_id, map_id, serial_num, packet_index = 0, 0, 0, 0  # 米米号、地图号、发送包序列号、封包序号索引
recv_buf = bytearray()  # 接收封包的数据缓冲区
buf_index = 0  # 数据索引
is_show_send, is_show_recv = True, True  # 显示send包、recv包
lock = Lock()  # 发送锁
pending_waits = []  # 等待中的请求
item_info_callbacks = {} # getItemInfo 回传分发表
msg_show_states = {}  # 是否显示过消息
min_show_time = 0.4  # 最小显示时间
# 拉姆
can_get_lamu_info = True  # 能否获取拉姆信息
lamus_num, lamus_dict = 0, {}  # 拉姆数量、信息
super_lamu_id, lamu_times = 0, 0  # 超级拉姆ID、变身获得物品成功次数
lamu_id, lamu_name, lamu_index, lamu_types = 0, "", 0, ()  # 当前拉姆ID、名字、索引、可使用技能类型
lamu_thresholds = (40, 180, 660, 1340, 2660, 4280, 6840, 9800, 14000, 18700)  # 拉姆变身值阈值
lamu_skill_types = ("火", "水", "木")  # 拉姆技能类型
lamu_max_skill_level, lamu_last_skill_level, = 0, 0  # 拉姆最大技能等级、次大技能等级
lamu_last_skill_id = 0 # 上次变身技能id
lamu_last_item_level, lamu_max_item_level = 0, 0  # 拿取的物品等级
lamu_last_type_index, lamu_max_type_index = 0, 0  # 拿取的物品类型索引
lamu_last_item_index, lamu_max_item_index = 0, 0  # 拿取的物品索引
lamu_limit_item_dict, limit_data = {}, {}  # 已经拿到上限的物品
is_max_skill_success, is_last_skill_success = True, True  # 最大技能拿取物品是否成功、次大技能拿取物品是否成功
lamu_pick_result = {}  # 拉姆采集物品结果：{拉姆ID: [物品名, ...]}
super_lamu_value, super_lamu_level = 0, 0  # 超拉成长值、等级
# 摩摩怪
mmg_energy, mmg_vigour, mmg_level, mmg_card, mmg_game_id = 0, 0, 0, 0, ""  # 能量、活力、等级、摩摩挑战卡、游戏ID
mmg_type, mmg_times = 0, 0  # 摩摩怪挑战类型、执行次数
mmg_boss_times_thresholds = (0, 0, 0, 0)  # 超级Boss、超拉Boss、限时Boss、活动Boss的挑战阈值
mmg_friends, mmg_friends_dict, mmg_students_dict, mmg_fight_friends = [], {}, {}, deque()  # 好友、好友字典（米米号：等级）、师徒、可挑战好友
mmg_friends_state_dict = {1: [], 2: [], 3: [], 4: []}  # 4种状态的好友字典
mmg_friends_num, mmg_query_size_max, mmg_query_page_max, mmg_query_page = 0, 14, 0, 0  # 好友数、最大可查询好友数、最大查询页码、查询页码
# 魔灵传说
mlcs_energy, mlcs_arena_times, mlcs_exp_times = 0, 0, 0  # 魔灵体力值、竞技场可挑战次数、经验之路可挑战次数
mlcs_fight_sprites_dict, mlcs_material_sprites_dict, mlcs_sprites_dict = {}, {}, {}  # 出战魔灵、可删除/材料魔灵、全部魔灵
# 不可作为升级材料的魔灵类型：进阶材料魔灵家族（豆丁/果子/能量/宝石，最高等级均为 1）+ 烈焰剑齿虎
mlcs_non_material_sprites_types = frozenset({
    0x1A3F6A,  # 烈焰剑齿虎
    0x1A3F04, 0x1A3F05, 0x1A3F06, 0x1A3F07, 0x1A3F08  # 5种宝石进化材料
})
mlcs_factors = (1000000, 1500000, 2000000, 2500000, 3000000, 4000000, 5000000)  # 经验上限计算因子
# 元素骑士
ysqs_max_floor, ysqs_attack, ysqs_energy = 0, 0, 0  # 无尽深渊最高层数、最低攻击力、体力值
can_fight_wjsy, can_fight_ssmy, is_equip_card = False, False, True  # 能否挑战无尽深渊、莎士摩亚、是否装备卡牌
ysqs_cards_dict, ysqs_material_cards_dict, ysqs_max_level_cards_dict = {}, {}, {}  # 元素可升级卡牌、材料卡牌、最高等级卡牌
# 不可作为升级材料的卡牌类型：奥丁、汉青、洛基（5星及以下各形态）
ysqs_non_material_cards_types = frozenset({
    0x1962A0,  # 奥丁⭐5
    0x196277,  # 汉青⭐5
    0x19628E, 0x19628F, 0x196290  # 洛基⭐3/4/5
})
# 元素骑士竞技场
ysqs_talent_cd_thresholds = (
    (1, 1), (5, 1), (10, 8), (15, 3), (20, 5), (25, 2), (30, 5), (45, 3), (50, 2), (60, 10)  # 天赋冷却阈值
)
ysqs_stones_num, ysqs_free_left, has_stones = 0, 3, False # 领悟石数量、剩余免费领悟次数、初始时是否有领悟石
ysqs_countdown_info: dict[str, datetime | None] = {}  # 竞技场倒计时信息
ysqs_arena_ctx = {}  # 推荐玩家数据统计信息
is_arena_run = False  # 竞技场是否运行中
is_arena_choose = False  # 竞技场是否挑选对手中
ysqs_state: "State | None" = None  # 状态
ysqs_state_since = None  # 状态开始时间
ysqs_state_queue: deque[str] = deque()  # 待展示任务队列
ysqs_task = ""  # 状态展示信息
# 餐厅
ct_cooked_dishes_dict, ct_cooking_dishes_dict, ct_cooking_countdowns_dict = {}, {}, {}  # 餐台菜信息、灶台菜信息、灶台做菜倒计时信息
ct_state: "State | None" = None  # 状态
ct_state_since, is_connect, is_done = None, False, False  # 状态开始时间、客户端是否连接、做菜是否完成
# 化石
hs_countdown_info = {}  # 化石鉴定倒计时信息
hs_state: "State | None" = None  # 状态
hs_state_since = None  # 状态开始时间
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
    "特殊节点": "175.178.55.57"
}
# 版本文件地址
version_url = "https://raw.githubusercontent.com/lingcraft/mole/master/pyproject.toml"
# 链接加速前缀
cdn_prefixs = [
    "https://v4.gh-proxy.org/",
    "https://github.cnxiaobai.com/",
    "https://wget.la/",
    "https://ghfast.top/",
    "https://ghproxy.net/",
    "https://github.boki.moe/",
    "https://gh.ddlc.top/"
]
available_cdn_prefix = ""
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
hook_log = base_dir / "hook.log"
mole_log = base_dir / "mole.log"
login_record = next(
    (
        record_dir / "127.0.0.1" / "#mole" / "login.sol"
        for record_dir in (Path(environ["appdata"]) / "Macromedia" / "Flash Player" / "#SharedObjects").glob("*")
    ),
    None
)
account_records = [
    sol_file
    for cache_dir in (Path(environ["appdata"]) / "Macromedia" / "Flash Player" / "#SharedObjects").glob("*")
    for sol_file in (cache_dir / "127.0.0.1" / "#mole").glob("*.sol")
    if sol_file.stem.isdigit()
]
caches_dir = Path(environ["localappdata"]) / "Microsoft" / "Windows" / "INetCache" / "IE"
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


class State(IntEnum):
    COUNTDOWN = 1  # 倒计时
    LOGGING_IN = 2  # 正在登录
    LOGIN_OK = 3  # 登录成功
    COOKING = 4  # 做菜中
    DONE = 5  # 做菜完成
    RUNNING = 6  # 运行中


class Button(IntFlag):
    OK = QMessageBox.StandardButton.Ok
    CANCEL = QMessageBox.StandardButton.Cancel
    OK_CANCEL = OK | CANCEL


class MainWindow(QMainWindow, Ui_MainWindow):
    show_signal = Signal(str, int, int, str, str)

    def __init__(self):
        super().__init__()
        # 界面基础设置
        self.setupUi(self)
        # 界面额外设置
        # 读取配置
        self.config = ConfigParser()
        if config.exists():
            self.config.read(config, encoding="utf-8")
        with open(path("pyproject.toml"), "rb") as file:  # 获取版本
            self.version = load(file)["project"]["version"]
        self.account_dict = {}
        if login_record and login_record.exists():
            with open(login_record, "rb") as file:  # 获取登录信息
                self.account_dict = {data["userID"]: get_password(data["pwd"]) for data in sol.decode(file.read())[1]["list"]}
        self.friend_dict = {}
        for account_record in account_records:  # 获取好友信息
            with open(account_record, "rb") as file:
                self.friend_dict[int(account_record.stem)] = [int(data["friend"]) for data in sol.decode(file.read())[1]["FriendsList"] if "friend" in data]
        # 界面主区域设置
        set_upstream(server_dict[self.server].replace("$node", node_dict[self.node]))
        start_bridge()  # 注入服务、命令桥，端口自适应
        set_response_handler(dispatch_item_info)  # 注册回传分发器
        self.axWidget.dynamicCall("LoadMovie(long,string)", 0, self.url())
        self.set_scale_mode()
        self.tableWidget.setFont(QFont("Cascadia Code, Microsoft YaHei UI", 9))
        self.tableWidget.verticalHeader().setDefaultSectionSize(10)  # 行高
        self.tableWidget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # 禁止编辑单元格
        self.tableWidget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)  # 禁止选多行
        self.tableWidget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)  # 一次选一行
        self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # 允许手动调整列宽
        self.clear_table()
        self.tableWidget.setHorizontalHeaderLabels(["类型", "通信号", "命令号", "解析", "封包数据"])
        self.tableWidget.currentCellChanged.connect(self.change_row)
        self.tab_geometry = QRect(self.tabWidget.geometry())  # tabWidget 原始位置、尺寸
        self.tabWidget.currentChanged.connect(self.change_tab)
        self.add_mrjl_tab()  # 添加"每日奖励"勾选列表
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
        self.menubar.addAction("清除缓存", self.clear_cache)
        self.menubar.addAction("检查更新", self.check_update)
        self.menubar.addAction(QIcon(path("github.ico")), "关于", self.open_github)
        self.check_menu()  # 节点勾选
        # 线程初始化
        self.send_thread = SendThread()
        self.send_ex_thread = SendExThread()
        self.send_to_server_thread = SendToServerThread()
        self.send_to_server_thread.result.connect(self.mmg_get_reward)
        self.update_thread = UpdateThread()
        self.update_thread.result.connect(self.update_notice)
        self.clear_thread = ClearThread()
        self.clear_thread.result.connect(self.refresh)
        self.advance_dialog = AdvanceDialog()
        self.show_signal.connect(self.add_data)
        self.client = None  # 独立进程客户端，懒启动时才创建
        self.ppl_thread = PPLThread()
        # 单次运行功能
        self.sendButton.clicked.connect(self.send)
        self.sendClearButton.clicked.connect(self.send_clear)
        self.sendCheckBox.stateChanged.connect(self.change_show_send)
        self.recvCheckBox.stateChanged.connect(self.change_show_recv)
        self.socketCheckBox.stateChanged.connect(self.change_socket)
        self.clearButton.clicked.connect(self.clear_table)
        self.ysqsFightButton.clicked.connect(self.ysqs_start)
        self.ysqsUpgradeButton.clicked.connect(self.ysqs_upgrade_start)
        self.ysqsAdvanceButton.clicked.connect(self.ysqs_advance_start)
        self.mlcsFightButton.clicked.connect(self.mlcs_start)
        self.mlcsSellButton.clicked.connect(self.mlcs_sell_start)
        self.mlcsUpgradeButton.clicked.connect(self.mlcs_upgrade_start)
        self.pplPlayButton.clicked.connect(self.ppl_start)
        self.hsIdentifyButton.clicked.connect(self.hs_start)
        self.ysqsArenaFightButton.clicked.connect(self.ysqs_arena_start)
        # 多次运行功能
        self.sendLoopButton.clicked.connect(lambda: self.start_task("循环发送", self.send, Interval.FAST, self.sendLoopButton))
        self.lamuGrowButton.clicked.connect(lambda: self.start_task("拉姆", self.lamu_run, Interval.IDLE, self.lamuGrowButton, self.lamu_start))
        self.dddGetButton.clicked.connect(lambda: self.start_task("点点豆", self.ddd_run, Interval.FAST, self.dddGetButton))
        self.medGetButton.clicked.connect(lambda: self.start_task("摩尔豆", self.med_run, Interval.FAST, self.medGetButton))
        self.bhOpenButton.clicked.connect(lambda: self.start_task("缤纷七彩宝盒", self.bh_run, Interval.SLOW, self.bhOpenButton))
        self.kllFinishButton.clicked.connect(lambda: self.start_task("卡罗拉幸运儿", self.kll_run, Interval.IDLE, self.kllFinishButton))
        self.is_show_recv = None  # 记录启动任务前是否显示recv包
        # 摩摩怪功能
        self.timer_pool = {
            "摩摩怪": RunTimer(self.mmg_run),
            "餐厅": {pos: RunTimer() for pos in range(1, 8)},
            "化石": RunTimer(self.hs_run, 60 * 1000),
            "元素骑士": RunTimer(self.ysqs_arena_run, 10 * 60 * 1000)
        }
        self.mmgPVBButton.clicked.connect(lambda: self.mmg_start(1))
        self.mmgPVEButton.clicked.connect(lambda: self.mmg_start(2))
        self.mmgPVPButton.clicked.connect(lambda: self.mmg_start(3))
        # 餐厅功能
        self.ctSellButton.clicked.connect(lambda: self.start_task("餐厅卖菜", self.ct_sell_run, Interval.FAST, self.ctSellButton))
        self.ctHarvestButton.clicked.connect(self.ct_harvest_start)
        self.user_id = None  # 记录启动自动做菜时的用户id
        # 标题功能提示信息
        self.title = self.windowTitle()
        self.title_timer_pool: dict[str, RunTimer] = {}
        self.title_part_pool = {}

    # ================================================== 界面功能方法 ==================================================
    @property
    def server(self):
        if (server := self.config.get("Settings", "server", fallback="官服")) in server_dict:
            return server
        else:
            self.server = "官服"
            return "官服"

    @property
    def node(self):
        if (node := self.config.get("Settings", "node", fallback="主节点")) in node_dict:
            return node
        else:
            self.node = "主节点"
            return "主节点"

    @server.setter
    def server(self, value):
        self.save("server", value)

    @node.setter
    def node(self, value):
        self.save("node", value)

    def save(self, option, value):
        if not self.config.has_section("Settings"):
            self.config.add_section("Settings")
        self.config.set("Settings", option, value)
        if not config.parent.exists():
            config.parent.mkdir()
        with open(config, "w", encoding="utf-8") as file:
            self.config.write(file)

    def closeEvent(self, event: QCloseEvent):
        self.stop_send()
        if hook_log.exists():
            hook_log.unlink()
        if mole_log.exists():
            logger.remove()
            try:
                mole_log.unlink()
            except:
                pass
        super(MainWindow, self).closeEvent(event)

    def url(self):
        prefix = "" if self.server == "官服" else f"/server{list(server_dict).index(self.server)}"
        return injector_url(f"{prefix}/Client.swf?t={time()}")

    def set_scale_mode(self):
        start = monotonic()

        def apply():
            self.axWidget.dynamicCall("SetScaleMode(int)", 2)
            if monotonic() - start > 1:
                timer.stop()

        timer = RunTimer(apply, Interval.NORMAL, 0).start()

    def change_show_send(self, state: int):
        global is_show_send
        is_show_send = state > 0

    def change_show_recv(self, state: int):
        global is_show_recv
        is_show_recv = state > 0

    def change_socket(self, state: int):
        self.socketLineEdit.setEnabled(state > 0)
        if state > 0 and len(self.socketLineEdit.text()) == 0 and login_socket_num != 0:
            self.socketLineEdit.setText(str(login_socket_num))

    def send(self):
        # 使用后台发送，防止添加自定义延迟后阻塞界面
        send_lines_back_ex(self.textEdit.toPlainText().split("\n"), Interval.FAST)

    def send_clear(self):
        self.textEdit.clear()

    def change_row(self, row: int, column: int):
        data = self.tableWidget.item(row, column if column < 2 else 4)
        if data is not None:
            self.textEdit.setPlainText(data.toolTip() if column == 0 else data.text())

    def change_server(self, checked: bool):
        if checked:
            self.server = self.sender().text()
            if self.server == "官服":
                self.node = "主节点"
            self.refresh()
        else:
            self.sender().setChecked(True)

    def change_node(self, checked: bool):
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
        self.ppl_thread.stop()
        set_upstream(server_dict[self.server].replace("$node", node_dict[self.node]))
        self.axWidget.dynamicCall("LoadMovie(long, string)", 0, self.url())
        self.set_scale_mode()
        self.enable_all_buttons(False)

    def clear_cache(self):
        if not self.clear_thread.isRunning():
            self.clear_thread.start()

    def add_data(self, data_type: str, socket_num: int, cmd_id: int, cmd_analyse: str, data: str):
        self.tableWidget.blockSignals(True)
        global packet_index
        if packet_index >= 10000:  # 已有数据10000条，清空
            self.clear_table()
        if len(str(packet_index + 1)) > self.row_len:
            self.row_len += 1
            self.column_width -= 7  # 缩小序号列增加的宽度
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
        self.column_width = 232  # 封包数据初始列宽
        self.tableWidget.clearContents()  # 清空内容
        self.tableWidget.setRowCount(13)  # 初始行数
        self.tableWidget.setColumnCount(5)
        self.tableWidget.setColumnWidth(0, 45)
        self.tableWidget.setColumnWidth(1, 45)
        self.tableWidget.setColumnWidth(2, 45)
        self.tableWidget.setColumnWidth(3, 100)
        self.tableWidget.setColumnWidth(4, self.column_width)
        self.tableWidget.setCurrentCell(-1, -1)  # 清除选中，避免恢复信号后触发 currentCellChanged
        self.tableWidget.scrollToTop()  # 拖动到顶部
        self.tableWidget.blockSignals(False)

    def enable_lamu_button(self, is_enabled: bool):
        self.lamuGrowButton.setEnabled(is_enabled)

    def enable_mmg_button(self, is_enabled: bool):
        self.mmgPVBButton.setEnabled(is_enabled)
        self.mmgPVEButton.setEnabled(is_enabled)
        self.mmgPVPButton.setEnabled(is_enabled)
        self.mmgLevelBox.setEnabled(is_enabled)
        self.mmgBossBox.setEnabled(is_enabled)

    def enable_ysqs_button(self, is_enabled: bool):
        self.ysqsFightButton.setEnabled(is_enabled)
        self.ysqsUpgradeButton.setEnabled(is_enabled)
        self.ysqsAdvanceButton.setEnabled(is_enabled)
        self.ysqsLevelBox.setEnabled(is_enabled)
        self.ysqsCardBox.setEnabled(is_enabled)
        self.ysqsArenaFightButton.setEnabled(is_enabled)

    def enable_mlcs_button(self, is_enabled: bool):
        self.mlcsFightButton.setEnabled(is_enabled)
        self.mlcsUpgradeButton.setEnabled(is_enabled)
        self.mlcsSellButton.setEnabled(is_enabled)
        self.mlcsSpriteBox.setEnabled(is_enabled)

    def enable_ct_button(self, is_enabled: bool):
        self.ctSellButton.setEnabled(is_enabled)
        if not is_running("餐厅"):
            self.ctHarvestButton.setEnabled(is_enabled)
            self.ctDishBox.setEnabled(is_enabled)
        elif not is_enabled:
            self.ctDishBox.setEnabled(is_enabled)

    def enable_ddd_button(self, is_enabled: bool):
        self.dddGetButton.setEnabled(is_enabled)

    def enable_med_button(self, is_enabled: bool):
        self.medGetButton.setEnabled(is_enabled)

    def enable_bh_button(self, is_enabled: bool):
        self.bhOpenButton.setEnabled(is_enabled)

    def enable_kll_button(self, is_enabled: bool):
        self.kllFinishButton.setEnabled(is_enabled)

    def enable_mrjl_button(self, is_enabled: bool):
        self.rewardSelectAllButton.setEnabled(is_enabled)
        self.rewardInvertButton.setEnabled(is_enabled)
        self.rewardGetButton.setEnabled(is_enabled)

    def enable_ppl_button(self, is_enabled: bool):
        self.pplPlayButton.setEnabled(is_enabled)

    def enable_hs_button(self, is_enabled: bool):
        self.hsIdentifyButton.setEnabled(is_enabled)

    def enable_all_buttons(self, is_enabled: bool):
        self.enable_lamu_button(is_enabled)
        self.enable_mmg_button(is_enabled)
        self.enable_ysqs_button(is_enabled)
        self.enable_mlcs_button(is_enabled)
        self.enable_ddd_button(is_enabled)
        self.enable_med_button(is_enabled)
        self.enable_bh_button(is_enabled)
        self.enable_kll_button(is_enabled)
        self.enable_mrjl_button(is_enabled)
        self.enable_ppl_button(is_enabled)
        self.enable_hs_button(is_enabled)
        if not is_enabled:  # 刷新游戏后的操作
            self.stop_timer("摩摩怪")
            self.stop_timer("拉姆")
            self.enable_ct_button(is_enabled)

    # 简单的多次任务
    def start_task(self, name: str, func: Callable, interval: int, button: QPushButton | None = None, start_func: Callable | None = None, stop_text: str = "停止"):
        if name in self.timer_pool:
            timer, text, button = self.timer_pool[name]
            if timer.isActive():  # 停止
                button.setText(text)
                if interval < Interval.NORMAL and self.is_show_recv:
                    self.recvCheckBox.setChecked(True)
                if name == "循环发送":
                    self.send_ex_thread.stop()
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
        if interval < Interval.NORMAL:
            self.is_show_recv = is_show_recv
            if is_show_recv:
                self.recvCheckBox.setChecked(False)
        msg_show_states[name] = False
        timer.start()

    def stop_task(self, name: str):
        if name in self.timer_pool:
            timer, text, button = self.timer_pool[name]
            if timer.isActive():  # 停止
                button.setText(text)
                timer.stop()

    def stop_timer(self, name: str):
        if name in self.timer_pool:
            timer = self.timer_pool[name]
            if isinstance(timer, dict):
                for item in timer.values():
                    if isinstance(item, QTimer) and item.isActive():
                        item.stop()
            elif isinstance(timer, tuple):
                for item in timer:
                    if isinstance(item, QTimer) and item.isActive():
                        item.stop()
            elif isinstance(timer, QTimer) and timer.isActive():
                timer.stop()

    def stop_send(self):
        self.send_thread.stop()
        self.send_ex_thread.stop()

    def check_update(self):
        if not self.update_thread.isRunning():
            self.update_thread.start()

    def update_notice(self, is_first: bool, version: str, description: str):
        is_latest_msg = f"当前版本 v{self.version} 已是最新！"
        is_expired_msg = f"发现新版本：v{version}，更新信息：\n{sub(r"(?m)^- ", "  ●  ", description)}"
        is_error_msg = "检查更新失败，是否前往下载页？"
        if version:
            if parse(self.version) < parse(version):
                if info(self, "提示", is_expired_msg, Button.OK_CANCEL) == Button.OK:
                    QDesktopServices.openUrl(QUrl(f"{available_cdn_prefix}https://github.com/lingcraft/mole/releases/download/v{version}/mole.exe"))
            elif not is_first:
                info(self, "提示", is_latest_msg)
        elif not is_first:
            if info(self, "提示", is_error_msg, Button.OK_CANCEL) == Button.OK:
                QDesktopServices.openUrl(QUrl(f"https://github.com/lingcraft/mole/releases"))


    def open_github(self):
        QDesktopServices.openUrl(QUrl("https://github.com/lingcraft/mole"))

    def update_title(self, module_name, module_user_id=None, func_name=None, func_info=None, next_run=None):
        if func_name is None:
            self.title_part_pool.pop(module_name, None)
        else:
            title = module_name
            if module_user_id is not None:
                title += f" ({module_user_id})"
            if func_name is not None:
                title += f" • {func_name}"
            if func_info is not None:
                title += f"：{func_info}"
            if next_run is not None:
                result = next_run()
                if isinstance(result, datetime):
                    remain = max(0, int((result - datetime.now()).total_seconds()))
                    h, left = divmod(remain, 3600)
                    m, s = divmod(left, 60)
                    cd = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
                    title += f"（{cd}）"
                elif isinstance(result, str):
                    title += f"（{result}）"
            self.title_part_pool[module_name] = title
        parts = [part for part in self.title_part_pool.values() if part]
        suffix = " | ".join(parts)
        self.setWindowTitle(f"{self.title}{(" | " + suffix) if suffix else ""}")

    def start_update_title(self, module_name: str, module_user_id: int | None = None, func_name: str | None = None, func_info: str | None = None,
                           next_run: Callable | None = None, tick_run: Callable | None = None, interval: int = 100):
        def tick():
            self.update_title(module_name, module_user_id, func_name, func_info, next_run)
            if tick_run is not None:
                tick_run()
        self.update_title(module_name, module_user_id, func_name, func_info, next_run)
        delay = (1000 - datetime.now().microsecond // 1000) % 1000  # 对齐到整秒
        timer = RunTimer(tick, interval, delay, True).start()
        self.title_timer_pool[module_name] = timer

    def stop_update_title(self, module_name: str):
        self.title_timer_pool[module_name].stop()
        self.update_title(module_name)

    def add_mrjl_tab(self):
        self.mrjl_tab = QWidget()
        self.tabWidget.addTab(self.mrjl_tab, "每日奖励")
        self.reward_checkboxes: list[QCheckBox] = []
        self.reward_widgets: list[QWidget] = []
        self.reward_radio_group = QButtonGroup(self)
        self.reward_radio_group.setExclusive(False)
        self.reward_radio_remember = None  # 上次选中的单选项
        self.reward_total = 0
        self.reward_packet_sent = 0
        self.reward_cum: list[int] = []
        self.reward_names: list[str] = []
        self.reward_done_disp = 0
        self.reward_done_disp_t = 0.0
        self.reward_finish_pending = False

        layout = QVBoxLayout(self.mrjl_tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        scroll = QScrollArea(self.mrjl_tab)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        list_layout.setContentsMargins(4, 4, 4, 4)
        list_layout.setSpacing(3)

        for name, packets in reward_dict.items():
            self.add_reward_checkbox(list_layout, name, packets)

        scroll.setWidget(list_container)
        layout.addWidget(scroll, stretch=1)

        btn_layout = QHBoxLayout()
        self.rewardSelectAllButton = QPushButton("全选")
        self.rewardInvertButton = QPushButton("反选")
        self.rewardGetButton = QPushButton("开始领取")
        self.rewardSelectAllButton.setEnabled(False)
        self.rewardInvertButton.setEnabled(False)
        self.rewardGetButton.setEnabled(False)
        btn_layout.addWidget(self.rewardSelectAllButton)
        btn_layout.addWidget(self.rewardInvertButton)
        btn_layout.addWidget(self.rewardGetButton)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.rewardSelectAllButton.clicked.connect(self.select_all_reward)
        self.rewardInvertButton.clicked.connect(self.invert_reward)
        self.rewardGetButton.clicked.connect(self.start_reward)

        # 默认：多选奖励全部勾选；互斥单选组默认选中第 1 个
        for cb in self.reward_checkboxes:
            cb.setChecked(True)
        radio_buttons = self.reward_radio_group.buttons()
        if radio_buttons:
            radio_buttons[0].setChecked(True)
            self.reward_radio_remember = radio_buttons[0]

    def change_tab(self):
        if self.tabWidget.currentWidget() is self.mrjl_tab:
            # 切到 tab3：隐藏上方发包区域
            self.groupBox.setVisible(False)
            g = self.groupBox.geometry()
            self.tabWidget.setGeometry(
                g.x(), g.y(), g.width(),
                self.tab_geometry.height() + g.height()
            )
        else:
            # 切回其它页：恢复发包区域与 tabWidget 原始位置、尺寸
            self.groupBox.setVisible(True)
            self.tabWidget.setGeometry(self.tab_geometry)

    def reward_tick_run(self):
        # 完成判定基于“显示值”而非实际发包数：显示值节流后可能滞后于实际，
        # 追上总个数，追上才收尾，避免定时器被过早停掉导致标题只闪一下。
        if self.reward_done_disp >= self.reward_total and self.rewardGetButton.text() == "停止":
            # 保留一个刷新间隔，下一拍才真正收尾。
            if self.reward_finish_pending:
                self.finish_reward()
            else:
                self.reward_finish_pending = True

    def add_reward_checkbox(self, layout: QVBoxLayout, name: str, packets: list):
        # 互斥抽奖单选组
        if name.endswith("（抽奖）"):
            cb = QRadioButton(name)
            self.reward_radio_group.addButton(cb)
            cb.toggled.connect(lambda checked, b=cb: self.toggle_radio(b, checked))
        else:
            cb = QCheckBox(name)
            self.reward_checkboxes.append(cb)
        cb.setProperty("packets", packets)
        layout.addWidget(cb)
        self.reward_widgets.append(cb)

    def toggle_radio(self, btn: QRadioButton, checked: bool):
        # 互斥选项、允许取消单选项
        if checked:
            for b in self.reward_radio_group.buttons():
                if b is not btn:
                    b.setChecked(False)
            # 记住选中项
            self.reward_radio_remember = btn

    def select_all_reward(self):
        for cb in self.reward_checkboxes:
            cb.setChecked(True)
        # 恢复上次记住的选中项
        if self.reward_radio_remember is not None:
            self.reward_radio_remember.setChecked(True)

    def invert_reward(self):
        for cb in self.reward_checkboxes:
            cb.setChecked(not cb.isChecked())
        # 单选组反选：有选中→取消，再次反选→恢复记住项
        radios = self.reward_radio_group.buttons()
        if not radios:
            return
        checked = self.reward_radio_group.checkedButton()
        if checked is not None:
            checked.setChecked(False)
        elif self.reward_radio_remember is not None:
            self.reward_radio_remember.setChecked(True)

    def start_reward(self):
        if self.rewardGetButton.text() != "停止":
            # 开始领取
            self.run_reward()
            if self.send_thread.isRunning():
                self.rewardGetButton.setText("停止")
                # 标题显示领取进度（已完项/总项）
                self.start_update_title(
                    "每日奖励",
                    None,
                    "领取",
                    "进度",
                    self.reward_next_run,
                    self.reward_tick_run
                )
        else:
            # 手动停止：请求线程中断并等待结束，再走统一收尾（含停止弹窗提示）
            self.send_thread.stop()
            self.finish_reward()

    def run_reward(self):
        # 收集每个勾选中的项（复选框 + 抽奖互斥单选组）的封包，按项分组以便统计进度。
        self.reward_items: list[list] = []
        self.reward_names: list[str] = []
        for cb in self.reward_widgets:
            if cb.isChecked():
                packets = cb.property("packets") or []
                if any("{super_lamu_level}" in body for packet in packets for body in packet.values()):
                    self.reward_items.append(
                        [
                            {cmd_id: body.replace("{super_lamu_level}", get_hex(super_lamu_level + 22))}
                            for packet in packets for cmd_id, body in packet.items()
                        ]
                    )
                else:
                    self.reward_items.append(packets)
                self.reward_names.append(cb.text())
        self.reward_total = len(self.reward_items)
        self.reward_packet_sent = 0
        # 重置进度显示节流状态，新一轮从 0 开始、不沿用上一轮残留的显示值
        self.reward_done_disp = 0
        self.reward_done_disp_t = 0.0
        self.reward_finish_pending = False
        # 累计每项的包数，用于按“已完成项/总项”显示进度
        self.reward_cum: list[int] = []
        acc = 0
        for item in self.reward_items:
            acc += len(item)
            self.reward_cum.append(acc)
        lines = [line for item in self.reward_items for line in item]
        if lines:
            send_lines_back(lines, progress=self.reward_progress)

    def finish_reward(self):
        # 发送线程自然结束（含被中断）：恢复按钮文字并清除进度标题
        if self.rewardGetButton.text() != "停止":
            return
        self.rewardGetButton.setText("开始领取")
        self.stop_update_title("每日奖励")
        # 停止时弹窗提示已领取个数（按实际已完成的个数统计）
        sent = self.reward_packet_sent
        cum = self.reward_cum
        done = sum(1 for c in cum if sent >= c)
        if done > 0 and not is_shown_msg("每日奖励"):
            alert_msg(f"已领取{done}个今日奖励")

    def reward_progress(self, index: int):
        self.reward_packet_sent = index + 1

    def reward_next_run(self):
        # 当前正在领取的勾选项名 + 已发送完的个数 / 总个数
        total = self.reward_total
        if total == 0:
            return "0/0"
        sent = self.reward_packet_sent
        cum = self.reward_cum
        done_actual = sum(1 for c in cum if sent >= c)
        names = self.reward_names
        # 不跳过中间数字，每项最少 0.1 秒，落后时逐步追平实际值。
        now = monotonic()
        disp = self.reward_done_disp
        disp_t = self.reward_done_disp_t
        if now - disp_t >= 0.1:
            if disp < done_actual:
                disp += 1
                disp_t = now
                self.reward_done_disp = disp
                self.reward_done_disp_t = disp_t
            elif disp > done_actual:
                disp = done_actual
                disp_t = now
                self.reward_done_disp = disp
                self.reward_done_disp_t = disp_t
        done = disp
        # 正在领取的项
        current_idx = min(done, total - 1)
        current_name = names[current_idx] if current_idx < len(names) else ""
        return f"{done}/{total}：{current_name}"

    # ================================================== 游戏功能方法 ==================================================
    def lamu_get_info(self):
        send_lines([
            f"0000000000000000D60000000000000000{get_hex(user_id)}",  # 获取拉姆数量
            f"0000000000000000D40000000000000000{get_hex(user_id)}0000000001",  # 获取所有拉姆信息
            f"0000000000000000CC0000000000000000{get_hex(user_id)}"  # 获取超拉信息
        ])

    def lamu_gift(self):
        send_lines([
            "00000000000000277500000000000000003B9ACA16",  # 超拉每日礼包
            f"0000000000000027760000000000000000{get_hex(super_lamu_level + 22)}"  # 超拉星级礼包
        ])

    def lamu_feed(self, _lamu_id: int, food_num: int = 2):
        send_lines([
            f"0000000000000001F500000000000000000002BF26{get_hex(food_num)}",  # 买十字架
            *[f"0000000000000001F90000000000000000{get_hex(user_id)}{get_hex(_lamu_id)}0002BF26"] * food_num  # 喂十字架
        ])

    def lamu_follow(self, _lamu_id: int):
        send_lines([
            f"0000000000000000D70000000000000000{get_hex(_lamu_id)}00000001"  # 拉姆跟随
        ])

    def lamu_learn(self, _lamu_id: int):
        send_lines(
            [
                f"0000000000000004670000000000000000{get_hex(_lamu_id)}{get_hex(lamu_skill_types.index(skill_type) + 1)}{get_hex(lamu_last_skill_level)}"
                for skill_type in lamu_types  # 学习技能
            ]
            +
            [
                f"0000000000000004C20000000000000000{get_hex(_lamu_id)}{"".join(get_hex(get_skill_id(lamu_max_skill_level if skill_type in lamu_types else 1, skill_type), 1) for skill_type in lamu_skill_types)}"
            ]  # 配置技能
        )

    def lamu_get_vars(self):
        if lamu_times == 0:
            return is_last_skill_success, lamu_last_skill_level, lamu_last_item_level, lamu_last_type_index, lamu_last_item_index
        else:
            return is_max_skill_success, lamu_max_skill_level, lamu_max_item_level, lamu_max_type_index, lamu_max_item_index

    def lamu_set_vars(self, item_level: int, type_index: int, item_index: int):
        global lamu_last_item_level, lamu_last_type_index, lamu_last_item_index, lamu_max_item_level, lamu_max_type_index, lamu_max_item_index
        if lamu_times == 0:
            lamu_last_item_level, lamu_last_type_index, lamu_last_item_index = item_level, type_index, item_index
        else:
            lamu_max_item_level, lamu_max_type_index, lamu_max_item_index = item_level, type_index, item_index

    def lamu_get_skill_info(self, skill_level: int, item_level: int, type_index: int):
        skill_type = lamu_types[type_index]
        return skill_type, get_skill_id(skill_level, skill_type), list(
            lamu_dict[item_level][skill_type].items())

    def lamu_collect_result(self):
        is_skill_success, skill_level, item_level, type_index, item_index = self.lamu_get_vars()
        skill_type, skill_id, items = self.lamu_get_skill_info(skill_level, item_level, type_index)
        item_name = items[item_index][0]
        if is_skill_success:
            lamu_pick_result.setdefault(lamu_id, []).append(item_name)

    def lamu_show_result(self):
        lines = []
        for _lamu_id, lamu_info in lamus_dict.items():
            if lamu_info["类型"] == "未进化":
                lines.append(f"拉姆（{lamu_info["名称"]}）未进化，无法采集物品")
                continue
            items = lamu_pick_result.get(_lamu_id, [])
            if items:
                pick_count = Counter(items)
                text = "，".join(f"{item_name}：{item_count}" for item_name, item_count in pick_count.items())
                lines.append(f"拉姆（{lamu_info["名称"]}）成功采集物品：{text}")
            else:
                lines.append(f"拉姆（{lamu_info["名称"]}）今天可采集物品已达上限")
        info(self, "一键获取拉姆变身值完毕", "\n".join(lines))

    def lamu_start(self):
        global lamu_index
        self.enable_lamu_button(False)
        lamu_pick_result.clear()
        lamu_index = 0
        self.lamu_init()

    def lamu_init(self):
        global lamu_index, lamu_times, is_max_skill_success, is_last_skill_success, lamu_max_skill_level, lamu_last_skill_level, \
            lamu_max_item_level, lamu_last_item_level, lamu_max_type_index, lamu_last_type_index, lamu_max_item_index, \
            lamu_last_item_index, limit_data, lamu_id, lamu_name, lamu_types, lamu_last_skill_id
        lamu_id = list(lamus_dict)[lamu_index]
        lamu_info = lamus_dict[lamu_id]
        lamu_name = lamu_info["名称"]
        match lamu_info["类型"]:
            case "超拉":
                lamu_types = lamu_skill_types
            case "未进化":
                self.lamu_next()
                return
            case _:
                lamu_types = (lamu_info["类型"],)
        lamu_max_skill_level = get_max_skill_level(lamu_info["等级"])
        lamu_last_skill_level = get_last_skill_level(lamu_info["等级"])
        lamu_last_skill_id = 0
        lamu_times = 0
        is_max_skill_success, is_last_skill_success = True, True
        lamu_max_item_level, lamu_last_item_level = lamu_max_skill_level, lamu_last_skill_level
        lamu_max_type_index, lamu_last_type_index = 0, 0
        lamu_max_item_index, lamu_last_item_index = 0, 0
        now = datetime.now()
        # 每日 3 点刷新采集上限（按账号共享：任一拉姆拿满某物品，其他拉姆也不能再拿）
        limit_data = lamu_limit_item_dict.setdefault(
            user_id, {"数据": {"火": {}, "水": {}, "木": {}}, "时间": now}
        )
        if limit_data["时间"] < datetime(now.year, now.month, now.day, 3) <= now:
            limit_data["数据"].clear()
            limit_data["时间"] = now
        if lamu_info["类型"] == "超拉":  # 超拉每日礼包/星级礼包仅超拉领取
            self.lamu_gift()
        self.lamu_follow(lamu_id)
        self.lamu_learn(lamu_id)
        self.lamu_feed(lamu_id)

    def lamu_get_item(self, skill_level: int, item_level: int, type_index: int, item_index: int):
        skill_type, skill_id, items = self.lamu_get_skill_info(skill_level, item_level, type_index)
        item_id = items[item_index][1]
        while item_id in limit_data["数据"][skill_type]:
            type_index += 1
            if type_index >= len(lamu_types):  # 技能类型都用过了
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
        global lamu_last_skill_id
        is_skill_success, skill_level, item_level, type_index, item_index = self.lamu_get_vars()
        item_id, skill_id, skill_type = self.lamu_get_item(skill_level, item_level, type_index, item_index)
        if lamu_times < 11 or item_level == 6:  # 最高级物品全部拿到上限
            if not is_skill_success:  # 上次技能拿取失败
                limit_data["数据"][skill_type][item_id] = item_id
                limit_data["时间"] = datetime.now()
                item_id, skill_id, skill_type = self.lamu_get_item(skill_level, item_level, type_index, item_index)
            if item_id is None:
                self.lamu_next()
                return
            if skill_id != lamu_last_skill_id:  # 变身技能与上次不同
                lines = [f"0000000000000004BC0000000000000000{get_hex(lamu_id)}{get_hex(skill_id)}"]  # 变身
                lamu_last_skill_id = skill_id
            else:
                lines = []
            lines.append(f"0000000000000004B90000000000000000{get_hex(lamu_id)}{get_hex(skill_id)}{get_hex(item_id)}")  # 采集物品
            send_lines(lines)
        else:
            self.lamu_next()

    def lamu_next(self):
        global lamu_index
        self.lamu_feed(lamu_id)
        lamu_index += 1
        if lamu_index < len(lamus_dict):
            self.lamu_init()
        else:
            self.lamu_stop()

    def lamu_stop(self):
        self.lamu_follow(super_lamu_id)
        self.lamu_feed(super_lamu_id, 1)
        self.enable_lamu_button(True)
        self.lamu_show_result()
        self.stop_timer("拉姆")

    def mmg_start(self, fight_type: int = 0):
        def start():  # 开始执行
            global mmg_energy
            if self.mmgLevelBox.currentText().endswith("疯狂"):
                mmg_energy /= 2
            self.enable_mmg_button(False)
            self.timer_pool["摩摩怪"].start()

        if fight_type == 0:  # 查询好友完毕
            start()
        else:
            global mmg_type, mmg_times
            mmg_type, mmg_times = fight_type, 0
            send_lines([
                "0000000000000001910000000000000000000000E40000000000000000000000000000000000000000",  # 获取地图信息
                f"0000000000000020080000000000000000{get_hex(user_id)}",  # 获取能量、活力、等级
                "0000000000000020200000000000000000",  # 获取Boss已挑战次数
                "0000000000000020090000000000000000"  # 获取摩摩挑战卡数量
            ])
            if fight_type < 3:
                run_later_expect(start, {0x2008: 1, 0x2020: 1, 0x2009: 1})
            else:
                friends = self.friend_dict[user_id]
                ids = "".join([get_hex(friend) for friend in friends])
                send_lines([
                    f"0000000000000020220000000000000000{get_hex(user_id)}",  # 获取师徒信息
                    f"0000000000000020100000000000000000{get_hex(len(friends))}{ids}",  # 获取好友信息
                ])
                run_later_expect(self.mmg_query_friends, {0x2022: 1, 0x2010: 1})

    def mmg_run(self):
        match mmg_type:
            case 1:  # 挑战Boss
                if self.mmgBossBox.currentText() == "独角萨摩":
                    if mmg_times < mmg_card:
                        level_id = get_level_info("独角萨摩", mmg_level)
                        self.mmg_fight(level_id, 1)
                    else:
                        self.mmg_stop()
                else:
                    boss_stages = [
                        lambda: get_level_info("飞沙蝎"),
                        lambda: get_level_info(self.mmgBossBox.currentText()),
                        lambda: get_level_info("怪味糖蓝龙", mmg_level),
                        lambda: get_level_info("鲁尼"),
                    ]
                    index = bisect_right(mmg_boss_times_thresholds, mmg_times)
                    if index < len(boss_stages):
                        level_id = boss_stages[index]()
                        self.mmg_fight(level_id, 1)
                    else:
                        self.mmg_stop()
            case 2:  # 挑战副本
                if mmg_times < mmg_energy // 10:
                    level_id = get_level_info(self.mmgLevelBox.currentText())
                    self.mmg_fight(level_id, 1)
                else:
                    self.mmg_stop()
            case 3:  # 挑战好友
                if mmg_times < mmg_vigour // 10 and len(mmg_fight_friends) > 0:
                    level_id, fight_type, _ = mmg_fight_friends.popleft()
                    self.mmg_fight(level_id, fight_type)
                else:
                    self.mmg_wish()
                    self.mmg_stop()

    def mmg_fight(self, level_id: int, fight_type: int):
        send_lines([
            "00000000000000019300000000000000000000000100000000"  # 进入游戏
        ])

        run_later_expect(lambda: send_lines_to_server_back(
            ("123.206.131.63", 3001),
            [
                f"0000008101000075310000000000000000{mmg_game_id}",  # 进入游戏
                f"000000212000007724000000000000000000000004{get_hex(fight_type)}{get_hex(level_id)}00000000",  # 开始挑战
                "000000152000007724000000000000000000000040",  # 开始战斗
                "000000152000007724000000000000000000000080"  # 快速战斗
            ],
            [3, 1, 1, 2]
        ), {0x2717: 1})

    def mmg_get_reward(self, is_success: bool):
        if is_success:
            send_lines([
                "0000000000000020140000000000000000"  # 校验能否翻牌
            ])
            run_later_expect(lambda: send_lines([
                "000000000000002015000000000000000000000000",  # 翻牌
                "000000000000000194000000000000000000"  # 离开游戏
            ]), {0x2014: 1})

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
        friends_ids = [get_hex(friend_id) for friend_id, friend_level in mmg_friends]
        lines = []
        for index in range(0, len(friends_ids), mmg_query_size_max):
            ids = friends_ids[index:index + mmg_query_size_max]
            lines.append(f"00000000000000201A0000000000000000{get_hex(len(ids))}{"".join(ids)}")
        mmg_query_page_max = len(lines)
        send_lines(lines)

    def mmg_stop(self):
        enter_map(0xE4)
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
            run_later_expect(self.ysqs_fight, {0x231D: {"num": 2, "offsets": (0, 28)}})

    def ysqs_fight(self, wjsy_info: tuple[int, int], ssmy_info: tuple[int, int]):
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
        run_later_expect(self.ysqs_upgrade_run, {0x231E: 1})

    def ysqs_upgrade_run(self):
        card_data = ysqs_cards_dict[self.ysqsCardBox.currentData()]
        ysqs_material_cards_dict.pop(card_data["ID"], None)
        required_exp = get_card_max_exp(card_data["星级"]) - card_data["经验"]
        # 计算需要的材料卡牌
        material_ids = []
        for card_id, card_exp in ysqs_material_cards_dict.items():
            material_ids.append(get_hex(card_id))
            required_exp -= card_exp
            if required_exp <= 0:
                break
        max_size = 30  # 每个包最多30张材料
        lines = []
        for index in range(0, len(material_ids), max_size):
            ids = material_ids[index:index + max_size]
            lines.append(f"00000000000000231B0000000000000000{get_hex(card_data["ID"])}{get_hex(len(ids))}{"".join(ids)}")
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
        run_later_expect(self.mlcs_run, {0x2EE4: 1, 0x2B01: 2})

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
            is_fight = fight_times > 0  # 是否挑战
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
                +
                [
                    "000000000000002EF2000000000000000000000000"  # 魔灵背包信息
                ] * is_fight
            )
        else:
            fight_times = (mlcs_energy - mlcs_exp_times * 20) // 10
            is_fight = fight_times > 0  # 是否挑战
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
                +
                [
                    "000000000000002EF2000000000000000000000000"  # 魔灵背包信息
                ] * is_fight
            )

    def mlcs_sell_start(self):
        send_lines([
            f"000000000000002EE40000000000000000{get_hex(user_id)}",  # 魔灵用户信息
            "000000000000002EF2000000000000000000000000"  # 魔灵背包信息
        ])
        run_later_expect(self.mlcs_sell_run, {0x2EE4: 1, 0x2EF2: 1})

    def mlcs_sell_run(self):
        material_ids = [get_hex(sprite_id) for sprite_id in mlcs_material_sprites_dict]
        max_size = 100  # 每个包最多100只材料
        lines = []
        for index in range(0, len(material_ids), max_size):
            ids = material_ids[index:index + max_size]
            lines.append(f"000000000000002F020000000000000000{get_hex(len(ids))}{"".join(ids)}")
        if lines:
            lines.append("000000000000002EF2000000000000000000000000")  # 魔灵背包信息
        send_lines_back(lines)

    def mlcs_upgrade_start(self):
        send_lines([
            f"000000000000002EE40000000000000000{get_hex(user_id)}",  # 魔灵用户信息
            "000000000000002EF2000000000000000000000000"  # 魔灵背包信息
        ])
        run_later_expect(self.mlcs_upgrade_run, {0x2EE4: 1, 0x2EF2: 1})

    def mlcs_upgrade_run(self):
        sprite_data = mlcs_sprites_dict[self.mlcsSpriteBox.currentData()]
        mlcs_material_sprites_dict.pop(sprite_data["ID"], None)
        required_exp = get_sprite_max_exp(sprite_data["星级"], sprite_data["最高等级"]) - sprite_data["经验"]
        # 计算需要的材料魔灵
        material_ids = []
        for sprite_id, sprite_exp in mlcs_material_sprites_dict.items():
            sprite_attr = mlcs_sprites_dict[sprite_id]["属性"]
            material_ids.append(get_hex(sprite_id))
            required_exp -= sprite_exp * (1.5 if sprite_attr == sprite_data["属性"] else 1)
            if required_exp <= 0:
                break
        max_size = 5  # 每个包最多5只材料
        lines = []
        for index in range(0, len(material_ids), max_size):
            ids = material_ids[index:index + max_size]
            lines.append(f"000000000000002EF50000000000000000{get_hex(sprite_data["ID"])}{get_hex(len(ids))}{"".join(ids)}")
        if lines:
            lines.append("000000000000002EF2000000000000000000000000")  # 魔灵背包信息
        send_lines_back(lines, Interval.SLOW)

    def ct_sell_run(self):
        send_lines([
            f"0000000000000003FA0000000000000000000027100000000000147293{get_hex(ct_cooked_dishes_dict[self.ctDishBox.currentText()]["ID"])}00000065"
        ])

    def ct_next_run(self):
        global ct_state, is_connect, is_done, ct_state_since
        if self.client is None or not self.client.is_alive():
            is_connect = False
        else:
            try:
                state = self.client.state_queue.get_nowait()
                if state == "connected":
                    is_connect = True
                elif state == "disconnected":
                    is_connect = False
                elif state == "done":
                    is_done = True
            except Empty:
                pass
        now = monotonic()
        if ct_state_since is None:
            ct_state_since = now
        dwell_ok = now - ct_state_since >= min_show_time
        match ct_state:
            case State.COUNTDOWN:
                next_run = min(countdown_info["下次运行时间"] for countdown_info in ct_cooking_countdowns_dict.values())
                if (next_run - datetime.now()).total_seconds() > 0:
                    return next_run
                else:
                    for countdown_info in ct_cooking_countdowns_dict.values():
                        if countdown_info["下次运行时间"] <= datetime.now():
                            countdown_info["下次运行时间"] += countdown_info["运行间隔"]
                    ct_state_since = now
                    if is_connect:
                        ct_state = State.COOKING
                        return "做菜中"
                    else:
                        ct_state = State.LOGGING_IN
                        return "正在登录"
            case State.LOGGING_IN:
                if is_connect and dwell_ok:
                    ct_state = State.LOGIN_OK
                    ct_state_since = now
                return "正在登录"
            case State.LOGIN_OK:
                if dwell_ok:
                    ct_state = State.COOKING
                    ct_state_since = now
                return "登录成功"
            case State.COOKING:
                if is_done and dwell_ok:
                    is_done = False
                    ct_state = State.DONE
                    ct_state_since = now
                return "做菜中"
            case State.DONE:
                if dwell_ok:
                    ct_state = State.COUNTDOWN
                    ct_state_since = now
                return "做菜完成"
            case _:
                return "准备中"

    def ct_harvest_start(self):
        if not is_running("餐厅"):  # 启动
            self.harvest_button_text = self.ctHarvestButton.text()
            self.ctHarvestButton.setText("停止")
            self.ctDishBox.setEnabled(False)
            self.user_id = user_id  # 启动时的用户ID
            self.password = self.account_dict[self.user_id]  # 启动时的用户密码
            self.start_update_title(
                "餐厅",
                self.user_id,
                "做菜",
                self.ctDishBox.currentText(),
                self.ct_next_run,
            )
            switch_map(user_id, 0x1F)
            run_later_expect(self.ct_harvest_run, {0x3F6: 1})  # 获取餐厅信息
        else:  # 停止
            self.ctHarvestButton.setText(self.harvest_button_text)
            self.ctDishBox.setEnabled(True)
            self.stop_update_title("餐厅")
            self.stop_timer("餐厅")
            if self.client is not None and self.client.is_alive():
                self.client.close()
                self.client = None
            switch_map(user_id, 0x1F)

    def ct_harvest_run(self):
        global ct_state
        cooked_info = ct_cooked_dishes_dict[self.ctDishBox.currentText()]
        need_time = cooked_info["完成时间"]
        expire_time = cooked_info["烧糊时间"]
        interval = need_time + 10  # 增加登录账号时间
        timer_dict = self.timer_pool["餐厅"]
        for dish_pos, dish_info in ct_cooking_dishes_dict.items():
            timer = timer_dict[dish_pos]
            now = datetime.now()
            delay = 0
            if dish_info.get("下次不收菜", False):
                if now.hour < 6:
                    cook_start = datetime(now.year, now.month, now.day, 6, 1)
                    delay = (cook_start - now).total_seconds()
            else:
                cook_time = dish_info["时间"]
                if cook_time < need_time:  # 未成熟的菜
                    delay = need_time - cook_time
                elif cook_time >= expire_time:  # 已糊的菜
                    dish_info["菜已糊"] = True
            ct_cooking_countdowns_dict[dish_pos] = {
                "运行间隔": timedelta(seconds=interval),
                "下次运行时间": now + timedelta(seconds=delay)
            }
            ct_state = State.COUNTDOWN
            timer.set_data(lambda pos=dish_pos: self.ct_harvest_func(pos), interval * 1000, delay * 1000).start()

    def ct_harvest_func(self, pos: int):
        cooked_info = ct_cooked_dishes_dict[self.ctDishBox.currentText()]
        dish_info = ct_cooking_dishes_dict[pos]
        countdown_info = ct_cooking_countdowns_dict[pos]
        now = datetime.now()
        # 首次登录包
        init_lines = [
            f"0000000000000001910000000000000000{get_hex(self.user_id)}0000001F00000000000000000000000000000000",  # 获取地图信息
            f"0000000000000003F60000000000000000{get_hex(self.user_id)}0000001F"  # 获取餐厅信息
        ]
        lines = []
        if not dish_info.pop("下次不收菜", False):
            if dish_info.pop("菜已糊", False):
                lines.append(f"0000000000000003FB0000000000000000{get_hex(dish_info["类型"])}{get_hex(dish_info["ID"])}{get_hex(pos)}")  # 处理糊菜
            else:
                lines.append(f"0000000000000003FD0000000000000000{get_hex(cooked_info["类型"])}{get_hex(dish_info["ID"])}{get_hex(pos)}{get_hex(cooked_info["位置"])}")  # 收菜
        if now.hour >= 6:
            lines.append(f"0000000000000003F90000000000000000{get_hex(dish_info["类型"])}{get_hex(pos)}")  # 做菜
        else:
            dish_info["下次不收菜"] = True
            cook_start = datetime(now.year, now.month, now.day, 6, 1)
            self.timer_pool["餐厅"][pos].restart(cook_start)
            countdown_info["下次运行时间"] = cook_start
        send_lines_by_client((self.user_id, self.password), init_lines, lines)

    def ct_cook_after(self, dish_id: int, dish_type: int, step: int, is_refresh: bool = False):
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
        send_lines([
            f"000000000000002B1A0000000000000000{get_hex(num)}" for num in range(1, 11)
        ])

    def bh_run(self):
        send_lines([
            "0000000000000022F9000000000000000000003E95"
        ])

    def kll_run(self):
        send_lines([
            "0000000000000020D20000000000000000"
        ])

    def kll_finish(self, body):
        send_lines([
            f"0000000000000020D30000000000000000{body}"
        ])

    def kll_reward(self):
        send_lines([
            "0000000000000020D90000000000000000"
        ])

    def ppl_start(self):
        if not self.ppl_thread.is_start:  # 启动
            self.ppl_button_text = self.pplPlayButton.text()
            self.ppl_thread.start()
        else:  # 停止
            self.ppl_thread.stop()

    def hs_next_run(self):
        global hs_state, hs_state_since
        now = monotonic()
        if hs_state_since is None:
            hs_state_since = now
        dwell_ok = now - hs_state_since >= min_show_time
        match hs_state:
            case State.COUNTDOWN:
                next_run = hs_countdown_info["下次运行时间"]
                if (next_run - datetime.now()).total_seconds() > 0:
                    return next_run
                else:
                    hs_countdown_info["下次运行时间"] += hs_countdown_info["运行间隔"]
                    hs_state = State.RUNNING
                    hs_state_since = now
                    return "鉴定中"
            case State.RUNNING:
                if dwell_ok:
                    hs_state = State.DONE
                    hs_state_since = now
                return "鉴定中"
            case State.DONE:
                if dwell_ok:
                    hs_state = State.COUNTDOWN
                    hs_state_since = now
                return "鉴定完成"
            case _:
                return "准备中"

    def hs_start(self):
        def start(delay: int):
            global hs_state, hs_countdown_info
            hs_countdown_info = {
                "运行间隔": timedelta(minutes=1),
                "下次运行时间": datetime.now() + timedelta(seconds=delay)
            }
            hs_state = State.COUNTDOWN
            self.timer_pool["化石"].start(delay * 1000)

        if not is_running("化石"):  # 启动
            self.hs_button_text = self.hsIdentifyButton.text()
            self.hsIdentifyButton.setText("停止")
            self.start_update_title(
                "化石",
                None,
                "鉴定",
                None,
                self.hs_next_run
            )
            send_lines([
                "0000000000000023280000000000000000"  # 化石鉴定冷却信息
            ])
            run_later_expect(start, {0x2328: {"offsets": (8,)}})
        else:
            self.hs_stop()

    def hs_run(self):
        def run(fossils_num: int):
            if fossils_num > 0:
                send_lines([
                    "0000000000000004DA0000000000000000000000740000000000000000"  # 鉴定化石
                ])
                if fossils_num > 1:
                    return
            self.hs_stop()
            if not is_shown_msg("化石"):
                alert_msg("已鉴定完化石，暂未获得瓦尔卡火龙蛋")

        send_lines([
            "00000000000000077B0000000000000000000000010002EA70"  # 获取化石数量
        ])
        run_later_expect(run, {0x77B: {"items": (0x2EA70,)}})

    def hs_stop(self):
        if is_running("化石"):
            self.hsIdentifyButton.setText(self.hs_button_text)
            self.stop_update_title("化石")
            self.stop_timer("化石")

    def ysqs_next_run(self):
        global ysqs_state, ysqs_state_since, ysqs_state_queue, ysqs_task
        now = monotonic()
        if ysqs_state_since is None:
            ysqs_state_since = now
        dwell_ok = now - ysqs_state_since >= min_show_time
        match ysqs_state:
            case State.COUNTDOWN:
                if ysqs_state_queue and (state := ysqs_state_queue.popleft()).endswith("中"):
                    ysqs_task = state[:-1]
                    ysqs_state = State.RUNNING
                    ysqs_state_since = now
                    return state
                return self.ysqs_next_run_time()[1]
            case State.RUNNING:
                if dwell_ok and ysqs_state_queue and (finish_state := f"{ysqs_task}完成") in ysqs_state_queue:
                    ysqs_state_queue.remove(finish_state)
                    ysqs_state = State.DONE
                    ysqs_state_since = now
                return f"{ysqs_task}中"
            case State.DONE:
                if dwell_ok:
                    ysqs_state = State.COUNTDOWN
                    ysqs_state_since = now
                return f"{ysqs_task}完成"
            case _:
                return "准备中"

    def ysqs_arena_start(self):
        def start(data: dict):
            global ysqs_countdown_info, ysqs_state, ysqs_state_queue, ysqs_task, ysqs_stones_num, ysqs_free_left, has_stones
            last_fight, = data[0x22B2]
            (talent_level, last_grasp, ysqs_stones_num), = data[0x231E]
            ysqs_countdown_info = {
                "下次竞技时间": datetime.fromtimestamp(last_fight) + timedelta(minutes=10),
                "下次领悟时间": datetime.fromtimestamp(last_grasp) + timedelta(minutes=get_talent_cd(talent_level))
            }
            ysqs_state = State.COUNTDOWN
            ysqs_state_queue.clear()
            ysqs_task = ""
            now = datetime.now()
            # 免费次数：每天前3次免费。若下次领悟时间在未来 → 今天至少已用1次免费（还剩≤2次）
            ysqs_free_left = 2 if ysqs_countdown_info["下次领悟时间"] > now else 3
            # 初始有领悟石 → 后续用 stones_num 查询值判定终止，减少1次等待冷却
            has_stones = ysqs_stones_num > 0
            _, next_run = self.ysqs_next_run_time()
            # 最近时间已到点则立即运行（0 延迟），否则按 datetime 到点触发
            self.timer_pool["元素骑士"].start(0 if next_run <= now else next_run)

        if not is_running("元素骑士"):  # 启动
            self.ysqs_button_text = self.ysqsArenaFightButton.text()
            self.ysqsArenaFightButton.setText("停止")
            self.start_update_title(
                "元素骑士",
                None,
                "竞技场",
                "挑战",
                self.ysqs_next_run
            )
            send_lines([
                "0000000000000022B2000000000000000000000270",  # 上次挑战时间
                "00000000000000231E000000000000000000000000"  # 天赋等级、上次领悟天赋时间
            ])
            run_later_expect(start, {0x22B2: {"offsets": (4,)}, 0x231E: {"offsets": (36, 40), "items": (0x19872A,)}})
        else:
            self.ysqs_arena_stop()

    def ysqs_arena_run(self):
        def run(data: dict):
            global ysqs_stones_num, ysqs_free_left, has_stones, ysqs_arena_ctx, is_arena_choose, is_arena_run
            arena_times, = data[0x22B2]
            rank, = data[0x2339]
            players_info, = data[0x2324]
            # 天赋等级、上次领悟时间、领悟石
            (talent_level, last_grasp, stones_num), = data[0x231E]
            now = datetime.now()
            # 天赋领悟：仅当冷却到（下次领悟时间已到）才发包
            next_grasp = ysqs_countdown_info.get("下次领悟时间")
            if next_grasp is not None and next_grasp <= now:
                # 启用石头终止时：免费次数已用光 且 当前无领悟石 → 直接终止，不再发领悟包（省1轮冷却等待）
                if stones_num == ysqs_stones_num - 1:
                    ysqs_free_left = 0
                else:
                    ysqs_free_left -= 1
                ysqs_stones_num = stones_num
                if has_stones and ysqs_free_left == 0 and stones_num == 0:
                    ysqs_countdown_info["下次领悟时间"] = None
                    self.ysqs_update_interval()
                else:
                    ysqs_state_queue.append("领悟中")
                    send_lines([
                        "00000000000000231A0000000000000000"  # 领悟天赋
                    ])
                    run_later_expect(lambda state: self.ysqs_talent_next(talent_level, state), {0x231A: {"offsets": (0,)}})
            # 竞技场挑战：仅当它自己的下次时间已到 且 次数>0 才挑战
            # （避免被领悟到点触发时误发挑战包 / 重复触发导致双「挑战中」）
            next_arena = ysqs_countdown_info.get("下次竞技时间")
            if next_arena is not None and next_arena <= now:
                if arena_times == 0:
                    ysqs_countdown_info["下次竞技时间"] = None
                    self.ysqs_update_interval()
                else:
                    ysqs_state_queue.append("挑战中")
                    if rank <= 100:
                        # 已进前100无排名收益，固定挑战一名看门玩家兜底
                        self.ysqs_arena_fight(262449414, arena_times)
                    else:
                        # 排名>100：按评分选对手。无正分时不干等，刷新推荐多挑（前3轮预热，第4轮起按策略挑）
                        opponents = [(players_info[i], players_info[i + 1]) for i in range(0, len(players_info), 2)]
                        ysqs_arena_ctx = {
                            "strategy": None, "warmup": 0, "stronger": 0, "weaker": 0, "total": 0,
                        }
                        is_arena_choose = True  # 竞技场评分/挑人开始，异步期间阻止误判"全部完成"
                        self.ysqs_arena_choose(opponents, arena_times, 1)
            is_arena_run = False  # 本轮查询包已处理完，允许下一次触发

        global is_arena_run
        if is_arena_run or is_arena_choose:
            return
        is_arena_run = True
        send_lines([
            "0000000000000022B200000000000000000000026F",  # 剩余挑战次数
            f"0000000000000023390000000000000000{get_hex(user_id)}",  # 声望、排名信息
            "00000000000000231E000000000000000000000000",  # 天赋等级、上次领悟天赋时间
            "0000000000000023240000000000000000"  # 推荐玩家
        ])
        run_later_expect(run, {
            0x22B2: {"offsets": (4,)},
            0x2339: {"offsets": (4,)},
            0x231E: {"offsets": (36, 40), "items": (0x19872A,)},  # 天赋等级、上次领悟时间、领悟石
            0x2324: {"offsets": tuple(offset for page in range(6) for offset in (4 + page * 28, 28 + page * 28))}  # 推荐玩家的ID、排名
        })

    def ysqs_talent_next(self, talent_level: int, state: int):
        if state <= 1:  # 0：成功，1：失败，2：道具不够，3：已经满级，4：冷却时间未到，5：未转职
            ysqs_countdown_info["下次领悟时间"] = datetime.now() + timedelta(minutes=get_talent_cd(talent_level + 1 - state))
        else:
            ysqs_countdown_info["下次领悟时间"] = None
        ysqs_state_queue.append("领悟完成")
        self.ysqs_update_interval()

    def ysqs_arena_choose(self, opponents, arena_times, round_num):
        # 每轮：重查自己最新攻防(实时)、自己最新排名，并逐个查推荐玩家攻防。
        # 预热前3次只统计"对手强度 vs 我强度"来判定段位策略；第4轮起按策略从当批挑对手。
        # 注：服务器只认最近一次 0x2324 回包里的玩家，绝不跨批累积候选。
        opp_ranks = dict(opponents)

        def evaluate(data):
            my_rank, = data[0x2339]  # 当前自己排名（实时）
            per_opp = data[0x231E]   # 按序收取：第1项必为自己(全0查询，米米号字段为0)，其后为各推荐玩家
            if not per_opp:
                self.ysqs_arena_next(arena_times)
                return
            mamin, mamax, mdmin, mdmax = per_opp[0][1:]  # 自己的攻防区间
            my_strength = mamin + mamax + mdmin + mdmax
            ctx = ysqs_arena_ctx
            # 本批评分数据
            logger.info(f"[竞技场] round={round_num} phase={"预热" if ctx["warmup"] < 3 else "正式"} "
                  f"strategy={ctx["strategy"]} my_rank={my_rank} "
                  f"我(攻{mamin}-{mamax} 防{mdmin}-{mdmax} 强度{my_strength})")
            # 当批有效对手：在推荐名单里、攻防区间合法
            rows = []
            for oid, a0, a1, d0, d1 in per_opp[1:]:
                rnk = opp_ranks.get(oid)
                if rnk is None or d1 < d0 or a1 < a0:
                    continue
                win_rate = (
                    0.5 * get_win_rate(mamin, mamax, d0, d1)
                    + 0.5 * (1 - get_win_rate(a0, a1, mdmin, mdmax))
                )
                win_rank = rnk if rnk < my_rank else my_rank
                rank_gain = max(0, max(my_rank - 100, 0) - max(win_rank - 100, 0))
                # 单个对手评分
                logger.info(f"  对手{oid} rank={rnk} 攻{a0}-{a1} 防{d0}-{d1} 胜率={win_rate:.3f} "
                      f"赢后名次={win_rank} 名次收益={rank_gain} score={win_rate * rank_gain:.3f} 强度={a0 + a1 + d0 + d1}")
                rows.append((oid, win_rate, rank_gain, a0 + a1 + d0 + d1))
            if ctx["warmup"] < 3:
                # 预热：只统计对手强度 vs 我，不挑战
                for _, _, _, ost in rows:
                    if ost > my_strength:
                        ctx["stronger"] += 1
                    elif ost < my_strength:
                        ctx["weaker"] += 1
                    ctx["total"] += 1
                ctx["warmup"] += 1
                if ctx["warmup"] >= 3:
                    ctx["strategy"] = self.ysqs_arena_detect_strategy(my_rank)
                self.ysqs_arena_refresh(arena_times, round_num + 1)
                return

            fight_id = None
            if ctx["strategy"] == "rank":
                if my_rank <= 100:
                    # 已进前100：打固定弱玩家保证赢
                    fight_id = 262449414
                else:
                    # 冲前100：看名次收益，但要求胜率>0 避免选必败
                    # 冲前100：优先名次收益，收益相同时再挑胜率更高者
                    cand, c_key = None, (-1, -1)
                    for oid, wr, rg, ost in rows:
                        if wr > 0 and (rg, wr) > c_key:
                            cand, c_key = oid, (rg, wr)
                    fight_id = cand
            elif ctx["strategy"] == "win":
                # 限名次不变(rank_gain==0)；胜率优先，胜率相同时挑强度最低的确保稳赢，留在靠后段捶弱的
                cand, c_key = None, (-1.0, float("inf"))
                for oid, wr, rg, ost in rows:
                    if rg == 0 and (wr, -ost) > c_key:
                        cand, c_key = oid, (wr, -ost)
                fight_id = cand
            else:  # balance
                cand, c_sc = None, 0.0
                for oid, wr, rg, ost in rows:
                    sc = wr * rg
                    if sc > c_sc:
                        cand, c_sc = oid, sc
                fight_id = cand

            if fight_id is not None:
                # 选中目标
                logger.info(f"[竞技场] round={round_num} 选中挑战 {fight_id}")
                self.ysqs_arena_fight(fight_id, arena_times)
            else:
                logger.info(f"[竞技场] round={round_num} 无合适目标，刷新下一批")
                self.ysqs_arena_refresh(arena_times, round_num + 1)

        send_lines([
            "00000000000000231E000000000000000000000000",  # 自己最新攻防
            *[f"00000000000000231E0000000000000000{get_hex(opp_id)}" for opp_id, _ in opponents],  # 推荐玩家攻防
            f"0000000000000023390000000000000000{get_hex(user_id)}"  # 自己最新排名
        ])
        run_later_expect(evaluate, {
            0x231E: {"num": len(opponents) + 1, "offsets": (0, 44, 48, 52, 56)},
            0x2339: {"num": 1, "offsets": (4,)},
        })

    def ysqs_arena_fight(self, opp_id, arena_times):
        send_lines([
            f"0000000000000023230000000000000000{get_hex(opp_id)}"  # 挑战玩家
        ])
        self.ysqs_arena_next(arena_times)

    def ysqs_arena_refresh(self, arena_times, round_num):
        # 发推荐玩家包拿下一批6个玩家，再继续评分循环（不携带上一批任何候选）
        send_lines(["0000000000000023240000000000000000"])

        def on_newbuf(players_info,):
            opponents = [
                (players_info[i], players_info[i + 1])
                for i in range(0, len(players_info), 2)
                if players_info[i]
            ]
            if opponents:
                self.ysqs_arena_choose(opponents, arena_times, round_num)
            else:
                self.ysqs_arena_next(arena_times)

        run_later_expect(on_newbuf, {
            0x2324: {"offsets": tuple(offset for page in range(6) for offset in (4 + page * 28, 28 + page * 28))}
        })

    def ysqs_arena_detect_strategy(self, my_rank):
        # 其余才按3次预热统计：≥2/3 对手强于我 → rank；≥2/3 弱于我 → win；否则 balance
        ctx = ysqs_arena_ctx
        if ctx["total"] == 0:
            return "balance"
        if my_rank <= 500 or ctx["stronger"] / ctx["total"] >= 2 / 3:
            return "rank"
        if my_rank >= 2000 or ctx["weaker"] / ctx["total"] >= 2 / 3:
            return "win"
        return "balance"

    def ysqs_arena_next(self, arena_times):
        global is_arena_choose
        is_arena_choose = False  # 挑选已结束(挑战发出或放弃)，解除"进行中"标记，允许判定全部完成
        # 剩>1次排下一轮10分钟冷却；打完最后1次(或已无次数)直接终止竞技场（天赋继续）
        if arena_times > 1:
            ysqs_countdown_info["下次竞技时间"] = datetime.now() + timedelta(minutes=10)
        else:
            ysqs_countdown_info["下次竞技时间"] = None
        ysqs_state_queue.append("挑战完成")
        self.ysqs_update_interval()

    def ysqs_next_run_time(self, future_only: bool = False):
        # 最近（剩余时间最小）的运行时间及键名；无则 ("全部完成", None)
        # future_only=True 只取未来时间(调度用)；False 连已到点的过去时间也算(标题显示/启动判断用)
        now = datetime.now()
        pending = [
            (task, next_run) for task, next_run in ysqs_countdown_info.items()
            if next_run is not None and (not future_only or next_run > now)
        ]
        return min(pending, key=lambda item: item[1]) if pending else ("全部完成", None)

    def ysqs_update_interval(self):
        # 每次运行后：根据2条倒计时动态调整单个任务的间隔（标题显示最近的一条）。
        # 只取未来的时间设 interval：已到点的任务由当前 run 就地处理。若把过去时间(如"下次领悟时间"
        # 还在等回包、尚未更新)设进去，from_data 会转成 0ms 让定时器立即再触发，导致刚启动(领悟/挑战都到点)
        # 且名次在前100时重复发查询包。
        task, next_run = self.ysqs_next_run_time(future_only=True)
        if next_run is not None:
            self.timer_pool["元素骑士"].set_interval(next_run)
        elif not is_arena_choose and not is_shown_msg("元素骑士"):
            self.ysqs_arena_stop()
            alert_msg("已完成元素骑士竞技场挑战和天赋领悟")

    def ysqs_arena_stop(self):
        if is_running("元素骑士"):
            self.ysqsArenaFightButton.setText(self.ysqs_button_text)
            self.stop_update_title("元素骑士")
            self.stop_timer("元素骑士")


class AdvanceDialog(QDialog, Ui_AdvanceDialog):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        for card_name in card_advance_dict:
            item = QListWidgetItem(card_name)
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
                f"{card_name} 共计 {card_count} 张"
                for card_name, card_count in consume_count.items()
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
                f"{get_card_info(card_type)["名称"]} Lv.{get_card_max_level(get_card_info(card_type)["星级"])} 需要 {card_count} 张，拥有 {owned_count[card_type]} 张"
                for card_type, card_count in need_count.items()
            )
            info(self, "提示", f"{self.card_name} 进阶到 {self.target_card_name} 材料不足：\n{need_text}")


class PPLThread(QThread):
    def __init__(self):
        super().__init__()
        self.bot = None
        self.is_start = False  # 下一关复活判断用
        self.game_socket = None  # 复用的游戏 socket 副本（fromfd dup），断连/stop 置 None 时重建

    def init(self):
        if self.bot is None:
            self.bot = Bot(self.send, user_id)
            self.bot.listen()
            self.bot.on_end_callback = self.stop
            self.bot.on_level_start_callback = self.resume

    def send(self, data: bytes):
        if game_socket_num == 0:
            return
        if self.game_socket is None:
            try:
                self.game_socket = fromfd(game_socket_num, AF_INET, SOCK_STREAM)
                self.game_socket.settimeout(1.0)
            except Exception as e:
                logger.error(f"[泡泡龙] 创建 socket 失败(已跳过): {e}")
                return
        try:
            self.game_socket.send(data)
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError) as e:
            # 连接已断开：丢弃副本，下次 send 自动重建
            logger.error(f"[泡泡龙] 发包失败，重置 socket: {e}")
            try:
                self.game_socket.close()
            except Exception:
                pass
            self.game_socket = None
        except TimeoutError as e:
            # 仅 1s 内未发完，连接仍有效，保留副本供复用
            logger.error(f"[泡泡龙] 发包超时(已跳过，不阻塞UI): {e}")
        except Exception as e:
            logger.error(f"[泡泡龙] 发包失败(已跳过，不阻塞UI): {e}")

    def run(self):
        while not self.isInterruptionRequested():
            if self.bot is None or not self.is_start:
                sleep(0.05)  # 未就绪/暂停时空转，避免忙等
                continue
            logger.info(f"[泡泡龙] maybe_shoot 进入（seq≈{getattr(self.bot, "seq", 0)}）")
            try:
                self.bot.maybe_shoot()
            except:
                logger.error("[泡泡龙] maybe_shoot 抛出异常已被隔离，本拍跳过")
            finally:
                logger.info(f"[泡泡龙] maybe_shoot 退出")
            sleep(0.5)

    def start(self):
        if game_socket_num == 0:
            logger.info("[泡泡龙] 尚未识别游戏服务器 socket（请先手动进入泡泡龙并开始游戏）")
            return
        self.is_start = True  # ★ 用户意图：想要自动打（用于 31114 软过渡后下一关复活判断）
        self.bot.start()
        window.pplPlayButton.setText("停止")
        if not self.isRunning():
            super().start()  # 启动 QThread 的 run 循环

    def stop(self):
        if self.is_start:
            self.is_start = False  # ★ 用户主动停止：下一关 797E 不再自动复活
            window.pplPlayButton.setText(window.ppl_button_text)
            if self.bot is not None:
                self.bot.running = False
            if self.game_socket is not None:
                try:
                    self.game_socket.close()
                except Exception:
                    pass
                self.game_socket = None
            logger.info("[泡泡龙] 自动通关已停止")

    def resume(self):
        if not self.is_start or self.bot is None:
            return
        if not self.isRunning():
            super().start()  # 线程已退出则重新拉起
        self.bot.running = True
        logger.info("[泡泡龙] 下一关开始：自动复活发射循环")


class SendThread(QThread):
    # 非驻留线程：启动后消费队列，连续 3 秒无新任务即自动退出；也可调用 stop() 提前终止
    def __init__(self):
        super().__init__()
        self.lock = Lock()
        self.max_size = 1000
        self.queue: deque[tuple[list, int, Callable | None]] = deque()  # 待发任务：(lines, interval, progress)

    def stop(self):
        with self.lock:
            self.queue.clear()
        self.requestInterruption()
        self.wait()

    def put_data(self, lines: list, interval: int, progress: Callable | None = None):
        if len(self.queue) < self.max_size:
            with self.lock:
                self.queue.append((lines, interval, progress))

    def send_lines(self, lines: list, interval: int, progress: Callable | None = None):
        send_lines(lines, interval, progress)

    def run(self):
        last_send = monotonic()
        while not self.isInterruptionRequested():
            with self.lock:
                data = self.queue.popleft() if self.queue else None
            if data is not None:
                self.send_lines(*data)
                last_send = monotonic()
            elif monotonic() - last_send >= 3:
                break
            else:
                sleep(0.1)  # 空闲休眠，不忙等；被中断或超时后退出


class SendExThread(SendThread):
    def send_lines(self, lines: list, interval: int, progress: Callable | None = None):
        if not window.socketCheckBox.isChecked():
            send_lines(lines, interval, progress)
        else:
            send_lines_to_socket(lines, interval)


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
    result = Signal(bool, str, str)

    def __init__(self):
        super().__init__()
        self.is_first = True

    def run(self):
        global available_cdn_prefix
        version, description = "", ""
        for cdn_prefix in cdn_prefixs:
            url = f"{cdn_prefix}{version_url}"
            try:
                res = get(url, timeout=(3, 5))
                res.raise_for_status()
            except:
                continue
            else:
                version, description = [loads(res.text)["project"][key] for key in ("version", "description")]
                available_cdn_prefix = cdn_prefix
                break
        self.result.emit(self.is_first, version, description)
        self.is_first = False


class ClearThread(QThread):
    result = Signal()

    def run(self):
        for cache_dir in caches_dir.glob("*/"):
            try:
                rmtree(cache_dir)
            except:
                pass
        self.result.emit()


class RunTimer(QTimer):
    signal = Signal()

    def __init__(self, func: Callable | None = None, interval: int | float = 1000, delay: int | float = 300, is_precise: bool = False):
        super().__init__()
        super().timeout.connect(self.on_timeout)
        if is_precise:
            self.setTimerType(Qt.TimerType.PreciseTimer)
        self.set_data(func, interval, delay)

    def set_data(self, func: Callable | None, interval: int | float, delay: int | float):
        if (old_func := getattr(self, "func", None)) is not None:
            try:
                self.signal.disconnect(old_func)
            except (TypeError, RuntimeError):
                pass
        if func is not None:
            self.signal.connect(func)
            self.func = func
        self.interval = int(interval)
        self.delay = int(delay)
        self.is_restart = False
        return self

    @staticmethod
    def from_data(data: int | float | datetime):
        if isinstance(data, datetime):
            msec = int((data - datetime.now()).total_seconds() * 1000)
        else:
            msec = int(data)
        return max(0, msec)

    def set_timer_interval(self):
        super().setInterval(self.interval)
        return self

    def set_interval(self, interval: int | float):
        if self.interval != interval:
            self.interval = self.from_data(interval)
            self.set_timer_interval()
        return self

    def start(self, delay: int | float | datetime | None = None):
        if delay is not None and self.delay != delay:
            self.delay = self.from_data(delay)
        self.is_first = True
        super().start(self.delay)
        return self

    def restart(self, delay: int | float | datetime):
        super().stop()
        self.is_restart = True
        return self.start(delay)

    def on_timeout(self):
        self.is_restart = False
        self.signal.emit()
        if self.is_first and not self.is_restart:
            self.is_first = False
            self.set_timer_interval()


class Packet:
    def __init__(self, packet: str | bytearray | bytes | buffer | None = None, cmd_id: int | None = None,
                 body: str | bytearray | bytes | buffer | None = None):
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
    def to_bytearray(data: str | bytearray | bytes | buffer | None):
        if data is None:
            return bytearray()
        if isinstance(data, str):
            # 支持带标注的输入，如：“绿：0000... {00003E81:药水ID}{0001869F:药水数量}”
            data = sub(r"{([^}:]*)(?::[^}]*)?}", r"\1", data.split("：", 1)[-1])
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

    def encrypt(self, is_get_serial_num: bool = True):
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
        if len(self.body) == 0:
            return self
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


# ================================================== 游戏功能方法 ==================================================
def get_lamu_level(value: int):
    return bisect_right(lamu_thresholds, value) + 1


def get_max_skill_level(level: int):
    return (level + 1) // 2


def get_last_skill_level(level: int):
    if level < 3:
        return 1
    else:
        return get_max_skill_level(level) - 1


def get_skill_id(skill_level: int, skill_type: str):
    match skill_type:
        case "火":
            return 3 * skill_level - 2
        case "水":
            return 3 * skill_level - 1
        case "木":
            return 3 * skill_level
        case _:
            return 1


def get_card_max_exp(star: int):
    # n星卡牌经验上限
    star = min(star, 6)
    return 120 * star ** 2 + 28 * star - 4


def get_card_max_level(star: int):
    # n星卡牌等级上限
    star = min(star, 6)
    return 10 * star


def get_card_provided_exp(star: int):
    # n星1级卡牌提供的经验值
    star = min(star, 6)
    return 5 * star - 2


def get_card_level(star: int, exp: int):
    # n星卡牌根据总经验计算等级
    star = min(star, 6)
    base = 2 * star + 5
    return floor((-base + sqrt(base ** 2 + 4 * exp)) / 2) + 1


def get_talent_cd(level: int):
    # 根据天赋等级计算冷却时间分钟数
    for minutes, count in ysqs_talent_cd_thresholds:
        if level <= count:
            return minutes
        level -= count
    return 60


def get_sprite_max_exp(star: int, max_level: int):
    # n星魔灵经验上限
    return mlcs_factors[star - 1] * pow((max_level - 1) / 98, 2.5)


# ================================================== 常规功能方法 ==================================================
def path(file: str):
    return str(base_dir / file)


def show_data(data_type: str, socket_num: int, packet: Packet):
    if is_window_init:
        if QThread.currentThread() is QApplication.instance().thread():
            window.add_data(data_type, socket_num, packet.cmd_id, analyse(packet.cmd_id), packet.data().hex().upper())
        else:
            window.show_signal.emit(data_type, socket_num, packet.cmd_id, analyse(packet.cmd_id), packet.data().hex().upper())


def info(parent, title: str, msg: str, buttons: int = Button.OK):
    return QMessageBox.information(parent, title, msg, QMessageBox.StandardButton(buttons))


def alert_msg(msg: str):
    push_cmd(f"alertMsg|{msg}")


def alert_reward(data: tuple | int, prefix: str = "", suffix: str = ""):
    items = data if isinstance(data, tuple) else (data, 1)
    seg = "|".join([prefix, suffix, ",".join(str(x) for x in items)])
    push_cmd(f"alertReward|{seg}")


def enter_map(_map_id: int, map_type: int = 0):
    push_cmd(f"enterMap|{_map_id},{map_type}")  # 进地图，已在地图时不会重新进，不会提示已在地图


def switch_map(_map_id: int, map_type: int = 0):
    push_cmd(f"switchMap|{_map_id},{map_type}")  # 进地图，已在地图时不会重新进，会提示已在地图，如果是进入餐厅则不管在不在都会重新进


def get_item_info(item_id: int, func: Callable | None = None):
    if func is not None:
        item_info_callbacks[item_id] = func
    push_cmd(f"getItemInfo|{item_id}")


def dispatch_item_info(cmd: str, payload: dict):
    if cmd != "getItemInfo":
        return
    if not isinstance(payload, dict) or "id" not in payload:
        return
    item_id = int(payload["id"])
    func = item_info_callbacks.pop(item_id, None)
    if func is not None:
        func(payload)


def run_later(func: Callable, delay: int = 300):
    QTimer.singleShot(delay, func)


def run_later_expect(func: Callable, expect: dict):
    # 等待到期望包之后运行
    # expect：{cmd_id：{"num"：数量, "offsets"：(offset, ...), "items"：(item, ...)}}
    # expect：{cmd_id：数量} 仅等待收齐指定数量的包
    # offsets：按绝对字节偏移取 4 字节整数
    # items：4 字节步进遍历包体，找到与 marker 匹配的 4 字节后，返回其后的 4 字节整数（取首个匹配）
    pending_waits.append({
        "expect": expect,
        "counts": {cmd_id: 0 for cmd_id in expect},
        "data": {cmd_id: [] for cmd_id in expect},
        "func": func,
    })


def is_need_data(expect_info: dict | int):
    return isinstance(expect_info, dict) and ("offsets" in expect_info or "items" in expect_info)


def find_item_value(buf: bytes, item: int):
    # 4 字节步进遍历包体，找到与 item 匹配的 4 字节后，返回其后的 4 字节整数；取首个匹配；未找到返回 0
    for offset in range(0, len(buf) - 7, 4):
        if get_int(buf, offset) == item:
            return get_int(buf, offset + 4)
    return 0


def check_waiting_packets(packet: Packet):
    # 检查待匹配包
    for index in range(len(pending_waits) - 1, -1, -1):
        wait_info = pending_waits[index]
        expect, counts, data, func = [wait_info[key] for key in ("expect", "counts", "data", "func")]
        if packet.cmd_id in expect:
            counts[packet.cmd_id] += 1
            expect_info = expect[packet.cmd_id]
            if is_need_data(expect_info):
                values = []
                if "offsets" in expect_info:
                    values += [get_int(packet.body, offset) for offset in expect_info["offsets"]]
                if "items" in expect_info:
                    values += [find_item_value(packet.body, item) for item in expect_info["items"]]
                data[packet.cmd_id].append(values[0] if len(values) == 1 else tuple(values))
            # 检查是否所有 cmd_id 都集齐
            if all(
                counts[cmd_id] >= (expect_info.get("num", 1) if isinstance(expect_info, dict) else expect_info)
                for cmd_id, expect_info in expect.items()
            ):
                if len(expect) == 1:
                    cmd_id, = expect
                    run_later(lambda args=data[cmd_id]: func(*args), 0)
                elif any(is_need_data(expect_info) for expect_info in expect.values()):
                    run_later(lambda args=data: func(args), 0)
                else:
                    run_later(func, 0)
                pending_waits.pop(index)


def clamp(value: int, lower: int, upper: int):
    return min(max(value, lower), upper)


def get_win_rate(x1: int, x2: int, y1: int, y2: int) -> float:
    # P(X > Y)，X ~ U[x1,x2]，Y ~ U[y1,y2]（连续均匀。攻防区间 min==max 时按退化处理）
    if y2 <= y1:
        return clamp((x2 - y1) / (x2 - x1), 0, 1) if x2 > x1 else float(x1 > y1)
    if x2 <= x1:
        return clamp((x1 - y1) / (y2 - y1), 0, 1) if y2 > y1 else float(x1 > y1)
    # 通用：1/(x2-x1) ∫_{x1}^{x2} clip((t-y1)/(y2-y1), 0, 1) dt 的分段解析值
    total = 0.0
    p, q = max(x1, y1), min(x2, y2)
    if q > p:
        total += ((q - y1) ** 2 - (p - y1) ** 2) / (2 * (y2 - y1))  # 线性段 (t-y1)/(y2-y1)
    if x2 > y2:
        total += x2 - max(x1, y2)  # t>=y2 段钳制为 1
    return total / (x2 - x1)


def get_int(buf: bytes, offset: int = 0, bytes_num: int = 4):
    if offset + bytes_num > len(buf):
        return 0
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


def get_bytes(buf: bytes, offset: int = 0, length: int = 0):
    return buf[offset:offset + length]


def get_hex(value: int, bytes_num: int = 4):
    return f"{value:0{2 * bytes_num}X}"


def get_name(buf: bytes, offset: int = 0):
    return unpack_from("16s", buf, offset)[0].rstrip(b"\x00").decode()


def get_password(pwd: str):
    return f"{pwd[8:16]}{pwd[0:8]}{pwd[24:32]}{pwd[16:24]}".encode().hex()


def process_data(packet: Packet):
    match packet.cmd_id:
        case 407:  # 小游戏提交分数
            score = get_int(packet.body, 4)
            set_int(packet.body, int(score ** 2 + datetime.now().day ** 2), 8)


def send_lines(lines: list, interval: int = Interval.INSTANT, progress: Callable | None = None):
    last_index = len(lines) - 1
    for index, data in enumerate(lines):
        if QThread.currentThread().isInterruptionRequested():
            break
        if isinstance(data, str) and len(data) < 17:
            if 0 < len(data) < 5 and data.isdigit():
                sleep(int(data) / 1000)
            continue
        if isinstance(data, dict):
            (cmd_id, body), = data.items()
            packet = Packet(cmd_id=cmd_id, body=body)
        else:
            packet = Packet(data)
        process_data(packet)
        with lock:
            packet.encrypt()
        send(login_socket_num, packet.data(), packet.length)
        if is_show_send:
            packet.decrypt()
            show_data(Show.SEND, login_socket_num, packet)
        if progress is not None:
            progress(index)
        if interval > 0 and index < last_index:
            sleep(interval / 1000)


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


def send_lines_back(lines: list, interval: int = Interval.NORMAL, progress: Callable | None = None):
    window.send_thread.put_data(lines, interval, progress)
    if not window.send_thread.isRunning():
        window.send_thread.start()


def send_lines_back_ex(lines: list, interval: int = Interval.NORMAL, progress: Callable | None = None):
    window.send_ex_thread.put_data(lines, interval, progress)
    if not window.send_ex_thread.isRunning():
        window.send_ex_thread.start()


def send_lines_to_server_back(address: tuple[str, int], lines: list, wait_recv_nums: list | None = None):
    if not window.send_to_server_thread.isRunning():
        window.send_to_server_thread.set_data(address, lines, wait_recv_nums)
        window.send_to_server_thread.start()


def is_running(name: str):
    res = False
    match name:
        case "餐厅":
            res = window.ctHarvestButton.text() == "停止"
        case "化石":
            res = window.hsIdentifyButton.text() == "停止"
        case "元素骑士":
            res = window.ysqsArenaFightButton.text() == "停止"
        case _:
            if name in window.timer_pool:
                timer = window.timer_pool[name]
                if isinstance(timer, dict):
                    res = any(isinstance(item, QTimer) and item.isActive() for item in timer.values())
                elif isinstance(timer, tuple):
                    res = any(isinstance(item, QTimer) and item.isActive() for item in timer)
                else:
                    res = isinstance(timer, QTimer) and timer.isActive()
            else:
                return False
    if not res:  # 启动时
        msg_show_states[name] = False
    return res


def is_shown_msg(name: str):
    is_shown = msg_show_states[name]
    if not is_shown:
        msg_show_states[name] = True
    return is_shown


def is_official_server():
    return window.server == "官服"


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
    if ip is None or not ip.startswith("123.206.131"):
        return 0
    else:
        if port in (1965, 1865, 1201, 1239):
            return 2
        else:
            return 1


def write_back(buf: buffer, packet: Packet):
    if len(buf) >= buf_index + packet.length:
        ffi.memmove(ffi.from_buffer(buf) + buf_index, packet.encrypt(False).data(), packet.length)


def send(socket_num: int, buf: bytes | buffer, length: int):
    return hook.Send(socket_num, ffi.from_buffer(buf), length)


@ffi.callback("int(ULONG64, PCHAR, INT)")
def process_send_packet(socket_num, buf, length):
    global login_socket_num, game_socket_num, login_ip, login_port, user_id, can_get_lamu_info
    raw_buf = ffi.buffer(buf, length)
    # 摩尔包
    if get_remote_info(socket_num) > 0 and raw_buf[:2] == b"\x00\x00" and len(raw_buf) > 17:
        packet = Packet(raw_buf)
        if packet.cmd_id == 201:  # 登录包
            login_socket_num = socket_num
            login_ip, login_port = get_ip_port(socket_num)
            user_id = packet.user_id
            can_get_lamu_info = True
            window.enable_all_buttons(True)
        if socket_num == login_socket_num:  # 摩尔主服务器包
            # 必须全部先解密再加密，因为只要手动发过包，后面的序列号就全都变了
            packet.decrypt()
            if is_show_send:
                show_data(Show.SEND, socket_num, packet)  # 界面显示send数据
            with lock:
                packet.encrypt()
        else:  # 其他服务器包
            if is_show_send:
                show_data(Show.SEND, socket_num, packet)  # 界面显示send数据
            match packet.cmd_id:
                case 30001 if map_id == 21:  # 进入泡泡龙游戏包
                    game_socket_num = socket_num
                    window.ppl_thread.init()
        return send(socket_num, packet.data(), length)
    else:
        return send(socket_num, raw_buf, length)


@ffi.callback("void(ULONG64, PCHAR, INT)")
def process_recv_packet(socket_num, buf, length):
    global recv_buf, buf_index, can_get_lamu_info, super_lamu_id, lamus_num, lamus_dict, lamu_id, lamu_name, lamu_times, is_last_skill_success, \
        is_max_skill_success, super_lamu_value, super_lamu_level, mmg_game_id, mmg_energy, mmg_vigour, mmg_level, mmg_card, mmg_times, mmg_friends, \
        mmg_fight_friends, mmg_friends_num, mmg_friends_dict, mmg_query_page, mmg_boss_times_thresholds, mlcs_energy, mlcs_arena_times, \
        mlcs_exp_times, mlcs_sprites_dict, ysqs_max_floor, ysqs_attack, ysqs_energy, ysqs_cards_dict, ysqs_material_cards_dict, \
        can_fight_wjsy, can_fight_ssmy, is_equip_card, map_id
    if get_remote_info(socket_num) == 0:
        return
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
                            case 228 if can_get_lamu_info:  # 跟随的拉姆ID
                                can_get_lamu_info = False
                                super_lamu_id = get_int(packet.body)
                                window.lamu_get_info()
                                if is_official_server():  # 官服才领取卡罗拉幸运儿奖励，平行服已有了
                                    window.kll_reward()
                            case 214: # 获取拉姆数量
                                lamus_num = get_int(packet.body, 0, 1)
                            case 212 if get_int(packet.body) == user_id and get_int(packet.body, 4) == lamus_num:  # 获取拉姆信息
                                lamus_dict.clear()
                                start = 8
                                size = 19 * 4 + 10
                                for page in range(lamus_num):
                                    lamu_id = get_int(packet.body, start + page * size)
                                    lamu_name = get_name(packet.body, start + page * size + 16)
                                    lamu_type = get_int(packet.body, start + page * size + 67)
                                    lamu_value = get_int(packet.body, start + page * size + 71)
                                    lamu_level = get_lamu_level(lamu_value)
                                    lamus_dict[lamu_id] = {
                                        "ID": lamu_id,
                                        "名称": lamu_name,
                                        "类型": "超拉" if lamu_id == super_lamu_id else "未进化" if lamu_type == 0 else lamu_skill_types[lamu_type.bit_length() - 1],
                                        "等级": lamu_level
                                    }
                                lamus_dict = dict(sorted(lamus_dict.items(), key=lambda item: item[0] == super_lamu_id, reverse=True))
                            case 204 if get_int(packet.body) == user_id:  # 获取超拉信息
                                super_lamu_level = get_int(packet.body, 92)
                                super_lamu_value = get_int(packet.body, 100)
                            case 1209 if is_running("拉姆"):  # 拉姆变身获得物品
                                if lamu_times == 0:
                                    is_last_skill_success = True
                                else:
                                    is_max_skill_success = True
                                window.lamu_collect_result()
                                lamu_times += 1
                            case 8200 if not is_running("摩摩怪"):  # 获取摩摩怪能量和活力值
                                mmg_energy = get_int(packet.body, 40)
                                mmg_vigour = get_int(packet.body, 48)
                                mmg_level = get_int(packet.body, 12)
                            case 8201 if not is_running("摩摩怪"):  # 获取摩摩挑战卡数量
                                mmg_card = 0
                                items_num = len(packet.body) // 4
                                size = 1 * 4
                                for page in range(items_num):
                                    item_id = get_int(packet.body, page * size)
                                    if item_id == 0x13DA23:
                                        mmg_card = get_int(packet.body, page * size + 4)
                                        break
                            case 8224 if not is_running("摩摩怪"):  # 获取摩摩怪Boss已挑战次数
                                mmg_super_boss_times = 10 - get_int(packet.body)
                                mmg_lamu_boss_times = 10 - get_int(packet.body, 4)
                                mmg_limit_boss_times = 10 - get_int(packet.body, 8) if datetime.now().hour == 13 else 0
                                mmg_activity_boss_times = 10 - get_int(packet.body, 12)
                                mmg_boss_times_thresholds = tuple(accumulate((
                                    mmg_limit_boss_times, mmg_super_boss_times, mmg_lamu_boss_times, mmg_activity_boss_times
                                )))
                            case 10007:  # 获取摩摩怪游戏ID
                                mmg_game_id = get_bytes(packet.body, 18, 112).hex()
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
                            case 8218 if not is_running("摩摩怪") \
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
                                mlcs_fight_sprites_dict.clear()
                                start = 24
                                size = 1 * 4
                                for page in range(15):  # 出战魔灵信息
                                    sprite_id = get_int(packet.body, start + page * size)
                                    if sprite_id != 0:
                                        mlcs_fight_sprites_dict[sprite_id] = sprite_id
                            case 12018:  # 魔灵背包信息
                                mlcs_sprites_dict.clear()
                                mlcs_material_sprites_dict.clear()
                                sprites_num = get_int(packet.body)
                                start = 4
                                size = 7 * 4
                                for page in range(sprites_num):
                                    sprite_id = get_int(packet.body, start + page * size)  # 魔灵ID
                                    sprite_type = get_int(packet.body, start + page * size + 4)  # 魔灵类型
                                    sprite_attr = get_int(packet.body, start + page * size + 8, 1)  # 魔灵属性
                                    sprite_level = get_int(packet.body, start + page * size + 9, 1)  # 魔灵等级
                                    sprite_exp = get_int(packet.body, start + page * size + 10)  # 魔灵经验
                                    sprite_info = get_sprite_info(sprite_type)
                                    mlcs_sprites_dict[sprite_id] = {
                                        "名称": f"{sprite_info["名称"]} Lv.{sprite_level}",
                                        "ID": sprite_id,
                                        "类型": sprite_type,
                                        "属性": sprite_attr,
                                        "等级": sprite_level,
                                        "经验": sprite_exp,
                                        "星级": sprite_info["星级"],
                                        "最高等级": sprite_info["最高等级"]
                                    }
                                    # 非出战魔灵、烈焰剑齿虎、进阶材料魔灵的0经验魔灵可为升级材料或出售
                                    if sprite_id not in mlcs_fight_sprites_dict and sprite_type not in mlcs_non_material_sprites_types and sprite_exp == 0:
                                        mlcs_material_sprites_dict[sprite_id] = sprite_info["提供经验"]
                                mlcs_sprites_dict = dict(
                                    sorted(
                                        mlcs_sprites_dict.items(),
                                        key=lambda item: (
                                            item[1]["星级"],
                                            item[1]["经验"]
                                        ),
                                        reverse=True
                                    )
                                )
                                # 更新数据并重新选中之前的魔灵
                                window.mlcsSpriteBox.blockSignals(True)
                                old_sprite_id = window.mlcsSpriteBox.currentData()
                                window.mlcsSpriteBox.clear()
                                for sprite_id, sprite_data in mlcs_sprites_dict.items():
                                    if sprite_data["等级"] < sprite_data["最高等级"]:
                                        window.mlcsSpriteBox.addItem(sprite_data["名称"], sprite_id)
                                if old_sprite_id is not None:
                                    index = window.mlcsSpriteBox.findData(old_sprite_id)
                                    if index != -1:
                                        window.mlcsSpriteBox.setCurrentIndex(index)
                                window.mlcsSpriteBox.blockSignals(False)
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
                                        "名称": f"{card_info["名称"]} Lv.{card_level}",
                                        "ID": card_id,
                                        "类型": card_type,
                                        "经验": card_exp,
                                        "已装备": card_is_equip,
                                        "星级": card_star
                                    }
                                    # 6星蛋蛋或者6星以下不是奥丁、汉青和洛基的0经验卡牌可为升级材料
                                    if (card_star < 6 and card_type not in ysqs_non_material_cards_types or card_type == 0x19627A) and card_exp == 0:
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
                            case 1014 if not is_running("餐厅"):  # 餐厅信息
                                ct_cooked_dishes_dict.clear()
                                ct_cooking_dishes_dict.clear()
                                house_type = get_int(packet.body, 36)  # 内部装潢类型
                                stoves_num = get_stove_num(house_type)  # 餐厅灶台数
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
                                for dish_pos in range(1, stoves_num + 1):
                                    ct_cooking_dishes_dict.setdefault(dish_pos, {
                                        "类型": 0x147267,
                                        "位置": dish_pos,
                                        "下次不收菜": True
                                    })
                                # 更新数据并重新选中之前的菜
                                window.ctDishBox.blockSignals(True)
                                old_dish_name = window.ctDishBox.currentText()
                                window.ctDishBox.clear()
                                window.ctDishBox.addItems(ct_cooked_dishes_dict)
                                if old_dish_name is not None:
                                    index = window.ctDishBox.findText(old_dish_name)
                                    if index != -1:
                                        window.ctDishBox.setCurrentIndex(index)
                                window.enable_ct_button(len(ct_cooked_dishes_dict) > 0)
                                window.ctDishBox.blockSignals(False)
                            case 1017:  # 餐厅做菜信息
                                dish_type = get_int(packet.body)
                                dish_id = get_int(packet.body, 4)
                                dish_pos = get_int(packet.body, 8)
                                dish_step = get_int(packet.body, 12)
                                if dish_step < 3:
                                    window.ct_cook_after(dish_id, dish_type, dish_step)
                                elif dish_step == 3 and not is_running("餐厅"):  # 做菜步骤完成后，更新灶台信息
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
                                if dish_info["名称"] not in ct_cooked_dishes_dict and not is_running("餐厅"):  # 新收的菜
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
                                task_name = "缤纷七彩宝盒"
                                item_id = get_int(packet.body)
                                item_num = get_int(packet.body, 4)
                                if item_id == 0x31CE:  # 火龙珠
                                    window.stop_task(task_name)
                                    alert_reward((item_id, item_num))
                                elif item_id == 0 and not is_shown_msg(task_name):
                                    window.stop_task(task_name)
                                    alert_msg("已开完宝盒，暂未获得火龙珠")
                            case 8402:  # 卡罗拉幸运儿游戏开始
                                window.kll_finish(packet.body.hex())
                            case 8403:  # 卡罗拉幸运儿游戏结果
                                task_name = "卡罗拉幸运儿"
                                if get_int(packet.body, 4) == 1:
                                    item_id = get_int(packet.body, 8)
                                    item_num = get_int(packet.body, 12)
                                    alert_reward((item_id, item_num))
                                elif not is_shown_msg(task_name):
                                    window.stop_task(task_name)
                                    alert_msg("已完成今日卡罗拉幸运儿游戏")
                            case 8409 if is_official_server():  # 卡罗拉幸运儿领奖
                                if get_int(packet.body) == 1:
                                    item_id = get_int(packet.body, 4)
                                    item_num = get_int(packet.body, 8)
                                    alert_reward((item_id, item_num), "恭喜你成为了卡罗拉祝福的幸运儿，获得了")
                            case 406:  # 进入地图
                                map_id = get_int(packet.body)
                            case 1242:  # 鉴定化石
                                item_id = get_int(packet.body, 4)
                                item_num = get_int(packet.body, 8)
                                if item_id == 0x2EA6E:  # 瓦尔卡火龙蛋
                                    window.hs_stop()
                                    alert_reward((item_id, item_num))
                        check_waiting_packets(packet)  # 检查待匹配包，放到结尾确保包数据已处理过
                    else:  # 错误包
                        match packet.cmd_id:
                            case 1209 if is_running("拉姆"):  # 拉姆变身获得物品
                                if lamu_times == 0:
                                    is_last_skill_success = False
                                else:
                                    is_max_skill_success = False
                            case 403 if is_running("摩摩怪"):  # 摩摩怪进入游戏失败
                                window.mmg_stop()
                    # 处理后面的包
                    recv_buf = recv_buf[packet_len:]
                    buf_index += packet_len
                else:
                    break
            else:
                break
    # 其他服务器包
    else:
        while True:
            if recv_buf.startswith(b"\x00\x00"):
                if len(recv_buf) >= 4:
                    packet_len = get_int(recv_buf)
                    if len(recv_buf) >= packet_len:
                        # 不是断包
                        cipher = recv_buf[:packet_len]
                        packet = Packet(cipher)
                        if is_show_recv:
                            show_data(Show.RECV, socket_num, packet)  # 界面显示recv数据
                        if socket_num == game_socket_num and map_id == 21:
                            window.ppl_thread.bot.feed(packet.cmd_id, packet.body)
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
    # 设置 DPI 感知级别
    windll.user32.SetProcessDpiAwarenessContext(c_void_p(-4))
    # 设置日志
    logger.add(mole_log, format="[{time:YYYY-MM-DD HH:mm:ss}] {message}", encoding="utf-8", enqueue=True)
    # 加载 hook.dll、设置回调、加载 Flash
    hook = ffi.dlopen("hook.dll")
    hook.SetSendCallBack(process_send_packet)
    hook.SetRecvCallBack(process_recv_packet)
    hook.LoadFlash()
    # 设置 Qt
    app = QApplication([])
    app.setStyle("Fusion")
    trans = QTranslator()
    trans.load(path("zh_CN.qm"))
    app.installTranslator(trans)
    # 加载主窗口
    window = MainWindow()
    is_window_init = True
    window.show()
    # 检查更新
    window.check_update()
    # 进入事件循环
    app.exec()
