"""
摩尔庄园登录模块 - Python 实现

对应 Go 代码:
  - login/login.go   -> Login / LoginHash / md5text
  - conn/connection.go -> MoleConn / Header / Packet / SendRecv / SendCmd / sendHdr / receive
"""

import hashlib
import socket
import struct
import threading
import time
from typing import Optional, Tuple

# ============================================================
# 常量
# ============================================================
HEADER_LENGTH = 0x11           # 17 字节
CMD_LOGIN = 103                # 登录命令号
LOGIN = 0xC9                   # 登录特殊命令(用于 nonce 跳过)

# 服务端错误码 -> 中文消息
ERROR_MSG = {
    -10004: "你填入的米米号不存在！",
    -10012: "使用了非法语言",
    -10023: "你投的鲜花或泥巴已经超过了上限,明天再来吧！",
    -10025: "这个小摩尔好像不欢迎你哦!",
    -10026: "这个小摩尔在你的黑名单里哦，你不能加他为好友呢！",
    -10512: "这件宝贝现在还不能送给你哦！",
    -10913: "今天你已经不能洒水或施肥\n了，休息下明天再来吧！",
    -10918: "你今天不能再给SMC向导投票了！",
    -10972: "你今天已经创建过一个派对了，明天再来吧！",
    -10991: "你今天不能再送福气了！",
    -11002: "数据库出错！",
    -11105: "这个位置没有蛋哦！",
    -11111: "你的拉姆表现很棒！明天一定要再来！只要坚持锻炼5天，我会送你一台拉姆跑步机！",
    -11117: "你的豆豆不足哦！",
    -11119: "兑换物品数量不足哦！",
    -11130: "你的宠物已经超过了上限！",
    -11140: "你的拉姆在拉姆运动会上没有获得任何一项参赛勋章，不能领取运动奖杯哦！明年继续努力吧！",
    -11170: "你已经有三笔存款！",
    -11171: "咳咳，我可不是零钱罐，低于1000摩尔豆的存款我是不接受的哦！请重新输入存款金额...",
    -11172: "这笔存款不可以中途取出哦！",
    -11173: "这笔存款不存在哦！",
    -11174: "这笔存款已存在哦！",
    -11175: "无效的存款期限值！",
    -11190: "你今天卖的东西超过上限啦，明天再来吧！",
    -11201: "你的小屋家具超过上限！",
    -11301: "你填入的米米号不存在！",
    -11311: "这棵毛毛树今天已经有了\n充足的水分和养料了，请明天再来吧！",
    -11313: "他今天不能再接受更多的投票了！",
    -11810: "服务器上的派对已满，你可以去其他服务器试试哦！",
    -12503: "你已经加入这个班级了,赶快进入班级看看吧！",
    -12504: "班级不存在喔！",
    -12523: "果实已经被摘取过啦！",
    -12526: "这里的动物还没长大哦，你还不能收获它们！",
    -12530: "目前鱼塘已经被锁了，你钓不到任何鱼哦！",
    -12531: "你今天已经钓过鱼了，不能太贪心哦，明天再来吧！",
    -12535: "你的牧场太拥挤了，已经不能再养更多的动物了！",
    -12536: "你的鱼塘太拥挤了，已经不能再养更多的鱼了！",
    -12537: "你捕捉了太多这种小动物，不能再捕捉了！！",
    -12538: "饲料房里不能放下这么多饲料哦！",
    -12539: "你已经领过了奖品！",
    -12540: "班级奖品已经领过了！",
    -12543: "你已经报过名了！",
    -12544: "已经接了任务！",
    -12545: "还没接任务！",
    -12546: "已经完成任务！",
    -12548: "对方分数太低，不能PK哦！",
    -12569: "已经拥有了这辆车",
    -12582: "太多人孵过了这个蛋啦！",
    -12583: "你今天已经孵过蛋啦,让别的小摩尔过来帮忙吧！",
    -12591: "这个蛋已经快要孵化了，不能再孵了哦！",
    -12598: "我这边已经卖光了，下个整点再来吧！",
    -12599: "你已经领过铃铛了！",
    -12600: "牧场饲养的昆虫达到上限！",
    -12602: "牧场中只能有一个菲尼克斯！",
    -12603: "牧场中养殖该物种超过上限！",
    -12604: "\t这棵植物被授粉超过上限了！",
    -12605: "\t这棵植物还不能授粉！",
    -12606: "\t你这只蝴蝶今天已经太疲倦啦！",
    -12607: "\t你身上已经没有礼物了，快去圣诞屋领取后再来赠送吧!",
    -12609: "\t\t你的壁炉中还没有礼物呢，给别人送上一份礼物去吧，说不定你也会收到惊喜的！",
    -12610: "你今天已经得到太多能量星啦，明天再来吧!",
    -12611: "该植物状态异常，无法进行施肥哦！",
    -12612: "你好像还没有化肥哦，快去梅森那里看看吧！",
    -12613: "这棵植物今天再施肥就会脱水了，要合理使用化肥！",
    -12615: "\t你的拉姆已经拥有这个物品啦！",
    -12616: "你的拉姆还没有学完课程，或未通过考试哦！",
    -12618: "你今天已经抽奖超过十次了，不能贪多哦！",
    -12619: "你今天已经中奖10次了，运气不错，但不能贪多哦！",
    -12628: "你的拉姆已经是第五阶段了哦！",
    -12629: "你的拉姆正在技能学习当中哦！",
    -12634: "你的母奶牛今天已经挤过奶啰！明天再来看看吧！",
    -12635: "你的母奶牛已经挤过 5 次奶啦！不能再挤奶了哟！",
    -12638: "你的菜吃完了！",
    -12639: "你的菜正在做！",
    -12640: "没有这道菜！",
    -12641: "雇佣的雇员太多了！不能再雇佣了！",
    -12642: "菜的数量到达上限！",
    -12643: "不是系统拉姆！",
    -12644: "菜还没煮熟！",
    -12645: "所有服务员都被解雇了，吃不了菜！",
    -12648: "这道菜已经糊了！",
    -12656: "你没有足够的食材做这道菜！",
    -12674: "你已经拥有卡牌册了，不能再次领取了哦。",
    -12682: "你用外挂，以为我不知道？小心封你号哦！下次不能再这样啦！",
    -12683: "你今天已经不能再购买这个物品了,请明天再来吧！",
    -12690: "你每天最多能获得200个火焰纹章哦！明天再过来吧！",
    -12712: "现在已经不能加课了，完成今天的教学安排准备考试吧！",
    -12718: "现在到了中间休息时间，耐心等待下一轮竞猜开始吧！",
    -12719: "这一轮你已经猜过了，耐心等待结果吧！",
    -12720: "今天已经联谊过三次了，学生已经很累啦 ，明天再来吧。",
    -12721: "今天已经和这间教室的学生联谊过了，去别人的教室看看吧。",
    -12722: "你还没有招收学生哦，去拉姆教导处招收学生以后再过来吧。",
    -12723: "兑换的数量不够哦！",
    -12724: "你今天已经给他送过苞子花啰！一天只能给一位摩尔送出一个苞子花哦！",
    -12725: "你今天已经送出太多的苞子花啰！请明天再来赠送吧！",
    -12736: "这只动物已经吃了太多啦，明天再过来喂它吧。",
    -12737: "你还没有快快长脆脆酥，快去用点点豆买一些吧。",
    -12741: "捕获的圣光兽数量已经太多了！",
    -12758: "这个天使已经成熟了，不能使用这个道具！",
    -12759: "这个道具一个天使一天只能使用一次哦！",
    -12764: "\t这个天使一定可以发生变异的，好好期待吧～",
    -12765: "这只天使已经变异啦，不需要再使用这个道具了。",
    -12768: "这个天使的星级比较高哦，需要使用更高级的道具才能生效。",
    -12769: "这个天使的变异几率已经提升过啦，不能再次使用道具了。",
    -12777: "你的精力是满的哦，不能再次使用道具了。",
    -16020: "留言板上已经贴满了留言！",
    -40001: "你的米米号不存在！",
    -40002: "这个神奇密码是错误的，再试试吧！",
    -40003: "这个神奇密码是错误的，再试试吧！",
    -40004: "你的神奇密码已经过了有效期了！",
    -40005: "这个神奇密码已经无效啦！",
    -40006: "这个神奇密码已经被使用过啦！",
    -40007: "这个神奇密码是错误的，再试试吧！",
    -40008: "这个神奇密码是错误的，再试试吧！",
    -40009: "宝箱里的宝贝你都已经有啦！不能再拥有了哦！",
    -40010: "这个神奇密码是错误的，再试试吧！",
    -40011: "宝箱好像有点问题哟！稍等一会再来试试吧！",
    -51001: "这个礼物没办法给你喔!！",
    -51002: "你输入的神奇密码不存在哦，检查看看是不是输入错误了呢？",
    -51003: "你输入的神奇密码还没有被开启，请拨打客服热线查询哦！",
    -51004: "你输入的神奇密码不在有效期内，请拨打客服热线查询哦！",
    -51005: "你输入的神奇密码被冻结，请拨打客服热线查询哦！",
    -51006: "你输入的神奇密码已经使用过,无法兑换哦!",
    -51007: "兑换失败！",
    -51008: "你的神奇密码暂时不能使用哦！",
    -51009: "领取物品达到上限！",
    -51010: "一个号只能用一个兑换码！",
    -51100: "你输入的神奇密码不是在这里兑换哦，请你去问问其他地方看看吧！",
    -52013: "这件宝贝已经购买完了哦！",
    -52015: "你已经拥有这件物品，不要浪费摩尔金豆哟！",
    -52016: "你已经拥有这件商品或这套商品某一部分，为避免重复，请重新选择或单件购买！",
    -52017: "你已经拥有这件商品或这套商品某一部分，为避免重复，请重新选择或单件购买！",
    -52019: "你已经拥有这件物品，不要浪费摩尔金豆哟！",
    -52021: "你已经拥有这件物品，不要浪费摩尔金豆哟！",
    -52105: "真可惜，你的金豆不足！",
    -52205: "真可惜，你的摩尔金豆不足！",
    -100001: "你不能在这个场景变身！",
    -100002: "今天你已经兑换了许多礼物，不可以再兑换了哦，请你明天再来吧！",
    -100003: "你的好朋友已经拥有太多这样礼品了,你可以选择其它礼品送他！",
    -100004: "你已经领取过本月的SMC工资了，下个月再来吧!",
    -100012: "今天你得到太多摩尔豆了！",
    -100020: "你还没有报名，快去火神山脚下报名吧！",
    -100024: "你已经领过了，不要太贪心哦！",
    -100025: "你已经领过了，不要太贪心哦！",
    -100030: "你真是个充满战斗力的小摩尔啊！可是，今天已经挑战超过30次了，休息下明天再来吧！",
    -100031: "今天你已经拿了很多卡片了，赶快去和其他队的队员交换吧！",
    -100032: "卡牌不能匹配！",
    -100034: "不能购买该物品!",
    -100042: "你今天已经领了2只小羊了，记得好好照顾它们哦！",
    -100046: "拉姆已经回家了！",
    -100047: "今天已经送了太多！",
    -100048: "你今天已经送了太多礼物啦，歇一歇，明天再来吧！",
    -100053: "你还没有参赛哦！",
    -100055: "你没有足够的萤火草！",
    -100056: "不能邀请你的好友到飞船上！",
    -100057: "你还没有通过SMC驾驶员考试哦！",
    -100059: "不能太贪心哦，你已经领取过摩尔豆的奖励了！",
    -100060: "为班级贡献300分以上会有特殊奖励哦，下次记得踊跃参加哦！",
    -100061: "你不是班长哦，只有班长才可以领取班级荣誉奖励哦！",
    -100063: "不能太贪心哦，你已经领取过了！",
    -100066: "你还没有超级拉姆哦！",
    -100067: "这个合成机的位置正在使用哦！",
    -100069: "百宝箱里的材料还不够加工需求哦，再仔细看一下吧。",
    -100071: "今天已经很辛苦了，明天继续来合成吧！",
    -100072: "每次只能使用一个加工机的制作位置哦！",
    -100075: "你的糖果太多啦！糖果篮子里最多只能装满200颗糖果哦！",
    -100078: "你已经做过此次问卷调查！",
    -100079: "你的超级拉姆正在彩虹姐姐那里托管，所以不能召唤过来哦！",
    -100080: "你没有渔网！",
    -100081: "你的渔网太破了，不能用了！",
    -100082: "你已经有渔网了！",
    -100085: "用户的糖果不够！",
    -100086: "你今天已经拿了5次糖果了！",
    -100090: "你的超级拉姆今天已经修理时光门5次啦，休息一下吧！",
    -100092: "每次查询最多10个，超过了这个限制！",
    -100094: "你不能领取这件物品哦!",
    -100096: "你的养殖级别不够！",
    -100097: "已经关门啦，下次再来吧!",
    -100101: "你已经show的太累了，明天再来吧！",
    -100102: "你今天已经买了很多了，明天再来吧！",
    -100104: "这个位置已经有蛋啦！",
    -100110: "已经有人在跳舞了！",
    -100112: "你已经钓了很多鱼了，保持生态平衡，明天再来吧！",
    -100114: "你今天捡的钱够多了！",
    -100115: "在你犹豫期间，这件年货已经被别人抢购啦！机不可失，失不再来哟！",
    -100116: "你今天从别人家钓了太多的鱼！",
    -100117: "你的精力真的太充沛了！但是年货可是有限的！明天再来当摊主吧！",
    -100118: "\t你今天已经拿的太多了，明天再来吧！",
    -100121: "\t你已经拥有这个脚印啦！",
    -100122: "你的超级拉姆正在上课，所以不能召唤过来哦！",
    -100124: "今天已经索取很多线索了，自己动动脑筋吧！",
    -100125: "你还有任务没完成，暂时不能接这个任务哦！",
    -100126: "你还没有车库，快去交通署找贝塔吧！",
    -100127: "你今天搬石头已达到上限了，多多休息，改天再来吧！",
    -100129: "企鹅爸爸已经为你的企鹅蛋孵化过啦，明天再来吧！",
    -100144: "学会小水滴、小火苗、小树苗技能后，再来领取礼包吧！",
    -100145: "这周你已经领取过该礼物了，不能太贪心哦！",
    -100150: "你的拉姆生病了，赶紧带它去拉姆医院看病吧！",
    -100166: "你拉姆现在状态很不好，带它回去吃点东西，洗个澡，然后再过来吧。",
    -100170: "你已经拥有土地证了！不能再领取了哟！",
    -100171: "今天发放的土地证到达上限了！明天再来看看吧！",
    -100172: "你还没有土地证哟！",
    -100173: "今天开放时间已经过了！明天再来看看吧！",
    -100174: "你的餐厅不存在！",
    -100175: "这不是你的餐厅，此功能无效！",
    -100176: "你已经有餐厅了！",
    -100177: "你还没有餐厅！",
    -100178: "这个餐厅不是你的！",
    -100179: "你的拉姆已经被雇佣了！",
    -100180: "你的餐厅等级太低了！",
    -100181: "没有位置了！",
    -100182: "现在营业时间已经过了，快去好好休息吧！",
    -100185: "这套房型或者内部装潢现在还不能建设哦。",
    -100186: "你还没有达到这套房型或者内部装潢的解锁条件！",
    -100189: "拉姆没有成长哦，快速成长温泉的力量每天只能发动一次呢，明天再来试试吧！",
    -100197: "你已经拿了太多这个东西了",
    -100199: "你的操作不对哦！没有获得奖品！",
    -100202: "你已经领取过大礼包了！",
    -100203: "你的摩尔等级不够，不能领取这个任务！",
    -100208: "现在已经放学了，明天再来上课吧！",
    -100216: "这个蛋已经被别人领走了，去别的地方找找看吧！",
    -100312: "你还没有把图片拼合完成，继续调查吧！",
    -100313: "你已经领取过这个奖励了，试着解开其他谜团吧！",
    -100327: "你今天还没玩游戏哦，赶快去玩吧！",
    -100353: "支配力达到最大 ",
    -100354: "你已经领取过这个奖励了 ",
    -100361: "摩灵背包满了！",
    -100363: "战斗已经结束",
    -100364: "不在活动时间内",
    -101117: "你的摩尔豆不够啰！",
}

# 登录响应结果 -> 消息
LOGIN_ERR_MSG = {
    0: "Success",
    1: "Incorrect password",
    2: "Incorrect captcha",
}


# ============================================================
# 加密/解密 (对应 conn/connection.go 中的 encrypt/decrypt)
# ============================================================

# 密钥 (对应 Go 中的 var key)
_KEY = b"^FStx,wl6NquAVRF@f%6\x00"
_KEYLEN = len(_KEY)  # 22


def crc(data: bytes) -> int:
    """计算 CRC (对应 Go 的 CRC 函数)"""
    c = 0
    for v in data:
        c = (c ^ v) & 0xFF
    return c


def encrypt_data(plain: bytes) -> bytes:
    """
    加密算法 (对应 Go 的 encrypt 函数)
    1. 逐字节 XOR 密钥(循环)
    2. 从尾部向前: cipher[i] |= cipher[i-1]>>3, cipher[i-1] <<= 5
    3. cipher[0] |= 3
    """
    plen = len(plain)
    cipher = bytearray(plen + 1)

    # Step 1: XOR with key
    for i in range(plen):
        cipher[i] = plain[i] ^ _KEY[i % _KEYLEN]

    # Step 2: 移位混淆 (从尾部向前)
    for i in range(plen, 0, -1):
        cipher[i] = cipher[i] | (cipher[i - 1] >> 3)
        cipher[i - 1] = (cipher[i - 1] << 5) & 0xFF

    # Step 3: 标记位
    cipher[0] = cipher[0] | 3

    return bytes(cipher)


def decrypt_data(cipher: bytes) -> bytes:
    """
    解密算法 (对应 Go 的 decrypt 函数)
    encrypt 的逆操作
    """
    plen = len(cipher) - 1
    plain = bytearray(plen)
    ki = 0

    for i in range(plen):
        # 逆移位: plain[i] = (cipher[i]>>5) | (cipher[i+1]<<3)
        plain[i] = ((cipher[i] >> 5) | ((cipher[i + 1] << 3) & 0xFF)) & 0xFF
        # 逆 XOR
        plain[i] = plain[i] ^ _KEY[ki % _KEYLEN]
        ki += 1
        if ki == _KEYLEN:
            ki = 0

    return bytes(plain)


# ============================================================
# 协议数据结构
# ============================================================

class Header:
    """协议头 (对应 Go 的 Header struct)"""
    FORMAT = ">I B i I i"  # Len(uint32) Nonce(uint8) Cmd(int32) User(uint32) ErrCode(int32)
    SIZE = struct.calcsize(FORMAT)  # 17 字节

    def __init__(self, length: int = 0, nonce: int = 1, cmd: int = 0,
                 user: int = 0, err_code: int = 0):
        self.length = length
        self.nonce = nonce
        self.cmd = cmd
        self.user = user
        self.err_code = err_code

    def pack(self) -> bytes:
        return struct.pack(self.FORMAT, self.length, self.nonce,
                           self.cmd, self.user, self.err_code)

    @classmethod
    def unpack(cls, data: bytes) -> "Header":
        length, nonce, cmd, user, err_code = struct.unpack(cls.FORMAT, data)
        return cls(length, nonce, cmd, user, err_code)


class Packet:
    """响应包 (对应 Go 的 Packet struct)"""
    def __init__(self, header: Header, data: bytes):
        self.header = header
        self.data = data


# ============================================================
# 登录请求/响应 (对应 login/login.go)
# ============================================================

class LoginReq:
    """
    登录请求 (对应 Go 的 LoginReq struct)
    struct { Pwd [32]byte; ZZZ1 int32; ZZZ2 int32; ZZZ3 int32; Captcha [22]byte }
    """
    FORMAT = ">32s i i i 22s"

    def __init__(self, pwd: bytes):
        # pwd 必须是 32 字节
        self.pwd = pwd[:32] if len(pwd) >= 32 else pwd.ljust(32, b'\x00')
        self.zzz1 = 0
        self.zzz2 = 1
        self.zzz3 = 0
        self.captcha = b'\x00' * 22

    def pack(self) -> bytes:
        return struct.pack(self.FORMAT, self.pwd, self.zzz1, self.zzz2,
                           self.zzz3, self.captcha)


class LoginResp:
    """
    登录响应 (对应 Go 的 LoginResp struct)
    struct { Result int32; Session [16]byte; Errlen int32 }
    """
    FORMAT = ">i 16s i"

    def __init__(self):
        self.result = 0
        self.session = b'\x00' * 16
        self.errlen = 0

    @classmethod
    def unpack(cls, data: bytes) -> "LoginResp":
        resp = cls()
        resp.result, resp.session, resp.errlen = struct.unpack(cls.FORMAT, data[:struct.calcsize(cls.FORMAT)])
        return resp


# ============================================================
# MoleConn - TCP 连接封装 (对应 conn/connection.go 的 MoleConn)
# ============================================================

class MoleConn:
    """摩尔庄园 TCP 连接"""

    def __init__(self, host: str, user: int, encrypt: bool = False):
        self.host = host
        self.user = user
        self.encrypt = encrypt
        self.nonce = 65

        self._sock: Optional[socket.socket] = None
        self._resp_channels: dict[int, "queue.Queue"] = {}
        self._quit = threading.Event()
        self._recv_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        """建立 TCP 连接并启动接收线程 (对应 NewMoleConn)"""
        host, port = self.host.rsplit(":", 1)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((host, int(port)))

        self._recv_thread = threading.Thread(target=self._receive, daemon=True)
        self._recv_thread.start()

    def close(self) -> None:
        """关闭连接 (对应 Close)"""
        self._quit.set()
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None

    def _recv_exact(self, n: int) -> bytes:
        """从 socket 精确读取 n 字节"""
        data = b""
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed by server")
            data += chunk
        return data

    def _read_header(self) -> Header:
        """读取协议头 (对应 readHdr)"""
        data = self._recv_exact(Header.SIZE)
        return Header.unpack(data)

    def _receive(self) -> None:
        """后台接收协程 (对应 Go 的 receive goroutine)"""
        import queue
        while not self._quit.is_set():
            try:
                hdr = self._read_header()
            except Exception:
                continue

            body_len = hdr.length - HEADER_LENGTH
            try:
                resp = self._recv_exact(body_len)
            except Exception:
                continue

            with self._lock:
                ch = self._resp_channels.pop(hdr.cmd, None)
            if ch is not None:
                ch.put(Packet(hdr, resp))

    def _update_nonce(self, length: int, cmd: int, data: bytes) -> None:
        """更新 nonce (对应 updateNonce)"""
        if cmd == LOGIN:
            return
        tmp = self.nonce - (self.nonce // 7) + 147 + (length % 21) + (cmd % 13) + crc(data)
        self.nonce = tmp % 256

    def _send_header(self, hdr: Header, req_body: bytes) -> bytes:
        """
        发送 Header + Body，阻塞等待响应 (对应 sendHdr)
        """
        import queue
        ch: "queue.Queue" = queue.Queue(maxsize=1)

        with self._lock:
            self._resp_channels[hdr.cmd] = ch

        # 发送 header + body
        self._sock.sendall(hdr.pack())
        self._sock.sendall(req_body)

        # 阻塞等待响应
        packet = ch.get()

        if packet.header.err_code != 0:
            msg = ERROR_MSG.get(packet.header.err_code, f"未知错误码: {packet.header.err_code}")
            raise MoleError(packet.header.err_code, msg)

        return packet.data

    def send_cmd(self, cmd: int, req_obj) -> bytes:
        """
        发送命令并接收原始响应 (对应 SendCmd)
        """
        import io

        if self.encrypt:
            # 加密模式: 先序列化 -> 更新 nonce -> 加密 -> 发送
            buf = io.BytesIO()
            # 这里 req_obj 需要实现 pack() 方法
            req_bytes = req_obj.pack()
            buf.write(req_bytes)
            raw = buf.getvalue()

            self._update_nonce(17 + len(raw), cmd, raw)

            hdr = Header(
                length=len(raw) + 1 + 17,
                nonce=self.nonce,
                cmd=cmd,
                user=self.user,
                err_code=0,
            )
            req_bytes = encrypt_data(raw)
        else:
            # 非加密模式
            req_bytes = req_obj.pack()
            hdr = Header(
                length=len(req_bytes) + HEADER_LENGTH,
                nonce=1,
                cmd=cmd,
                user=self.user,
                err_code=0,
            )

        data = self._send_header(hdr, req_bytes)

        if self.encrypt:
            data = decrypt_data(data)

        time.sleep(0.2)  # 对应 Go 中的 time.Sleep(200 * time.Millisecond)
        return data

    def send_recv(self, cmd: int, req_obj, resp_cls) -> object:
        """
        发送命令并解析响应 (对应 SendRecv)
        resp_cls: 响应类，需有 unpack(bytes) 类方法
        """
        import io
        data = self.send_cmd(cmd, req_obj)
        return resp_cls.unpack(data)


class MoleError(Exception):
    """摩尔庄园协议错误"""
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ============================================================
# 密码处理 & 登录 (对应 login/login.go)
# ============================================================

def md5text(pwd: str) -> bytes:
    """
    双重 MD5 哈希 (对应 Go 的 md5text)
    1. MD5(pwd) -> hex字符串
    2. MD5(hex字符串) -> hex字符串
    3. 取前 32 字节
    """
    hash1 = hashlib.md5(pwd.encode()).hexdigest().encode()
    hash2 = hashlib.md5(hash1).hexdigest().encode()
    return hash2[:32]  # 32 字节


def login(user: int, pwd: str, host: str = "203.73.22.200", port: int = 8888) -> bytes:
    """
    登录函数 (对应 Go 的 Login)
    参数:
        user: 用户 ID (米米号)
        pwd:  原始密码
        host: 服务器地址
        port: 服务器端口
    返回:
        16 字节的 session (会话令牌)
    """
    return login_hash(user, md5text(pwd), host, port)


def login_hash(user: int, pwd_hash: bytes, host: str = "203.73.22.200", port: int = 8888) -> bytes:
    """
    使用哈希后的密码登录 (对应 Go 的 LoginHash)
    参数:
        user:     用户 ID
        pwd_hash: 32 字节密码哈希 (来自 md5text)
        host:     服务器地址
        port:     服务器端口
    返回:
        16 字节的 session
    """
    conn = MoleConn(f"{host}:{port}", user, encrypt=False)
    try:
        conn.connect()
        req = LoginReq(pwd_hash)
        resp = conn.send_recv(CMD_LOGIN, req, LoginResp)
    finally:
        conn.close()

    # 注意：原 Go 代码中 err 处理有逻辑问题
    # 这里 resp.result 是 LoginResp 的 Result 字段
    # send_recv 内部的 send_cmd -> sendHdr 已经检查了 Header.ErrCode
    # 但 LoginResp.Result 是业务层返回码，这里单独检查
    if resp.result != 0:
        msg = LOGIN_ERR_MSG.get(resp.result, f"未知错误: {resp.result}")
        raise MoleError(resp.result, msg)

    return resp.session


# ============================================================
# 使用示例
# ============================================================

if __name__ == "__main__":
    import os

    user_id = int(os.getenv("USER", "0"))
    password = os.getenv("PASSWORD", "")

    if user_id == 0 or not password:
        print("请设置环境变量 USER 和 PASSWORD")
        exit(1)

    try:
        session = login(user_id, password)
        print(f"登录成功! Session: {session.hex()}")
    except MoleError as e:
        print(f"登录失败: {e}")
    except Exception as e:
        print(f"网络错误: {e}")
