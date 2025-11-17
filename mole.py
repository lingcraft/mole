from PySide6.QtCore import QTimer, QThread, Signal, QUrl
from PySide6.QtWidgets import QApplication, QWidget, QHeaderView, QTableWidgetItem, QTableWidget, QMessageBox, QMainWindow
from PySide6.QtGui import QFont, QIcon, QDesktopServices
from ui_main import Ui_MainWindow
from struct import pack, unpack
from threading import Lock
from cffi import FFI
from socket import socket, fromfd, AF_INET, SOCK_STREAM
from dict import *
from datetime import datetime
from time import sleep
from enum import IntEnum
from configparser import ConfigParser
from os import getenv
from pathlib import Path
from json import load
from requests import get

# 封包
secret_key = b"^FStx,wl6NquAVRF@f%6\x00"  # 封包算法密钥
login_socket_num, login_ip, login_port = 0, 0, 0  # 登录后的socket、IP、Port
user_id, serial_num, packet_index = 0, 0, 0  # 米米号、发送包序列号、封包序号索引
recv_buff = bytearray()  # 接收封包的数据缓冲区
show_send, show_recv = True, True  # 显示send包、recv包
lock = Lock()  # 发送锁
# 拉姆
is_get_lamu_info = True  # 是否获取拉姆信息
lamu_id, lamu_name, lamu_value, lamu_level, lamu_times = 0, "", 0, 0, 0  # 拉姆ID、名字、变身值、变身等级、变身获得物品成功次数
lamu_skill_types = ["火", "水", "木"]  # 拉姆技能类型
lamu_max_skill_level, lamu_last_skill_level, = 0, 0  # 拉姆最大技能等级、次大技能等级
lamu_last_item_level, lamu_max_item_level = 0, 0  # 拿取的物品等级
lamu_last_type_index, lamu_max_type_index = 0, 0  # 拿取的物品类型索引
lamu_last_item_index, lamu_max_item_index = 0, 0  # 拿取的物品索引
lamu_limit_item_dict, limit_data = {}, {}  # 已经拿到上限的物品
lamu_max_skill_success, lamu_last_skill_success = True, True  # 最大技能拿取物品是否成功、次大技能拿取物品是否成功
lamu_pick_result_dict = {}  # 拉姆拿取物品结果
super_lamu_value, super_lamu_level = 0, 0  # 超拉成长值、等级
# 摩摩怪
mmg_energy, mmg_vigour, mmg_game_id = 0, 0, ""  # 能量、活力、游戏ID
mmg_type, mmg_times = 0, 0  # 摩摩怪挑战类型、执行次数
mmg_super_boss_times, mmg_lamu_boss_times, mmg_limit_boss_times = 0, 0, 0  # 超级Boss、超拉Boss、限时Boss的可挑战次数
mmg_boss_index1, mmg_boss_index2, mmg_boss_index3 = 0, 0, 0  # 3种Boss挑战次数索引
mmg_friends, mmg_friends_dict, mmg_students, mmg_fight_friends = [], {}, [], []  # 好友、好友字典（米米号：等级）、师徒、可挑战好友
mmg_friends_state_dict = {1: [], 2: [], 3: [], 4: []}  # 4种状态的好友字典
mmg_friends_num, mmg_query_size_max, mmg_query_page_max, mmg_query_page = 0, 14, 0, 0  # 好友数、最大可查询好友数、最大查询页码、查询页码
# 魔灵传说
mlcs_energy, mlcs_arena_times, mlcs_exp_times = 0, 0, 0  # 魔灵体力值、竞技场可挑战次数、经验之路可挑战次数
mlcs_fight_elves_dict, mlcs_elves_dict = {}, {}  # 出战魔灵、全部魔灵
# 元素骑士
ysqs_max_floor, ysqs_attack, ysqs_energy = 0, 0, 0  # 无尽深渊最高层数、最低攻击力、体力值
# 餐厅
ct_cooked_dishes_dict, ct_cooking_dishes_dict = {}, {}  # 餐台菜信息、灶台菜信息
# 游戏版本
server_dict = {
    "官服": "http://mole.61.com",
    "平行服": f"http://$node.61player.com",
    "骑士版": f"http://$node.61player.com/moleverse/20090626",
    "圣诞版": f"http://$node.61player.com/moleverse/20111225",
    "万圣版": f"http://$node.61player.com/moleverse/20190815",
    "火神版": f"http://$node.61player.com/moleverse/2025hsb",
    "桃源版": f"http://$node.61player.com/moleverse/taoyuan",
}
# 平行服节点
node_dict = {
    "主节点": "mole",
    "子节点": "mole-sub"
}
# 版本文件地址
version_url = "https://raw.githubusercontent.com/lingcraft/mole/master/version.json"
# 链接加速前缀
cdn_prefixs = [
    "https://hk.gh-proxy.com",
    "https://v6.gh-proxy.com",
    "https://hub.gitmirror.com",
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
""")
config = Path(getenv("appdata")) / "mole" / "config.ini"
base_dir = Path(__file__).resolve().parent
window_defined = False


class Interval(IntEnum):
    NONE = 0  # 无延迟模式，前台发送，防止界面阻塞
    NORMAL = 25  # 正常模式，后台发送，适用于元素骑士、魔灵传说等需要一定间隔发送的游戏


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        # 界面基础设置
        self.setupUi(self)
        # 界面额外设置
        self.config = ConfigParser()
        if config.exists():  # 读取配置
            self.config.read(config)
            self.server = self.config["Settings"].get("server", "官服")
            self.node = self.config["Settings"].get("node", "主节点")
        else:
            self.server = "官服"
            self.node = "主节点"
        with open(path("version.json"), "r", encoding="utf-8") as file:  # 获取版本
            self.version = load(file).get("version")
        self.check_menu()
        self.axWidget.dynamicCall("LoadMovie(long,string)", 0, self.url())
        self.axWidget.dynamicCall("SetScaleMode(int)", 0)
        self.tableWidget.setFont(QFont("Cascadia Code, Microsoft YaHei UI", 9))
        self.tableWidget.verticalHeader().setDefaultSectionSize(10)  # 行高
        self.tableWidget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)  # 禁止编辑单元格
        self.tableWidget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)  # 禁止选多行
        self.tableWidget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)  # 一次选一行
        self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # 允许手动调整列宽
        self.init_table_size()
        self.tableWidget.setHorizontalHeaderLabels(["类型", "通信号", "命令号", "解析", "封包数据"])
        self.tableWidget.currentCellChanged.connect(self.change_row)
        for action in self.serverMenu.actions():  # 切换版本
            action.triggered.connect(self.change_server)
        for action in self.nodeMenu.actions():  # 切换节点
            action.triggered.connect(self.change_node)
        self.menubar.addAction("刷新游戏", self.refresh)
        self.menubar.addAction("检查更新", self.check_update)
        self.menubar.addAction(QIcon(path("github.ico")), "关于", self.open_github)
        self.send_thread = SendThread()
        self.send_ex_thread = SendExThread()
        self.update_thread = UpdateThread(self.update_result)
        # 单次运行功能
        self.sendButton.clicked.connect(self.send)
        self.sendClearButton.clicked.connect(self.send_clear)
        self.sendCheckBox.stateChanged.connect(self.change_show_send)
        self.recvCheckBox.stateChanged.connect(self.change_show_recv)
        self.socketCheckBox.stateChanged.connect(self.change_set_socket)
        self.clearButton.clicked.connect(self.clear_table)
        self.ysqsFightButton.clicked.connect(self.ysqs_start)
        self.mlcsFightButton.clicked.connect(self.mlcs_start)
        self.mlcsSellButton.clicked.connect(self.mlcs_sell_start)
        # 多次运行功能
        self.sendLoopButton.clicked.connect(lambda: self.start_task("循环发送", self.send, 1, self.sendLoopButton))
        self.lamuGrowButton.clicked.connect(lambda: self.start_task("拉姆", self.lamu_run, 200, self.lamuGrowButton, self.lamu_start))
        self.dddGetButton.clicked.connect(lambda: self.start_task("点点豆", self.ddd_run, 1, self.dddGetButton))
        # 摩摩怪功能
        self.timer_pool = {
            "摩摩怪": (RunTimer(self.mmg_run, 1000), ""),
            "好友查询": (RunTimer(self.mmg_query_run, 500), ""),
            "餐厅收菜": tuple(RunTimer() for _ in range(7))
        }
        self.mmgPVBButton.clicked.connect(lambda: self.mmg_start(1))
        self.mmgPVEButton.clicked.connect(lambda: self.mmg_start(2))
        self.mmgPVPButton.clicked.connect(lambda: self.mmg_start(3))
        # 餐厅功能
        self.ctSellButton.clicked.connect(lambda: self.start_task("餐厅卖菜", self.ct_sell_run, 1, self.ctSellButton))
        self.ctHarvestButton.clicked.connect(self.ct_harvest_start)

    def closeEvent(self, event):
        self.config["Settings"] = {
            "server": self.server,
            "node": self.node
        }
        if not config.parent.exists():
            config.parent.mkdir()
        with open(config, "w") as file:
            self.config.write(file)
        super(MainWindow, self).closeEvent(event)

    def timer(self, name):
        return self.timer_pool.get(name, (QTimer(),))[0]

    def timers(self, name):
        return self.timer_pool.get(name)

    def url(self):
        return f"{server_dict.get(self.server)}/Client.swf".replace("$node", node_dict.get(self.node))

    def init_table_size(self):
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
        self.tableWidget.scrollToTop()  # 拖动到顶部

    def change_show_send(self, state):
        global show_send
        show_send = state > 0

    def change_show_recv(self, state):
        global show_recv
        show_recv = state > 0

    def change_set_socket(self, state):
        self.socketLineEdit.setEnabled(state > 0)
        if state > 0 and len(self.socketLineEdit.text()) == 0 and login_socket_num != 0:
            self.socketLineEdit.setText(str(login_socket_num))

    def send(self):
        # 使用后台发送，防止添加自定义延迟后阻塞界面
        send_lines_back_ex(self.textEdit.toPlainText().split('\n'), Interval.NONE)

    def send_clear(self):
        self.textEdit.clear()

    def change_row(self, row, column):
        data = self.tableWidget.item(row, column if column < 2 else 4)
        if data is not None:
            self.textEdit.setPlainText(data.toolTip() if column == 0 else data.text())

    def change_server(self, checked):
        if checked:
            self.server = self.sender().text()
            if self.server == "官服":
                self.node = "主节点"
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
        self.nodeAction2.setEnabled(self.server != "官服")

    def refresh(self):
        self.check_menu()
        self.axWidget.dynamicCall("LoadMovie(long, string)", 0, "http://gf.61.com/Client.swf")
        self.axWidget.dynamicCall("LoadMovie(long, string)", 0, self.url())
        self.enable_all_buttons(False)

    def add_data(self, data_type, socket_num, cmd_id, cmd_analyse, data):
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

    def clear_table(self):
        global packet_index
        packet_index = 0
        self.init_table_size()

    def enable_lamu_button(self, enable):
        self.lamuGrowButton.setEnabled(enable)

    def enable_mmg_button(self, enable):
        self.mmgPVBButton.setEnabled(enable)
        self.mmgPVEButton.setEnabled(enable)
        self.mmgPVPButton.setEnabled(enable)
        self.mmgLevelBox.setEnabled(enable)
        self.mmgBossBox.setEnabled(enable)

    def enable_ddd_button(self, enable):
        self.dddGetButton.setEnabled(enable)

    def enable_ysqs_button(self, enable):
        self.ysqsFightButton.setEnabled(enable)
        self.ysqsLevelBox.setEnabled(enable)

    def enable_mlcs_button(self, enable):
        self.mlcsFightButton.setEnabled(enable)
        self.mlcsSellButton.setEnabled(enable)

    def enable_ct_button(self, enable):
        self.ctSellButton.setEnabled(enable)
        self.ctHarvestButton.setEnabled(enable)
        self.ctDishBox.setEnabled(enable)

    def enable_all_buttons(self, enable):
        self.enable_lamu_button(enable)
        self.enable_mmg_button(enable)
        self.enable_ddd_button(enable)
        self.enable_ysqs_button(enable)
        self.enable_mlcs_button(enable)
        if not enable:  # 刷新游戏后的操作
            mmg_friends.clear()
            self.enable_ct_button(False)
            if self.timer("拉姆").isActive():
                self.timer("拉姆").stop()
            if self.timer("摩摩怪").isActive():
                self.timer("摩摩怪").stop()

    # 简单的多次任务
    def start_task(self, name, func, interval, button=None, start_func=None, button_stop_text="停止"):
        if name in self.timer_pool:
            timer, text = self.timer_pool[name]
            if timer.isActive():  # 停止
                button.setText(text)
                timer.stop()
            else:  # 启动
                if start_func is not None:
                    start_func()
                else:
                    button.setText(button_stop_text)
                timer.start()
        else:  # 创建新timer并启动
            timer = RunTimer(func, interval)
            self.timer_pool[name] = timer, button.text()
            if start_func is not None:
                start_func()
            else:
                button.setText(button_stop_text)
            timer.start()

    def check_update(self):
        if not self.update_thread.isRunning():
            self.update_thread.start()

    def update_result(self, res, msg, version):
        match res:
            case 1:
                QMessageBox.information(self, "提示", msg)
            case 2:
                button = QMessageBox.information(self, "提示", msg, QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
                if button == QMessageBox.StandardButton.Ok:
                    QDesktopServices.openUrl(QUrl(f"https://github.com/lingcraft/mole/releases/download/v{version}/mole.exe"))
            case 3:
                QMessageBox.warning(self, "错误", msg)

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
            f"0000000000000004670000000000000000{get_hex(lamu_id)}0000000100000001",  # 学习火系技能
            f"0000000000000004670000000000000000{get_hex(lamu_id)}0000000200000001",  # 学习水系技能
            f"0000000000000004670000000000000000{get_hex(lamu_id)}0000000300000001"  # 学习木系技能
        ])

    def lamu_feed(self):
        send_lines([
            "0000000000000001F500000000000000000002BF2600000002",  # 买十字架
            f"0000000000000001F90000000000000000{get_hex(user_id)}{get_hex(lamu_id)}0002BF26",  # 喂十字架
            f"0000000000000001F90000000000000000{get_hex(user_id)}{get_hex(lamu_id)}0002BF26"  # 喂十字架
        ])

    def lamu_get_vars(self):
        if lamu_times == 0:
            return lamu_last_skill_success, lamu_last_skill_level, lamu_last_item_level, lamu_last_type_index, lamu_last_item_index
        else:
            return lamu_max_skill_success, lamu_max_skill_level, lamu_max_item_level, lamu_max_type_index, lamu_max_item_index

    def lamu_set_vars(self, *args):
        global lamu_last_item_level, lamu_last_type_index, lamu_last_item_index, lamu_max_item_level, lamu_max_type_index, lamu_max_item_index
        if lamu_times == 0:
            lamu_last_item_level, lamu_last_type_index, lamu_last_item_index = args
        else:
            lamu_max_item_level, lamu_max_type_index, lamu_max_item_index = args

    def lamu_get_skill_info(self, skill_level, item_level, type_index):
        skill_type = lamu_skill_types[type_index]
        return skill_type, get_skill_id(skill_level, skill_type), list(
            lamu_dict.get(item_level).get(skill_type).items())

    def lamu_collect_result(self):
        skill_success, skill_level, item_level, type_index, item_index = self.lamu_get_vars()
        skill_type, skill_id, items = self.lamu_get_skill_info(skill_level, item_level, type_index)
        item_name = items[item_index][0]
        if skill_success:
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
            QMessageBox.information(self, "一键获取拉姆变身值结束", f"拉姆（{lamu_name}）成功采集以下物品：\n{text}")
        else:
            QMessageBox.information(self, "一键获取拉姆变身值结束", f"拉姆（{lamu_name}）今天可采集物品已达上限")

    def lamu_start(self):
        global lamu_times, lamu_max_skill_success, lamu_last_skill_success, lamu_max_skill_level, lamu_last_skill_level, \
            lamu_max_item_level, lamu_last_item_level, lamu_max_type_index, lamu_last_type_index, lamu_max_item_index, \
            lamu_last_item_index, limit_data
        self.enable_lamu_button(False)
        self.lamu_gift()
        self.lamu_learn()
        self.lamu_feed()
        lamu_times = 0
        lamu_max_skill_level = get_max_skill_level(lamu_level)
        lamu_last_skill_level = get_last_skill_level(lamu_level)
        lamu_max_skill_success, lamu_last_skill_success = True, True
        lamu_max_item_level, lamu_last_item_level = lamu_max_skill_level, lamu_last_skill_level
        lamu_max_type_index, lamu_last_type_index = 0, 0
        lamu_max_item_index, lamu_last_item_index = 0, 0
        lamu_pick_result_dict.clear()
        now = datetime.now()
        refresh_time = datetime(now.year, now.month, now.day, 3)
        limit_data = lamu_limit_item_dict.get(user_id)
        if limit_data is None:
            limit_data = {"数据": {}, "时间": now}
            lamu_limit_item_dict[user_id] = limit_data
        elif limit_data.get("时间") < refresh_time <= now:
            limit_data.get("数据").clear()
            limit_data["时间"] = now

    def lamu_get_item(self, skill_level, item_level, type_index, item_index):
        skill_type, skill_id, items = self.lamu_get_skill_info(skill_level, item_level, type_index)
        item_id = items[item_index][1]
        while item_id in limit_data.get("数据"):
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
                        return None, None
            self.lamu_set_vars(item_level, type_index, item_index)
            skill_type, skill_id, items = self.lamu_get_skill_info(skill_level, item_level, type_index)
            item_id = items[item_index][1]
        return item_id, skill_id

    def lamu_run(self):
        skill_success, skill_level, item_level, type_index, item_index = self.lamu_get_vars()
        item_id, skill_id = self.lamu_get_item(skill_level, item_level, type_index, item_index)
        if lamu_times < 11 or item_level == 6:  # 最高级物品全部拿到上限
            if not skill_success:  # 上次技能拿取失败
                limit_data.get("数据")[item_id] = item_id
                limit_data["时间"] = datetime.now()
                item_id, skill_id = self.lamu_get_item(skill_level, item_level, type_index, item_index)
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
        self.timer("拉姆").stop()

    def mmg_start(self, fight_type):
        def start():  # 开始执行
            send_lines([
                "0000000000000001910000000000000000000000E40000000000000001000000000000000000000000",  # 获取地图信息
            ])
            self.timer("摩摩怪").start()

        if fight_type == 4:  # 查询好友完毕
            start()
        else:
            global mmg_type, mmg_times
            self.enable_mmg_button(False)
            mmg_type, mmg_times = fight_type, 0
            send_lines([
                "0000000000000020200000000000000000" * (fight_type == 1),  # 查询Boss已挑战次数
                f"0000000000000020080000000000000000{get_hex(user_id)}",  # 获取基础信息
                "0000000000000001960000000000000000000000E400000000"  # 进入地图场景
            ])
            if fight_type < 3:
                run_later(start)
            else:
                if len(mmg_friends) == 0:
                    QMessageBox.information(self, "提示", "进入地图后，请先将鼠标移至右侧好友按钮处以获取好友列表")
                self.timer("好友查询").start()

    def mmg_run(self):
        match mmg_type:
            case 1:  # 挑战Boss
                match mmg_times:
                    case n if n < mmg_boss_index1:
                        level_id = get_level_id(self.mmgBossBox.currentText())
                        self.mmg_fight(level_id, 1)
                    case n if mmg_boss_index1 <= n < mmg_boss_index2:
                        level_id = get_level_id("怪味糖蓝龙")
                        self.mmg_fight(level_id, 1)
                    case n if mmg_boss_index2 <= n < mmg_boss_index3:
                        level_id = get_level_id("飞沙蝎")
                        self.mmg_fight(level_id, 1)
                    case _:
                        self.mmg_stop()
            case 2:  # 挑战副本
                match mmg_times:
                    case n if n < mmg_energy // 10:
                        level_id = get_level_id(self.mmgLevelBox.currentText())
                        self.mmg_fight(level_id, 1)
                    case _:
                        self.mmg_stop()
            case 3:  # 挑战好友
                match mmg_times:
                    case n if n < mmg_vigour // 10 and len(mmg_fight_friends) > 0:
                        level_id, fight_type = mmg_fight_friends.pop(0)
                        self.mmg_fight(level_id, fight_type)
                    case _:
                        self.mmg_wish()
                        self.mmg_stop()

    def mmg_fight(self, level_id, fight_type):
        send_lines([
            "00000000000000019300000000000000000000000100000000"  # 进入游戏
        ])

        def fight():
            is_no_error = send_lines_to_server(("123.206.131.63", 3001), [
                f"0000008101000075310000000000000000{mmg_game_id}",  # 进入游戏
                f"000000212000007724000000000000000000000004{get_hex(fight_type)}{get_hex(level_id)}00000000",  # 开始挑战
                "000000152000007724000000000000000000000040",  # 开始战斗
                "000000152000007724000000000000000000000080"  # 快速战斗
            ], [3, 1, 1, 2])  # 摩摩怪服务器操作
            if is_no_error:
                run_later(lambda: send_lines([
                    "0000000000000020140000000000000000",  # 校验能否翻牌
                    "000000000000002015000000000000000000000000",  # 翻牌
                    "000000000000000194000000000000000000"  # 离开游戏
                ]))

        run_later(fight)

    def mmg_wish(self):
        send_lines_back([
            *[f"0000000000000020170000000000000000{get_hex(friend_id)}" for friend_id in mmg_friends_state_dict.get(1)],  # 祝福
            *[f"0000000000000020190000000000000000{get_hex(friend_id)}00000002" for friend_id in mmg_friends_state_dict.get(2)],  # 呼唤
            *[f"0000000000000020190000000000000000{get_hex(friend_id)}00000003" for friend_id in mmg_friends_state_dict.get(3)],  # 抱抱
            *[f"0000000000000020190000000000000000{get_hex(friend_id)}00000004" for friend_id in mmg_friends_state_dict.get(4)]  # 解救
        ])

    def mmg_query_run(self):
        if len(mmg_friends) > 0:
            self.timer("好友查询").stop()
            self.mmg_query_friends()

    def mmg_query_friends(self):
        global mmg_query_page_max, mmg_query_page
        mmg_fight_friends.clear()
        mmg_friends_state_dict.get(1).clear()
        mmg_friends_state_dict.get(2).clear()
        mmg_friends_state_dict.get(3).clear()
        mmg_friends_state_dict.get(4).clear()
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
        self.timer("摩摩怪").stop()

    def ddd_run(self):
        send_lines([
            "0000000000000001F500000000000000000002737200000001",
            "0000000000000004DB0000000000000000000000790000000100000001",
            *["0000000000000017850000000000000000000000010002E96400000001"] * 5
        ])

    def ysqs_start(self):
        send_lines([
            "00000000000000231E000000000000000000000000"  # 获取元素骑士信息
        ])
        run_later(self.ysqs_run)

    def ysqs_run(self):
        hour = datetime.now().hour
        can_fight_ssmy = ysqs_attack >= 2000  # 莎士摩亚战力达标
        is_fight_ssmy = ysqs_energy > 0 and 10 <= hour < 21 and can_fight_ssmy  # 是否挑战莎士摩亚
        can_fight_wjsy = ysqs_max_floor >= 50 or ysqs_attack >= 7000  # 无尽深渊战力达标
        is_fight_wjsy = ysqs_energy > 0 and 13 <= hour < 21 and can_fight_wjsy  # 是否挑战无尽深渊
        remain_times = ysqs_energy // 5  # 当前体力可挑战次数
        if can_fight_wjsy:  # 战力达标
            if hour < 21:
                fight_times = 40 * is_fight_wjsy
            else:  # 已过无尽深渊开放时间
                fight_times = remain_times
        else:  # 战力未达标
            if self.ysqsLevelBox.currentText() == "莎士摩亚":  # 挑战类副本
                fight_times = min(40, remain_times) * is_fight_ssmy
            else:  # 探索类副本
                if ysqs_attack == 0:  # 无卡牌挑战
                    fight_times = remain_times * 2
                else:
                    fight_times = remain_times
        is_reward = is_fight_wjsy or fight_times >= 20  # 是否领取每日任务奖励
        send_lines_back(
            [
                "00000000000000231A0000000000000000"  # 领悟技能
            ]
            +
            [
                f"00000000000000231D0000000000000000{get_hex(get_level_id("无尽深渊"))}",
                f"0000000000000023210000000000000000{get_hex(get_level_id("无尽深渊"))}"
            ] * 80 * is_fight_wjsy
            +
            [
                f"00000000000000231D0000000000000000{get_hex(get_level_id("莎士摩亚"))}",
                f"0000000000000023210000000000000000{get_hex(get_level_id("莎士摩亚"))}"
            ] * 40 * is_fight_wjsy
            +
            [
                "000000000000002319000000000000000000000000"  # 恢复体力
            ] * is_fight_wjsy
            +
            [
                f"00000000000000231D0000000000000000{get_hex(get_level_id("莎士摩亚"))}",
                f"0000000000000023210000000000000000{get_hex(get_level_id("莎士摩亚"))}"
            ] * 20 * is_fight_wjsy
            +
            [
                f"00000000000000231D0000000000000000{get_hex(get_level_id(self.ysqsLevelBox.currentText()))}",
                f"0000000000000023210000000000000000{get_hex(get_level_id(self.ysqsLevelBox.currentText()))}"
            ] * fight_times
            +
            [
                "000000000000002331000000000000000000000000",  # 每日任务奖励1
                "000000000000002331000000000000000000000001"  # 每日任务奖励2
            ] * is_reward
        )

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
                    f"000000000000002EE70000000000000000{get_hex(get_level_id("希望之光5"))}",
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
                    f"000000000000002EE70000000000000000{get_hex(get_level_id("经验之路"))}",
                    *["000000000000002EF000000000000000000000F000F000F000F000F000F000F0"] * 5,
                    "000000000000002EEA0000000000000000"
                ] * mlcs_exp_times
                +
                [
                    f"000000000000002EE70000000000000000{get_hex(get_level_id("希望之光5"))}",
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
            f"0000000000000003FA0000000000000000000027100000000000147293{get_hex(ct_cooked_dishes_dict.get(self.ctDishBox.currentText()).get("ID"))}00000065"
        ])

    def ct_harvest_start(self):
        if self.ctHarvestButton.text() == "自动收菜":
            self.ctHarvestButton.setText("停止")
            send_lines([
                f"0000000000000001910000000000000000{get_hex(user_id)}0000001F00000096000000000000000000000000",
                f"0000000000000003F60000000000000000{get_hex(user_id)}0000001F"
            ])
            run_later(self.ct_harvest_run)
        else:
            self.ctHarvestButton.setText("自动收菜")
            for timer in self.timers("餐厅收菜"):
                timer.stop()

    def ct_harvest_run(self):
        if len(ct_cooking_dishes_dict) == 0:
            self.ctHarvestButton.setText("自动收菜")
            QMessageBox.information(self, "提示", f"当前所有灶台为空，请先在需要自动改菜为{self.ctDishBox.currentText()}和收菜的灶台制作1次阳光酥油肉松或酱爆雪顶菇")
            return
        need_time = ct_cooked_dishes_dict.get(self.ctDishBox.currentText()).get("时间")
        interval = need_time + 5  # 做菜包+2秒动画+2次设置菜状态包
        timers = self.timers("餐厅收菜")
        for dish_pos, dish_info in ct_cooking_dishes_dict.items():
            cook_time = dish_info.get("时间")
            timer = timers[dish_pos - 1]
            if cook_time < need_time:  # 未成熟的菜
                timer.set_data(lambda pos=dish_pos: self.ct_harvest_func(pos), interval * 1000, (need_time - cook_time) * 1000).start()
            elif need_time <= cook_time < 3 * need_time:  # 已成熟的菜
                timer.set_data(lambda pos=dish_pos: self.ct_harvest_func(pos), interval * 1000, 0).start()
            else:  # 已糊的菜
                send_lines([
                    f"0000000000000003FB0000000000000000{get_hex(dish_info.get("种类"))}{get_hex(dish_info.get("ID"))}{get_hex(dish_pos)}",  # 处理糊菜
                    f"0000000000000003F90000000000000000{get_hex(dish_info.get("种类"))}{get_hex(dish_pos)}"  # 做菜
                ])
                timer.set_data(lambda pos=dish_pos: self.ct_harvest_func(pos), interval * 1000, interval * 1000).start()

    def ct_harvest_func(self, pos):
        cooked_info = ct_cooked_dishes_dict.get(self.ctDishBox.currentText())
        dish_info = ct_cooking_dishes_dict.get(pos)
        now = datetime.now()
        if not dish_info.get("跳过收菜"):
            send_lines([
                f"0000000000000003FD0000000000000000{get_hex(cooked_info.get("种类"))}{get_hex(dish_info.get("ID"))}{get_hex(pos)}{get_hex(cooked_info.get("位置"))}"  # 收菜
            ])
        else:
            dish_info["跳过收菜"] = False
        if now.hour >= 6:
            send_lines([
                f"0000000000000003F90000000000000000{get_hex(dish_info.get("种类"))}{get_hex(pos)}"  # 做菜
            ])
        else:
            dish_info["跳过收菜"] = True
            cook_start = datetime(now.year, now.month, now.day, 6)
            self.timers("餐厅收菜")[pos - 1].restart((cook_start - now).total_seconds() * 1000)

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


class UpdateThread(QThread):
    result = Signal(int, str, str)

    def __init__(self, func):
        super().__init__()
        self.result.connect(func)

    def run(self):
        version, description = "", ""
        for cdn_prefix in cdn_prefixs:
            url = f"{cdn_prefix}/{version_url}"
            try:
                response = get(url, timeout=(3, 5))
                response.raise_for_status()
            except:
                continue
            else:
                version, description = response.json().values()
                break
        if len(version) > 0:
            new_version = version.split(".")
            curr_version = window.version.split(".")
            is_latest = True
            for i in range(3):
                new_num = int(new_version[i])
                curr_num = int(curr_version[i])
                if curr_num < new_num:
                    is_latest = False
                    break
            if is_latest:
                self.result.emit(1, f"当前版本 v{window.version} 已是最新！", version)
            else:
                self.result.emit(2, f"发现新版本：v{version}，更新信息：\n{description}", version)
        else:
            self.result.emit(3, "检查失败，请检查网络连接！", version)


class RunTimer(QTimer):
    signal = Signal()

    def __init__(self, func=None, interval: int = 1000, delay: int = 300):
        super().__init__()
        super().timeout.connect(self.on_timeout)
        self.func = None
        self.set_data(func, interval, delay)

    def set_data(self, func, interval: int, delay: int):
        if self.func is None and func is not None:
            self.func = func
            self.signal.connect(func)
        self.interval = interval
        self.delay = min(delay, interval)
        return self

    def start(self):
        self.is_first = True
        super().start(self.delay)

    def restart(self, delay):
        self.stop()
        self.delay = delay
        self.start()

    def on_timeout(self):
        self.signal.emit()
        if self.is_first:
            self.is_first = False
            super().setInterval(self.interval)


class Packet:
    def __init__(self, packet):
        if isinstance(packet, str):
            packet = bytes.fromhex(packet)
        if len(packet) >= 17:
            self.length, self.serial_num, self.cmd_id, self.user_id, self.version = unpack("!IBIII", packet[:17])
            self.body = packet[17:]
        else:
            self.length, self.serial_num, self.cmd_id, self.user_id, self.version = 0, 0, 0, 0, 0
            self.body = bytes()

    def data(self):
        head = pack("!IBIII", self.length, self.serial_num, self.cmd_id, self.user_id, self.version)
        return head + self.body

    @staticmethod
    def parse_data(data: str):
        packet = bytearray.fromhex(data)
        if packet.startswith(b'\x00\x00'):
            packet[9:13] = pack("!I", user_id)
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
            for i in range(len(self.body)):
                crc ^= self.body[i]
            # 计算发送包序列号
            serial_num = (serial_num - int(serial_num / 7) + 147 + (
                    self.length - 1) % 21 + self.cmd_id % 13 + crc) % 256
        self.serial_num = serial_num

    def encrypt(self):
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


def show_data(packet: Packet, data_type: str, socket_num: int = None):
    global window_defined
    if window_defined:
        if socket_num is None:
            socket_num = login_socket_num
        window.add_data(data_type, socket_num, packet.cmd_id, analyse(packet.cmd_id), packet.data().hex().upper())
    else:
        if "window" in globals():
            window_defined = True


def run_later(func, delay: int = 300):
    QTimer.singleShot(delay, func)


def get_lamu_level(value: int):
    match value:
        case n if n < 40:
            return 1
        case n if 40 <= n < 180:
            return 2
        case n if 180 <= n < 660:
            return 3
        case n if 660 <= n < 1340:
            return 4
        case n if 1340 <= n < 2660:
            return 5
        case n if 2660 <= n < 4280:
            return 6
        case n if 4280 <= n < 6840:
            return 7
        case n if 6840 <= n < 9800:
            return 8
        case n if 9800 <= n < 14000:
            return 9
        case n if 14000 <= n < 18700:
            return 10
        case _:
            return 11


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


def get_super_lamu_level(value: int):
    match value:
        case n if n < 311:
            return 1
        case n if 311 <= n < 776:
            return 2
        case n if 776 <= n < 1706:
            return 3
        case n if 1706 <= n < 3566:
            return 4
        case n if 3566 <= n < 5426:
            return 5
        case n if 5426 <= n < 7286:
            return 6
        case n if 7286 <= n < 9146:
            return 7
        case _:
            return 8


def get_int(buff: bytes, bytes_num: int = 4):
    match bytes_num:
        case 4:
            return unpack("!I", buff[:4])[0]
        case 2:
            return unpack("!H", buff[:2])[0]
        case 1:
            return unpack("!B", buff[:1])[0]
        case 8:
            return unpack("!Q", buff[:8])[0]
        case _:
            return unpack("!I", buff[:4])[0]


def get_hex(data: int, bytes_num: int = 4):
    return f"{data:0{bytes_num * 2}X}"


def get_name(buff: bytes):
    return buff[:16].rstrip(b'\x00').decode()


def send_lines(lines: list, interval: int = Interval.NONE):
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
        if show_send:
            show_data(packet, "S ==>")
        if interval > 0:
            sleep(interval / 1000)


def send_lines_to_server(address: tuple, lines: list, wait_recv_nums: list = None):
    need_wait_recv = wait_recv_nums is not None
    with socket(AF_INET, SOCK_STREAM) as s:
        s.connect(address)
        for data in lines:
            s.send(Packet.parse_data(data))
            if need_wait_recv:
                for i in range(wait_recv_nums.pop(0)):
                    packet = Packet(s.recv(17))
                    if packet.version != 0:
                        return False
                    s.recv(packet.length - 17)
    return True


def send_lines_to_socket(lines: list, interval: int = Interval.NONE):
    socket_num = window.socketLineEdit.text()
    if socket_num.isdigit():
        socket_num = int(socket_num)
        try:
            with fromfd(socket_num, AF_INET, SOCK_STREAM) as s:
                for data in lines:
                    if len(data) < 17:
                        continue
                    s.send(Packet.parse_data(data))
                    if interval > 0:
                        sleep(interval / 1000)
        except:
            pass


def send_lines_back(lines: list, interval: int = Interval.NORMAL):
    if not window.send_thread.isRunning():
        window.send_thread.set_data(lines, interval)
        window.send_thread.start()


def send_lines_back_ex(lines: list, interval: int = Interval.NORMAL):
    if not window.send_ex_thread.isRunning():
        window.send_ex_thread.set_data(lines, interval)
        window.send_ex_thread.start()


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
        if port in [1965, 1865, 1201, 1239]:
            return 2
        else:
            return 1


def send(socket_num: int, buff: bytes, length: int):
    return hook.Send(socket_num, ffi.from_buffer(buff), length)


@ffi.callback("int(ULONG64, PCHAR, INT)")
def process_send_packet(socket_num, buff, length):
    global login_socket_num, login_ip, login_port, user_id, is_get_lamu_info
    sock_type = get_remote_info(socket_num)
    cipher = ffi.buffer(buff, length)[:]
    # 摩尔主服务器包
    if sock_type > 0 and cipher.startswith(b'\x00\x00') and len(cipher) > 17:
        packet = Packet(cipher)
        if packet.cmd_id == 201:  # 登录包
            login_socket_num = socket_num
            login_ip, login_port = get_ip_port(socket_num)
            user_id = packet.user_id
            is_get_lamu_info = True
            window.enable_all_buttons(True)
        if socket_num == login_socket_num:
            packet.decrypt()
            if show_send:
                show_data(packet, "S ==>")  # 界面添加send数据
            with lock:
                packet.encrypt()
            return send(socket_num, packet.data(), length)
    # 其他包
    if show_send and cipher.startswith((b'\x00\x00', b'\x3C\x70', b'\x3C\x3F')):
        show_data(Packet(cipher), "S ==>", socket_num)  # 界面添加send数据
    return send(socket_num, cipher, length)


@ffi.callback("void(ULONG64, PCHAR, INT)")
def process_recv_packet(socket_num, buff, length):
    global recv_buff, is_get_lamu_info, lamu_id, lamu_name, lamu_value, lamu_level, lamu_times, lamu_last_skill_success, lamu_max_skill_success, \
        super_lamu_value, super_lamu_level, mmg_game_id, mmg_energy, mmg_vigour, mmg_times, mmg_friends, mmg_friends_num, mmg_friends_dict, \
        mmg_query_page, mmg_super_boss_times, mmg_lamu_boss_times, mmg_limit_boss_times, mmg_boss_index1, mmg_boss_index2, mmg_boss_index3, \
        mlcs_energy, mlcs_arena_times, mlcs_exp_times, ysqs_max_floor, ysqs_attack, ysqs_energy
    cipher = ffi.buffer(buff, length)[:]
    recv_buff.extend(cipher)
    # 摩尔主服务器包
    if socket_num == login_socket_num:
        while True:
            if len(recv_buff) >= 4:
                packet_len = get_int(recv_buff)
                if packet_len <= len(recv_buff):
                    # 不是断包
                    cipher = recv_buff[:packet_len]
                    recv_buff = recv_buff[packet_len:]
                    packet = Packet(cipher)
                    packet.decrypt()
                    if show_recv:
                        show_data(packet, "R <==")  # 界面添加recv数据
                    if packet.version == 0:  # 正确包
                        if packet.cmd_id == 228 and is_get_lamu_info:  # 第1次进入游戏时获取拉姆ID
                            is_get_lamu_info = False
                            lamu_id = get_int(packet.body)
                            window.lamu_get_info()
                        if packet.cmd_id == 212 and get_int(packet.body[4:]) == 1:  # 获取拉姆信息
                            lamu_id = get_int(packet.body[8:])
                            lamu_name = get_name(packet.body[24:])
                            lamu_value = get_int(packet.body[79:])
                            lamu_level = get_lamu_level(lamu_value)
                        if packet.cmd_id == 204:  # 获取超拉信息
                            super_lamu_value = get_int(packet.body[100:])
                            super_lamu_level = get_super_lamu_level(super_lamu_value)
                        if packet.cmd_id == 1209:  # 拉姆变身获得物品
                            if lamu_times == 0:
                                lamu_last_skill_success = True
                            else:
                                lamu_max_skill_success = True
                            window.lamu_collect_result()
                            lamu_times += 1
                        if packet.cmd_id == 8200:  # 获取摩摩怪能量和活力值
                            if not window.timer("摩摩怪").isActive():
                                mmg_energy = get_int(packet.body[40:])
                                mmg_vigour = get_int(packet.body[48:])
                        if packet.cmd_id == 8224:  # 获取摩摩怪Boss已挑战次数
                            if not window.timer("摩摩怪").isActive():
                                mmg_super_boss_times = 10 - get_int(packet.body)
                                mmg_lamu_boss_times = 10 - get_int(packet.body[4:])
                                if datetime.now().hour == 13:
                                    mmg_limit_boss_times = 10 - get_int(packet.body[8:])
                                else:
                                    mmg_limit_boss_times = 0
                                mmg_boss_index1 = mmg_super_boss_times
                                mmg_boss_index2 = mmg_boss_index1 + mmg_lamu_boss_times
                                mmg_boss_index3 = mmg_boss_index2 + mmg_limit_boss_times
                        if packet.cmd_id == 10007:  # 获取摩摩怪游戏ID
                            mmg_game_id = packet.body[18:130].hex()
                        if packet.cmd_id == 8212:  # 翻牌成功
                            mmg_times += 1
                        if packet.cmd_id == 8226:  # 获取师徒ID
                            mmg_students.clear()
                            students_num = get_int(packet.body[40:])
                            for i in range(students_num):
                                student_id = get_int(packet.body[44 + i * 12:])
                                mmg_students.append(student_id)
                            teacher_num = get_int(packet.body[12:])
                            if teacher_num > 0:
                                teacher_id = get_int(packet.body[16:])
                                mmg_students.append(teacher_id)
                        if packet.cmd_id == 8208:  # 获取好友ID
                            mmg_friends_dict.clear()
                            friends_num = get_int(packet.body)
                            for i in range(friends_num):
                                friend_id = get_int(packet.body[4 + i * 12:])
                                friend_level = get_int(packet.body[12 + i * 12:])
                                mmg_friends_dict[friend_id] = friend_level
                            for student_id in mmg_students:
                                mmg_friends_dict[student_id] = 100
                            # 师徒放前面，后面好友等级从高到低
                            mmg_friends = sorted(mmg_friends_dict.items(), key=lambda item: item[1], reverse=True)
                            mmg_friends_num = len(mmg_friends)
                        if packet.cmd_id == 8218 and get_int(packet.body) in [mmg_query_size_max, mmg_friends_num % mmg_query_size_max]:
                            # 查询好友能否对战
                            query_size = get_int(packet.body)
                            index = 4
                            for i in range(query_size):
                                friend_id = get_int(packet.body[index:])
                                fight_state = get_int(packet.body[index + 4:])
                                other_state_num = get_int(packet.body[index + 8:])
                                if fight_state == 0:  # 未挑战过的
                                    friend_level = mmg_friends_dict[friend_id]
                                    if friend_level == 100:
                                        fight_type = 4  # 师徒
                                    else:
                                        fight_type = 0  # 好友
                                    mmg_fight_friends.append((friend_id, fight_type))
                                for j in range(other_state_num):
                                    state = get_int(packet.body[index + 12 + j * 4:])
                                    mmg_friends_state_dict[state].append(friend_id)
                                index += 12 + other_state_num * 4
                            mmg_query_page += 1
                            if mmg_query_page == mmg_query_page_max:  # 查询完毕
                                # 将师徒放在最前面，因为返回的好友挑战信息和查询时的好友ID顺序可能不一样
                                mmg_fight_friends.sort(key=lambda item: item[1], reverse=True)
                                window.mmg_start(4)
                        if packet.cmd_id == 12004:  # 魔灵用户信息
                            mlcs_energy = get_int(packet.body[13:], 2)  # 剩余体力值
                            mlcs_fight_elves_dict.clear()
                            for i in range(15):  # 出战魔灵信息
                                elf_id = get_int(packet.body[24 + i * 4:])
                                if elf_id != 0:
                                    mlcs_fight_elves_dict[elf_id] = elf_id
                        if packet.cmd_id == 12018 and not window.send_thread.isRunning():  # 魔灵背包信息
                            mlcs_elves_dict.clear()
                            elves_num = get_int(packet.body)
                            for i in range(elves_num):
                                elf_id = get_int(packet.body[4 + i * 28:])
                                elf_type = get_int(packet.body[4 + i * 28 + 4:])
                                elf_level = get_int(packet.body[4 + i * 28 + 9:], 1)
                                if elf_id not in mlcs_fight_elves_dict and elf_type != 0x1A3F6A and elf_level == 1:  # 非出战魔灵、烈焰剑齿虎且等级为1的可删除
                                    mlcs_elves_dict[elf_id] = elf_id
                        if packet.cmd_id == 11009:  # 魔灵竞技场信息
                            info_type = get_int(packet.body)
                            if info_type == 5:  # 竞技场信息
                                remain_times = 10 - get_int(packet.body[4:])  # 剩余挑战次数
                                purchase_times = get_int(packet.body[8:])  # 金豆购买挑战次数
                                mlcs_arena_times = remain_times + purchase_times
                            elif info_type == 1:  # 经验之路信息
                                mlcs_exp_times = 3 - get_int(packet.body[4:])  # 剩余挑战次数
                        if packet.cmd_id == 8990:  # 元素骑士信息
                            ysqs_energy = get_int(packet.body[28:])
                            ysqs_attack = get_int(packet.body[44:])
                            ysqs_max_floor = get_int(packet.body[68:])
                        if packet.cmd_id == 1014:  # 餐厅信息
                            ct_cooked_dishes_dict.clear()
                            ct_cooking_dishes_dict.clear()
                            window.ctDishBox.clear()
                            dishes_num = get_int(packet.body[68:])
                            for i in range(dishes_num):
                                dish_pos = get_int(packet.body[72 + i * 24:])
                                dish_type = get_int(packet.body[72 + i * 24 + 4:])
                                dish_id = get_int(packet.body[72 + i * 24 + 8:])
                                dish_num = get_int(packet.body[72 + i * 24 + 12:])
                                dish_step = get_int(packet.body[72 + i * 24 + 16:])
                                dish_time = get_int(packet.body[72 + i * 24 + 20:])
                                dish_info = get_dish_info(dish_type)
                                if dish_step == 6:  # 已熟菜信息
                                    ct_cooked_dishes_dict[dish_info.get("名称")] = {
                                        "ID": dish_id, "种类": dish_type, "位置": dish_pos, "时间": dish_info.get("时间"), "数量": dish_num
                                    }
                                elif dish_step == 3 and dish_info.get("名称") in ["酱爆雪顶菇", "阳光酥油肉松"]:  # 正在做的菜信息
                                    ct_cooking_dishes_dict[dish_pos] = {
                                        "ID": dish_id, "种类": dish_type, "位置": dish_pos, "时间": dish_time, "跳过收菜": False
                                    }
                                elif dish_step < 3:
                                    window.ct_cook_after(dish_id, dish_type, dish_step, True)
                                    if dish_info.get("名称") in ["酱爆雪顶菇", "阳光酥油肉松"]:
                                        ct_cooking_dishes_dict[dish_pos] = {
                                            "ID": dish_id, "种类": dish_type, "位置": dish_pos, "时间": -3, "跳过收菜": False
                                        }
                            window.ctDishBox.addItems(ct_cooked_dishes_dict.keys())
                            window.enable_ct_button(len(ct_cooked_dishes_dict) > 0)
                        if packet.cmd_id == 1017:  # 餐厅做菜信息
                            dish_type = get_int(packet.body)
                            dish_id = get_int(packet.body[4:])
                            dish_pos = get_int(packet.body[8:])
                            dish_step = get_int(packet.body[12:])
                            if dish_step < 3:
                                window.ct_cook_after(dish_id, dish_type, dish_step)
                            elif dish_step == 3:  # 做菜步骤完成后，更新灶台信息
                                ct_cooking_dishes_dict[dish_pos] = {
                                    "ID": dish_id, "种类": dish_type, "位置": dish_pos, "时间": 0, "跳过收菜": False
                                }
                        if packet.cmd_id == 1021:  # 餐厅收菜信息
                            dish_type = get_int(packet.body)
                            dish_id = get_int(packet.body[4:])
                            dish_pos = get_int(packet.body[12:])
                            dish_info = get_dish_info(dish_type)
                            if dish_info.get("名称") not in ct_cooked_dishes_dict:  # 新收的菜
                                ct_cooked_dishes_dict[dish_info.get("名称")] = {
                                    "ID": dish_id, "种类": dish_type, "位置": dish_pos, "时间": dish_info.get("时间")
                                }
                                window.ctDishBox.addItem(dish_info.get("名称"))
                                window.enable_ct_button(True)
                    else:  # 错误包
                        if packet.cmd_id == 1209:  # 拉姆变身获得物品
                            if lamu_times == 0:
                                lamu_last_skill_success = False
                            else:
                                lamu_max_skill_success = False
                else:
                    break
            else:
                break
    # 其他包
    else:
        if cipher.startswith(b'\x00\x00'):  # 摩尔包
            while True:
                if len(recv_buff) >= 4:
                    packet_len = get_int(recv_buff)
                    if packet_len <= len(recv_buff):
                        # 不是断包
                        cipher = recv_buff[:packet_len]
                        if show_recv:
                            show_data(Packet(cipher), "R <==", socket_num)  # 界面添加recv数据
                        recv_buff = recv_buff[packet_len:]
                    else:
                        break
                else:
                    break
        elif cipher.startswith((b'\x3C\x70', b'\x3C\x3F')):  # 其他包
            if show_recv:
                show_data(Packet(cipher), "R <==", socket_num)  # 界面添加recv数据
            recv_buff = recv_buff[length:]


if __name__ == '__main__':
    hook = ffi.dlopen("hook.dll")
    hook.SetSendCallBack(process_send_packet)
    hook.SetRecvCallBack(process_recv_packet)
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
