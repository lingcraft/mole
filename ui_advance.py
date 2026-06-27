# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ui_advance.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLayout,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

class Ui_AdvanceDialog(object):
    def setupUi(self, AdvanceDialog):
        if not AdvanceDialog.objectName():
            AdvanceDialog.setObjectName(u"AdvanceDialog")
        AdvanceDialog.resize(150, 350)
        AdvanceDialog.setMinimumSize(QSize(150, 350))
        AdvanceDialog.setMaximumSize(QSize(150, 350))
        self.verticalLayout = QVBoxLayout(AdvanceDialog)
        self.verticalLayout.setSpacing(4)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(4, 4, 4, 4)
        self.lineEdit = QLineEdit(AdvanceDialog)
        self.lineEdit.setObjectName(u"lineEdit")

        self.verticalLayout.addWidget(self.lineEdit)

        self.listWidget = QListWidget(AdvanceDialog)
        self.listWidget.setObjectName(u"listWidget")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.listWidget.sizePolicy().hasHeightForWidth())
        self.listWidget.setSizePolicy(sizePolicy)
        self.listWidget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.verticalLayout.addWidget(self.listWidget)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setSpacing(0)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.horizontalSpacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.pushButton = QPushButton(AdvanceDialog)
        self.pushButton.setObjectName(u"pushButton")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.pushButton.sizePolicy().hasHeightForWidth())
        self.pushButton.setSizePolicy(sizePolicy1)
        self.pushButton.setMinimumSize(QSize(0, 30))
        self.pushButton.setStyleSheet(u"QPushButton {\n"
"    margin: -1px;\n"
"}")

        self.horizontalLayout.addWidget(self.pushButton)

        self.horizontalLayout.setStretch(0, 1)
        self.horizontalLayout.setStretch(1, 1)

        self.verticalLayout.addLayout(self.horizontalLayout)


        self.retranslateUi(AdvanceDialog)

        QMetaObject.connectSlotsByName(AdvanceDialog)
    # setupUi

    def retranslateUi(self, AdvanceDialog):
        AdvanceDialog.setWindowTitle(QCoreApplication.translate("AdvanceDialog", u"卡牌", None))
        self.pushButton.setText(QCoreApplication.translate("AdvanceDialog", u"确认", None))
    # retranslateUi

