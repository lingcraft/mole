# -*- coding: utf-8 -*-
"""界面样式集中定义（色值对齐 gfp 项目的 WPF 版 wpf/Styles.xaml，已按实机截图逐像素校准）。

为什么单独抽一个文件：
  按钮的配色用 QSS 表达最省事；下拉框的悬停/聚焦却**不能用 QSS**（原因见 ComboHoverStyle
  的说明），只能靠代理样式自绘。两者色值又必须完全一致，放在一起才好对照、免得改一处漏一处。

⚠ 一个反直觉的坑：**主界面的按钮千万不要在 QSS 里写 min-width / padding**。
  本项目的按钮是 setGeometry 绝对定位、宽度写死的（如「发送」50px、「循环发送」70px、
  「清空封包」61px），而 QSS 的 min-width 会抬高 widget 的 minimumWidth，
  **setGeometry 会被夹到那个最小值** —— 实测给这几个按钮设 min-width: 66px（= 总宽 80）后，
  它们全被撑成 80px：底部那排按钮挤在一起、文字被裁（「循环发送」显示成「环发送」）。
  绝对定位的按钮本来就不需要 sizeHint，所以什么都不用补。
  **只有弹窗按钮**（QMessageBox，走布局）需要 min-width/padding 还原 Fusion 的 80x20。

用法（mole.py 里三行）：
    import style
    style.apply(app)            # 代理样式挂在 app 上（QApplication 创建后）
    style.apply_window(self)    # QSS 挂在主窗口 / 对话框上
"""
from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainterPath
from PySide6.QtWidgets import (QApplication, QComboBox, QProxyStyle, QPushButton, QStyle,
                               QStyleOptionComboBox, QTabWidget)

# ==================== 色值（唯一的真值来源）====================
# 四态实测可见像素：常态 #ABABAB / #FDFDFD→#EEEEEE；悬停 #8A8A8A（底不变）；
# 聚焦 #7170D0 / #FDFDFD→#E5E5EE；聚焦悬停 #7170D0 / #F7F6FC→#DFDFED。
BORDER = "#ABABAB"                 # 常态边框
BORDER_HOVER = "#8A8A8A"           # 悬停边框
BORDER_FOCUS = "#7170D0"           # 聚焦（键盘焦点）边框
BG_TOP, BG_BOTTOM = "#FEFEFE", "#EDEDED"
BG_FOCUS_TOP, BG_FOCUS_BOTTOM = "#FEFEFE", "#E4E4ED"
BG_FOCUS_HOVER_TOP, BG_FOCUS_HOVER_BOTTOM = "#F8F7FD", "#DEDEEC"
BG_PRESSED = "#D3D3DC"
BORDER_DISABLED = "#C4C4C4"        # 禁用态边框（Fusion 原生值，实测取色）
# 弹窗按钮（走布局）还原 Fusion 原生 80x20 用的补偿值：QSS 的 min-width 是「内容区」宽度，
# 不含 padding 与 border，所以 80 - 2*6 - 2 = 66。主界面按钮是绝对定位，不能用（见模块开头）。
BTN_MIN_WIDTH = "66px"
BTN_PADDING = "3px 6px"

# ============================ QSS ============================
# 挂在窗口上（窗口级 → 覆盖该窗口的所有子控件，含 QMessageBox 弹窗）。
STYLE_SHEET = f"""
/* 标签页面板：原先是写在 ui_main.ui 里 tabWidget 自己的 styleSheet 属性上的，抽到这里统一管理。
   ⚠ 控件自身的样式表优先级高于窗口级，所以 .ui 里那份必须删掉，否则这条规则会被它盖住。 */
QTabWidget::pane {{
    background-color: #F0F0F0;
    border: 1px solid #DCDCDC;
}}

/* 渐变 stop 是按实机截图的可见像素反解校准过的（QSS 渐变含 1px 边框，会偏 1 个色阶）；
   :pressed 不写 border，让 :focus(紫) / :hover(深灰) 决定——鼠标按下会带来键盘焦点。
   ⚠ 主界面的按钮是绝对定位，这里不能写 min-width/padding（会把 setGeometry 撑开）；
     只有下面走布局的弹窗按钮才需要它们来还原 Fusion 的尺寸。 */
QPushButton {{
    border: 1px solid {BORDER};
    border-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BG_TOP}, stop:1 {BG_BOTTOM});
}}
QPushButton:hover {{
    border: 1px solid {BORDER_HOVER};
}}
QPushButton:pressed {{
    background: {BG_PRESSED};
}}
QPushButton:focus {{
    border: 1px solid {BORDER_FOCUS};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BG_FOCUS_TOP}, stop:1 {BG_FOCUS_BOTTOM});
}}
QPushButton:focus:hover {{
    border: 1px solid {BORDER_FOCUS};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BG_FOCUS_HOVER_TOP}, stop:1 {BG_FOCUS_HOVER_BOTTOM});
}}
QPushButton:focus:pressed {{
    border: 1px solid {BORDER_FOCUS};
    background: {BG_PRESSED};
}}
/* 禁用态：QSS 接管绘制后会无视 enabled 状态（禁用按钮看起来和正常一样），
   而本项目的按钮初始大量是 setEnabled(False) —— 这里把边框换回 Fusion 原生的浅灰。
   底色与文字 Qt 仍按禁用 palette 绘制，不用自己写。 */
QPushButton:disabled {{
    border: 1px solid {BORDER_DISABLED};
}}

/* 弹窗按钮：用 QMessageBox 前缀限定作用范围（否则会继承上面的规则，尺寸/内边距都得再对一遍）。 */
QMessageBox QPushButton {{
    min-width: {BTN_MIN_WIDTH};
    padding: {BTN_PADDING};
    border: 1px solid {BORDER};
    border-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BG_TOP}, stop:1 {BG_BOTTOM});
}}
QMessageBox QPushButton:hover {{
    border: 1px solid {BORDER_HOVER};
}}
QMessageBox QPushButton:pressed {{
    background: {BG_PRESSED};
}}
QMessageBox QPushButton:focus,
QMessageBox QPushButton:default {{
    border: 1px solid {BORDER_FOCUS};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BG_FOCUS_TOP}, stop:1 {BG_FOCUS_BOTTOM});
}}
QMessageBox QPushButton:focus:hover,
QMessageBox QPushButton:default:hover {{
    border: 1px solid {BORDER_FOCUS};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BG_FOCUS_HOVER_TOP}, stop:1 {BG_FOCUS_HOVER_BOTTOM});
}}
QMessageBox QPushButton:focus:pressed,
QMessageBox QPushButton:default:pressed {{
    border: 1px solid {BORDER_FOCUS};
    background: {BG_PRESSED};
}}
QMessageBox QPushButton:disabled {{
    border: 1px solid {BORDER_DISABLED};
}}
"""


class ComboHoverStyle(QProxyStyle):
    """让下拉框的悬停 / 聚焦外观与按钮一致（这是唯一不能交给 QSS 的部分）。

    Fusion 原生行为有三处不合适：悬停时边框不变却把**整块背景提亮**（实测 3703/4080
    像素被改）、聚焦时边框和底色都不变、展开态还会换按钮区。所以悬停或聚焦时：
    先按"既没悬停也没聚焦"的常态让 Fusion 重绘 → 聚焦时用按钮那套渐变盖掉底色
    （含聚焦再悬停的加深）→ 重画被盖住的箭头 → 最后叠 1px 边框。

    为什么不用 QSS（踩过的三个坑，别再试）：
      1. QSS 命中 :hover/:focus 会接管**整个**下拉框绘制：内边距丢失（文字左起 6px → 2px）、
         右下角被画成「1px 黑线 + 白块」；
      2. Qt 的 QSS **不支持 CSS 三角**（width/height:0 + border 那套会渲染成实心方块），
         箭头只能外挂图片，还得处理 url() 的相对路径；
      3. 一接管弹层列表就失去高亮，且列表边框只能画出左右、上下画不出来。

    挂在 app 级：只拦 CC_ComboBox，其余绘制（含弹层列表）全部转发给 Fusion。
    """

    HOVER_BORDER = QColor(BORDER_HOVER)
    FOCUS_BORDER = QColor(BORDER_FOCUS)
    FOCUS_BG = (BG_FOCUS_TOP, BG_FOCUS_BOTTOM)
    FOCUS_HOVER_BG = (BG_FOCUS_HOVER_TOP, BG_FOCUS_HOVER_BOTTOM)

    def drawComplexControl(self, control, option, painter, widget=None):
        if (control != QStyle.ComplexControl.CC_ComboBox
                or not isinstance(widget, QComboBox)):
            super().drawComplexControl(control, option, painter, widget)
            return
        if not widget.isEnabled():
            # 禁用的下拉框交给 Fusion（浅灰边框），别按悬停/聚焦处理
            super().drawComplexControl(control, option, painter, widget)
            return
        hovered = widget.underMouse()
        focused = widget.hasFocus()
        if not (hovered or focused):
            super().drawComplexControl(control, option, painter, widget)
            return
        sub = QStyleOptionComboBox()
        widget.initStyleOption(sub)
        # 清掉悬停/焦点（含焦点附带的 Selected）带来的绘制差异，按常态画底子
        sub.state &= ~(QStyle.StateFlag.State_MouseOver
                       | QStyle.StateFlag.State_HasFocus
                       | QStyle.StateFlag.State_Selected)
        super().drawComplexControl(control, sub, painter, widget)
        if focused:
            self.paint_focused_background(painter, widget, sub, hovered)
        painter.setPen(self.FOCUS_BORDER if focused else self.HOVER_BORDER)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # adjusted 收 1px：drawRoundedRect 的右/下边界是闭区间，不收会画出界
        painter.drawRoundedRect(widget.rect().adjusted(0, 0, -1, -1), 2, 2)

    def paint_focused_background(self, painter, widget, sub, hovered):
        """盖掉底色，并在箭头区把箭头补回来（文字由 QComboBox::paintEvent 之后重画）。"""
        top, bottom = self.FOCUS_HOVER_BG if hovered else self.FOCUS_BG
        rect = widget.rect()
        # 两端各让 0.5px：QSS 的 qlineargradient(y1:0, y2:1) 按"像素左上角 / (h-1)"采样，
        # 而 Qt 的 QLinearGradient 按"像素中心"采样 —— 直接用 (0, h) 或 (0, h-1)
        # 都会让整条渐变与按钮差 1 个色阶（实测逐行比对出来的）。
        gradient = QLinearGradient(0, 0.5, 0, rect.height() - 0.5)
        gradient.setColorAt(0, QColor(top))
        gradient.setColorAt(1, QColor(bottom))
        path = QPainterPath()
        # 只填边框以内，圆角半径 2 与边框一致
        path.addRoundedRect(QRectF(rect.adjusted(1, 1, -1, -1)), 2, 2)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(rect, gradient)
        painter.restore()
        arrow = QStyleOptionComboBox()
        widget.initStyleOption(arrow)
        arrow.state &= ~(QStyle.StateFlag.State_MouseOver
                         | QStyle.StateFlag.State_HasFocus
                         | QStyle.StateFlag.State_Selected)
        arrow.rect = self.subControlRect(
            QStyle.ComplexControl.CC_ComboBox, sub,
            QStyle.SubControl.SC_ComboBoxArrow, widget)
        self.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorArrowDown,
                           arrow, painter, widget)


class FocusKeeper(QObject):
    """记住窗口里最后获得焦点的按钮 / 下拉框，供切换 tab 时恢复。

    为什么要记：按钮和下拉框的聚焦态（紫边框）由 QSS 的 :focus 绘制，而切换 tab 时
    Qt 会把焦点交给新页面里的第一个可聚焦控件 —— 表现就是「切过去莫名有个控件变紫」。
    把焦点收给标签栏能解决它，可收走之后原来那个控件的聚焦态也丢了，切回来紫边框
    就没了。所以这里记住最后聚焦的控件，切回它所在的页面时再把焦点还给它。

    用 parent=window + 全局事件过滤器（而不是 focusChanged 信号）：窗口销毁时本对象
    随之销毁、过滤器被 Qt 自动摘掉。对方的对话框会反复创建/销毁，靠信号连接会不断累积，
    还可能访问到已析构的 C++ 对象。
    """

    def __init__(self, window):
        super().__init__(window)   # parent = 窗口，生命周期跟着窗口走
        self._win = window
        self.widget = None         # 最后获得过焦点的按钮 / 下拉框

    def eventFilter(self, obj, event):
        # 只认"鼠标按下"，不认 FocusIn：切换 tab 时 Qt 会自动把焦点转给新页面里的第一个
        # 可聚焦控件，跟着 FocusIn 记的话记忆会被那次自动转移覆盖（实测过，等于全不记）。
        if (event.type() == QEvent.Type.MouseButtonPress
                and isinstance(obj, (QPushButton, QComboBox))):
            if obj.window() is self._win:
                self.widget = obj
        return False

    def restore(self, tabs, bar):
        """切换 tab 后决定焦点去向：记住的控件还在当前页面就还给它，否则收给标签栏。"""
        widget = self.widget
        try:
            if (widget is not None and widget.isEnabled()
                    and self.in_current_page(widget, tabs)):
                widget.setFocus()
                return
        except RuntimeError:      # 记住的控件已被销毁（如动态创建的按钮）
            self.widget = None
        bar.setFocus()

    @staticmethod
    def in_current_page(widget, tabs):
        """控件是否位于标签页当前显示的那一页里。

        不用 isVisible()：切换过程中它有一瞬间还是旧值（实测出现过该隐藏的控件报
        visible=True，于是把焦点又塞回了隐藏页）。
        """
        page = tabs.currentWidget()
        node = widget
        while node is not None:
            if node is page:
                return True
            node = node.parentWidget()
        return False


def apply(app):
    """把代理样式挂到 QApplication 上（须在创建控件之前调用）。"""
    app.setStyle(ComboHoverStyle("Fusion"))


def apply_window(window):
    """把 QSS 挂到窗口上（主窗口与各对话框都调一次）。

    用窗口级而不是 app.setStyleSheet()：这样不会波及 QFileDialog 这类顶层对话框 ——
    它们的按钮没有尺寸补偿，会被 QSS 压扁。
    """
    window.setStyleSheet(STYLE_SHEET)
    # 切换 tab 时的焦点处理见 _FocusKeeper：记住最后聚焦的按钮/下拉框，切回它所在的
    # 页面时把焦点还给它（紫边框随之恢复），其他情况一律收给标签栏，免得新页面里
    # 莫名冒出紫边框。
    keeper = FocusKeeper(window)
    app = QApplication.instance()
    if app is not None:
        app.installEventFilter(keeper)
    # 必须延后到事件循环下一轮：Qt 在 setCurrentIndex 之后才做焦点转移（转给新页面里第一个
    # 可聚焦控件），如果在这里同步 setFocus，会立刻被 Qt 覆盖掉，等于没做。
    for tabs in window.findChildren(QTabWidget):
        tabs.currentChanged.connect(
            lambda _index, bar=tabs.tabBar(), t=tabs, k=keeper:
                QTimer.singleShot(0, lambda: k.restore(t, bar)))
