"""
paopaolong.py —— 摩尔庄园「泡泡龙」小游戏自动通关（游戏服务器段）

协议背景（来自 ffdec 反编译 /paopaolongSocket.as + gameSocket.as）：
- 游戏服务器包格式与主服务器相同，使用 !IBIII 头（大端，不加密）：
    PkgLen:uint(4) | Version:byte(1)=1 | Command:uint(4) | UserID:uint(4) | Result:int(4)=0
    其后为 body，PkgLen = 17 + len(body)。
- 进入流程：先向游戏服务器发 7531(请求进入, body=128B token)，服务端回 7534 初始化；
  首关棋盘由服务端直接推 797E；过关后客户端发 31101(新关卡) 请求下一关。
- 关键 opcode（游戏服务器段）：
    31102(797E) 棋盘布局: [level:1B][count:2B][(x:1B,y:1B,type:1B) × count]，type=0xFF 为空位
    31106(7982) 发射落点: [x:1B][y:1B][seq:1B]   (颜色由客户端自行决定，不在包内)
    31107(7983) 同色消除: [seq:1B][count:1B][(x:1B,y:1B) × count]（本次发射后同色连通≥3消除）
    31108(7984) 悬空消除: [seq:1B][count:1B][(x:1B,y:1B) × count]（31107 后失去支撑的悬空球，随之掉落也算被消除）
                ★ 31107/31108 都是"被消除的球坐标"，本地均直接 remove；服务端已算好，不本地判悬空
    31111(7987) 行移动(下降一行): [ButtomRowIndex:1B]
    31137(7989) 添加球: [len:1B][(x:1B,y:1B,color:1B) × len]
    31138(79A2) 发射球队列: [len:1B][(PopColor:1B) × len]  （AS 读 PopType 后硬编码为 1，队列仅普通球）
    31139(79A3) 发射球更新: [PopColor:1B]
    31104(7980) 道具数量: [Type:1B][Num:1B]   Type=2 为炸弹，Num 为持有数量
    31112(7988) 使用道具(useProp): [Type:1B][Seq:1B]   Type=2 触发炸弹模式（后接 31106 落点）
    31113(7989) 使用道具应答: [Type:1B][Result:1B]
    31114/31115/31116 关卡通过 / 游戏失败 / 游戏全部结束（收到即本局结束）

棋盘坐标系（需实测校准，见下方 FLAG）：
- 坐标 (x, y) 与 797E / 7982 / 7983 共用同一套网格，典型为六边形(hex)泡泡龙棋盘。
- 797E 发的是本关【全部待消除行】的球数据（count 可能远大于可见行数）；
  游戏显示框只渲染从某行(y=7 起)往下 3 行，其余行在屏外，等 7987 下降后才露出。
- 消除由服务端判定；本脚本在本地用六边形六连通 flood-fill 模拟「把当前球落到某格后
  同色连通块是否 ≥ 3」，从而挑出能消除的落点（基于整盘计算，落点优先最靠下可见区）。
- 发射包 y = best_shot 选中的【落点格子 y】，是动态值，会随选中落点不同而改变
  （可落 y=6/7/8/... 任意合法空格），并非恒定常量。某次手动测试两次都恰好选到
  最低落点 y=initial_min_y-1=6，仅是该测试的巧合，不可推广为「炮口行恒 y=6」。

使用前提：
- 需先从主服务器 2717(10007) 重定向包取得游戏服务器 IP、端口与 128B token。
- 本模块只负责「游戏服务器段自动发射」，进入/重定向逻辑（抓 2717、拿 token）由调用方提供。
"""

import time
from collections import deque
from struct import pack
from loguru import logger

# 颜色字节映射（用户确认）：1红 2蓝 3黄 5绿；4 暂未出现
COLOR_NAME = {1: "红", 2: "蓝", 3: "黄", 5: "绿", 0: "彩"}  # 0 = 彩球（特殊），见 on_31110

# 炸弹道具（独立道具栏，不走发射队列；队列 PopType 在 AS 里被硬编码为 1）
BOMB_PROP_TYPE = 2          # 31104/31112 包里的 Type 字段：2=炸弹
PROP_COUNT_CMD = 31104      # 7980 道具数量更新：[Type:1B][Num:1B]
USE_PROP_CMD = 31112        # 7988 使用道具(useProp)：[Type:1B][Seq:1B]
BOMB_RADIUS = 2             # 炸弹炸范围：以落点为中心、六连通距离 ≤ 2 的正六边形内所有球（共 19 格：3+4+5+4+3）

# ★ GIL 饥饿止血（2026-08-05）：two_step 两步预测内层原本遍历整个 pool 调 shot_count_after，
#   pool 大时 O(pool²) 整盘 BFS 占满 GIL → UI/recv 饿死 → 界面未响应。现限制内层最多扫描的
#   候选数（超出放弃该维度），配合 deadline 双保险把单拍压在毫秒级。
TWO_STEP_CAP = 20

# ★ 残局空转兜底（2026-08-05，本局 seq=44~55 实测）：残局归位评分修复后 bot 不再飞空区，
#   但仍会因 gather_cluster 簇记忆自我强化——队列给同色时每发堆到上一发同色相邻位，形成角落
#   分散孤球，永远凑不出≥3。本局模式是「消3→归位0→消3→归位0」交替，用"连续消除=0"计数永远
#   到不了阈值（被间隔的消除打断）。故改用【滑动窗口】指标：最近 WIN 发里，消除=0 的归位发数
#   ≥ WIN_EMPTY_LIMIT 即判定空转，放弃 choose_gather_landing 偏好、清空簇记忆、强制推进，让游戏
#   走向正常结束（31115 或等下降过关）。
EMPTY_WIN = 12          # 滑动窗口大小（最近多少发）
WIN_EMPTY_LIMIT = 10    # 窗口内归位空转(消除=0)发数 ≥ 此值即触发兜底（2026-08-06 由 8→10：炸弹救场更保守，空转门槛抬高，避免残局早期误炸）
STALL_TIMEOUT = 6.0      # 残局停滞超时（秒）：本地残球≤2 且超过此时长无服务端回包 → 主动通关退出，防逻辑卡死

# ── 可校准参数（若自动消除判断与实际不符，翻转下列开关） ──
# 坐标约定（已据实抓包确认）：
#   * 棋盘包 (797E/7982/7983) 共用同一网格，坐标 (x, y)。
#   * y 越大越靠屏幕【上】方；y 越小越靠【下】方（靠近炮筒）。
#   * 炮口行固定为 y=-1（球从 -1 飞出向上，撞到第一个障碍球停在相邻空格）。
#   * 初始第1关只发 y=7,8,9 三行（从下往上），其下方 y<7 为空白区域；收到 7987（下降一行）
#     后，球的【实际坐标不变】，仅屏幕多显示一行（可见区顶部 visible_top +1），用于判负与显示。
#   * ★ 木板占位机制（用户实测）：当棋盘【全部球行已显示】后，再下降不再冒出新球行，
#     而是最上方出现【占位木板行】（非球）；继续下降木板行数变多。木板不是球，不参与
#     同色连通、不计入「最底有球 y」。故落点顶界由"棋盘实际最高球 y"决定（见 best_shot safe_top），
#     即便 visible_top 随下降越出棋盘顶，落点也绝不越过木板/屏外（y > 最高球y 即判负）。
#   * 判负规则（用户实测）：最下面有球的最小 y - 已下降行数 < 0 时服务端判负（31115）。
#   * 发射包 y 为选中的落点 y（动态），非恒定。
ODD_R_SHIFT_RIGHT = True    # 六边形棋盘：奇数行是否相对偶数行右移半格（odd-r 布局）
# Y_DOWN_IS_POSITIVE 已弃用：自确认 7987 不改变球的实际坐标后，不再做坐标 shift，该开关失效。
Y_DOWN_IS_POSITIVE = False  # [弃用] 7987 不再平移坐标，保留仅作历史标记
SHOOT_INTERVAL = 0.5        # 两次发射之间的最小间隔（秒），避免发包过快被踢/卡死；亦作主循环定时节拍
                          # 2026-08-06 由 1.0→0.5：用户实测要求 500ms 节拍。
AWAIT_RESP_TIMEOUT = 2.0     # 等回包闸超时（秒）：上一发 31106 发出后超过此时长仍未收到同 seq 的
                          # 7983/31108 结算回包，则强制清闸放行，防永久卡死（须 < STALL_TIMEOUT 6s）。


# ───────────────────────── 协议层 ─────────────────────────
class Packet:
    def __init__(self, cmd_id: int, user_id: int, body: bytes = b""):
        self.cmd_id = cmd_id
        self.user_id = user_id
        self.body = body

    def data(self):
        head = pack("!IBIII", 17 + len(self.body), 1, self.cmd_id, self.user_id, 0)
        return head + self.body


# ───────────────────────── 棋盘模型 ─────────────────────────
def neighbors(x: int, y: int):
    """六边形六连通邻居（offset coordinates，odd-r / even-r 可切换）。"""
    # redblobgames offset 布局：odd rows pushed right
    dirs_odd = [(1, 0), (-1, 0), (1, -1), (0, -1), (1, 1), (0, 1)]
    dirs_even = [(1, 0), (-1, 0), (0, -1), (-1, -1), (0, 1), (-1, 1)]
    use_odd = ((y % 2 == 1) == ODD_R_SHIFT_RIGHT)
    dirs = dirs_odd if use_odd else dirs_even
    return [(x + dx, y + dy) for dx, dy in dirs]


def cells_within_radius(x: int, y: int, r: int):
    """返回以 (x,y) 为中心、六连通距离 ≤ r 的所有格（含中心）。用于炸弹炸范围计算。"""
    if r <= 0:
        return {(x, y)}
    seen = {(x, y)}
    frontier = [(x, y)]
    for _ in range(r):
        nxt = []
        for cx, cy in frontier:
            for nx, ny in neighbors(cx, cy):
                if (nx, ny) not in seen:
                    seen.add((nx, ny))
                    nxt.append((nx, ny))
        frontier = nxt
    return seen


class Board:
    def __init__(self):
        self.cells: dict[tuple[int, int], int] = {}  # (x, y) -> color
        self.wood_row: int = None                    # 占位木板行 y（球最多停到 wood_row-1，木板在【顶部】作天花板，不提供下方支撑）
        self.last_eliminated: set = set()            # 最近一次 7983 消除的坐标（用于优先回填）
        self.top_roots: list = []                    # ★ 顶排可凑同色消除根节点数组（2026-08-05 用户方案）

    def reset(self, cells: dict):
        self.cells = dict(cells)
        self.last_eliminated = set()
        self.recent_empty = []            # 新关清空"连续空转(消除=0)"滑动窗口，避免上关残留误触炸弹救场

    def remove(self, coords):
        for c in coords:
            self.cells.pop(c, None)
        self.last_eliminated = set(coords)

    def add(self, coords_colors):
        for x, y, col in coords_colors:
            self.cells[(x, y)] = col

    # ───────── 顶排可凑同色消除根节点数组（2026-08-05 用户方案） ─────────
    def refresh_top_roots(self):
        """重建 self.top_roots：扫描顶排(y=wood_row-1)，把"能凑≥3同色消除"的顶排同色段记为根节点。
        ★ 用户规则（2026-08-07 扩展，覆盖全部顶排凑消格局）：
          * 段内（连续同色）：3连→need=0；2连+≥1空→need=1(情形B)；1孤球+≥2空→need=2(情形A)。
          * ★ 同侧连续2空位扩展（C□□，用户情形七）：1孤球一侧有2个连续顶排空格→need=2，
            两格都入 slots（旧版只收紧贴1格、漏算第2格→free 难达2→该根建不出→顶层优化失效）。
          * ★ 同色隔空桥接（C□C / C□□C，用户情形六）：两同色 run 被纯空位隔开(gap=1→need=1、
            gap=2→need=2)，填 gap 把两 run 连成一体(结果 size≥3)。旧版按"连续段"扫描把 C□C
            切成两个孤段、各需 free≥2 才能建根→通常建不出→隔空同色永远凑不出3连，顶层优化漏此最
            关键的残局格局。本扩展专门补它。
          * slots=可落空位列表（优先顶排内空格 ny==top，其次顶排正下方 ny==top-1 且 is_supported），
            供 top_row_chain_landing 按当前球色挑落点。
          * 消除后(on_7983)与每关初(on_797e)都刷新；本函数纯读棋盘、O(顶排长度)，无重计算。
        返回根节点数（调试用）。"""
        self.top_roots = []
        if self.wood_row is None or not self.cells:
            return 0
        top = self.wood_row - 1
        # 顶排每列状态（color 或 None），供段扫描与隔空桥接统一取用
        col_color = {}
        for x in range(10):
            p = (x, top)
            col_color[x] = self.cells[p] if p in self.cells else None
        if not any(v is not None for v in col_color.values()):
            return 0
        # ★ 注意：顶排【满排也照常扫描建根节点】。满排时顶排内无空格，但顶排同色段的
        #   正下方 y=13 空格（is_supported 成立）可作为 slots；等下方消出空间后，顶排相邻
        #   列空位也会进入 slots。旧版「满排 return 0」是错的——它会让顶排规划永不触发。

        # ---- 第一遍：扫描同色连续段（run），记录 (color, seg_start, seg_end) ----
        runs = []
        x = 0
        while x < 10:
            if col_color[x] is None:
                x += 1
                continue
            c = col_color[x]
            s = x
            while x < 10 and col_color[x] == c:
                x += 1
            runs.append((c, s, x - 1))

        def _below_slots(seg_cols):
            out = []
            for gx in seg_cols:
                for nx, ny in neighbors(gx, top):
                    if ny == top - 1 and (nx, ny) not in self.cells and self.is_placeable(nx, ny) and self.is_supported(nx, ny):
                        if (nx, ny) not in out:
                            out.append((nx, ny))
            return out

        # ---- 第二遍：逐 run 建根（沿用段长判定 + 同侧连续2空位扩展） ----
        for (c, s, e) in runs:
            seg_cols = list(range(s, e + 1))
            seg_len = e - s + 1
            slots = []
            # 顶排内空格：左外侧 s-1、右外侧 e+1
            for sx in (s - 1, e + 1):
                if 0 <= sx < 10 and col_color.get(sx) is None and self.is_placeable(sx, top) and (sx, top) not in self.cells:
                    slots.append((sx, top))
            # ★ 同侧连续第2个空位（C□□ 扩展）：仅当其紧邻已入 slots 的外空格才加（保证连续、不隔列）
            for sx in (s - 2, e + 2):
                if 0 <= sx < 10 and col_color.get(sx) is None and self.is_placeable(sx, top) and (sx, top) not in self.cells and (sx, top) not in slots:
                    if (sx + 1, top) in slots or (sx - 1, top) in slots:
                        slots.append((sx, top))
            # 正下方 y=13 合法空格
            for ns in _below_slots(seg_cols):
                if ns not in slots:
                    slots.append(ns)
            free = len(slots)
            need = None
            if seg_len >= 3:
                need = 0   # 已可消（best_shoot 会处理，仍记以便统一规划）
            elif seg_len == 2:
                if free >= 1:   # 情形B：2个同色 + ≥1空 → 补1个
                    need = 1
            elif seg_len == 1:
                if free >= 2:   # 情形A / C□□：1孤球 + ≥2空 → 补2个
                    need = 2
            if need is not None:
                self.top_roots.append({
                    'color': c,
                    'cells': [(x2, top) for x2 in seg_cols],
                    'need': need,
                    'slots': slots,
                })

        # ---- 第三遍：同色相邻 run 的"纯空位桥接"（C□C→need1 / C□□C→need2） ----
        #   两 run 之间须为纯空位（无球、无其它颜色），gap_len 取 1 或 2。填全部 gap 即把两 run 连成
        #   一体，结果 size = len(run1)+len(run2)+gap ≥ (1+1+1)=3，必≥3 可消。gap>2 不桥接（避免远填）。
        for i in range(len(runs) - 1):
            c1, s1, e1 = runs[i]
            c2, s2, e2 = runs[i + 1]
            if c1 != c2:
                continue
            gap_start, gap_end = e1 + 1, s2 - 1
            if gap_start > gap_end:
                continue
            gap_len = gap_end - gap_start + 1
            if gap_len > 2:
                continue
            gap_slots = []
            ok = True
            for gx in range(gap_start, gap_end + 1):
                p = (gx, top)
                if p in self.cells or col_color.get(gx) is not None or not self.is_placeable(gx, top):
                    ok = False
                    break
                gap_slots.append(p)
            if not ok:
                continue
            self.top_roots.append({
                'color': c1,
                'cells': [(x2, top) for x2 in range(s1, e1 + 1)] + [(x2, top) for x2 in range(s2, e2 + 1)],
                'need': gap_len,
                'slots': gap_slots,
            })
        return len(self.top_roots)

    def shift_down(self, dy: int):
        self.cells = {(x, y + dy): col for (x, y), col in self.cells.items()}
        # 消除记录同步下移，使「刚被消除的位置」在下降后仍是合法回填目标
        self.last_eliminated = {(x, y + dy) for (x, y) in self.last_eliminated}

    @staticmethod
    def is_placeable(x: int, y: int) -> bool:
        """落点是否合法可放置：
          * 列在 [0,9] 内（已知棋盘 10 列，odd/even 偏移会产生 x=-1/10 须剔除）；
          * 奇数行(y%2==1)的 x=9 永远为空位，禁止放球（用户实测：行容量规则
            奇数行仅 x=0~8 共 9 球，x=9 恒为 FF 空位，落此判负）。"""
        if not (0 <= x <= 9):
            return False
        if y % 2 == 1 and x == 9:
            return False
        return True

    def is_supported(self, x: int, y: int, cells: dict = None) -> bool:
        """落点 (x,y) 是否【贴着球群、不悬空】（球落此格后通过六连通相邻与已有球相连）。
        ★ cells 参数（2026-08-06 净化棋盘统一口径）：默认 self.cells；传入 served 视图
          （cells 排除 shot_landed 幽灵球）可让支撑判定基于服务端真实球群，避免幽灵球假支撑。
        ★ 坐标约定（实测确认）：y 越大越靠【上】、y 越小越靠【下/炮口】。
        ★ 支撑语义（2026-08-05 用户纠正后终版）：落点只要存在任一六邻居满足「ny >= y 且
          (nx,ny) in cells」即视为有支撑——即落点的【同排或下方】有相邻球就合法。这包含两类：
          (a) 正下方一格(ny==y+1)有球：原严格支撑（从下往上逐层堆，落点贴着球群下缘）。
          (b) 同排水平/斜向邻居(ny==y)有球：落点贴着【同一排已落的球】。例：第1个不同色球落
              y=13 靠正下方 y=14 顶排支撑；第2个不同色球落在第1个 y=13 球【旁边】(同排 ny==y)，
              它靠第1个球连着、第1个球又连顶排 → 整链不悬空，落点合法（用户 2026-08-05 怒批
              「第2个球不需要支撑、因为它和第1个连着、第1个又和上面连着」）。旧版只认 ny==y+1
              把这种合法落点误杀，导致 y=13 填不满、bot 跳排往下乱扔。
          ★ 防隔空（保留 seq=47 教训）：仅【上方邻居】(ny < y) 有球、而落点【正下方 ny==y+1 为空】
              时，本函数返回 False——因为球从炮口向上飞会穿过本格停在更靠上处，本格非真落点
              （(9,10) 上方 (9,9) 有球、下方 (9,11) 空 → 非法，避免 seq=47 判负）。
              注意 ny==y+1 空但同排 ny==y 有球仍合法（水平贴着已落球，非隔空），二者不冲突。
          ★ 木板天花板（用户实测，2026-08-04 修正）：木板在【顶排上方】(y=wood_row > 顶排 max_y)，
              是封顶天花板，**不是**支撑。木板不出现在任何落点的邻居 cells 中（非球），本函数
              【绝不】把木板当支撑。切勿写 y+1==wood_row 特例。"""
        if cells is None:
            cells = self.cells
        for nx, ny in neighbors(x, y):
            if (nx, ny) in cells and ny >= y:
                return True
        return False

    def loose_supported(self, x: int, y: int, cells: dict = None) -> bool:
        """宽松支撑判定（2026-08-04 死局兜底用）。
        ★ 严格 is_supported 要求落点【正下方紧邻一格】(ny==y+1) 有球（防隔空误判，第十八轮收紧）。
          但六边形奇偶偏移下，落点正下方邻居未必落在同 x 列，且「顶排满、其下一排球悬在下方」的
          结构里，落点下方一格因偏移/隔空不在 cells → 严格判定把合法落点全判 unsupported →
          候选空集 → best_shot 误扔炸弹判负。
        ★ 真实物理：球从炮口(底, y 小)直线上升，穿过所有空白格，停在【球群最底缘球】的紧邻上方。
          即「从落点沿六边形下方邻居( ny 增大方向)做 BFS，第一个遇到的有球格」即为合法落点
          （允许隔空，且沿六边形偏移路径走，而非固定同 x 列——同 x 列射线会漏掉奇偶偏移后的
          真实下方支撑球，这是旧版 loose_supported 在顶排密实局误判 unsupported 的根因）。
        ★ 顶排(wood_row-1)下方是木板(y=wood_row 非球) → BFS 自然越界返回 False（顶排满则无解，
          物理正确：球飞到顶排上方即撞木板，非法落点）。
        ★ 此判定用于死局兜底（归位/接住/推进），不用于正常消除预测（预测落点 y 偏低，消除数
          按宽松落点算；但至少能推进而非误扔炸弹）。"""
        # 从落点沿六边形下方邻居( my>cy )BFS，找第一个有球的格（允许隔空）
        # ★ 2026-08-06 修复死循环（栈看门狗定位：best_shot 的 loose 兜底分支调用 loose_supported
        #   卡在 neighbors 进出）。旧逻辑的 bug：seen.add 只在 my>cy 分支执行，而 my==cy（同排/平走）
        #   的邻居被 `continue` 跳过既不收录也不再探索——但六边形奇偶偏移下，同一 (mx, my) 格可能被
        #   多层不同父格反复生成且每次 my==cy 被跳过、永远不被 seen 收录，导致 frontier 虽不无限增长
        #   却在某些棋盘拓扑下反复处理等价节点；更致命的是若方向过滤未真正单调推进则可能回环。
        #   修复：seen 收录【所有】生成的邻居（无论方向），但只把 my>cy（严格向下）的格放入 nxt 继续
        #   探索。这样每个格最多被访问/收录一次（seen 去重），算法绝对终止（y 单调增 + seen 有限），
        #   同时保留"沿六边形向下找第一个有球格"的语义。额外加 y 上限 guard 防越界极端。
        seen = {(x, y)}
        frontier = [(x, y)]
        guard_y = (self.wood_row + 2) if self.wood_row is not None else 30
        while frontier:
            nxt = []
            for cx, cy in frontier:
                for mx, my in neighbors(cx, cy):
                    if (mx, my) in seen:
                        continue
                    seen.add((mx, my))   # ★ 所有方向都收录，杜绝重复访问/回环
                    if my > cy and my < guard_y:   # 仅严格向下且未越界者继续探索
                        if (mx, my) in (cells if cells is not None else self.cells):
                            return True
                        nxt.append((mx, my))
                    # my<=cy 或越界的邻居：已收录 seen 防回环，但不再向下探索
            frontier = nxt
        return False

    def candidate_landings(self, cells: dict = None, allow_top_row: bool = False):
        """所有「可放空格、贴着球群、从下往上堆」的坐标 —— 球能落的稳定位置。
        ★ 2026-08-05 修正：与主策略一致——不填顶排(y=wood_row-1)、非顶排须 is_supported
        （落点正下方一格有球，从下往上逐层堆），避免悬空/乱填高位致消除=0。
        ★ 2026-08-06 净化棋盘统一口径(cells 参数)：默认 self.cells；传入 served 视图
          （cells 排除 shot_landed 幽灵球）可让候选基于服务端真实球群，避免幽灵球假支撑
          把候选算到 y=12↓ 下方空格（残局乱堆根因）。
        ★ 2026-08-06 放宽顶排铁律(allow_top_row)：True 时允许落顶排正下方 y=cap 空格
          （残局填补 y=13 空格贴真实球群，不跳过 y=13 往下漏堆）。"""
        if cells is None:
            cells = self.cells
        cap = self.wood_row - 1 if self.wood_row is not None else None
        res = set()
        for (x, y) in list(cells.keys()):
            for nx, ny in neighbors(x, y):
                if not (self.is_placeable(nx, ny) and (nx, ny) not in cells):
                    continue
                if cap is not None and ny == cap and not allow_top_row:
                    continue  # 不填顶排（除非 allow_top_row）
                if not self.is_supported(nx, ny, cells):
                    continue  # 从下往上堆
                res.add((nx, ny))
        return res

    def shot_count(self, x: int, y: int, color: int) -> int:
        """临时把 (x,y) 当作 color 落下，计算该色六连通块大小。
        ★ 消除规则（2026-08-07 用户确认 + seq=6 实证）：服务端按【六连通 ≥3】消除，含纵向/斜向/L 形
           簇（seq=6 落 (8,1) 绿连 (9,2)(8,3) 斜向 Z 形3连，服务端回 消除=3）。故必须 BFS 数六连通块，
           不可只数同行横向直线。
        ★ GIL 饥饿止血（2026-08-05 第二十九轮卡死根治）：旧版 tmp = dict(self.cells) 整盘复制 +
           BFS，在密实棋盘(~40球)上 high-frequency 调用（best_shot 每候选一次、choose_gather_landing
           的 two_step 内层 pool×pool 次、top_row_chain_landing 每 root slot 一次）→ 单拍数百次整盘
           复制占满 GIL → daemon 线程卡死、busy 永真、日志停更、用户手动杀(0xCFFFFFFF)。
           现改为【原地模拟 + 回滚】：self.cells 原地 add (x,y)，算完 pop 回滚，零复制。
           try/finally 保证即使 BFS 中途异常也回滚，绝不泄漏幽灵球。"""
        self.cells[(x, y)] = color
        try:
            seen = set()
            stack = [(x, y)]
            cnt = 0
            while stack:
                cx, cy = stack.pop()
                if (cx, cy) in seen:
                    continue
                seen.add((cx, cy))
                if self.cells.get((cx, cy)) != color:
                    continue
                cnt += 1
                stack.extend(neighbors(cx, cy))
            return cnt
        finally:
            self.cells.pop((x, y), None)

    def best_shot(self, color: int, abs_floor: int = None, allow_same_row: bool = False, excluded: set = None, visible_top: int = None, auth_min_y: int = None, cells: dict = None):
        """返回 (落点(x,y), 连通数)。
        ★ 坐标约定（用户实测，务必牢记）：屏幕 y 从【下】到【上】增大。
            即 y 越大越靠【上/屏幕顶】，y 越小越靠【下/炮筒口】。
            炮筒在屏幕最下方 y=-1；球从炮筒【向上飞】时 y【增大】。
            初始棋盘 3 行从下往上 = y=7,8,9（y=7 最靠炮筒=底排，y=9 最靠屏幕顶=顶排）。
            故「底排」= 当前所有球里 y【最小】的一排（最靠炮筒口的那排）；「顶排」= y 最大。
        合法落点只能贴着【底排(min_y)那排球】的相邻空格：球从炮筒(y=-1)向上飞(y 增大)撞到底排，
            停在底排【正下方一格】(y=min_y-1)，故初始棋盘最低落点 y=6。
            注意：发射包 y 取【选中落点】的 y，是动态值；手动测试两次都恰好选到最低落点 y=6
            纯属巧合（initial_min_y=7 → 最低落点 y=6），不可理解为「炮口行恒 y=6」。
        abs_floor：落点 y 绝对下限（防御性，主要防落点过低成悬空最底球）。由判负规则反推，
            判负线随下降推动，abs_floor 仅作防御性下界，默认 0（炮筒下方整片空白均可落，y>=0）。
        auth_min_y：权威底排 y（= initial_min_y - 已下降次数，因 7987 不改变坐标、底排随下降
            在绝对坐标里逐渐逼近炮口方向即 y 减小）。bot 发射的消除0球会写回 cells，
            其 y=min_y-1 会拉低 cells 最小 y，使「min(cells)」误判底排。故优先用权威底排，
            避免写回球污染底排推导（这是第六轮回退写回后又恢复的关键修正）。
        规则：
          * 候选只取「底排球的相邻空格」；
          * 能消除(≥3)的候选中，优先选 y 最小（最靠炮筒口/最下方），其次连通最大；
          * 若底排存在与当前球同色的球，但无≥3消除落点：选 y 最小（最靠炮筒口）的合法候选兜底；
          * 若底排【没有】与当前球同色的球（底部无法消除）：随便发到一个能发的最靠上( y 最大)的位置。
        """
        # ★ 2026-08-06 净化棋盘统一口径(cells 参数)：默认 self.cells；传入 served 视图
        #   （cells 排除 shot_landed 幽灵球）让候选遍历/支撑判定基于服务端真实球群，避免幽灵球
        #   假支撑把落点算到 y=12↓ 下方（残局乱堆根因）。all_cells/is_supported 均走 served。
        if cells is None:
            cells = self.cells
        all_cells = list(cells.keys())
        if not all_cells:
            return None, 0
        # ── 服务端真实底排（★ y 从下往上增大：底排=最靠炮筒=y【最小】的一排）──
        # 遍历【所有】已有球的邻居生成候选，并排除 bot 写回球(excluded=shot_landed)
        # 后取最小 y 作为真实底排 min_y（写回球落在原底排下方会拉低 min(cells)，
        # 排除后才得到服务端权威底排，根治第九轮「写回污染底排」问题）。
        served = [(x, y) for (x, y) in all_cells if excluded is None or (x, y) not in excluded]
        real_min_y = min((y for (x, y) in served), default=None)
        min_y = real_min_y if real_min_y is not None else (auth_min_y if auth_min_y is not None else min(y for _, y in all_cells))
        # effective_floor：落点 y 下限（防御性，主要防落点过低成悬空最底球）。
        #   原则上只要 is_supported（落点紧邻下方一格有球）就合法，floor 只作防御性下界 = abs_floor(0)。
        #   min_y-1 通道由 is_supported 自然开放（落点若真的贴底排下方，其下方一格有球即支持）。
        effective_floor = abs_floor if abs_floor is not None else 0
        # 上界 safe_top 的计算见下方「落点合法上界 safe_top」段（第二十六轮改为可见行顶）。
        real_max_y = max((y for (x, y) in served), default=None)
        # ── 落点合法上界 safe_top ──
        #   ★ 2026-08-04 修正（详见下方新逻辑）：旧版 safe_top=min(visible_top, real_max_y)
        #     假设"落在屏幕外(y>visible_top)的球不参与消除"，但实测服务端按【全关(含屏外)六连通 ≥3】
        #     消除（2026-08-07 用户确认 + seq=6 实证，含纵向/斜向/L 形簇），与屏幕可见窗口无关。visible_top 按 descended_count 线性推算，严重落后于
        #     真实球顶（降3次算到12，真实球已堆到14），导致顶排合法落点被误掐 → best_shot 全空
        #     → 误扔炸弹 → 漏炸顶排 → 判负。现上界直接取 wood_row-1(顶排)，贴真实球群即可落。
        # ── 落点合法上界 safe_top ──
        #   ★ 2026-08-04 修正（实测日志 seq=22 后 best_shot 全空→误扔炸弹→判负）：
        #     旧逻辑 safe_top = min(visible_top, real_max_y)，但 visible_top 按
        #     initial_min_y+2+descended_count 线性推算，严重落后于实际。本关降3次后
        #     visible_top=12，而真实球已堆到顶排 y=14（木板在15压下来）——y=13,14 的
        #     空格邻居全被 safe_top=12 掐掉 → 18 个候选全 unsupported → best_shot 返回 None
        #     → 误判死局扔炸弹，炸弹落 (6,12) 漏炸 y=13,14 → 31115 判负。
        #   ★ 正确模型：球坐标不变、797E 一次下发全关球（含 y=14 顶排）。落点只要贴着
        #     【真实球群】(served) 即合法，服务端按全关六连通消除（含纵向/斜向/L 形簇，2026-08-07 用户
        #     确认 + seq=6 实证），与屏幕可见窗口无关。
        #     故上界直接取【木板下方一行 wood_row-1】(= 顶排，封顶天花板)，绝不钳到
        #     visible_top。visible_top 只用于「防御性不落到屏外太远」，但不应小于真实球顶。
        #     safe_top = wood_row - 1（顶排），real_max_y 仅作兜底（无木板时）。
        if self.wood_row is not None:
            safe_top = self.wood_row - 1
        else:
            safe_top = real_max_y
        # ── 统一候选集：所有「可放空格」────
        #   ★ 2026-08-05 归位策略修正（用户三条铁律）：
        #     ① bot 直接发包，服务端只认落点坐标，不查"撞球支撑"——故【顶排空位(y=wood_row-1)
        #        也允许放】（上次用户坚持 (6,14) 能放，用于凑顶排同色）。
        #     ② 但【残局归位不主动往顶排(y=14)填】——顶排是固定球群，往其空位塞球跟下方已清空的
        #        球群不连通，纯浪费。故 legal 候选【排除顶排空位】(ny==cap)。
        #     ③ 【中间空洞须从下往上逐层堆】：非顶排空格落点，其正下方一格(ny+1)必须有球
        #        （is_supported），否则悬空、不连通、消除=0（本次日志 seq=44+ 往 y=14/悬空高位
        #        乱填致 11/12 消除=0 空转）。is_supported 的 ny==y+1 语义 = 从下往上堆，
        #        自然实现"y=13 某列没球→该列 y=12 不被放"的逐层约束。
        #   约束：可放置、空格、未被 excluded、floor<=y<=safe_top、非顶排空位、非顶排须 is_supported。
        cap = self.wood_row - 1 if self.wood_row is not None else None
        legal = set()
        for (x, y) in all_cells:
            for nx, ny in neighbors(x, y):
                if not (self.is_placeable(nx, ny) and (nx, ny) not in cells):
                    continue
                if excluded is not None and (nx, ny) in excluded:
                    continue
                if ny < effective_floor:
                    continue
                if safe_top is not None and ny > safe_top:
                    # 顶界 = 木板下方一行(wood_row-1=顶排)。ny 超过顶排即越木板，过滤。
                    continue
                # ★ ② 不往顶排(y=cap)填：顶排空位不在常规候选集（归位不填顶排；凑顶排同色由
                #   top_row_chain_landing 在 best_shot 之前单独处理，落顶排正下方 y=13 空格）。
                if cap is not None and ny == cap:
                    continue
                # ★ ③ 非顶排空格须从下往上堆（落点正下方一格有球），避免悬空不消除。
                if not self.is_supported(nx, ny, cells):
                    continue
                # ★ 底排同层(min_y 排)空洞：用户铁律"往最底排球更靠下(ny<min_y)才判负风险"，
                #   落 min_y 排本身(平铺)不会降低最底有球y、is_supported 已保证支撑，合法。
                #   旧版 allow_same_row=False 时一律排除 ny==min_y，会把【能凑≥3消除的落点】
                #   (如 (6,12) 落红3连) 一并误杀，导致 best_shot 漏选能消点、返回兜底 (5,11)。
                #   故彻底移除 min_y 行过滤：能否消除由下方 eliminable 分支裁决，平铺兜底由
                #   cnt<3 的 upper_candidates(min_y排点仅作兜底)约束，互不冲突。
                legal.add((nx, ny))
        legal = list(legal)
        if not legal:
            # ── 诊断：legal 为空时打印关键状态，便于定位卡死根因 ──
            n_cells = len(self.cells)
            n_served = len(served)
            served_miny = min((y for (_, y) in served), default=None)
            served_maxy = max((y for (_, y) in served), default=None)
            # 每排占用数（诊断用）
            per_row = {}
            for (x, y) in served:
                per_row[y] = per_row.get(y, 0) + 1
            # 统计：有多少「空格邻居」因各约束被过滤
            cand_total = 0
            filt_floor = filt_top = filt_same = filt_sup = 0
            top_cands = []   # 被 top 过滤的候选明细
            for (x, y) in all_cells:
                for nx, ny in neighbors(x, y):
                    if not (self.is_placeable(nx, ny) and (nx, ny) not in cells):
                        continue
                    if excluded is not None and (nx, ny) in excluded:
                        continue
                    cand_total += 1
                    if ny < effective_floor:
                        filt_floor += 1
                        continue
                    if safe_top is not None and ny > safe_top:
                        # 木板行(wood_row)落点：不计入 top 过滤（它必然越过顶界，本就会被
                        # is_supported 拦下判 unsupported），此处豁免以便并入 filt_sup 统计。
                        if self.wood_row is not None and ny == self.wood_row:
                            pass
                        else:
                            filt_top += 1
                            if len(top_cands) < 40:
                                wd = True
                                sup = self.is_supported(nx, ny, cells)
                                top_cands.append((nx, ny, wd, sup))
                            continue
                    if not allow_same_row and ny == min_y:
                        filt_same += 1
                        continue
                    if not self.is_supported(nx, ny, cells):
                        filt_sup += 1
                        continue
            rows_str = " ".join(f"y={y}:{per_row[y]}" for y in sorted(per_row))
            tc_str = " ".join(f"({a},{b})wd={c}sup={d}" for a, b, c, d in top_cands[:12])
            # 候选明细（每个空格邻居的完整支撑探测），便于定位"全 unsupported"根因
            detail_lines = []
            for (x, y) in all_cells:
                for nx, ny in neighbors(x, y):
                    if not self.is_placeable(nx, ny):
                        continue
                    if (nx, ny) in cells:
                        continue
                    if excluded is not None and (nx, ny) in excluded:
                        continue
                    sup = self.is_supported(nx, ny, cells)
                    los = self.loose_supported(nx, ny, cells)
                    detail_lines.append(f"({nx},{ny})ny={ny}place=Y cell=N excl="
                                         f"{'Y' if (excluded is not None and (nx,ny) in excluded) else 'N'}"
                                         f" sup={sup} loose={los}")
            detail_str = " | ".join(detail_lines)
            logger.debug(f"[best_shot] 候选为空！min_y={min_y} eff_floor={effective_floor} "
                  f"safe_top={safe_top} allow_same_row={allow_same_row} wood_row={self.wood_row} "
                  f"cells={n_cells} served={n_served} served_y=[{served_miny},{served_maxy}]")
            logger.warning(f"          排占用: {rows_str}")
            logger.warning(f"          空格邻居={cand_total} 过滤: floor={filt_floor} top={filt_top} "
                  f"same={filt_same} unsupported={filt_sup}")
            logger.warning(f"          top过滤候选(前12): {tc_str}")
            logger.warning(f"          候选明细: {detail_str}")
            # ★ 2026-08-06 净化过度兜底修复：served = cells - shot_landed 会【错误剔除真实写回球】
            #   （record=True 的归位落点既写回 cells 又入 shot_landed → 被当作幽灵球剔除），导致
            #   其支撑的子排空格全部判 unsupported → legal 空 → 被迫顶排推进 → 死局判负。
            #   真实幽灵球（服务端已消除但本地未删）应由 on_7983/31108 删，shot_landed 实际只含
            #   【真实球】，剔除它会破坏支撑结构。故当净化视图下 legal 空时，用【完整棋盘
            #   self.cells】（含真实写回球）重算候选与 is_supported（不再剔除 shot_landed），
            #   恢复被误删的支撑 → 找回贴着真实球群的下排合法落点。仅在净化视图全空时触发，
            #   不扰正常路径；即便残留个别真幽灵，也比被迫顶排堆死更优。
            full_cells = self.cells
            if full_cells is not cells and len(full_cells) > len(cells):
                flegal = set()
                for (x, y) in full_cells:
                    for nx, ny in neighbors(x, y):
                        if not (self.is_placeable(nx, ny) and (nx, ny) not in full_cells):
                            continue
                        if ny < effective_floor:
                            continue
                        if safe_top is not None and ny > safe_top:
                            continue
                        if cap is not None and ny == cap:
                            continue
                        if not self.is_supported(nx, ny, full_cells):
                            continue
                        flegal.add((nx, ny))
                if flegal:
                    logger.debug(f"[best_shot] 净化视图全空，改用完整棋盘重算找回 {len(flegal)} 个下排合法落点: "
                          f"{sorted(flegal)[:12]}")
                    legal = list(flegal)
                    # 直接跳过下方底排/宽松兜底，按正常 scored 流程打分（优先能消除点）
                    scored = []
                    best_deadline = time.time() + 0.04
                    for (x, y) in legal:
                        if time.time() > best_deadline:
                            break
                        c = self.shot_count(x, y, color)
                        scored.append((c, y, x, (x, y)))
                    if scored:
                        scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
                        best = scored[0][3]
                        cnt = scored[0][0]
                        if cnt < 3:
                            logger.debug(f"[best_shot] 完整棋盘兜底 best=({best[0]},{best[1]}) "
                                  f"连通={cnt}(<3，归位) served_max_y={real_max_y}")
                        return best, cnt
                    return None, 0
            # ── 兜底：常规候选(球邻居空格)全空时，枚举【底排相关空洞】──
            #   ★ 2026-08-05 修正：用户铁律"不动 y=14"——【不再往顶排(y=wood_row-1)填】，
            #     删去原顶排分支（那会让 best=None 时仍往顶排塞，违反规则且常悬空）。
            #   仅保留底排孤球正下方一格 (y = min_y-1)：六连通偏移下该格未必出现在 neighbors
            #      遍历（孤球孤立时尤其如此），但物理上球落到此处、下方底排(y=min_y)有球支撑，
            #      合法可落。用于"接住"孤球、改变底排结构。须 is_supported（从下往上堆）。
            fb = set()
            below = min_y - 1 if min_y is not None else None
            if below is not None and below >= 0:
                for x in range(10):
                    if (x, below) in cells:
                        continue
                    if excluded is not None and (x, below) in excluded:
                        continue
                    if not self.is_placeable(x, below):
                        continue
                    if safe_top is not None and below > safe_top:
                        continue
                    if self.is_supported(x, below, cells):   # 从下往上堆，下方底排有球即支撑
                        fb.add((x, below))
            if fb:
                logger.debug(f"[best_shot] 常规候选空，启用底排兜底候选(已按可见行过滤): {sorted(fb)}")
                legal = list(fb)
            else:
                # ── 第二层兜底（2026-08-04 死局）：严格+端排兜底全空时，用 loose_supported
                #   （竖直向下射线第一格有球）放宽支撑。倒三角悬空球群下严格 is_supported 把合法
                #   落点全判 unsupported，此处放行让球能接住球群最底缘，避免误扔炸弹判负。
                loose = set()
                for (x, y) in all_cells:
                    for nx, ny in neighbors(x, y):
                        if not (self.is_placeable(nx, ny) and (nx, ny) not in cells):
                            continue
                        if excluded is not None and (nx, ny) in excluded:
                            continue
                        if ny < effective_floor:
                            continue
                        if safe_top is not None and ny > safe_top:
                            continue
                        if not allow_same_row and ny == min_y and not (
                                self.wood_row is not None and ny == self.wood_row - 1):
                            continue
                        if self.loose_supported(nx, ny, cells):
                            loose.add((nx, ny))
                if loose:
                    loose_sorted = sorted(loose)
                    logger.debug(f"[best_shot] 严格/端排兜底均空，启用宽松支撑兜底(loose_supported): "
                          f"{loose_sorted}")
                    legal = list(loose)
                else:
                    return None, 0
        scored = []
        # ★ GIL 饥饿止血（2026-08-05 五之二十轮）：best_shot 在 choose_gather_landing 之前调用，
        #   残局棋盘大时 legal 候选可达上百、每候选 shot_count 全量 BFS，无预算保护 → 单拍可超 10s
        #   占满 GIL → UI/recv 饿死 → 看门狗触发（日志"maybe_shoot 超过 10s"）。现加 deadline：
        #   超预算即停止评估剩余候选，用已算 scored 返回（残局少评估几个候选不影响大局）。
        best_deadline = time.time() + 0.04
        for (x, y) in legal:
            if time.time() > best_deadline:
                break
            c = self.shot_count(x, y, color)
            scored.append((c, y, x, (x, y)))  # (连通数, y, x, 落点)
        # ★ 安全网：deadline 提前 break 可能使 scored 为空（legal 很大但首候选就超预算）。
        #   此时返回 legal 中【最靠上(y 最大)、x 最小】的合法候选，而非 legal[0]（set 无序、
        #   可能恰好取到最靠下低 y 点，强堆到判负线 → 31115）。方向与 upper_candidates 一致：
        #   残局宁可贴顶排/球群上方填，绝不往最底排下方堆（最底有球y 不下降才不触判负线）。
        if not scored:
            return max(legal, key=lambda p: (p[1], -p[0])), 0
        # ★ 铁律（用户 2026-08-05）：存在能消除(≥3)落点时【必须优先选之】，绝不被其他分支绕过。
        #   故 eliminable 必须放在 elim_positions（回填）之前——否则 elim_positions 可能返回
        #   一个不能消的"刚消除位"而吞掉真正能消的落点（如 (6,12) 红3连被 (5,11) 兜底吞掉）。
        legal_set = set(legal)
        # 可消除优先：连通数≥3 的候选集合
        eliminable = [s for s in scored if s[0] >= 3]
        if eliminable:
            # 最靠下(y最小)优先，其次连通最大
            eliminable.sort(key=lambda s: (s[1], -s[0]))
            best = eliminable[0]
            return best[3], best[0]
        # 次优先：回填「刚被消除的位置」（下降后坐标，物理上必然稳定合法）：
        #   用户实测经验——消除包清空的位置可直接作为下一发落点，不会悬空/判负。
        #   仅当【没有能消除的落点】才启用本保底（避免它压过可消除点）。
        #   且必须二次校验合法性——消除位坐标可能因 7987 下降
        #   shift_down 同步下移后错位（如变成奇数行 x=9 的非法格、或恰与写回球重叠），
        #   直接返回会绕过 is_placeable/is_supported 校验，发到非法格 → 31115 判负
        #   （本次实测：seq=20 选 (9,8) 判负，(9,8) 是奇数行 x=9 非法格且已被占用，
        #   只能来自本分支，因 legal 候选集绝不会生成该格）。故只保留落在 legal 集内的消除位。
        elim_positions = [(s[3], s[0]) for s in scored if s[3] in self.last_eliminated and s[3] in legal_set]
        if elim_positions:
            elim_positions.sort(key=lambda p: (-p[1], p[0][1], p[0][0]))  # 能消除优先，其次最靠下
            return elim_positions[0][0], elim_positions[0][1]
        # ── 无≥3消除落点时（残局归位）：落点下界=death_floor(abs_floor)，优先最靠下让悬浮塔下长 ──
        #   ★ 2026-08-06 修正（修复 seq=22 顶到木板 31115）：旧版「只选比 min_y 更靠上(upper_candidates,
        #   p[1]>min_y) + 取最靠上(max y)」会让悬浮塔只长高不长低→顶到木板 y=15。正确判负模型：判负线
        #   是服务端 ButtomRowIndex(death_floor=abs_floor)，由下降计数驱动、与 bot 落点 y 无关——落低点
        #   不会拉低 death_floor，故"落低点拉低最底y→判负"的旧担忧是错的。legal 候选已受 effective_floor
        #   (=abs_floor)约束（落点不得越过判负线），本兜底只需在 legal 内选【最靠下(y最小)】的 supported
        #   落点：death_floor=0 且塔底下方有空时，球落最底 supported 空位、悬浮塔往空区下长、压低远离木板；
        #   death_floor 收紧时 legal 只剩上方候选、最靠下≡贴顶排，与旧铁律一致、不冲突。
        lower_floor = abs_floor if abs_floor is not None else 0
        lower_candidates = [p for p in legal if p[1] >= lower_floor]
        if lower_candidates:
            # 最靠下(y最小)、x最小：压低塔、远离木板
            bottom_cand = min(lower_candidates, key=lambda p: (p[1], p[0]))
            fallback = bottom_cand, 0
        else:
            # 极端：合法候选都 < lower_floor，退化为最靠上避免继续下沉
            scored.sort(key=lambda s: (-s[1], s[0]))
            fallback = (scored[0][3], 0)
        # ── 返回硬兜底（防非法点逃逸）──
        # 任何分支算出的 best 理论上都在 legal 内，但为绝对防止「非法格（如奇数行 x=9、
        # 已被占用的写回球坐标）/悬空位」被返回导致 31115 判负，做最后一道栅栏：
        #   若 best 不在 legal 集，则回退到「可消除优先、其次最靠下」的 legal 最优。
        best_pt = fallback[0]
        if best_pt not in legal_set:
            logger.debug(f"[best_shot] 警告：选出落点 {best_pt} 不在合法候选集，已回退到合法最优")
            scored.sort(key=lambda s: (-s[0], s[1]))  # 连通大优先，其次最靠下
            fallback = scored[0][3], scored[0][0]
        return fallback

    def choose_gather_landing(self, color: int, excluded: set = None, next_color: int = None, prefer_pos: tuple = None, future_colors: list = None, death_floor: int = 0, cells: dict = None):
        """残局归位策略（第四十五轮重构）：
        当当前球无法立即消除(cnt<3)时，把球送到【最能推进消除】的合法落点，而非远离球群/随机归位。
        改进点（相对旧版 35 轮）：
          ① 候选从「仅同色球紧邻空格」扩展为【全棋盘所有 supported 空格】，避免同色球孤立时
             找不到聚合点；每个候选算 shot_count(该色六连通块大小)。
          ② 聚合优先：不仅看连通块大小，更看「落点后该色连通块能否把分散的同色球合一片」
             —— 用连通块内【包含的原有同色球个数】衡量（合并越多越优），因为这直接决定
             下个同色球到来时能否凑≥3。
          ③ 两步预测：若给出了队列下一个球颜色 next_color，则模拟「当前球落 A 后，next_color 能否
             在某合法落点消除 ≥3」；能的 A 优先（即便 A 自身连通块不大，但为 next 铺好了路）。
          ④ 无同色球时退化为「最靠下(贴近底排) supported 空格」，把球往下方压、抬高最底有球 y，
             远离判负线（旧版堆到顶排 y 最大反而堆高判负线，已修正）。
          ⑤ 【脆弱单连接借消除 hang】(第五十二轮)：优先把异色球落到"顶排缺色孤球正下方邻居位"
             （落点支撑来自该孤球，且该孤球仅贴落点一个邻居）。等该色出现凑消孤球后，落点失去
             唯一支撑→悬空→31108 顺带消除。用一次孤球色消除带走贴它的异色球，破解"队列迟迟不给
             某色"的残局死结。hang 计数这种"落点正下方仅贴着的异色孤球"个数，优先于普通聚合。
          ⑥ ★ 2026-08-05 队列前瞻（用户要求"根据当前球和队列剩余球决定落点，不只当前球"）：
             future_colors = 当前球之后的队列颜色列表（不含炸弹）。据此统计 queue_same=队列里
             当前球色的剩余个数。决策：
               - queue_same>0（未来还有同色球要来）：当前球应【主动贴现有同色簇预堆】，
                 为将来凑 3 连铺路 → queued_plan 维度（贴同色时 +1）优先级提到 hang 之后、origin_same 之前。
               - queue_same==0（当前色是绝唱，未来无同色）：不要再往同色簇死堆（凑不出 3 连），
                 退化为 top_adjacent 贴顶排 y=13 归位铁律（queued_plan 不生效）。
             这样 bot 不再"只看当前球平摊"，而是按队列颜色分布做前瞻规划。
        返回 (x,y) 或 None（调用方回退到 best_shot 原兜底）。
        """
        if excluded is None:
            excluded = set()
        # ★ 2026-08-05 队列前瞻：统计队列后续（当前球之后）当前球色剩余个数。
        #   future_colors 由 _shoot_impl 传入（list(self.queue)[1:] 的颜色，排除炸弹）。
        #   queue_same>0 → 未来还有同色球，当前球应主动贴同色簇预堆；==0 → 绝唱，退化为贴顶排归位。
        queue_same = 0
        if future_colors:
            queue_same = sum(1 for c in future_colors if c == color)
        # 全棋盘合法落点池：可放空格、未被排除、不越木板顶界、非顶排、从下往上堆
        # ★ 2026-08-05 归位策略修正（用户三条铁律）：
        #   ① 顶排空位(y=cap)不进 pool（残局归位不主动填顶排，用户"不动 y=14"）；
        #   ② 非顶排空格须 is_supported（落点正下方一格有球=从下往上堆），否则悬空不消除、
        #      且实现"y=13 某列没球→该列 y=12 不被放"的逐层约束（本次日志乱填高位致空转）。
        #   顶排同色凑消由 top_row_chain_landing 在 best_shot 前单独处理（落顶排正下方 y=13）。
        cap = self.wood_row - 1 if self.wood_row is not None else None
        # ★ 2026-08-05 终极修复（用户怒批"没能动消的球时 y 越放越靠下、最后到 y=6 判负"）：
        #   残局归位落点【绝不允许比现存最底排球更靠下】(ny <= min_y)。否则球会一路滑到
        #   炮口侧 y=6（min_y-1 底排下方兜底），越堆越靠近判负线 → 31115 判负。
        #   归位只许贴着球群往【上方/周围】填（ny > min_y），配合 top_gap_set 贴顶排优先，
        #   球只会长高、不会长低。min_y 用 served 口径（排除 bot 写回幽灵球，避免底排被拉低）。
        served_cells_miny = [p for p in self.cells.keys() if (excluded is None or p not in excluded)]
        min_y_val = min((y for (_, y) in served_cells_miny), default=None)
        # ★ 2026-08-06 净化棋盘统一口径(cells 参数)：默认 self.cells；传入 served 视图
        #   （cells 排除 shot_landed 幽灵球）让候选/支撑/顶排判断基于服务端真实球群，
        #   避免 bot 自己写回但服务端已消的幽灵球制造假支撑、把落点算到 y=12↓ 下方。
        if cells is None:
            cells = self.cells
        pool = []
        # ★ 计算预算（2026-08-05 止血）：残局 board 越来越大时，choose_gather_landing 的评分循环
        #   （pool 候选 × 每候选 BFS 连通块 + two_step 两步预测）会膨胀，占满 GIL 把 UI 线程/recv
        #   回调线程都饿死 → 表现为"日志停更→过会儿界面未响应（用户手动杀 0xCFFFFFFF）"。
        #   加统一时间预算，超预算立即跳过后续评估，用已算出的 scored 直接排序返回。
        #   另配 TWO_STEP_CAP 限制内层扫描上限、原地模拟替代整盘复制（见下方循环），双保险把单拍压在毫秒级。
        deadline = time.time() + 0.04
        for (x, y) in list(cells.keys()):
            for nx, ny in neighbors(x, y):
                if (nx, ny) in cells:
                    continue
                if (nx, ny) in excluded:
                    continue
                if not self.is_placeable(nx, ny):
                    continue
                if cap is not None and ny > cap:
                    continue
                if cap is not None and ny == cap:
                    continue  # ② 不往顶排填
                if ny < death_floor:
                    continue  # ★ 死亡线硬下限：落点 y < ButtomRowIndex 服务端直接判负，排除
                if not self.is_supported(nx, ny, cells):
                    continue  # ③ 从下往上堆，悬空位不放（基于 served 真实球群）
                # ★ 归位下界修正（2026-08-06）：旧版「落点不得比最底排球更靠下(ny < min_y_val)」
                #   是 seq=22 顶到木板 31115 的元凶——本局消除后最底排是【悬浮塔底 y=8】、下方
                #   y=7~0 大片空区，旧铁律禁止把球发到塔底下方空区，逼 bot 只能往塔顶(y≥9)贴、
                #   塔越长越高直到顶到木板 y=15。正确下界应是【死亡线 death_floor】(第 783 行已
                #   排除 ny<death_floor)，而非 min_y。删掉本处 min_y 排他后，下方空区的 supported
                #   落点重新合法，配合「-gy 最靠下优先」评分，bot 会把球压到最底合法处、让悬浮塔
                #   往空区下长、远离木板。death_floor 收紧时下方候选被 783 行排除，pool 只剩上方，
                #   自动回到「贴顶排 y=13 往上堆」铁律，互不冲突。
                pool.append((nx, ny))
        if not pool:
            return None
        # ★ 方案 A（2026-08-05 用户规则「残局顶排有【空位/缺球】时，往它正下方 y=13 堆别的颜色，
        #   y=13 满再往 y=12 逐行往下；等顶排那几个球被消除后下方都悬空」）：
        #   关键修正（本轮回血）：用户原话是「y=14 有【空位】时往 y=13 堆」——即顶排某列【缺球】
        #   才需要往它下方填（让该列球群长高、等顶排球被同色凑消后下方连锁悬空）。
        #   旧版误把"顶排【满】列的正下方"也收进 top_gap_set，导致顶排整行塞满时 top_gap_set 覆盖
        #   y=13/y=12 大片区域，bot 永远优先"贴顶排往下填"而【不去聚合同色凑 3 连】→ 30+ 发空转、
        #   越堆越往下、31111 下降计数一直涨、迟早判负（见 seq=17~55 日志）。
        #   现改为：仅当顶排该列【缺球】(x,top) 不在 cells 且该列下方存在【有支撑的空格】时才收集，
        #   让 top_gap_set 真正反映"顶排空位下方的归位位"。满列不再贡献 top_gap_set（满列下方由
        #   聚合/普通逻辑处理），避免空转堆高。
        top_gap_set = set()
        if cap is not None:
            top = cap
            # ★ 2026-08-05 用户铁律修正（本轮翻车根因）：【贴顶排 y=13 优先于更低排】。
            #   旧版只在"顶排该列【缺球】"时收其下方空格，导致顶排满列的正下方 y=13 空格
            #   完全不进 top_gap_set → bot 跳过 y=13 直接落 y=12/y=11 甚至更低（日志 seq=26/27/36
            #   等"y=13 没放满就往下扔"）。正确逻辑：
            #   仅当【顶排该列【有球】】时，收集其正下方 y=13 空格（is_supported 必成立，因 y+1=top
            #   有球）→ 这是首要归位点（贴顶排把 y=13 填满/凑消，等顶排被同色消后下方连锁悬空）。
            #   顶排【缺球】列的下方不强制收（该列顶排无球，下方悬空风险低，交给聚合/普通逻辑），
            #   避免旧版"满列下方大片 y=13/y=12 优先空转堆高"的反向错误。
            for x in range(10):
                if (x, top) not in cells:
                    continue  # 顶排该列缺球：不强制归位其下方，交给聚合逻辑（基于 served 真实球群）
                # 顶排该列有球 → 其正下方一圈（ny<top）合法空格即首要归位点
                for nx, ny in neighbors(x, top):
                    if ny >= top:
                        continue  # 只要顶排正下方那一圈（ny < top）
                    if (nx, ny) in cells:
                        continue
                    if not self.is_placeable(nx, ny):
                        continue
                    if not self.is_supported(nx, ny, cells):
                        continue  # 从下往上堆，悬空位不归位（基于 served 真实球群）
                    top_gap_set.add((nx, ny))
        # ① 立即消除优先（≥3 直接选，理论 best_shot 已处理，这里兜底）
        #   ★ GIL 饥饿止血（2026-08-05 第五次复发根因修复）：旧版 immediate 在【任何 deadline
        #     检查之前】对 pool 每个候选调 self.shot_count，而 shot_count 内部 tm=dict(self.cells)
        #     全量复制整盘+BFS。残局 board 几百球、pool 数百时，几百次全盘复制即超 10s，且此处
        #     无预算保护 → maybe_shoot 线程卡死 → 看门狗 10s 强制释放（日志 seq=32 现象）。
        #     现删除独立预计算，改在下方主评分循环内【复用已算的 block】(落点后该色连通块大小)：
        #     block>=3 即 immediate，零额外 shot_count 调用，彻底消除该热点。
        immediate_cands = []   # 主循环内按已算 block 收集（不额外复制棋盘）
        # ② 聚合评分：模拟落当前色，统计连通块大小 + 合并的原同色球数
        #    评分元组 (簇记忆命中, 两步消除, 合并同色数, 连通块大小, 贴球群度, 最靠下, x最小)
        #    —— 越靠后越靠后的兜底维度。
        #    【簇记忆命中 prefer_hit】(第四十七轮新增)：若提供了 prefer_pos（上一发同色归位的
        #      簇锚点），且本落点落 color 后与 prefer_pos 同色连通（prefer_pos 落入该连通块），
        #      则 prefer_hit=1，排最高优先级。目的：队列里连续多个同色球时，强制把它们全堆到
        #      同一簇上（而非摊薄到棋盘各处孤立同色球旁），第 3 个必凑≥3消除。这是本局
        #      seq=16~18 连续红球各落各的、永远凑不出 3 连的死局根因修复。
        #    【贴球群度 -dist】(第四十六轮)：落点到最近已有球(任意色)六边形步数取负。当
        #      two_step/origin_same/block/prefer_hit 全为 0 时，优先选离球群最近而非最靠下空洞。
        #    【脆弱单连接借消除 hang】(第五十二轮，用户实战技巧)：顶排(y 大)剩某色孤球(如蓝)但
        #      队列迟迟不给该色时，把【别的颜色】发到该孤球【正下方邻居位】(by==gy+1，落点支撑来自
        #      该孤球)。此时落点是该孤球唯一邻居(孤球 others==0)。等该色出现凑消孤球 → 落点失去
        #      唯一支撑(下方变空) → 悬空 → 触发 31108 顺带消除。即"用一次孤球色消除，借单连接点把
        #      贴它的异色球也带走"。hang 计数这种"落点正下方仅贴着的异色孤球"个数，越多越优先。
        scored = []
        for (gx, gy) in pool:
            if time.time() > deadline:
                break
            # ★ GIL 饥饿止血（本轮回血）：旧版 tmp=dict(self.cells) 每候选复制整盘（pool=100 即百次
            #   整盘 dict 复制 + 各自 BFS），单拍可超数百 ms 占满 GIL → UI/recv 饿死 → 界面未响应。
            #   现改为【原地模拟 + 回滚】：self.cells 原地 add (gx,gy)，算完 del 回滚。连通块/BFS
            #   直接读 self.cells，零复制。budget 检查在循环首行，超时立即 break（已算 scored 排序返回）。
            #   ★ 用 try/finally 保证 (gx,gy) 必定回滚：即使 two_step 内层 break / deadline 中途触发
            #     导致迭代未跑到底，也不会泄漏幽灵球污染棋盘（第四轮曾因幽灵球导致 best_shot 误判）。
            self.cells[(gx, gy)] = color
            try:
                # 计算落点处该色连通块（含落点）及其包含的原有同色球个数（六连通，服务端消除口径）
                seen = set()
                stack = [(gx, gy)]
                block = 0
                origin_same = 0
                while stack:
                    cx, cy = stack.pop()
                    if (cx, cy) in seen:
                        continue
                    seen.add((cx, cy))
                    if self.cells.get((cx, cy)) != color:
                        continue
                    block += 1
                    if (cx, cy) != (gx, gy) and self.cells.get((cx, cy)) == color:
                        # 注意：刚 add 的 (gx,gy) 不算"原有同色"，用 != (gx,gy) 排除
                        origin_same += 1
                    stack.extend(neighbors(cx, cy))
                # 簇记忆命中：落点后 prefer_pos 是否在本色连通块内
                # ★ 2026-08-05 修复（残局空转）：仅当落点真能合并同色(origin_same>=1)才给
                #   prefer_hit=1。否则孤立锚点（上一发同色归到空区、未凑出消除）会被反复
                #   prefer_hit 拉回同一空区，自我强化成左侧空转死循环（见 seq=33~53 日志）。
                prefer_hit = 0
                # ★ 2026-08-05 修正（本轮日志 seq=39 悬空簇记忆落点 (9,12)）：prefer_hit 命中必须
                #   叠加落点本身 is_supported 校验，否则"为追同色簇"会把球发到悬空位（y=13 该列空、
                #   落点靠同排/下方均无球支撑）→ 服务端判负/不消除。簇记忆只应在"合法支撑位"生效。
                if prefer_pos is not None and origin_same >= 1 and self.cells.get(prefer_pos) == color and self.is_supported(gx, gy, cells):
                    # 从落点 BFS 看能否连通到 prefer_pos
                    vis = {(gx, gy)}
                    st = [(gx, gy)]
                    while st:
                        cx, cy = st.pop()
                        if (cx, cy) == prefer_pos:
                            prefer_hit = 1
                            break
                        for mx, my in neighbors(cx, cy):
                            if (mx, my) in vis:
                                continue
                            if self.cells.get((mx, my)) == color:
                                vis.add((mx, my))
                                st.append((mx, my))
                # 两步预测：落 gx,gy 后，next_color 能否在某处消除
                # ★ GIL 饥饿止血（本轮回血）：旧版内层 for (hx,hy) in pool 调 shot_count_after（内部再
                #   复制 tmp + BFS），pool=100 时达 O(pool²)=万次级整盘 BFS，单拍数秒占满 GIL → UI/recv
                #   线程饿死 → 界面未响应（用户手动杀进程 0xCFFFFFFF）。现改为：
                #   ① 直接复用【外层已落子】的 self.cells（外层循环首行已 self.cells[(gx,gy)]=color，
                #     循环末统一 del 回滚），此处【不再】自行 add/del（否则会和外层回滚冲突 → KeyError
                #     且破坏状态一致性）；② 内层硬上限 TWO_STEP_CAP 个候选，超出即放弃该维度
                #     （two_step 置 0，不影响主评分）；③ budget 检查在循环首行，超时立即 break。
                two_step = 0
                if next_color is not None and next_color != color:
                    scanned = 0
                    for (hx, hy) in pool:
                        if time.time() > deadline or scanned >= TWO_STEP_CAP:
                            break
                        if (hx, hy) == (gx, gy):
                            continue
                        scanned += 1
                        # ★ bot 直接发包，候选池已全是可放空格（pool 生成时去掉了 is_supported），
                        #   此处不再查支撑，直接算落 next 色能否凑≥3。
                        if self.shot_count(hx, hy, next_color) >= 3:
                            two_step = 1
                            break
                # 脆弱单连接借消除：落点正下方(by==gy+1)的异色已有球，若它是仅贴落点的孤球
                # （除落点外无其它 cells 邻居），则将来该异色被消→落点失唯一支撑→悬空顺带消除。
                hang = 0
                for (bx, by) in neighbors(gx, gy):
                    if by != gy + 1:
                        continue  # 只认落点正下方邻居（落点的支撑来源方向）
                    if (bx, by) in self.cells and self.cells[(bx, by)] != color:
                        others = sum(1 for n in neighbors(bx, by)
                                     if n in self.cells and n != (gx, gy))
                        if others == 0:
                            hang += 1
                # ★ 方案 A「贴顶排 y=13 归位」(2026-08-05 用户铁律修正)：
                #   top_adjacent=1 表示落点恰在顶排正下方一排（gy == top-1，即 y=13）——这是残局归位的
                #   【首要位置】（先把 y=13 这排贴着顶排填满/凑消，等顶排被同色消后下方连锁悬空），
                #   优先级高于"贴球群 -dist"和"最靠下 -gy"，但低于能凑消除的维度
                #   (prefer_hit/two_step/hang/origin_same/block)。用户原话"y=13 没放满就往下接着放"是错的，
                #   必须 y=13 优先填。
                #   top_fill=1 表示落点恰在 top_gap_set（顶排有球列的正下方空格，现已是 y=13 为主），
                #   ty=gy 越大(越贴近顶排)越优，使 y=13 优先于 y=12，逐行往下填。
                top_adjacent = 1 if (cap is not None and gy == cap - 1) else 0
                # ★ 顶排同色根借位铺路（2026-08-06 方向1：队列借位优化顶排凑消）：
                #   当顶排存在 need>=1 的同色根、且【当前球≠根色】时，若落点(gx,gy)紧邻该根段任一球
                #   （六邻居相邻，落点即根的支撑/借位基座），则 top_root_pave=1——表示"当前异色球
                #   主动贴到该根旁，等队列后续该色球到来时即可 need→0 凑3连消除，消除后下方连锁悬空"。
                #   这是"当前球不凑顶排、但为未来同色铺路"的明确维度（区别于 hang：hang 只看落点正下方
                #   异色孤球；本维度看顶排同色根，覆盖 need=1/2 的顶排段，是更确定的清盘路径）。
                #   仅当根 need>=1（还需补球）才铺路；need=0 根已齐、只差同色来触发（由 top_row_chain_landing
                #   在后续同色拍处理），异色落其旁无意义，故排除 need=0。
                top_root_pave = 0
                if self.top_roots and color is not None:
                    # ★ 顶层优化（2026-08-06）：为【所有】need>=1 的异色顶排根铺路，不区分 solvable。
                    #   理由：发射队列会由 79A3 持续追加新球，任何色最终都会再来——当前队列暂时缺色
                    #   不代表永远缺色（旧版用当前队列判"死根"并排除铺路是错的近似，会让该根永远不补、
                    #   等不到补给就 31115）。故所有异色根都积极贴旁预铺，等该色球到来即 need→0 凑3连。
                    #   need<1(已齐)或同色(由 chain 段直接消)不铺。
                    for _r in self.top_roots:
                        if _r['need'] < 1 or _r['color'] == color:
                            continue
                        _adj = False
                        for (_cx, _cy) in _r['cells']:
                            for _nx, _ny in neighbors(_cx, _cy):
                                if (_nx, _ny) == (gx, gy):
                                    _adj = True
                                    break
                            if _adj:
                                break
                        if _adj:
                            top_root_pave = 1
                            break
                top_fill = 0
                ty = -999
                if (gx, gy) in top_gap_set:
                    top_fill = 1
                    ty = gy
                # ★ 2026-08-05 队列前瞻维度 queued_plan：
                #   仅当「队列后续还有当前球色(queue_same>0)」且「落点贴着现有同色簇(origin_same>=1)」
                #   时为 1 —— 表示"把当前球预堆到同色簇，为未来同色球凑 3 连铺路"。
                #   若 queue_same==0（当前色绝唱），queued_plan 恒 0，不干扰贴顶排归位铁律。
                queued_plan = 1 if (queue_same > 0 and origin_same >= 1) else 0
                # ★ 方案 A 归位时也尽量往同色旁堆（用户 2026-08-05 补充规则：「往 y=13 及以下堆不是乱堆，
                #   尽量往同色旁边堆，不然越堆越多也消除不掉」）。顶排空位归位的多个候选里：
                #   tf_same=1 表示落点后该色连通块≥2（落点紧邻同色，block 已算好），归位同时把同色聚拢，
                #   等后续同色球/下降即凑≥3消除；异色旁/孤立落点 tf_same=0。
                #   该维度放在 top_fill 内部、ty 之前：先选"归位 + 贴同色"，再选"归位 + 贴顶排近"，最后
                #   才"归位但贴异色/孤立"。保证残局归位不空转堆高。
                tf_same = 1 if (top_fill and block >= 2) else 0
                # 贴球群度：落点到最近已有球(任意色)的六边形步数，取负（越近越优）
                # ★ 迭代内二次 deadline 检查：单次迭代若含大棋盘 BFS（dist_to_nearest_ball 等）
                #   可能本身超过 0.04s，必须在最贵子步骤前再查一次，确保单拍绝不大幅超预算。
                if time.time() > deadline:
                    break
                dist = self.dist_to_nearest_ball(gx, gy)
                # 注：第四十九轮曾加 above_penalty（落点 y<min_y 时降权），其根因是当时把 31108
                #   误当成"悬空球坠落到新位置"做重定位，导致本地棋盘失真、归位落点误判合法→31115。
                #   现 31108 已改为"悬空球直接 remove"（与服务端一致），棋盘不再失真，该止血项已无依据，移除。
                # 评分元组顺序（reverse=True，越靠前权重越高）：
                #   top_adjacent 贴顶排正下方(y=13) > top_root_pave 顶排异色根借位铺路 >
                #   prefer_hit 簇记忆(须 is_supported) > two_step 两步消除 > hang 脆弱单连接借消除 >
                #   queued_plan 队列前瞻预堆(后续有同色且贴同色簇) > origin_same 合并同色数 >
                #   block 连通块大小 > -dist 贴球群度 > top_fill 顶排有球列下方归位 >
                #   tf_same 归位且贴同色 > ty 贴顶排近 > -gy 最靠下 > gx 最小
                # ★ 2026-08-05 终版修正（本局 seq=19~24 簇记忆把同色球拽到中低排、远离顶排、永远凑不掉）：
                #   top_adjacent(y=13 贴顶排) 提到 prefer_hit【之前】。用户铁律"残局先填满 y=13 贴顶排，
                #   y=13 没合法空格才往下"是最高优先级——簇记忆(prefer_hit)只在"落点也贴顶排或真凑3连"
                #   时才有意义，否则它把球拽回中低排旧锚点、自我强化空转（本局 seq=46 起空转根因）。
                #   故贴 y=13 无条件优先于追簇记忆；prefer_hit 退居次高，仅在 top_adjacent 同分时决胜。
                #   immediate(真3连)已在循环外单独优先返回，不受此顺序影响。
                #   ★ top_root_pave(顶排异色根借位铺路，2026-08-06 方向1)置于 top_adjacent 之后、prefer_hit
                #   之前：贴 y=13 是"填满顶排基座"的普适最高优先；而"紧邻 need>=1 顶排同色根、为未来同色
                #   铺路"是次高优先（比追簇记忆/两步消更确定能推进顶排清盘）。当 y=13 无合法空格时，
                #   top_root_pave 成为首选归位方向。
                #   ★ queued_plan(队列前瞻)置于 hang 之后、origin_same 之前：仅当队列后续还有当前球色
                #   且本落点贴同色簇时才生效，让 bot 主动为未来同色球预堆（而非平摊），但低于"真能借
                #   消除/两步消"——避免为预堆而预堆牺牲即时收益。queue_same==0 时恒 0 不干扰贴顶排铁律。
                # ★ 归位评分方向（2026-08-07 修正，针对"初始棋盘一球未消、bot 往死亡线搭塔"根因）：
                #   评分首项由「-gy 最靠下」改为「gy 最靠上」。理由：本游戏判负线(death_floor)在【最下方】，
                #   球越靠下(y 越小)越危险；木板(y=15)只是天花板(不能越界、非判负)。故归位应优先把球放在
                #   【最高(最靠上)的合法 supported 落点】——即贴着现有球群往上/贴初始棋盘(y=6 起)，而非
                #   一路往下搭塔滑向 death_floor→31115。初始满盘(y=7~14)下方唯一合法 supported 行是 y=6，
                #   gy 优先使其贴着棋盘逐排向上聚拢、借 origin_same/block 与棋盘同色球凑≥3消除，从而真正
                #   清理初始棋盘（旧 -gy 让落点一路沉到 y=0，棋盘球全程未消）。y=13(top_adjacent) 本就比
                #   y=6 更高，gy 首项与之不冲突、且 death_floor 收紧时 pool 只剩上方候选仍自然贴合铁律。
                #   其余维度作为同 y 内决胜项保留。
                score = (gy, top_adjacent, top_root_pave, prefer_hit, two_step, hang, queued_plan, origin_same, block, -dist, top_fill, tf_same, ty, gx)
                scored.append((score, (gx, gy)))
                # ★ ① 立即消除优先（复用已算 block，零额外 shot_count 复制）：落点后该色连通块≥3
                #   即能消除，收集到 immediate_cands（循环首行有 deadline 保护，不会卡死）。
                if block >= 3:
                    immediate_cands.append((gx, gy))
            finally:
                # 无论迭代正常结束还是被 deadline/two_step break 中断，(gx,gy) 都回滚，不污染棋盘
                self.cells.pop((gx, gy), None)   # pop 防御性：避免极端重复 add 时 KeyError
                self.cells.pop((gx, gy), None)   # 用 pop 而非 del：防御性，避免极端重复 add 时 KeyError
        # ① immediate 优先于聚合评分：能消除(>=3)直接选最靠下、x 最小（复用主循环已算 block）
        if immediate_cands:
            immediate_cands.sort(key=lambda p: (p[1], p[0]))
            return immediate_cands[0]
        if scored:
            scored.sort(key=lambda s: s[0], reverse=True)
            best = scored[0][1]
            return best
        return None

    def top_row_chain_landing(self, color: int, excluded: set = None, next_color: int = None):
        """顶排连锁借消除（基于 self.top_roots 根节点数组，2026-08-05 用户方案）：
        遍历 refresh_top_roots 维护的根节点，找【当前球色==root.color 且本拍能消(need<=1)】的根，
        从其 slots 挑一个落点使 shot_count(落点,color)>=3 即返回。X(顶排同色段)被消后，其正下方
        整片球失去最顶支撑→连锁悬空→31108 一波清掉大半盘。
        ★ 用户铁律：凑顶排同色时，【同色球就落 y=14 同色球旁边】(slots 含 ny==top 顶排内空格)；
          不同色才落其正下方 y=13（归位分支处理）。本函数只处理【当前色即可直接消】的最高优先命中，
          其余根节点(need=2 等两拍)留数组中待后续同色球来消。
        返回落点 (x,y) 或 None。"""
        if excluded is None:
            excluded = set()
        # ★ GIL 饥饿止血（2026-08-05 第二十九轮卡死根治）：本函数对每个 root 的每个 slot 调
        #   shot_count（现已改为原地模拟，不再整盘复制，但顶排满10列、slots 数十个时仍可能累积
        #   数百 ms）。加统一 deadline，超预算即停止扫描剩余 slots，用已找到的命中返回（或返回
        #   None 退化到普通归位）。避免 maybe_shoot 在 daemon 线程卡死 → busy 永真 → 日志停更。
        deadline = time.time() + 0.04
        # 第一段：need<=1（本拍即可消3连）——最高优先，立即清顶排
        for root in sorted(self.top_roots, key=lambda r: r['need']):
            if root['color'] != color or root['need'] > 1:
                continue
            for slot in root['slots']:
                if time.time() > deadline:
                    break
                nx, ny = slot
                if (nx, ny) in self.cells or (nx, ny) in excluded:
                    continue
                if not self.is_placeable(nx, ny):
                    continue
                if ny >= self.wood_row:
                    continue
                # bot 直接发包，不查撞球支撑；临时落 color 验证与 root 同色段连通≥3
                if self.shot_count(nx, ny, color) >= 3:
                    return (nx, ny), True
        # 第二段：need==2（顶排同色孤球，本拍补1个即成2连，为下一同色凑3连铺路）
        #   ★ 2026-08-05 修复（用户质疑 seq=35/36/37/38 顶排孤球旁不堆同色、全跑普通归位）：
        #     旧版 need>1 直接跳过 → 顶排孤球永远等不到同色来补，top_roots 形同虚设，
        #     同色球全落普通归位(如 (8,13)/(6,12))，顶排连锁清盘永不触发。
        #     现：当前球色==根节点色时，优先把球落到该根节点 slots（顶排内空格或 y=13 紧邻），
        #     落点后该色连通块≥2（即贴住孤球段、推进 need 2→1），比普通 y=13 归位更优。
        #     约束：落点须真贴住孤球段(shot_count>=2)，否则不推进根节点、白堆。
        # ★ 顶层优化（2026-08-06）：need>=1 段必须优先补【solvable】根——即队列后续还有足够同色球
        #   能把它凑齐消除的根。多个同色根时，先补 solvable 的（确定性通关），不可凑齐的死根(solvable
        #   为 False，队列里已无该色球)留到最后、甚至不主动补（交由炸弹/下降处理，而非乱堆废球拖延）。
        #   排序：solvable 优先(True在前)，同档再按 need 升序、slots 数升序（孤球优先、小段优先）。
        # ★ 2026-08-07 修复（用户实测"顶层只剩2球：绿(0,14)+蓝(0,13) 时顶层优化失效、退普通归位乱堆"）：
        #   旧版此处仅收 need==2，漏掉【单球 need==1】的顶排孤球（如仅剩 (0,14) 单绿，free=1→need=1）。
        #   该孤球第一段 shot_count>=3 必败（落1球只成2连、消不掉），第二段 need==2 又跳过 → 返回 None →
        #   顶层优化彻底失效，bot 退普通归位把异色球堆在 y=13/12 远离顶排孤球，永远凑不出 3 连。
        #   修正：收 need>=1（含 need==1 单球），单球 need==1 落1球→2连(need 1→0 待下一同色凑3连)，
        #   与 need==2 同走"贴根铺路"逻辑；第一段已优先返回能直接消的 need<=1 段，此处不会重复消除。
        _n2 = sorted([r for r in self.top_roots if r['color'] == color and r['need'] >= 1],
                     key=lambda r: (not r.get('solvable', True), r['need'], len(r['slots'])))
        for root in _n2:
            for slot in root['slots']:
                if time.time() > deadline:
                    break
                nx, ny = slot
                if (nx, ny) in self.cells or (nx, ny) in excluded:
                    continue
                if not self.is_placeable(nx, ny):
                    continue
                if ny >= self.wood_row:
                    continue
                # ★ 门槛须为 shot_count>=1（紧挨根球即贴住起步），绝不能用 >=2：
                #   单根孤球场景（整盘只剩1个同色球，如只剩 (0,14) 红球）任何 slots 空格
                #   最多只挨着那1个根 → shot_count 恒=1，>=2 会让 need==2 分支永远返回 None
                #   → 顶层优化第一拍失效、退化普通归位乱堆（用户实测"只剩1红球顶层逻辑没动"根因）。
                #   >=1 才能正确贴住 → 本拍落1个变2连（need 2→1）→ 下一同色拍 need<=1 凑3连消除
                #   → 下方垫底的非红球悬空(31108)通关。slots 已限本根同色邻空，仅贴当前根不引偏色。
                if self.shot_count(nx, ny, color) >= 1:
                    return (nx, ny), False
        return None, False

    def min_y(self) -> int:
        """当前棋盘所有球里的最小 y（最靠下/炮口方向的行号）。空棋盘返回大常数。"""
        if not self.cells:
            return 999
        return min(y for _, y in self.cells)

    def dist_to_nearest_ball(self, x: int, y: int) -> int:
        if not self.cells:
            return 999
        seen = {(x, y)}
        frontier = [(x, y)]
        step = 0
        while frontier:
            nxt = []
            for cx, cy in frontier:
                if (cx, cy) in self.cells:
                    return step
                for mx, my in neighbors(cx, cy):
                    if (mx, my) in seen:
                        continue
                    if not self.is_placeable(mx, my):
                        continue
                    seen.add((mx, my))
                    nxt.append((mx, my))
            frontier = nxt
            step += 1
        return 999

    def __str__(self):
        if not self.cells:
            return "（空棋盘）"
        xs = [x for x, _ in self.cells]
        ys = [y for _, y in self.cells]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        # ★ y 大=上（屏幕顶）、y 小=下（炮口侧）。按用户要求【从上往下显示 y=14→y=0】，
        #   故逆序遍历（从 y1 最大行 到 y0 最小行），首行 y 最大=顶排在最上方。
        lines = []
        for y in range(y1, y0 - 1, -1):
            row = []
            for x in range(x0, x1 + 1):
                col = self.cells.get((x, y))
                row.append(COLOR_NAME.get(col, ".") if col is not None else " ")
            lines.append(f"y={y:2d} " + " ".join(row))
        return "\n".join(lines)


# ───────────────────────── 自动玩家 ─────────────────────────
class Bot:
    """被动驱动版：不自己建连，由外部（mole.py）把游戏服务器 socket 经 fromfd 注入
    send_func(cmd_id, body)，并把游戏服务器收包经 feed() 喂进来。"""

    def __init__(self, send_func, user_id: int):
        self.send_func = send_func        # callable(cmd_id:int, body:bytes) -> None
        self.user_id = user_id
        self.board = Board()
        self.queue: deque = deque()   # 79A2 整条发射队列 (type, color)，type: 1普通球 2炸弹
        self.current = None           # 当前待发射 (type, color) 或 None
        self.bomb_count = 0           # 炸弹道具持有数量（来自 31104 道具数量包，Type=2）
        self.seq = 0
        self.running = False          # 是否允许发射（点按钮后 True）
        self.listening = False        # 是否持续接收并维护棋盘（识别 socket 后即 True，早于 running）
        self.finished = False         # 收到 31114/31115/31116 后置 True
        self.initial_min_y = None     # 797E 初始棋盘最小 y（用于落点绝对下限）
        self.descended = False        # 是否已发生过真正的 7987 行移动（下降后落点下限需抬到 min_y）
        self.descended_count = 0       # 累计真正下降次数（权威底排 auth_min_y = initial_min_y - count）
        self.buttom_row_index = None  # 31111 下发的 ButtomRowIndex（服务端权威底行号，仅记录备用）
        self.initial_buttom_index = None  # 首个 31111 的 idx（用于判断后续是否真下降）
        self.prev_buttom_index = None     # 上一拍 ButtomRowIndex（idx 变化=下降一行）
        self.shot_landed: set = set()     # 本局已发射落点（排除集，防重复命中已占格判负）
        self._pending_rf = None           # ★ 2026-08-07 seq=6 根因修复：待服务端确认的 cnt>=3 即时消除落点
                                        #   (seq,x,y,color)。若 7983 回包显示该球未被消除(n=0)，则本地补录占位球，
                                        #   防止下拍重选同格→服务端视角已占→31115。
        self._await_seq = None           # ★ 2026-08-08 等回包闸：当前在等待结算回包的发射 seq（None=可发下一发）。
                                        #   send_ball 发出 31106 后置为该发 seq；on_7983/on_31108 带相同 seq 回包
                                        #   处理完即清 None，放行下一发。避免用「尚未回包的旧棋盘」算下一发→新发散。
        self._await_since = 0.0          # 等回包闸置位时刻（time.time()），用于超时强制清闸防卡死。
        self.rf_cells = set()           # ★ 2026-08-08 失步修复球标记集：记录经 _pending_rf 补录的占位球坐标，
                                        #   用于「连续失步修复避让」判定（不在其下方继续堆逼近死亡线）。
        self.last_rf_pos = None         # ★ 最近一次失步修复补录的占位球坐标；None=当前无连续失步链。
                                        #   每次真正补录时更新；某次 cnt>=3 潜在失步发被服务端真实消除后清 None（断链）。
        self.gather_cluster: dict = {}    # 归位簇记忆：{color: (x,y)} 当前正在聚集的同色簇锚点（第四十七轮）
        self.recent_empty: list = []      # 滑动窗口：最近每发是否消除=0（True=归位空转），见 EMPTY_WIN/WIN_EMPTY_LIMIT
        self.bomb_target_override = None  # 炸弹救场指定的落点（下一拍 cur_type==2 分支优先用，一次性消费）
        self.bomb_armed = False            # 炸弹已发 31112 激活、等待队列滚到炸弹并真正发射 31106 的状态机标志。
                                           # 防止救场分支因 best 持续为 None 而连续发多个 31112（服务端炸弹模式被冲乱/本地 bomb_count 被 31104 回包反复覆盖导致死循环）。
        self.bomb_inflight = False         # ★ 炸弹已发 31106（落点已飞出）、等待服务端 7983 消除回包确认的状态。
                                           #   乱序回包下：炸弹发射后本地棋盘/炸弹数仍停留在"旧局"，若立刻解锁 bomb_armed，
                                           #   stuck_at_bottom 会误判"仍有炸弹+死局"→重复发 31112（双炸）→第二枚落点悬空→31115。
                                           #   故炸弹发射后保持 bomb_inflight=True，直到 on_7983 收到该炸弹消除回包才解锁。
        self.visible_top = None           # 显示框顶部行号（屏幕可见区上界），落点不得超出
        self.last_shot = 0
        self.last_response_time = 0    # ★ 残局停滞检测（2026-08-05）：最近一次收到服务端回包(79A3/7983/31104/31108等)的时间。
                                        #   用于识别"本地已清盘但服务端不再回包"的逻辑性卡死（非 GIL 饥饿），主动通关退出。
        self._had_cells = False        # ★ 本局是否曾出现过非空棋盘（797E 填盘后置 True）。
                                        #   用于区分"开局等待填盘(cells 暂空)"与"真通关(cells 曾非空现又空)"，
                                        #   避免开局误判通关；仅在 cells 曾非空、现又空时主动 on_end(31114)。
        self.on_end_callback = None    # 游戏结束时回调（由 mole.py 注入，用于停掉发射 timer）
        self.on_level_start_callback = None  # ★ 下一关初始化(797E)回调（由 mole.py 注入）：
        self.level = 0                  # ★ 当前关卡号（on_797e 从 body[0] 读，仅作记录/诊断）
        self._next_requested = False    # ★ 残留标志（历史用于防 31101 重复请求，现已不再主动发 31101）
        from threading import Lock
        self.lock = Lock()              # 状态锁：maybe_shoot(决策/发包) 与 feed(收包改棋盘) 串行化，
                                        # 避免 recv 钩子线程与发射线程并发改 board/queue/shot_landed。
                                        # 发射放到独立线程后，本锁保证本地棋盘状态一致。

    # ---- 发包（经外部注入的 socket） ----
    def send(self, cmd_id: int, body: bytes = b""):
        self.send_func(Packet(cmd_id, self.user_id, body).data())

    def send_ball(self, x: int, y: int, is_bomb: bool = False, record: bool = True, track_landed: bool = True):
        self.seq += 1
        # 对齐 AS 源码 paopaolongSocket.sendBall: writeByte(x); writeByte(Math.abs(y)); writeByte(seq)
        body = bytes([x & 0xFF, abs(y) & 0xFF, self.seq & 0xFF])
        _s0 = time.time()
        self.send(31106, body)   # ★ 计时诊断：send_func 经 fromfd 发包，若 game socket 缓冲满可能阻塞
        _sd = time.time() - _s0
        if _sd > 0.1:
            logger.debug(f"[计时] send_ball({x},{y}) 发包阻塞 {_sd:.2f}s（send_func 疑似卡）")
        # ★ 等回包闸置位：记下本发 seq，下一发须等其结算回包（同 seq 的 on_7983/on_31108）才放行。
        #   避免下一拍用「尚未回包的旧棋盘」（仍含本该被上发消除的球）算落点→新发散/失步修复。
        self._await_seq = self.seq
        self._await_since = time.time()
        if is_bomb:
            # 炸弹落点：飞到 (x,y) 后炸掉以落点为中心、六连通距离≤BOMB_RADIUS 的所有球。
            # 本地不预删 cells——等 7983 消除列表回包再扣，避免与权威状态错位。
            self.shot_landed.add((x, y))  # 排除集双保险：防重选同格
            # ★ 诊断口径与落点选择一致：基于净化棋盘（cells 排除 shot_landed 幽灵球），
            #   否则幽灵球会让 in_region 虚高、is_supported 误判 True。
            served_b = {(sx, sy) for (sx, sy) in self.board.cells if (sx, sy) not in self.shot_landed}
            proxy_b = Board()
            # ★ 注意：served_b 是【坐标元组集合】，绝不能用 dict(served_b)！
            #   dict(set_of_tuples) 会把每个 (x,y) 解包成 (key=x, value=y)，导致 proxy_b.cells
            #   的 key 变成 int（x），candidate_landings 解包崩溃（TypeError）。
            #   须用 dict.fromkeys 保留 (x,y) 元组作为 key。
            proxy_b.cells = dict.fromkeys(served_b)
            proxy_b.wood_row = self.board.wood_row
            region = cells_within_radius(x, y, BOMB_RADIUS)
            in_region = sum(1 for (rx, ry) in region if (rx, ry) in served_b)
            n_cands = len(proxy_b.candidate_landings())
            logger.info(f"[发射] 炸弹 落点：({x},{y}) seq：{self.seq}"
                  f" 半径内球={in_region} 候选落点数={n_cands} 落点is_supported={proxy_b.is_supported(x, y)}"
                  f" 落点空格={((x, y) not in served_b)}")
        else:
            # ★ 落点写回纪律（2026-08-05 致命失步修复）：
            #   本地 cells 只反映「服务端真实留在场上的球」。落点球是否被消除由服务端判定，
            #   回包前 bot 无从知晓，故：
            #   · record=True（默认）：消除=0 的球确实留在场上，写回正确（cnt<3 归位/armed 推进）。
            #   · record=False：cnt>=3 即时消除分支——该球落下去【立刻被消除】（31107 同色消除
            #     包含落点球本身），服务端不会让它在场上。若本地写回 → 产生【幽灵球】污染棋盘，
            #     后续 candidate_landings/is_supported 基于错误棋盘选出服务端视角的非法落点 →
            #     服务端拒绝发包 → 无回包 → 棋盘冻结卡死。`record=False` 时不写回，
            #     7983 回包会 remove 对应坐标（本地本就没它，remove 找不到无害），自洽。
            if record and self.current is not None:
                color = self.current[1]
                if (x, y) not in self.board.cells:
                    self.board.cells[(x, y)] = color
                # ★ 真实归位点(record=True)已写回 cells，candidate_landings 会自然排除已占格，
                #   不必加入 shot_landed。若加入会导致 served = cells - shot_landed 误剔真实球，
                #   破坏其子排的 is_supported 支撑判定 → legal 空 → 被迫顶排/兜底死局。
                #   shot_landed 只记 record=False 的幽灵落点（即时消除）与 is_bomb，见下方分支。
            else:
                # ★ 2026-08-06 seq=62 根因修复：cnt>=3 即时消除的落点球落下去立刻被消除，服务端不会让
                #   它在场上，落点格随即变回空格。旧代码此处无条件 shot_landed.add，使这些"本应变空"的格
                #   永久被判为已占 → best_shot 候选生成把它们当占用排除 → 残局塌缩到顶排时，唯一能凑≥3消除
                #   的空格(如 (6,13))被误判占用 → best_shot 返回 None → 炸弹救场误触发、唯一炸弹浪费在可
                #   消除的红对上 → 残局剩 绿/蓝 孤球无法匹配 → 31115。
                #   正确做法：即时消除落点不入 shot_landed（球已消除、格变空，本就不应排除；落点格未被写回
                #   cells，7983/31108 回包前由 cells 暂态反映占用，后续决策靠 cells 自然排除）。仅"炸弹等待态
                #   占位推进球"(不消除、球真留场上)需 track_landed=True 入集防重选。cnt>=3 即时消除的 caller
                #   传 track_landed=False（见 line 1842）。
                if track_landed:
                    self.shot_landed.add((x, y))  # 占位推进/炸弹：本地未写回 cells，需排除防重选同格
                else:
                    # ★ 2026-08-07 seq=6 根因：cnt>=3 即时消除落点。本应被服务端消除，但若服务端
                    #   实际未消除(n=0：本地预测连通≥3、服务端视角不足)，球会留在场上，而本地既未
                    #   写回 cells 也未入 shot_landed → 棋盘错位、下一拍重选同格 → 31115。记下待确认
                    #   落点，等 on_7983 回包时若 n=0 则补录占位球（见 on_7983）。
                    self._pending_rf = (self.seq, x, y, self.current[1] if self.current else None)
            logger.info(f"[发射] {COLOR_NAME.get(self.current[1] if self.current else None, str(self.current))} 落点：({x},{y}) seq：{self.seq}"
                  + ("" if record else "（即时消除，不写回本地）"))

    def use_bomb_prop(self):
        """点击炸弹道具：发 31112([Type=2, Seq=0])，**本地**把队列【下一个球(索引1)】直接置为炸弹。
        ★ 用户实测权威协议（已对 AS 源码核对）：点炸弹发包 7988 0200 后，服务端回——
          · 0x7989(31113使用道具应答) 02 01 00
          · 0x7980(31104道具数量) 01 01   （其它道具 Type=1 Num=1）
          · 0x7980(31104道具数量) 02 00   （炸弹 Type=2 Num=0：服务端已扣掉1个，剩余0）
          · **炸弹数据不是靠 79A3 收包来的，是直接本地把当前炮筒的【下一发弹药】置为炸弹**。
            实测：初始队列[蓝,黄,蓝,蓝,蓝]当前炮筒=蓝，点炸弹后→[蓝,炸弹,蓝,蓝,蓝]；
            当前蓝球发出→下一个炮筒=炸弹（走 31106 落点炸）。
        ★ 铁律：
          - bomb_count 由 7980 回包驱动（on_31104 已 `bomb_count = pnum`），bot **不**本地减，
            否则与 7980(02 00) 双重扣减错乱，stuck 分支 `bomb_count>0` 守卫提前失效。
          - 炸弹就位 = 本地 queue[1]=(BOMB_PROP_TYPE,0)，与后续 79A3 追加(append 队尾)不冲突。
          - 发 31112 后由调用方置 bomb_armed=True 进等待态，持续发队首普通球推进队列，
            直到 queue 滚到炸弹（cur_type==2），由上方炸弹分支真正发 31106 引爆。"""
        if self.bomb_armed:
            return False  # 已在等待态，禁止连发多个 31112（冲乱服务端炸弹模式）
        # ★ 不在此判 bomb_count>0、不本地 bomb_count-=1：bomb_count 由 7980 回包更新，
        #   调用方(stuck_at_bottom)已确认 bomb_count>0 才调本函数。
        self.send(USE_PROP_CMD, bytes([BOMB_PROP_TYPE, 0]))
        # ★ 本地把"下一发弹药"(队列第2位，索引1)置为炸弹 —— 这是泡泡龙客户端真实就位机制。
        if len(self.queue) >= 2:
            self.queue[1] = (BOMB_PROP_TYPE, 0)
        elif self.queue:
            # 队列仅1个时顶替队首（极端兜底）
            self.queue[0] = (BOMB_PROP_TYPE, 0)
        return True

    # ---- 收包分发 ----
    def on_31102(self, body):
        # ★ 下一关初始化：清除上一关 31114 设置的 finished（暂停发射）标志，bot 恢复自动发射。
        #   31114 软过渡只暂停发射、不停止 bot，故此处必须清 finished 才能续打。
        if self.finished:
            self.finished = False
            logger.info(f"[797E] 下一关初始化：清除 finished(暂停)标志，bot 恢复自动发射")
        # ★ 通知 mole.py：新一关开始。若"用户仍想要自动"但发射循环因故被停（如上一关真正结束时
        #   的 stop、或异常），此处复活 timer+running，避免下一关静默。用户主动停止时不复活。
        if self.on_level_start_callback is not None:
            try:
                self.on_level_start_callback()
            except Exception as e:
                logger.warning(f"[错误] on_level_start_callback 异常: {e}")
        level = body[0]
        self.level = level              # ★ 记录当前关号（仅作记录/诊断）
        self._next_requested = False    # ★ 残留标志复位（历史用于防 31101 重复请求）
        count = (body[1] << 8) | body[2]   # 大端 2 字节：高字节 body[1]，低字节 body[2]
        cells = {}
        off = 3
        for _ in range(count):
            x, y, t = body[off], body[off + 1], body[off + 2]
            off += 3
            # 第三字节 type：0xFF 为空位；其余 1/2/3/5 为真实颜色记入棋盘。
            # 注意：第一字节是 x 坐标（x=0 合法），0x00 不是 type，勿误判为空位。
            if t != 0xFF:
                cells[(x, y)] = t
        self.board.reset(cells)
        self.board.top_roots = []         # 新关重建：清空顶排根节点数组（下面 refresh 重算）
        self.board.refresh_top_roots()    # 新关：按初始顶排建根节点
        self.shot_landed = set()    # 新关重建：清空已发射落点排除集
        self.queue = deque()        # ★ 新关重建：清空发射队列（避免跨关残留旧颜色→首拍抢跑失步）
        self.current = None         # ★ 新关重建：清空当前待射（须等新 79A2 重建，否则 _shoot_impl 会因 not self.queue 等待）
        self._pending_rf = None     # 新关重建：清空待确认落点（防上一关残留误补录）
        self._await_seq = None      # 新关重建：清空等回包闸（防上一关残留 seq 误挡本关发射）
        self.rf_cells = set()        # 新关重建：清空失步修复球标记集（防上一关残留误避让）
        self.last_rf_pos = None      # 新关重建：清空连续失步链（防上一关残留 last_rf_pos 误挡本关下方落点）
        # ★ 2026-08-07 seq 跨关重置修复：服务端在【每一关】把发射 seq 计数器归零、从 01 开始。
        #   用户抓包实证下一关首发包 seq 字段=01（如 00000014010000798203ABF31C00000000060601 =
        #   x=6,y=6,seq=01）。bot 若沿用上关递增 seq（如 56），服务端按自身 01 起始计数：
        #   ① 若服务端校验 seq 直接丢弃该发→无回包→失步；② 即便只回显，也令 on_7983/on_31108 的
        #   _pending_rf(pr_seq) 匹配失败→失步修复补录失效→第二轮持续失步。
        #   故新关必须让 self.seq 归零，使下一发 send_ball 产生 seq=01，对齐服务端（首关正是 seq=0 起）。
        self.seq = 0
        self.gather_cluster = {}     # 新关重建：清空归位簇记忆
        # 新关重建：重置下降跟踪状态，避免上一关残留污染本关坐标推算
        self.initial_buttom_index = None
        self.prev_buttom_index = None
        # ★ 2026-08-07 第4关根因修复：死亡线 buttom_row_index 必须随新关重建归零！
        #   旧代码只重置 prev/initial_buttom_index 却【漏掉 buttom_row_index 本身】，
        #   导致新关首拍仍沿用上一关残留值（如 8）。于是 death_floor=8、eff_floor=8，
        #   把唯一空闲的 y=6 候选（<8）全部过滤掉 → best_shot 常规候选空 → 被迫走 fb 兜底
        #   按 min_y-1 逐排往下、每行只堆 1 列（"一个y只堆1个、往y减小堆积"），而非贴着
        #   底排把同一行填满。正确行为：新关死亡线=0（7987 初始 ButtomRowIndex=0 也会再次确认），
        #   y=6 候选合法，bot 会贴底排逐列填满一行后再进下一行。
        self.buttom_row_index = 0
        self.descended = False
        self.descended_count = 0
        self.last_eliminated = set()
        self.recent_empty = []            # 新关清空"连续空转(消除=0)"滑动窗口，避免上关残留误触炸弹救场
        self.initial_min_y = None   # 重置，使本关 visible_top 按新棋盘重算（见下）
        # 记录初始底排 y（= 初始最靠炮筒口那排的 y，用于 visible_top 推算；落点下限 abs_floor
        #   改由 descended_count 决定，见 maybe_shoot，不依赖 initial_min_y）。
        # 显示框渲染 y=initial_min_y 起 3 行 → 可见区顶 = initial_min_y + 2（初始 7+2=9）。
        #   落点不得超出该顶（屏幕外位置不可发射，服务端会判负/无效）。
        if cells:
            self._had_cells = True    # ★ 标记本局已出现非空棋盘（用于 _shoot_impl 清盘时主动通关判定，区分开局等待）
            self.initial_min_y = min(y for _, y in cells)
            self.visible_top = self.initial_min_y + 2
            # 木板行推断（用户实测，2026-08-04 修正）：
            #   ★ 坐标方向不变（y 大=上、y 小=下、炮口 y=-1 在最下），球的 (x,y) 也永不改变；
            #     下降只是【屏幕整体显示窗口向下移】，露出更上方(更大 y)的球行。
            #   ★ 木板在所有球的【上方】(更大 y 一侧)：当棋盘顶排(y=max_y，本关=14)显示出来后，
            #     再下降一行，就从屏幕最上方压下来【一行木板】(y=max_y+1=15)。木板不是球，
            #     不在 cells，但封顶——落点不得越过木板(y >= wood_row 即越界判负)。
            #   ★ 故 wood_row = 顶排 max_y + 1（通用，不再硬编码 max_y==14）。落点合法上界 =
            #     wood_row-1（=顶排，球最多停到这一行，其上方一格即木板天花板）。
            max_y = max(y for _, y in cells)
            self.board.wood_row = max_y + 1
            logger.info(f"[797E] 顶排 y={max_y}，木板 y={self.board.wood_row}"
                  f"（木板从屏幕最上方压下来，落点不得越过）")
        self.bomb_target_override = None  # 新关清空炸弹落点 override，避免跨关残留
        self.bomb_armed = False            # 新关重置炸弹激活状态机，避免跨关残留导致卡死
        self.bomb_inflight = False         # 新关重置炸弹在途状态，避免跨关残留导致卡死
        # ★ 对齐 AS nextLevel `PropArray = [0,0,0]`：道具/炸弹库存每关归零，由新关 31104(7980)
        #   回包重新下发。跨关残留旧值会令救场分支 `bomb_count>0` 守卫误判"仍有炸弹"→错发 31112→双炸/悬空 31115。
        self.bomb_count = 0
        # ★ 初始棋盘显示复用 dump_board 的同一套 odd-r 槽位对齐格式（与发射后本地棋盘一致，
        #   避免两套格式错位）。self.board.cells 已由上方 reset(cells) 写好，直接打。
        self.dump_board("初始棋盘(797E)")

    def dump_board(self, tag: str = "本地棋盘"):
        """打印本地棋盘布局（self.board.cells），从上往下 y=14 → y=0（含炮口侧通道，便于看炸弹落点/下落球）。
        ★ 用户 2026-08-05 要求：每次发射后显示本地棋盘，便于核对 bot 与服务端是否一致。
        ★ 显示规则：六边形 odd-r 布局，奇数行(y%2==1)相对偶数行【右移半格】，按【屏幕槽位】
          (偶数行 x→槽 2x，奇数行 x→槽 2x+1)排序打印，使两行在同一水平轴对齐、视觉顺序正确。
          ★ 奇数行 x=9 恒为不可放空位（is_placeable 写死），不显示该列（不输出 09:❌️）。
          ★ 空格也显示 x 坐标（如 9:空），x 用 1 位；有球显示 x:色（色用 COLOR_NAME）。"""
        logger.debug(f"[{tag}] 本地棋盘布局：")
        for y in range(14, -1, -1):
            odd = (y % 2 == 1)
            slot_map: dict[int, tuple[int, int]] = {}
            for x in range(10):
                if odd and x == 9:
                    continue  # 奇数行 x=9 不可放，跳过不显示
                if (x, y) in self.board.cells:
                    slot_map[2 * x + (1 if odd else 0)] = (x, self.board.cells[(x, y)])
            parts = []
            for slot in range(20):
                if slot in slot_map:
                    x, col = slot_map[slot]
                    parts.append(f"{x}:{COLOR_NAME.get(col, str(col))}")
                else:
                    is_legal_slot = (slot % 2 == (1 if odd else 0))
                    if is_legal_slot:
                        # 该合法槽对应的 x：偶行槽=2x→x=slot//2；奇行槽=2x+1→x=(slot-1)//2
                        x = (slot // 2) if not odd else ((slot - 1) // 2)
                        if odd and x == 9:
                            continue  # 奇数行 x=9 不可放置点，不显示
                        # 空位显示 x:  （冒号后2空格），与有球的 x:色 明显区分，便于看球位置
                        parts.append(f"{x}:  ")
                    # 非法槽（偶数行奇槽 / 奇数行偶槽）不占显示列
            # y=7/8/9 是 1 位数标签（y=7 比 y=10 少 1 字符），后面补一个空格让棋盘对齐
            ytag = f"y={y}" + (" " if y < 10 else "")
            logger.debug(f"  {ytag}{'  ' if odd else ''} " + " ".join(parts))

    def on_31138(self, body):
        n = body[0]
        q = []
        off = 1
        for _ in range(n):
            ptype = body[off]          # 真实条目含类型：1=普通球，2=炸弹（AS 客户端读后覆盖，但包内是真实值）
            col = body[off + 1]
            off += 2
            q.append((ptype, col))
        self.queue = deque(q)
        # 队首即"当前待射"，不弹出；发射时才 popleft
        self.current = self.queue[0] if self.queue else None
        names = [f'{"炸" if t == BOMB_PROP_TYPE else ""}{COLOR_NAME.get(c, str(c))}' for t, c in self.queue]
        logger.info(f"[79A2] 收到发射球队列({n}个)：{names}")

    def on_31139(self, body):
        # 每发射一个球后，服务端回 79A3 把"下一个球"推送过来（含类型，炸弹条目同样出现）。
        # 真实机制：发射的是 79A2 预备队列的队首；79A3 的条目追加到队列【末尾】循环使用。
        ptype = body[0]
        col = body[1]
        self.queue.append((ptype, col))
        self.current = self.queue[0] if self.queue else None
        cur = self.current
        cur_name = f'{"炸" if cur[0] == BOMB_PROP_TYPE else ""}{COLOR_NAME.get(cur[1], str(cur[1]))}' if cur else "?"
        names = [f"{"炸" if t == BOMB_PROP_TYPE else ""}{COLOR_NAME.get(c, str(c))}" for t, c in self.queue]
        logger.info(f"[更新] 下个球：{cur_name} 队列：{names}")

    def on_31104(self, body):
        # 31104(7980) 道具数量更新：[Type:1B][Num:1B]
        #   Type=2 为炸弹；Num 为当前持有数量。
        # 用户抓包确认：00000013010000798003ABF31C00000000 02 01 → Type=2(炸弹) Num=1
        if len(body) >= 2:
            ptype, pnum = body[0], body[1]
            if ptype == BOMB_PROP_TYPE:
                self.bomb_count = pnum

    def on_31111(self, body):
        # 31111 行移动：服务端下发 ButtomRowIndex（下降行数包）。
        # ★ 用户实测铁律（2026-08-05）：ButtomRowIndex 是【死亡线】，落点 y 若【小于】它就游戏结束
        #   （游戏定时收服务端包更新它）。对照 AS：paopaolong.as case 31111→moveToLine(data)；
        #   gameCore.as moveToLine(idx) 设 currentLine=idx、背景随之下移 → 死亡线在【靠下/y 小】侧，
        #   与 bot 坐标系（y 小=下/炮口）方向一致。故落点 y 必须 >= buttom_row_index，这是服务端
        #   权威判负线，优先于一切本地推算（initial_min_y/descended_count 仅作兜底）。
        #   注：7987 不改球的实际坐标（坐标体系固定），仅推进死亡线 + 显示行；cells 一律不改。
        idx = body[0]
        if self.initial_buttom_index is None:
            self.initial_buttom_index = idx
            logger.info(f"[7987] 初始死亡线：y={idx}（死亡线：落点 y 必须 >= {idx}）")
        # idx 相对上一拍【严格变大】= 真正下降（连续相同 idx 为冗余推送，不计）。
        # 注意：idx 可能一次跳多行（如实测 seq=33：ButtomRowIndex 由 4 跳 6，一次降 2 行），
        # 必须按差值累加，不能只 +1，否则 visible_top 会与实际下降次数偏差。
        if self.prev_buttom_index is not None and idx > self.prev_buttom_index:
            delta = idx - self.prev_buttom_index
            self.descended = True
            self.descended_count += delta
            # 显示框顶部多露 delta 行：顶行号 +delta（不再做 shift_down / 坐标位移）
            if self.visible_top is not None:
                self.visible_top += delta
            logger.info(f"[7987] 死亡线下移：y={self.prev_buttom_index}→y={idx}（降{delta}行），落点 y 下限收紧到 {idx}")
        elif idx == self.prev_buttom_index:
            pass   # 冗余推送（同 idx），不计下降但需更新（不动）
        else:
            # idx 变小（罕见，如重开/回退）：以最新值为准
            logger.info(f"[7987] 死亡线异常回退：y={self.prev_buttom_index}→y={idx}，以最新值更新")
        self.prev_buttom_index = idx
        self.buttom_row_index = idx

    def on_31107(self, body):
        seq = body[0]
        n = body[1]
        off = 2
        coords = []
        for _ in range(n):
            coords.append((body[off], body[off + 1]))
            off += 2
        self.board.remove(coords)
        # ★ 等回包闸（2026-08-08）：本回包对应在途发射的结算，放行下一发
        if self._await_seq == seq:
            self._await_seq = None
        self._cleanup_gather_clusters()
        self.board.refresh_top_roots()    # 消除/坠落后棋盘变化：刷新顶排可凑同色根节点数组
        # ★ 2026-08-07 seq=6 根因修复：cnt>=3 即时消除落点(record=False, track_landed=False)本应被
        #   服务端消除，但若服务端实际未消除(本地预测连通块≥3、服务端视角不足→n=0)，该球【留在场上】
        #   而本地因 record=False 从未写回 cells、track_landed=False 也未入 shot_landed → 本地棋盘与服务端
        #   错位：下一拍 best_shot 仍会选同一空格重复发射 → 服务端视角该格已占 → 31115。
        #   修复：落点球未出现在消除列表且本地未记录时，按"占位球"补录进 cells，使本地与服务端一致，
        #   候选生成自然排除已占格，杜绝重复命中同格。
        if self._pending_rf is not None:
            pr_seq, px, py, pcolor = self._pending_rf
            self._pending_rf = None
            if pr_seq == seq:
                # ★ 连续失步修复链管理（2026-08-08）：本发是"预测 cnt>=3 即时消除"的潜在失步发。
                #   ① 回包确认该落点被真实消除（(px,py) 在 coords 或已入 cells）→ 上次潜在失步实际成功，
                #      断开连续失步链（last_rf_pos=None），恢复常态避让。
                #   ② 回包未消除（下方补录分支）→ 又失步，更新 last_rf_pos 指向新补录的占位球。
                if pcolor is not None and (px, py) not in coords and (px, py) not in self.board.cells:
                    self.board.cells[(px, py)] = pcolor
                    self.rf_cells.add((px, py))
                    self.last_rf_pos = (px, py)
                    logger.warning(f"[失步修复] cnt>=3 落点({px},{py})服务端未消除，本地补录占位球 色={COLOR_NAME.get(pcolor)}（避免重选同格→31115）")
                else:
                    # 本发被服务端真实消除（落点在 coords 内）→ 连续失步链断开
                    self.last_rf_pos = None
        # ★ 炸弹在途态解锁（2026-08-05 双炸修复）：本发是炸弹引爆后的消除回包，确认炸弹已落地，
        #   允许后续救场分支重新评估（否则在乱序回包期间会重复激活 31112 导致双炸→第二枚悬空→31115）。
        if self.bomb_inflight:
            self.bomb_inflight = False
            logger.info(f"[炸弹确认] 收到炸弹消除回包 seq：{seq} 消除{len(coords)}个，解锁炸弹在途态")
        # 滑动窗口记录：本发消除=0 记 True（归位空转），否则 False；超 EMPTY_WIN 截断尾部
        self.recent_empty.append(len(coords) == 0)
        if len(self.recent_empty) > EMPTY_WIN:
            self.recent_empty.pop(0)
        empty_cnt = sum(1 for e in self.recent_empty if e)
        logger.info(f"[7983] seq：{seq} 消除{len(coords)} 个"
              + (f" (窗口空转{empty_cnt}/{len(self.recent_empty)})" if len(coords) == 0 else ""))
        # ★ 用户 2026-08-05：在 7983 显示消除几个之后，显示发射后的棋盘布局
        #   （落点已写入 + 本次同色消除已 remove，但可能还有 31108 悬空消除未到，故仅作中间态）。
        self.dump_board(f"发射后 seq={seq}（7983 消除{len(coords)}个，待 31108）")

    def _cleanup_gather_clusters(self):
        """第四十七轮：消除/坠落后，清除 gather_cluster 里已失效（锚点坐标不在 cells）的簇记忆。"""
        dead = [c for c, pos in self.gather_cluster.items() if pos not in self.board.cells]
        for c in dead:
            del self.gather_cluster[c]

    def on_31108(self, body):
        # 31108 = 同色消除(31107)后，因失去支撑而【悬空的球，随之掉落=被消除】的坐标广播
        #   （seq:1B + n:1B + n×(x:1B, y:1B)，不含颜色）。
        # ★ 协议关键澄清（用户 2026-08-04）：
        #   31108 不是"悬空球坠落到新位置（仍在场上）"，而是【悬空之后这些球也算被消除了】。
        #   → 即 31108 的坐标就是"被消除的球"，从本地棋盘【直接 remove】，与 31107 完全同类。
        #   服务端已经算好了全部消除结果，本地无需、也不能做任何悬空/坠落判断或重定位。
        seq = body[0]
        n = body[1] if len(body) >= 2 else 0
        off = 2
        coords = []
        for _ in range(n):
            if off + 1 >= len(body):
                break
            coords.append((body[off], body[off + 1]))
            off += 2
        if not coords:
            return
        self.board.remove(coords)
        # ★ 等回包闸（2026-08-08）：本回包对应在途发射的结算，放行下一发
        if self._await_seq == seq:
            self._await_seq = None
        self._cleanup_gather_clusters()
        self.board.refresh_top_roots()    # 消除/坠落后棋盘变化：刷新顶排可凑同色根节点数组
        # ★ 2026-08-07 seq=6 根因修复：cnt>=3 即时消除落点(record=False, track_landed=False)本应被
        #   服务端消除，但若服务端实际未消除(本地预测连通块≥3、服务端视角不足→n=0)，该球【留在场上】
        #   而本地因 record=False 从未写回 cells、track_landed=False 也未入 shot_landed → 本地棋盘与服务端
        #   错位：下一拍 best_shot 仍会选同一空格重复发射 → 服务端视角该格已占 → 31115。
        #   修复：落点球未出现在消除列表且本地未记录时，按"占位球"补录进 cells，使本地与服务端一致，
        #   候选生成自然排除已占格，杜绝重复命中同格。
        if self._pending_rf is not None:
            pr_seq, px, py, pcolor = self._pending_rf
            self._pending_rf = None
            if pr_seq == seq:
                # ★ 连续失步修复链管理（2026-08-08）：本发是"预测 cnt>=3 即时消除"的潜在失步发。
                #   ① 回包确认该落点被真实消除（(px,py) 在 coords 或已入 cells）→ 上次潜在失步实际成功，
                #      断开连续失步链（last_rf_pos=None），恢复常态避让。
                #   ② 回包未消除（下方补录分支）→ 又失步，更新 last_rf_pos 指向新补录的占位球。
                if pcolor is not None and (px, py) not in coords and (px, py) not in self.board.cells:
                    self.board.cells[(px, py)] = pcolor
                    self.rf_cells.add((px, py))
                    self.last_rf_pos = (px, py)
                    logger.warning(f"[失步修复] cnt>=3 落点({px},{py})服务端未消除，本地补录占位球 色={COLOR_NAME.get(pcolor)}（避免重选同格→31115）")
                else:
                    # 本发被服务端真实消除（落点在 coords 内）→ 连续失步链断开
                    self.last_rf_pos = None
        # ★ 炸弹在途态解锁（2026-08-05 双炸修复）：本发是炸弹引爆后的消除回包，确认炸弹已落地，
        #   允许后续救场分支重新评估（否则在乱序回包期间会重复激活 31112 导致双炸→第二枚悬空→31115）。
        if self.bomb_inflight:
            self.bomb_inflight = False
            logger.info(f"[炸弹确认] 收到炸弹消除回包 seq：{seq} 消除{len(coords)}个，解锁炸弹在途态")
        # ★ 用户 2026-08-05：31108 悬空消除后的棋盘 = 本次发射的最终布局，打印一次。
        self.dump_board(f"发射后 seq={seq}（31108 悬空消除{len(coords)}个，最终布局）")

    def on_31137(self, body):
        n = body[0]
        off = 1
        adds = []
        for _ in range(n):
            x, y, col = body[off], body[off + 1], body[off + 2]
            off += 3
            adds.append((x, y, col))
        self.board.add(adds)

    def on_31109(self, body):
        # 31109 彩球生成：[x:1B][y:1B]（dict.py）。
        # ★ 2026-08-05 修正（用户明确）：彩球只是让该格球加晃动动画，【颜色不变】，与原色球
        #   功能完全一样——【和原本颜色的球 3 个就能消除】。故本地棋盘【保持原色】，
        #   绝不改写为彩球色(0)。该格在本地 cells 里本就是原色（来自 797E/消除包维护），
        #   31109 只表示"动画"，不应覆盖颜色。保持原色后，shot_count 的六连通消除计算
        #   自然把彩球当原色参与，正确凑 3 连消除。
        #   若本地 cells 恰无该格（异常失步），也不写 0（避免污染为彩球色），直接跳过。
        if len(body) >= 2:
            x, y = body[0], body[1]
            if (x, y) not in self.board.cells:
                # 本地无该格：说明状态失步，不强行写 0（用户要求不记彩球色），跳过保持原样。
                return
            # 否则 cells[(x,y)] 已是原色，什么都不改——彩球动画不影响本地颜色模型。


    def on_end(self, cmd_id):
        name = {31114: "关卡通过", 31115: "游戏失败", 31116: "游戏全部结束"}.get(cmd_id, str(cmd_id))
        # ★ 诊断（2026-08-06）：游戏结束前打印关键状态，区分"落点非法导致 31115" vs "残局步数/策略失败"。
        served = [(x, y) for (x, y) in self.board.cells if (x, y) not in self.shot_landed]
        min_y = min((y for (_, y) in served), default=None)
        max_y = max((y for (_, y) in served), default=None)
        msg = (
            f"[游戏结束] cmd_id={cmd_id}({name}) 本地cells球数={len(self.board.cells)} "
            f"(served={len(served)}) served_y=[{min_y},{max_y}] "
            f"death_floor={self.buttom_row_index} wood_row={self.board.wood_row} "
            f"队列={[("炸" if t == BOMB_PROP_TYPE else "") + str(c) for t, c in self.queue]}"
        )
        if cmd_id == 31115:
            logger.warning(msg)
        else:
            logger.success(msg)
        # ★ 31114 单关通过：游戏会自动进入下一关并重新发 31102 初始化棋盘，
        #   故【不真正结束 bot】——只暂停发射(finished=True)等下一关，不 stop timer、不调 on_end_callback。
        #   下一关 31102(on_797e) 到达时清 finished 并重建棋盘，bot 自动续上。
        if cmd_id == 31114:
            self.running = True     # 保持运行态（仅暂停发射），下一关继续
            self.finished = True    # 暂停发射：_shoot_impl/maybe_shoot 见 finished 即静默返回，等下一关
            self._had_cells = False # 复位：下一关开局等待期(cells 暂空)不被误判通关
            self.bomb_armed = False
            self.bomb_inflight = False
            self.bomb_target_override = None
            logger.success(f"[本关通过] 暂停发射，等待用户在界面手动点击「下一关」按钮（bot 不发 31101，避免触发游戏退出）")
            # ★ 不再主动发 31101 请求下一关：用户要求通关后由界面手动点击下一关按钮，
            #   由 mole.py / UI 侧触发下一关初始化（797E）。bot 只暂停发射，保持运行态，
            #   待界面发出的下一关 31102 到达后自动续打。
            return
        # ★ 31115 失败 / 31116 全部结束：真正停掉 bot。
        self.running = False
        self.finished = True
        self._had_cells = False    # 复位：下一关开局等待期(cells 暂空)不被误判通关
        # 通知外部停掉发射 timer（全局 paopaolong_running 与实例 running 不同步，
        # 不在此停会导致 31115 后 bot 继续发射，socket 失效报 10038）
        if self.on_end_callback is not None:
            try:
                self.on_end_callback()
            except Exception as e:
                logger.warning(f"[错误] on_end_callback 异常: {e}")

    def handle(self, cmd_id, body):
        # ★ 残局停滞检测：任意回包都刷新"最近响应时间"（用于识别本地清盘后服务端不再回应 → 主动通关）
        import time as _t
        self.last_response_time = _t.time()
        if cmd_id == 31102:
            self.on_31102(body)
        elif cmd_id == 31138:
            self.on_31138(body)
        elif cmd_id == 31139:
            self.on_31139(body)
        elif cmd_id == PROP_COUNT_CMD:
            self.on_31104(body)
        elif cmd_id == 31111:
            self.on_31111(body)
        elif cmd_id == 31107:
            self.on_31107(body)
        elif cmd_id == 31108:
            self.on_31108(body)
        elif cmd_id == 31137:
            self.on_31137(body)
        elif cmd_id == 31109:
            self.on_31109(body)
        elif cmd_id == 31110:
            # 31110 彩球消除：[x:1B][y:1B]，从本地棋盘移除占位
            if len(body) >= 2:
                self.board.cells.pop((body[0], body[1]), None)
        elif cmd_id in (31114, 31115, 31116):
            self.on_end(cmd_id)

    # ---- 自动发射 ----
    def maybe_shoot(self):
        """加锁包装：状态锁保证与 feed(recv 线程改棋盘) 串行，避免并发损坏 board/queue。
        实际决策逻辑在 _shoot_impl。异常隔离在调用方（mole.py 的 paopaolong_tick）处理。"""
        if not self.running or self.finished:
            return
        # ★ 状态锁：与 feed 的 handle 串行，杜绝并发读写共享状态（第四轮无响应修复）
        with self.lock:
            self._shoot_impl()

    def _shoot_impl(self):
        # 未启动发射 / 已结束，直接返回（避免 socket 失效后继续发包报 10038）
        if not self.running or self.finished:
            logger.debug(f"[诊断] _shoot_impl 静默返回：running={self.running} finished={self.finished}")
            return
        # ★ 等回包闸（2026-08-08）：上一发 31106 尚在等待结算回包（同 seq 的 on_7983/on_31108），
        #   本拍不决策、不发，避免用「尚未回包的旧棋盘」算下一发→新发散/失步修复。超时强制清闸防卡死。
        if self._await_seq is not None:
            if time.time() - self._await_since > AWAIT_RESP_TIMEOUT:
                logger.warning(f"[等回包闸] 等待 seq={self._await_seq} 超过 {AWAIT_RESP_TIMEOUT:.1f}s 无回包，"
                               f"强制清闸（防卡死）")
                self._await_seq = None
            else:
                logger.info(f"[等回包闸] 等待 seq：{self._await_seq} 结算回包，本拍跳过发射")
                return
        # ★ 落点绝对下限 death_floor：服务端权威死亡线 ButtomRowIndex（用户实测：落点 y < 它就 game over）。
        #   直接用 buttom_row_index（31111 下发），方向在 y 小侧，与 bot y 体系一致（y 小=下/炮口）。
        #   仅在已知且 >0 时启用（初始=0，与棋盘无冲突）；否则回退 0（炮口下方均合法）。
        #   注意：death_floor 是【硬下限】，best_shot/choose_gather_landing/_choose_bomb_target/bomb_target_override
        #   所有候选生成都须排除 ny < death_floor 的落点，否则服务端判负 31115。
        #   定义在函数开头，使炸弹分支 / 推进分支等所有路径都能引用（避免 UnboundLocalError）。
        death_floor = self.buttom_row_index if (self.buttom_row_index is not None and self.buttom_row_index > 0) else 0
        # ★ 残局停滞检测（2026-08-05）：本地棋盘已近清空（≤2 球，含 0）但 bot 仍持续发包或静默等待、
        #   服务端却不再回包（如 seq=41 后本地残留幽灵球/或已清空但服务端已通关不回 31114）→ 逻辑性卡死。
        #   此时主动判定通关退出，避免无限空转。注意：这是【逻辑停滞检测】，非 GIL 饥饿看门狗（后者已删除）。
        #   阈值：残球≤2 且 距上次回包 > STALL_TIMEOUT 秒（默认 6s，足够覆盖正常发射间隔+回包乱序）。
        #   刚收到回包（last_response_time 新，如正常等待 79A3/开局填盘）不触发，避免误判。
        if len(self.board.cells) <= 2 and (time.time() - self.last_response_time) > STALL_TIMEOUT:
            logger.warning(f"[残局停滞] 本地残球={len(self.board.cells)} 且 {time.time()-self.last_response_time:.1f}s 无服务端回包，"
                  f"判定本关已清/服务端停止回应，主动通关退出（避免卡死）")
            self.on_end(31114)
            return
        # 当前待射 = 预备队列队首（不弹出，发射时才 popleft）
        if not self.queue or not self.board.cells:
            if not self.board.cells and self._had_cells:
                # ★ 棋盘曾非空、现又被清空：本局已真通关（本地 cells 落点全消/悬空掉落），
                #   但服务端可能迟迟不发 31114（或根本不发）→ 残局停滞检测的 last_response_time
                #   被 handle 无条件刷新压制（见 1459 行），导致 bot 无限空转卡死。此处主动结束，
                #   不再静默等待服务端。等价于"本地清盘即通关"，与 31114 语义一致。
                logger.warning(f"[游戏结束] 本地棋盘已清空且曾有过球 → 主动 on_end(31114) 通关（队列剩 {len(self.queue)} 球，不等服务端 31114）")
                self.on_end(31114)
                return
            # 静默等待：① 队列空→等下一个 79A3 追加新球；② 开局等待 797E 填盘(cells 暂空、_had_cells=False)
            logger.debug(f"[诊断] _shoot_impl 静默返回：队列空={not self.queue} cells空={not self.board.cells} "
                           f"queue长={len(self.queue) if self.queue else 0} cells数={len(self.board.cells)}")
            return
        _t0 = time.time()   # ★ 分阶段计时诊断（2026-08-06 seq=39 卡死定位）：记录每阶段耗时，
        _stages = {}        #   任一阶段 >0.1s 即记 warning 落盘（mole.log），定位 daemon 线程卡死处。
        def _mark(name):
            nonlocal _t0
            dt = time.time() - _t0
            if dt > 0.1:
                logger.debug(f"[计时] _shoot_impl 阶段[{name}]耗时 {dt:.2f}s（疑似卡死点）")
            _stages[name] = dt
            _t0 = time.time()
        # ★ 每次决策前刷新顶排根节点数组（O(顶排长度)，无重计算），保证与当前棋盘一致
        #   （send_ball 写回落点、下降等都会改变顶排结构，on_797e/on_7983 也已刷新，此处兜底）。
        self.board.refresh_top_roots()
        _mark("refresh_top_roots")
        self.current = self.queue[0]   # 队列条目 (type, color)；type: 1普通球 2炸弹
        cur_type, color = self.current
        # ★ 顶层优化（2026-08-06，替代"认输"）：给每个顶排根标注 solvable——队列后续是否还有
        #   ≥need 个该色球足以把它凑齐消除。这是"确定性通关规划"的基石：bot 优先补 solvable 根，
        #   但不把暂时缺色的根当死根排挤（发射队列会由 79A3 持续追加新球，任何色最终会再来，见下轮）。
        #   future_colors 就地计算（当前球之后的全部球色，排除炸弹），避免引用函数后方才定义的同名变量。
        from collections import Counter as _C
        future_colors = [c for (t, c) in list(self.queue)[1:] if t != BOMB_PROP_TYPE]
        if future_colors is not None:
            _qcount = _C(future_colors)
            _have_cur = (color is not None)
            for _r in self.board.top_roots:
                _c = _r['color']
                # 当前这发若正好是根色，先扣掉它（补一根），剩余队列还得够 need-1
                _is_cur = (_have_cur and _c == color)
                _avail = _qcount.get(_c, 0) - (1 if _is_cur else 0)
                _r['solvable'] = _avail >= max(0, _r['need'] - (1 if _is_cur else 0))
        else:
            for _r in self.board.top_roots:
                _r['solvable'] = True
        now = time.time()
        if now - self.last_shot < SHOOT_INTERVAL:
            return
        # ── 炸弹分支：当前炮筒是炸弹，直接发落点（31106）炸 ──
        if cur_type == BOMB_PROP_TYPE:
            # ★ 状态机收尾：arms 已置位，现在队列滚到炸弹、真正发射 31106。
            #   发射成功后清除 bomb_armed，解锁后续救场/普通发射逻辑（否则会卡在等待态永不推进）。
            bomb_target = None
            # 优先用救场分支指定的落点 override（校验为合法空格：无球 + 不越木板）；
            # 否则自动选最多球。★ 炸弹只能落空格（用户 2026-08-05 铁律）。
            if self.bomb_target_override is not None:
                ox, oy = self.bomb_target_override
                # 校验基于净化棋盘（排除 shot_landed 幽灵球），与 _choose_bomb_target 一致
                served_b = {(x, y) for (x, y) in self.board.cells
                            if (x, y) not in self.shot_landed}
                # ★ 炸弹落点保护（2026-08-06 seq=34 根因）：override 落点必须【仍是空格】，
                #   即绝对不能在 shot_landed 里——armed 等待态推进球可能已落在同格（服务端已接收、
                #   该格在服务端变成有球）。旧校验用 served_b（排除 shot_landed）导致「被推进球占的格
                #   不在 served_b」反而被判合法→炸弹落已占格→31115。故额外要求 not in shot_landed。
                if ((ox, oy) not in self.shot_landed
                        and (ox, oy) not in served_b
                        and self.board.is_placeable(ox, oy)
                        and oy >= death_floor
                        and (self.board.wood_row is None or oy < self.board.wood_row)):
                    bomb_target = (ox, oy, sum(1 for (rx, ry) in cells_within_radius(ox, oy, BOMB_RADIUS)
                                                if (rx, ry) in served_b))
                else:
                    # override 落点已被推进球占用或非法 → 丢弃，回退到 _choose_bomb_target 重选
                    logger.warning(f"[炸弹落点] override ({ox},{oy}) 已被占用/非法"
                                   f"（in_shot_landed={(ox,oy) in self.shot_landed}），丢弃回退重选")
                self.bomb_target_override = None   # 一次性消费
            if bomb_target is None:
                bomb_target = self._choose_bomb_target()
            if bomb_target is not None:
                bx, by, bcnt = bomb_target
                logger.info(f"[提示] 当前炮筒为炸弹！落点：({bx},{by}) 可炸{bcnt}个")
                self.send_ball(bx, by, is_bomb=True)
                self.last_shot = now
                self.queue.popleft()  # 炸弹已发射，弹出
                self.current = self.queue[0] if self.queue else None
                self.bomb_armed = False   # ★ 退出等待态
                self.bomb_inflight = True  # ★ 进入在途态：等 7983 确认（防乱序回包期间重激活双炸）
                return
            # 无目标（棋盘空）→ 不应发生，消费掉避免卡死
            logger.info(f"[提示] 炸弹无可用目标，消费炸弹")
            self.queue.popleft()
            self.current = self.queue[0] if self.queue else None
            self.bomb_armed = False
            self.bomb_inflight = True  # 在途：等 7983 确认
            return
        # ── bomb_armed 等待态：已发 31112 激活炸弹，但炸弹还在队列里没滚到队首（cur_type 仍为普通球）。
        #   ★ 此期间【禁止进入任何救场分支重发 31112】（连发多个 31112 会冲乱服务端炸弹模式、且
        #   bomb_count 被 31104 回包反复覆盖导致死循环）。但仍允许【正常发射队首普通球】推进队列，
        #   使炸弹尽快滚到队首、下一拍 cur_type==2 分支真正发射 31106 引爆。
        #   故下方两个救场分支均被 `if not self.bomb_armed` 守卫；armed 态下只走普通球发射逻辑。
        #   若 armed 态 best_shot 仍返回 None（极少见，fb 兜底也空），则只等待、不救场（炸弹即将就位）。
        # ★ 棋盘真实最底有球行（max y，已排除写回幽灵球的 served 口径）：
        #   用于判定「球是否已堆到木板底排 y=14、底排全满、普通球无合法落点」，这种死局前兆
        #   必须由炸弹炸开。
        served_cells = [(x, y) for (x, y) in self.board.cells if (x, y) not in self.shot_landed]
        served = {p: c for p, c in self.board.cells.items() if p not in self.shot_landed}
        served_max_y = max((y for (_, y) in served_cells), default=0)
        abs_floor = death_floor
        best, cnt = self.board.best_shot(color, abs_floor=abs_floor, allow_same_row=self.descended, excluded=self.shot_landed, visible_top=self.visible_top, cells=served)
        _mark("best_shot")
        if best is None:
            # 连底排兜底候选都空（= 底排全满/所有空格邻居 unsupported，真死局前兆）。
            # ★ 关键修正（第二十九轮实测）：served_min_y>=14 条件过于严格——
            #   本局 y=11 残留 1 个孤立球使 served_min_y=11 永不到 14，但 y=12~14 已密实到
            #   所有空格邻居指向 y=15(木板)→is_supported=False→best_shot 永远 None→无限死等判负。
            #   正确判定：best=None（常规候选确实全空）+ served_max_y>=14（球已堆到木板底排）
            #   + 持有炸弹 → 直接发炸弹救场。_choose_bomb_target 自带可见行过滤防越界。
            #   served_min_y>=14 不再要求（"只剩底排一行"太理想化，实际常有上层残球卡住 min_y）。
            stuck_at_bottom = (served_max_y >= 14)
            # ★ 炸弹救场触发：stuck_at_bottom(best 全空且球堆到木板底排) + 死亡线已下移(death_floor>=2)
            #   即判负线已逼近、确属真死局才动用炸弹。death_floor>=2 而非更严，避免 death_floor=2 时
            #   该炸不炸→持续空转→31115（2026-08-06 实测本局 death_floor=2 即死，门槛4放过导致判负）。
            # ★ 2026-08-06 本轮实测：death_floor 从 0→1 后不再增长，但 board 已从 y=7 填满到 y=1（14行全满）
            #   → `death_floor >= 2` 永不满足 → 炸弹永不触发 → 71 球 31115。降至 >=1：死亡线只要动过一次，
            #   结合 stuck_at_bottom(球堆到木板顶排 best=None) 已是足够强的真死局信号，无需等 death_floor 再降。
            if not self.bomb_armed and not self.bomb_inflight and stuck_at_bottom and death_floor >= 1 and self.bomb_count > 0:
                tgt = self._choose_bomb_target()
                _mark("_choose_bomb_target")
                if tgt is not None:
                    self.bomb_target_override = (tgt[0], tgt[1])
                    self.use_bomb_prop()   # 发 31112 激活炸弹，下拍 cur_type==2 分支发 31106 炸
                    self.bomb_armed = True   # ★ 进入等待态：本周期内禁止重发 31112
                    self.last_shot = now
                    logger.warning(f"[炸弹救场] best_shot 候选全空且球已堆到木板底排(served_max_y>=14)，"
                          f"已激活炸弹，下拍将炸落点=({tgt[0]},{tgt[1]}) 可炸={tgt[2]}个 剩余炸弹={self.bomb_count}")
                    # ★ 等待态推进：炸弹已激活，但还在队列里没滚到队首。必须【立即发射队首普通球】
                    #   把炸弹往前推一格，否则队列永远滚不到炸弹 → 炸弹永不发射 → 卡死判负。
                    #   （该普通球本来 best=None 没落点，但 armed 态本就只求推进队列，发队首普通
                    #   球落到哪里都行，下一拍 cur_type==2 走炸弹分支真正引爆。）
                    self._advance_queue_normal(now)
                    _mark("_advance_queue_normal[stuck]")
                    return
                else:
                    # ★ 致命静默卡死修复（第五十三轮）：_choose_bomb_target 返回 None（顶排密实、
                    #   半径2内覆盖不足、或所有候选被 filtered）时，原代码会穿透到下方 1097 行
                    #   静默 return → 每拍 best=None→tgt=None→静默 return 永久空转 = 用户感知的
                    #   "游戏卡死"（日志无任何结尾输出）。必须打印诊断并退化为「顶排兜底落点推进」，
                    #   让游戏继续（不浪费炸弹、不干等），可能凑消除或暴露真正死局走向 31115。
                    logger.warning(f"[炸弹救场] _choose_bomb_target 返回 None（顶排密实/半径2覆盖不足），"
                          f"不静默空转，改用顶排兜底落点强制推进 剩余炸弹={self.bomb_count}")
                    self._advance_queue_normal(now)
                    return
            # ★ bomb_armed 等待态：炸弹已激活、在队列等待滚到队首。此时必须持续发射队首普通球
            #   推进队列，绝不能干等（否则炸弹永不就位、队列停滞、下降累积 → 判负）。
            #   每拍发队首普通球，直到队列前方清出炸弹(cur_type==2)由上方炸弹分支真正发射 31106。
            if self.bomb_armed:
                logger.info(f"[炸弹等待] 炸弹已激活，发射队首普通球推进队列（剩余炸弹：{self.bomb_count}）")
                self._advance_queue_normal(now)
                return
            # 未 armed、且触发不了救场（无炸弹/未堆到木板底排）→ 本拍不发射，等下一拍棋盘变化
            # ★ 修复14（2026-08-06 用户"永久卡死空等"根因）：best is None 且【无炸弹可救场】
            #   （bomb_count==0 或 armed/inflated 中）→ 旧逻辑"本拍不发射等下一拍"会无限空转
            #   （判负线还在下降、球却一个不发 → 既不判负也不推进 → 永久卡死）。
            #   出路：用 candidate_landings(allow_top_row=True) 找【贴着残球群的最靠上空格】强制
            #   普通球推进（即便凑不出消除，也能推动游戏走向正常结束：等下降/凑消/判负，
            #   而非 daemon 线程空转卡死）。找不到任何空格才主动判负退出（兜底防死循环）。
            if not self.bomb_armed and not self.bomb_inflight:
                cap = self.board.wood_row - 1 if self.board.wood_row is not None else None
                fb = [(x, y) for (x, y) in self.board.candidate_landings(cells=served, allow_top_row=True)
                      if (x, y) not in self.shot_landed]
                if fb:
                    # 优先最靠上(y最大)贴球群、x 最小，让球往残球方向聚/推，远离炮口侧空等
                    best = max(fb, key=lambda p: (p[1], -p[0]))
                    logger.warning(f"[死局推进] best 全空且无炸弹，强制落点({best})推进（不空等）")
                    self.send_ball(best[0], best[1])
                    self.last_shot = now
                    self.queue.popleft()
                    self.current = self.queue[0] if self.queue else None
                    return
                else:
                    # 连候选空格都没有 → 真·无解，主动判负退出，避免 daemon 永久空转卡死
                    logger.warning(f"[死局] best 全空、无炸弹、无候选空格，主动判负退出（防卡死）")
                    self.on_end(31115)
                    return
            logger.info(f"[提示] best_shot 候选全空（底排可能全满/死局），本拍不发射，等下一拍")
            return
        # 优先能消除的已由 best_shot 处理；cnt>=3 直接发普通球消除
        if cnt >= 3:
            # ★ 落点球会被消除（31107 同色消除含落点球本身），本地绝不写回，避免幽灵球污染棋盘
            # ★ 即时消除：落点球被消除、格变空，绝不入 shot_landed（否则永久误判占用→best_shot 全空→误炸）
            # ★ 连续失步修复避让（2026-08-08）：若上一拍发生真正失步修复(last_rf_pos 指向被补录占位球)、
            #   且本次又走 cnt>=3 即时消除(潜在失步)路径、且 best 恰好落在【该失步球下方】(y 更小=更靠死亡线)，
            #   则改在其【左右】邻格落，打破"失步→下方补→又失步→继续下堆"逼近 31115 的链。
            if self.last_rf_pos is not None and best is not None:
                px, py = self.last_rf_pos
                below = {(x, y) for (x, y) in neighbors(px, py) if y < py}
                sides = {(x, y) for (x, y) in neighbors(px, py) if x != px and y == py}
                if best in below:
                    side_cands = [s for s in sides
                                  if self.board.is_placeable(*s) and s not in self.board.cells
                                  and s not in self.shot_landed and s[1] >= death_floor
                                  and (self.board.wood_row is None or s[1] < self.board.wood_row)
                                  and self.board.is_supported(*s, cells=served)]
                    if side_cands:
                        # 优先在失步球左右合法 supported 空格落（即便不能立消，也避免下方逼近死亡线）
                        best = max(side_cands, key=lambda p: (p[1], -p[0]))
                        cnt = 0
                        logger.warning(f"[失步避让] 落点原在失步球({px},{py})下方→改落其左右({best})（断链防下堆）")
                    else:
                        # 左右无合法空格：重算排除下方，让 best_shot 选其他非下方邻格
                        avoid = set(self.shot_landed) | below
                        best2, cnt2 = self.board.best_shot(
                            color, abs_floor=abs_floor, allow_same_row=self.descended,
                            excluded=avoid, visible_top=self.visible_top, cells=served)
                        if best2 is not None and best2 not in below:
                            logger.warning(f"[失步避让] 失步球左右无空格，改选非下方落点({best2})")
                            best, cnt = best2, cnt2
                        else:
                            logger.warning(f"[失步避让] 无避让空间，维持原落点({best})")
            self.send_ball(best[0], best[1], record=(cnt >= 3), track_landed=(cnt >= 3))
            self.last_shot = now
            self.queue.popleft()
            self.current = self.queue[0] if self.queue else None
            return
        # ★ 残局顶排残球炸弹救场（2026-08-06 本轮用户"y=14 只剩 2 个绿球就通关"根因）：
        #   当棋盘只剩少量残球且都堆在高位顶排(y>=13)、best_shot 又【无法立即消除】(cnt<3)时，
        #   bot 会一直走下方 cnt<3 归位/空转兜底，把球往 y=13/顶排堆——若残球分散凑不出 3 连，
        #   永远到不了消除、也进不去上方 best is None 的炸弹守卫 → 越堆越糟 → 31115。
        #   此时炸弹是【唯一正解】：半径2 直接炸掉顶排残球即通关。故主动用 _choose_bomb_target
        #   (allow_top_row=True) 选顶排空格落炸弹炸残球，不必等 best 真正 None 或空转 8 发。
        #   门槛保守：残球数≤5 且 最高有球行>=13，避免正常局误炸。
        #   ★ 死亡线已下移(death_floor>=2)才动用炸弹——避免 death_floor 较低、其实还有希望
        #   凑消的残局浪费唯一道具；但门槛不过高（>=3 放过 death_floor=2 死局）。
        #   仍要求【顶排根全部 need>=2（全是孤球、堆普通球永远凑不齐3连）】才炸，
        #   若顶排还有 need<=1 可消根则保留炸弹不炸。
        if (not self.bomb_armed and not self.bomb_inflight and self.bomb_count > 0
                and len(served) <= 5 and served_max_y >= 13 and death_floor >= 1
                and self.board.top_roots and all(r['need'] >= 2 for r in self.board.top_roots)):
            tgt = self._choose_bomb_target()
            _mark("_choose_bomb_target[residual]")
            if tgt is not None:
                self.bomb_target_override = (tgt[0], tgt[1])
                self.use_bomb_prop()
                self.bomb_armed = True
                self.last_shot = now
                logger.warning(f"[炸弹救场] 残局顶排残球(剩{len(served)}球,max_y={served_max_y})且本拍无法立即消除，"
                      f"已激活炸弹，下拍将炸落点=({tgt[0]},{tgt[1]}) 可炸={tgt[2]}个 剩余炸弹={self.bomb_count}")
                self._advance_queue_normal(now)  # 等待态推进：发队首普通球把炸弹往前推
                _mark("_advance_queue_normal[residual]")
                return
            else:
                logger.warning(f"[炸弹救场] 残局顶排残球但 _choose_bomb_target 返回 None（覆盖不足），"
                      f"不浪费炸弹，继续归位推进 剩余炸弹={self.bomb_count}")
        # cnt<3：普通球落下去也消不掉。★ 炸弹使用纪律（用户明确）：炸弹只在【真正走投无路】
        #   时才用——即 best_shot 连底排兜底候选都给不出(best is None，已在上方 stuck_at_bottom
        #   分支处理，用 _choose_bomb_target 选「半径内最多球」的满排落点炸)。
        # ★ 第三十四轮修复（重要）：【残球极少(≤3个孤球)时绝不用炸弹】。两次实测均在此分支
        #   触发：本地 served=1~2 个孤球 → 选 max(served,key=y) 贴木板落点(如 (5,14)/(7,14)) 炸；
        #   但游戏内炸弹落木板底排 y=14 的孤球【不产生任何 7983 消除包】(服务端视为无效落点)，
        #   直接 30006→31115 失败。孤球本就只炸 1~2 个、无任何收益，且贴木板落点易无效，纯浪费
        #   唯一救命道具。故此处 cnt<3 一律照发普通球推进/堆积（保留炸弹），由上方 best is None
        #   满排死局分支统一裁决炸弹。残球极少时普通球推进仍可凑消除或等队列同色球/下降过关。
        #   （若该局真是「满排死局」，best 会为 None 走到上方分支，不会漏救场。）
        # ★ 第三十五轮残局归位：cnt<3 无即时消除时，把球送到【最近同色球旁空位】(有同色)/
        #   或【最靠下空白位 y=14 附近】(无同色)，而非远离球群的空格——让同色球聚拢，等后续
        #   队列同色球/下降凑≥3消除，避免把球乱丢到远处堆高判负线。
        next_color = None
        if len(self.queue) >= 2 and self.queue[1][0] != BOMB_PROP_TYPE:
            next_color = self.queue[1][1]
        # ★ 2026-08-05 队列前瞻：future_colors = 当前球之后的队列颜色（排除炸弹类型），
        #   传给 choose_gather_landing 做"按队列颜色分布规划落点"（不只是当前球）。
        future_colors = [c for (t, c) in list(self.queue)[1:] if t != BOMB_PROP_TYPE]
        # ★ 炸弹纪律（用户关键反馈"炸弹使用还有有问题"）：上一轮曾在此处加"独立门槛(空转≥5+顶排满≥7)"
        #   主动炸，但实测证明门槛过松——残局顶排开局就满10列、空转交替到5/12 即误炸唯一炸弹，炸完
        #   游戏结束无清盘。故【彻底删除该独立误炸块】，炸弹只走上方 best_shot 全空 + 球堆到木板底排
        #   (served_max_y>=14) 的真死局分支(stuck_at_bottom)，确保：
        #   ① 能正常消除的交替局(best 不返回 None)永不浪费炸弹；
        #   ② 真死局(best=None 且球已堆到木板底排)才炸，符合"炸弹只在真正走投无路时用"的纪律。
        # ★ 连续消除=0 兜底（2026-08-05，本局 seq=44~55 实测）：当最近 ZERO_ELIM_LIMIT 发连续 7983
        #   消除=0，说明残局归位已陷入「簇记忆自我强化」空转（同色球摊在角落分散孤球、永远凑不出
        #   ≥3）。此时放弃 choose_gather_landing 偏好评分，清空簇记忆，改用「顶排缺球列下方/最靠下
        #   合法落点」强制推进——让游戏尽快走向正常结束（31115 判负或等下降过关）。注意：仅当确实连续空转才触发，正常消除中途不干扰。
        if len(self.recent_empty) >= EMPTY_WIN and sum(1 for e in self.recent_empty if e) >= WIN_EMPTY_LIMIT:
            empty_cnt = sum(1 for e in self.recent_empty if e)
            # ★ 空转死局炸弹救场（2026-08-05 本轮 seq=32~39 实测）：窗口内空转≥8 已是真死局信号
            #   （bot 连续 8 发消除=0，归位+空转兜底都救不活）。此时若持有炸弹且未 armed，直接炸开
            #   残局，不必等 served_max_y>=14（本局顶排球被反复消除清掉→served_max_y 常<14→
            #   stuck_at_bottom 分支永不进→炸弹永不触发→持续空转填球→判负）。
            #   门槛 WIN_EMPTY_LIMIT=8 足够保守，不会在交替局(空转≤7)误炸（前次"空转5/12就炸"被批的教训）。
            #   ★ 死亡线已下移(death_floor>=1)即动用炸弹——避免 death_floor=1 时该炸不炸持续空转
            #   填球→31115（2026-08-06 本轮实测：death_floor 最高仅到 1，board 已从 y=7 填满到 y=1 共 14 行、
            #   71 cells → 31115，而炸弹从未触发）。>=1 即死亡线动过一次，结合空转≥8+堆高≥13 已是可靠死局信号。
            #   仍保留 WIN_EMPTY_LIMIT 空转门槛(10)防止健康局误炸。
            # ★ 2026-08-06 seq=74~79 根因(B)：全局 WIN_EMPTY_LIMIT=10 过严——本局空转累计到
            #   8/12 时球已堆到木板顶排(served_max_y=14)却未达 10 门槛 → 炸弹分支不触发 → 继续归位
            #   空转填球到 best=None → stuck 分支才炸，但此时下方已堆跨多排散球、半径2清不掉→必败。
            #   本地门槛降为 8，并加 served_max_y>=13 守卫（球已堆高才炸），既救本局又不放松早期
            #   纪律（低空转、球未堆高时不误炸，保留全局 WIN_EMPTY_LIMIT=10 的保守兜底意图）。
            if (not self.bomb_armed and not self.bomb_inflight and self.bomb_count > 0
                    and death_floor >= 1 and served_max_y >= 13 and empty_cnt >= 8):
                tgt = self._choose_bomb_target()
                _mark("_choose_bomb_target")
                if tgt is not None:
                    self.bomb_target_override = (tgt[0], tgt[1])
                    self.use_bomb_prop()   # 发 31112 激活炸弹
                    self.bomb_armed = True
                    self.last_shot = now
                    logger.warning(f"[炸弹救场] 空转死局(窗口{empty_cnt}/{len(self.recent_empty)}消除=0)且持有炸弹，"
                          f"已激活炸弹，下拍将炸落点=({tgt[0]},{tgt[1]}) 可炸={tgt[2]}个 剩余炸弹={self.bomb_count}")
                    self._advance_queue_normal(now)  # 等待态推进：发队首普通球把炸弹往前推
                    _mark("_advance_queue_normal[empty]")
                    return
                else:
                    logger.warning(f"[炸弹救场] 空转死局但 _choose_bomb_target 返回 None（覆盖不足），"
                          f"不浪费炸弹，继续空转兜底推进 剩余炸弹={self.bomb_count}")
            # ★ 2026-08-07 空转兜底下仍须优先【顶排同色根】：残局连续空转≥10 进入本块会提前 return，
            #   跳过下方 top_row_chain_landing → 同色球全落 (0,13)/(0,12) 等远离顶排孤球的低位，
            #   使顶排孤球(如 (9,14) 红)永远等不到同色来补→堆死判负（用户 1.txt seq=76/77 实测）。
            #   空转只破簇记忆自激，不应放弃顶排根这一最优落点。故进入兜底前先试 top_row_chain_landing：
            #   命中即落根（贴顶排孤球/凑色段），不命中再走原通用兜底。
            chain_l, chain_imm = self.board.top_row_chain_landing(color, excluded=self.shot_landed, next_color=next_color)
            if chain_l is not None:
                self.gather_cluster.clear()
                logger.debug(f"[空转兜底·顶排根] 当前球{COLOR_NAME.get(color)}命中顶排根，落点({chain_l})发射"
                      + ("（本拍即消3连）" if chain_imm else "（本拍不消，待下一同色凑3连）")
                      + (f"（保留炸弹待死局救场）" if self.bomb_count <= 0 else ""))
                self.send_ball(chain_l[0], chain_l[1])
                self.last_shot = now
                self.queue.popleft()
                self.current = self.queue[0] if self.queue else None
                return
            logger.debug(f"[空转兜底] 最近 {len(self.recent_empty)} 发里 {empty_cnt} 发消除=0，放弃归位偏好，清空簇记忆并强制推进")
            self.gather_cluster.clear()
            cap = self.board.wood_row - 1 if self.board.wood_row is not None else None
            # ★ 2026-08-05 终极修复：空转兜底候选【禁止比现存最底排球更靠下】(ny <= min_y)，
            #   否则会落到 min_y-1 炮口侧 y=7，越堆越靠近判负线（本次日志 seq=18~32 实测）。
            #   ⚠️ 绝不"放宽回退用全量候选"——那会让 y=7 重新进入候选（旧版就栽在这）。
            #   严格过滤后若 fb 为空（残局球群塌缩、合法空格都≤min_y），则回退到
            #   choose_gather_landing 的合法集（它本身已排除 min_y 以下）+ 顶排空格兜底，
            #   绝不直接发炮口侧 (0, m-1)。
            # ★ 2026-08-05 终极铁律补充（本轮 seq=42~50 实测）：空转兜底候选【必须排除顶排 y=cap】。
            #   旧版 `p[1] <= cap` 放行顶排，导致 fb 里 max(y最大) 永远选 y=14 顶排空格
            #   （如 (1,14)(2,14)(5,14)...），把顶排堆满、反而让 y=12 变空→球群塌缩→判负。
            #   残局归位铁律"不主动往顶排填"对空转兜底同样生效：只许填顶排【下方】空格。
            # ★ 2026-08-06 修正：空转兜底落点下界改用 death_floor（判负线），不再用 fb_miny(最底排球)。
            #   旧版 p[1] > fb_miny 禁止往最底排下方落，会让悬浮塔只长高顶到木板(seq=22 根因)。
            #   且选择由「最靠下(min y)」改回「最靠上(max y)」(2026-08-07)：本游戏判负线在最下方，
            #   球越靠下(y越小)越危险，故空转兜底也应优先贴着球群【最靠上】的合法 supported 落点
            #   (如初始满盘下方 y=6)，而非沉到 death_floor 侧 y=0。death_floor 收紧时 fb 只剩上方候选、
            #   最靠上≡贴顶排，与旧铁律一致、不冲突。
            fb = [p for p in self.board.candidate_landings(cells=served)
                  if p not in self.shot_landed
                  and (cap is None or p[1] < cap)
                  and (p[1] >= death_floor)]
            if fb:
                best = max(fb, key=lambda p: (p[1], -p[0]))  # 最靠上(y最大)、x最小：贴球群、远离死亡线
            else:
                # 严格过滤后 fb 仍空（残局球群塌缩、合法空格都≤min_y 或都在顶排）：
                # 回退①：choose_gather_landing 的合法集（本身已排除 min_y 以下、且排除了顶排，最稳）。
                # ★ 禁止回退②填顶排空格 (x,cap)！残局铁律"不主动往顶排填"对空转兜底同样生效，
                #   填顶排会破坏顶排结构、且与"炸弹救场"的 served_max_y>=14 信号打架（本次 seq=34~36
                #   实测：fb 空→回退②填 (0,14)(2,14)(5,14)→顶排被填满但 best 仍为 None 进不去炸弹分支
                #   → 继续空转填满顶排→判负）。顶排空格绝不作为空转兜底落点。
                # 仍无解：保留当前 color 让游戏裁决/下降（不主动选判负线侧、也不填顶排）。
                fb_gather = self.board.choose_gather_landing(
                    color, excluded=self.shot_landed, next_color=next_color, future_colors=future_colors, death_floor=death_floor, cells=served)
                if fb_gather is not None:
                    best = fb_gather
                else:
                    m = self.board.min_y()
                    best = (0, m - 1 if m < (self.board.wood_row - 1) else self.board.wood_row - 2)
            logger.info(f"[提示] 当前球{COLOR_NAME.get(color)}无≥3消除落点，"
                  + f"空转兜底落点({best})发射"
                  + (f"（无炸弹，靠普通球推进）" if self.bomb_count <= 0 else "（保留炸弹待死局救场）"))
            self.send_ball(best[0], best[1])
            self.last_shot = now
            self.queue.popleft()
            self.current = self.queue[0] if self.queue else None
            return
        # ★ 顶排连锁借消除（2026-08-05 用户优化，最高优先）：若顶排(y=14)出现单色孤球且当前球
        #   色==该孤球色，直接落到孤球旁空位凑≥3消除它→其下整片连锁悬空→31108 一波清。
        #   这比通用归位/堆高判负线高明得多，故放在 choose_gather_landing 之前优先裁决。
        chain, chain_immediate = self.board.top_row_chain_landing(color, excluded=self.shot_landed, next_color=next_color)
        _mark("top_row_chain_landing")
        prefer_pos = None
        if chain is not None:
            best = chain
            gather = chain   # 复用后续栅栏/簇记忆/日志路径；不再调 choose_gather_landing
            # 命中哪个根节点（调试/可视化）
            hit = next((r for r in self.board.top_roots if r['color'] == color and r['need'] <= (1 if chain_immediate else 2)), None)
            seg_txt = ""
            if hit:
                seg_txt = "段" + "+".join(str(cx) for (cx, _) in hit['cells'])
            if chain_immediate:
                logger.debug(f"[顶排连锁] 当前球{COLOR_NAME.get(color)}命中顶排可凑色根节点"
                      + (f"({seg_txt})" if seg_txt else "")
                      + f"，落点({best})发射（本拍即消3连）"
                      + (f"（保留炸弹待死局救场）" if self.bomb_count <= 0 else ""))
            else:
                logger.debug(f"[顶排规划归位] 当前球{COLOR_NAME.get(color)}补顶排孤球(段{seg_txt})成2连，"
                      + f"落点({best})发射（本拍不消，待下一同色凑3连）"
                      + (f"（保留炸弹待死局救场）" if self.bomb_count <= 0 else ""))
        else:
            # 无根节点可本拍凑消时，打印当前顶排根节点概况（便于观察规划进度）
            if self.board.top_roots:
                summary = ",".join(
                    f"{COLOR_NAME.get(r['color'])}x{len(r['cells'])}需{r['need']}"
                    for r in self.board.top_roots)
                # ★ 2026-08-06 方向1：提示是否有"异色根待铺路"——即 need>=1 且根色≠当前球，
                #   归位时会优先贴该根铺路（top_root_pave 维度），便于观察 bot 是否在为未来同色预铺。
                pave_roots = [r for r in self.board.top_roots
                              if r['need'] >= 1 and r['color'] != color]
                pave_txt = ""
                if pave_roots:
                    pave_txt = "（为" + "/".join(
                        f"{COLOR_NAME.get(r['color'])}" for r in pave_roots) + "根铺路）"
                logger.debug(f"[顶排规划] 根节点({len(self.board.top_roots)}): {summary}；"
                      + f"当前球{COLOR_NAME.get(color)}未命中，走归位{pave_txt}")
            # 簇记忆：若本色已有归位簇锚点（上一发同色归位落点），优先堆到同一簇（第四十七轮）
            prefer_pos = self.gather_cluster.get(color)
            # ★ 防御：锚点可能已被消除/坠落移走（cleanup 偶发遗漏或 31108 重定位偏差），
            #   失效锚点会让 prefer_hit 永远算不出 → 簇记忆形同虚设，且可能干扰评分。
            #   若锚点不在 cells，立即清除，prefer 退化为 None 走普通聚合（第四十七轮修）
            if prefer_pos is not None and prefer_pos not in self.board.cells:
                self.gather_cluster.pop(color, None)
                prefer_pos = None
            gather = self.board.choose_gather_landing(color, excluded=self.shot_landed, next_color=next_color, prefer_pos=prefer_pos, future_colors=future_colors, death_floor=death_floor, cells=served)
            _mark("choose_gather_landing")
        if gather is not None:
            best = gather
            # ★ 发射前合法性栅栏（第四十七轮止血）：choose_gather_landing 的 pool 已全部过
            #   is_supported+is_placeable 校验，但本地棋盘可能因 31108 重定位偏差而与服务端
            #   不一致（某支撑球本地在、服务端已消）→ 本地判合法、服务端判负(31115)。
            #   此处再核对一次 best 的严格合法性，非法则回退到 pool 内【最靠下】合法点；
            #   若 pool 为空则保留 best（让服务端裁决，但至少不主动选明显悬空点）。
            # ★ bot 直接发包，合法性只看 is_placeable + 不越木板顶界 + 非已占格（不查 is_supported，
            #   悬空位服务端自行判定，bot 不替服务端操心）。
            if not (self.board.is_placeable(best[0], best[1])
                    and best[1] < self.board.wood_row
                    and best not in self.shot_landed):
                cap = self.board.wood_row - 1 if self.board.wood_row is not None else None
                fb = [p for p in self.board.candidate_landings(cells=served)
                      if p not in self.shot_landed
                      and (cap is None or p[1] < cap)]  # ★ 排除顶排，残局归位不填顶排
                if fb:
                    # ★ 2026-08-05 终极修复（栅栏回退方向）：选【最靠上(y最大)】且
                    #   【不比现存最底排球更靠下】的合法点（ny > miny）。
                    miny = self.board.min_y()
                    safe = [p for p in fb if p[1] > miny]
                    pool_fb = safe if safe else fb
                    best = max(pool_fb, key=lambda p: (p[1], -p[0]))  # 最靠上(y最大)、x最小
                    logger.warning(f"[栅栏] 归位点非法，回退到合法最靠上 {best}")
            # 簇记忆：落点即记为该色簇锚点（第四十七轮）。无论连通块大小：
            #   - 若落点贴住已有同色(blk>=2)，锚点=聚合簇，后续同色继续堆这必消；
            #   - 若落点孤立(blk=1)，锚点=此新球，下一发同色贴它即成2、再下一发成3。
            #   下一发同色经 prefer_pos 命中最高优先级，强制堆同一簇，根治"同色球摊薄"死局。
            #   锚点若被消除/坠落移走，由 _cleanup_gather_clusters 清除。
            self.gather_cluster[color] = best
        logger.info(f"[提示] 当前球{COLOR_NAME.get(color)}无≥3消除落点，"
              + ("残局归位" if gather is not None else "兜底")
              + f"落点({best})发射"
              + (f"（无炸弹，靠普通球推进）" if self.bomb_count <= 0 else "（保留炸弹待死局救场）")
              + (f"（聚合下一发{COLOR_NAME.get(next_color)}）" if gather is not None and next_color is not None else "")
              + (f"（同色簇{gather}）" if gather is not None and prefer_pos is not None else ""))
        # 兜底发普通球（cnt<3 一律照发）
        self.send_ball(best[0], best[1])
        self.last_shot = now
        self.queue.popleft()
        self.current = self.queue[0] if self.queue else None

    def _advance_queue_normal(self, now):
        """炸弹等待态/救场后立即推进：把当前队首普通球发出去（落点用 choose_gather_landing
        兜底，或 best_shot 的最靠下候选），sole 目的为把炸弹往前推一格，不改变救场状态。"""
        if not self.queue or not self.board.cells:
            return
        _a0 = time.time()
        cur_type, color = self.current
        death_floor = self.buttom_row_index if (self.buttom_row_index is not None and self.buttom_row_index > 0) else 0
        # 防御：若队首恰好已经是炸弹(cur_type==2)，不应走到这里（上方炸弹分支已处理）；
        # 但极端情况下仍走普通发射逻辑会出错，故此处再次校验。
        if cur_type == BOMB_PROP_TYPE:
            return
        # 选一个合法落点推进：优先同色归位，否则用 best_shot 当前 color 的最靠下候选
        adv_next = None
        if len(self.queue) >= 2 and self.queue[1][0] != BOMB_PROP_TYPE:
            adv_next = self.queue[1][1]
        adv_future = [c for (t, c) in list(self.queue)[1:] if t != BOMB_PROP_TYPE]
        adv_served = {p: c for p, c in self.board.cells.items() if p not in self.shot_landed}
        # ★ 炸弹落点保护（2026-08-06 seq=34 实测 31115 根因）：armed 等待态下，炸弹落点
        #   bomb_target_override 已在激活那拍定死（如 (1,9)）。本拍推进球若落在同一格，
        #   服务端会先接收推进球→该格在服务端变成【有球】；下一拍炸弹分支直接用 override
        #   的 (1,9) 落炸弹→服务端视角落点已占→31115。故 armed 推进必须把炸弹落点从所有
        #   候选集排除，让推进球落到【别的】空格，炸弹落点留给炸弹独占。
        bomb_reserved = set()
        # ★ 2026-08-06 seq=79 根因修复：原条件 `self.bomb_armed and ...` 在某些调用路径下
        #   （stuck/residual 救场分支先设 override、再 _advance_queue_normal 占位推进）因
        #   状态机时序导致 bomb_reserved 偶发为空，使占位推进球压中 override 点 (3,14) →
        #   该点进 shot_landed → 下一拍炸弹分支 in_shot_landed=True 丢弃 override、炸弹落点
        #   偏离最优解、且污染 served 视图。改为「override 非空即独占」，不依赖 armed 标志
        #   （override 由 on_797e/on_end 跨关清空，本地残留风险已隔离）。
        if self.bomb_target_override is not None:
            bomb_reserved.add(self.bomb_target_override)
        gather = self.board.choose_gather_landing(color, excluded=self.shot_landed | bomb_reserved, next_color=adv_next, future_colors=adv_future, death_floor=death_floor, cells=adv_served)
        _ad = time.time() - _a0
        if _ad > 0.1:
            logger.debug(f"[计时] _advance_queue_normal.choose_gather_landing 耗时 {_ad:.2f}s")
        if gather is not None:
            pt = gather
            tag = "残局归位"
        else:
            # best_shot 已返回 None，找合法落点强推（炸弹等待态只为推进队列）。
            # ★ 残局归位铁律：普通/兜底落点【不主动填顶排 y=cap】，优先 candidate_landings
            #   （本身已排除顶排、按 is_supported 从下往上堆）。仅当 candidate_landings 全空
            #   （残局球群塌缩到顶排附近、下方无合法空格）才用顶排空格作最后兜底。
            cap = (self.board.wood_row - 1) if self.board.wood_row is not None else None
            cand = [(x, y) for (x, y) in self.board.candidate_landings(cells=adv_served)
                    if (x, y) not in self.shot_landed
                    and (x, y) not in bomb_reserved]
            if not cand and cap is not None:
                # ★ 仅当常规候选全空才退顶排（最后兜底，避免常态往顶排堆致球群塌缩判负）
                cand = [(x, cap) for x in range(10)
                        if (x, cap) not in adv_served
                        and (x, cap) not in self.shot_landed
                        and self.board.is_placeable(x, cap)]
            if cand:
                pt = max(cand, key=lambda p: (p[1], -p[0]))
                tag = "兜底推进"
            else:
                pt = None
                tag = "无落点"
        if pt is None:
            # ★ 炸弹等待态逃生通道（第三十六轮实测死锁修复，第三十七轮修正）：
            #   当前所有 supported 落点都空（残球极少、空格邻居全 unsupported），炸弹卡在队列第2位
            #   需队首普通球先发出去才能滚到队首引爆。
            #   ★ 第三十七轮修正：候选必须基于【真实球 served】而非 self.board.cells！
            #      self.board.cells 含 bot 自己发射的消除0球（send_ball 写回），下降/掉落后这些球
            #      可能已被服务端清除（幽灵球），但本地未同步移除 → 用 cells 枚举会把幽灵球邻居
            #      当占用、且其坐标在 shot_landed 里 → forced 空集 → 仍死锁。故改用 served
            #      （cells 排除 shot_landed，= 服务端原生球），其邻居空格才是真空格。
            #   ★ 逃生通道【不排除 shot_landed】：推进落点落哪都行（炸弹下一拍引爆），服务端真实
            #      空位即可，即便该坐标曾被 bot 发射过（幽灵已清）。只要求 is_placeable 且
            #      y<wood_row(不越木板行，落点顶界=顶排 wood_row-1)。不限制 visible_top（贴真实球群
            #      即可落，服务端全关消除，与屏幕可见窗口无关）。落点 unsupported 无所谓。
            served_cells = [(x, y) for (x, y) in self.board.cells
                            if (x, y) not in self.shot_landed]
            forced = set()
            for (x, y) in served_cells:
                for nx, ny in neighbors(x, y):
                    if (nx, ny) in self.board.cells:
                        continue
                    if not self.board.is_placeable(nx, ny):
                        continue
                    if self.board.wood_row is not None and ny >= self.board.wood_row:
                        continue
                    if (nx, ny) in bomb_reserved:
                        continue
                    forced.add((nx, ny))
            if forced:
                # 优先最贴真实球群（邻居有球数多）、再最靠下(y最大)、再 x 最小
                pt = max(forced, key=lambda p: (
                    sum(1 for nxx, nyy in neighbors(*p) if (nxx, nyy) in self.board.cells
                        and (nxx, nyy) not in self.shot_landed),
                    p[1], -p[0]))
                tag = "强制推进(无支撑)"
            else:
                logger.info(f"[炸弹等待] 无任何可落空格，本拍 skip")
                return
        # ★ 2026-08-06 seq=79 根因双保险：占位推进落点若压中炸弹落点 override，
        #   会使该点进 shot_landed → 下一拍炸弹分支 in_shot_landed=True 丢弃 override、
        #   炸弹落点偏离最优解、且占位球污染 served。硬保证占位球绝不落炸弹点。
        if self.bomb_target_override is not None and pt == self.bomb_target_override:
            alt_pool = []
            if 'cand' in locals() and cand:
                alt_pool += [c for c in cand if c != pt]
            if 'forced' in locals() and forced:
                alt_pool += [f for f in forced if f != pt]
            if cap is not None:
                alt_pool += [(x, cap) for x in range(10)
                             if (x, cap) not in adv_served and (x, cap) not in self.shot_landed
                             and (x, cap) not in bomb_reserved and self.board.is_placeable(x, cap)]
            alt_pool = [p for p in alt_pool if p != self.bomb_target_override]
            if alt_pool:
                pt = max(alt_pool, key=lambda p: (p[1], -p[0]))
                tag = "避让炸弹点重选"
            else:
                logger.info(f"[炸弹等待] 占位落点=炸弹点({pt})且无可避让候选，本拍 skip（直接等炸弹引爆）")
                return
        # ★ 炸弹等待态推进球写回纪律（2026-08-06 修复 seq=15 误判 31115）：
        #   本拍落点仅为把炸弹往前推一格，它【紧邻下一拍的炸弹落点】。若按旧纪律 cnt<3 写回本地，
        #   会把推进球塞进 self.board.cells，导致下一拍 _choose_bomb_target 在【含该球的棋盘】上选点
        #   （如本次 (2,8) 写回后炸弹选了紧贴它的 (2,9)）；但炸弹激活后服务端常【拒收/忽略】这发
        #   普通落点 → 服务端视角该格为空 → 本地/服务端棋盘错位 → 炸弹落点服务端判无效 → 31115。
        #   故 armed 推进球【一律 record=False 不写回本地】：它只是占位推进，炸弹引爆后即便服务端
        #   真接受了它、也会被炸清（本地本就不该记）。本地棋盘保持纯净 → 炸弹落点与服务端一致。
        cnt_adv = self.board.shot_count(pt[0], pt[1], color)
        self.send_ball(pt[0], pt[1], record=False)
        self.last_shot = now
        self.queue.popleft()
        self.current = self.queue[0] if self.queue else None
        logger.info(f"[炸弹等待] {COLOR_NAME.get(color)} 落点：({pt[0]},{pt[1]}) ({tag})"
              f" cnt={cnt_adv} 不写回(占位推进)")

    def _choose_bomb_target(self):
        """选择炸弹落点：炸弹像普通球一样从炮口飞上去，停在一个【空格】(没球的位置)引爆，
        炸掉以落点为中心、六连通距离 ≤ BOMB_RADIUS(=2) 内的所有球（正六边形，共 19 格：3+4+5+4+3）。
        ★ 用户 2026-08-05 铁律（手动实测核对）：炸弹发射位置要求【和普通球完全一样】——
           必须放到空位、且连着别的球（is_supported）。绝不可落在已有球上、也不可悬空。
        ★ 兼容性关键：炸弹落点候选【直接复用 candidate_landings()】（与普通球落点走完全
           同一套 is_placeable + is_supported + 非顶排 + 不越木板的合法性校验），不再另写
           一套（旧版自写邻居枚举与 candidate_landings 略有出入，易选出服务端物理落点偏移
           后不连球的空格 → 服务端判负 31115）。在此空格集上再筛「半径 BOMB_RADIUS 内至少有
           球」，选炸掉球最多者；同分选最靠下(y最大)以优先清底排密集区、拔高最底有球 y。
        返回 (x, y, 可炸球数) 或 None。"""
        if not self.board.cells:
            return None
        # ★ 候选空格必须基于【净化棋盘 = cells 排除 shot_landed 幽灵球】，与 bomb_target_override
        #   校验口径完全一致（line 1511）。★ 铁律（2026-08-06 seq=36 实测 31115 根因）：
        #   self.board.cells 含服务端已消除但本地未同步删除的【幽灵球】（on_7983/on_31108 的
        #   remove 在回包乱序/包体越界 break 时可能漏删）。若候选集用完整 cells，幽灵球会让
        #   is_supported(落点) 在本地返回 True（某支撑球"本地在、服务端已消"）→ 服务端视角该
        #   支撑球不存在 → 落点 unsupported → 30006 → 31115 判负。这与 line 1771 警告完全吻合。
        #   ★ 关于 armed 推进真实写回球被误当空格的担忧（seq=35 旧注释）：armed 推进球走
        #   record=False 不写回 cells（1887 行修复），它本就不在 cells 里，净化后确会被当空格；
        #   但 armed 推进后本拍即返回、下一拍 cur_type==2 走炸弹分支消费，不会重选推进球落点，
        #   无重复发射风险。故净化棋盘安全且必要。
        served = {(x, y): c for (x, y), c in self.board.cells.items()
                  if (x, y) not in self.shot_landed}
        if not served:
            return None
        proxy = Board()
        proxy.cells = dict(served)
        proxy.wood_row = self.board.wood_row
        # ★ 空格候选 = 与普通球完全相同的合法落点集（基于净化棋盘）。
        #   ★★★ 残局关键修复（2026-08-06 seq=43~50 实测 31115 根因）：残局只剩顶排(y=14)零散残球、
        #   下方已清空时，所有合法落点恰好都在【顶排空格】（其同排邻居支撑 is_supported=True，
        #   见 best_shot 明细 (2,14)sup=True）。若仍用默认 allow_top_row=False 把顶排空格全排除，
        #   候选集直接空 → _choose_bomb_target 返回 None → 炸弹永不引爆 → bot 退化成「顶排兜底推进」
        #   把普通球堆顶排越堆越糟 → 死亡线逼近 → 31115。故炸弹选点必须 allow_top_row=True，
        #   让炸弹能落在顶排空格炸掉顶排残球（炸弹就是要清顶排残局，落点紧贴残球是合法且必要的）。
        #   顶排落点仍受 is_supported（同排邻居支撑）与 death_floor 约束，不会悬空/越界。
        cands = proxy.candidate_landings(allow_top_row=True)
        # 双保险：候选再排除 shot_landed（净化棋盘已排除，此处确保 armed 推进球的落点不被选中）
        cands = {(x, y) for (x, y) in cands if (x, y) not in self.shot_landed}
        # 死亡线下限（落点 y < ButtomRowIndex 服务端判负）
        death_floor = self.buttom_row_index if (self.buttom_row_index is not None and self.buttom_row_index > 0) else 0
        cands = {(x, y) for (x, y) in cands if y >= death_floor}
        if not cands:
            return None
        best_target = None
        best_count = -1
        best_y = -1
        for (tx, ty) in cands:
            # 该空格落炸弹能炸掉的球数 = 半径 BOMB_RADIUS 内的有球格数（基于净化棋盘，
            # 与候选集同一套 served，幽灵球已排除，计数即服务端真实可见球数）
            region = cells_within_radius(tx, ty, BOMB_RADIUS)
            count = sum(1 for (rx, ry) in region if (rx, ry) in served)
            if count <= 0:
                continue  # 半径内无球，炸了个寂寞，跳过
            # 优先炸得多；同分优先落点最靠下(ty 最大) → 清理底排密集区
            if count > best_count or (count == best_count and ty > best_y):
                best_count = count
                best_target = (tx, ty)
                best_y = ty
        if best_target is not None and best_count > 0:
            return best_target[0], best_target[1], best_count
        return None

    # ---- 外部收包驱动 ----
    def feed(self, cmd_id: int, body: bytes):
        """由 mole.py 的 recv 回调在收到游戏服务器包时调用。
        ★★★ 重要（2026-08-04 修复「客户端进程无响应」死锁）：
        recv 钩子回调运行在【游戏客户端进程的 recv 上下文】中，且 paopaolong_send_func
        是通过 fromfd 复用【游戏客户端自己的 socket fd】发包。若在 recv 回调里同步调用
        maybe_shoot→send_ball→send，会向同一 socket 写数据并等待/触发服务端回包，而当前
        recv 回调尚未返回 → 重入死锁，游戏客户端表现为「无响应」。
        故本函数【只建棋盘、绝不在此处发射】。发射统一交给 mole.py 的 RunTimer 主动循环
        （paopaolong_start 里创建的定时器，运行在 UI 线程，不重入 recv 回调）。
        为让「收包后尽快发射」不延迟，收到包时把 last_shot 重置为很久以前，使下一次定时器
        立即（节流间隔内）发射，而非干等整整一个 SHOOT_INTERVAL。
        listening=True 时持续建棋盘（即使还没点发射按钮，避免错过初始 797E）。"""
        if not self.listening:
            return
        # ★ 泡泡龙收包进封包列表(show_data)由 mole.py 的 show_signal.emit 负责，此处不再 print 到
        #   控制台（用户要求仅保留封包列表视图、去掉控制台收包回显噪音）。
        # ★ 状态锁：recv 钩子线程在此处改 board/queue 等共享状态，必须与 maybe_shoot（发射线程）
        #   串行，避免并发读写 dict/deque 导致状态损坏或竞态。
        with self.lock:
            self.handle(cmd_id, body)
        # ★ 不再在此同步发射（死锁修复），也【不】改 last_shot——发射纯由 RunTimer 按 SHOOT_INTERVAL
        #   节拍驱动。若在此处把 last_shot 推前（如清零/减间隔），会让"收包即发"绕过节流，导致实际发射
        #   节奏远快于 SHOOT_INTERVAL（实测 0.3s/发 → 卡死）。收包只建棋盘，节奏交给定时器。

    def start(self):
        """点按钮：开始发射。"""
        self.listening = True
        self.running = True
        self.finished = False   # ★ 清除暂停发射标志（31114 软过渡或上局结束残留），确保手动「开始」必恢复

    def listen(self):
        """识别到游戏服务器 socket 后调用：持续接收并维护棋盘，但不发射。"""
        self.listening = True
        logger.info(f"[自动] 泡泡龙自动通关已启动")
