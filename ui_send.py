# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ui_send.ui'
##
## Created by: Qt User Interface Compiler version 6.9.3
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
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy,
    QSpacerItem, QVBoxLayout, QWidget)

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.resize(500, 150)
        Dialog.setMinimumSize(QSize(500, 150))
        Dialog.setMaximumSize(QSize(500, 150))
        self.verticalLayout = QVBoxLayout(Dialog)
        self.verticalLayout.setSpacing(0)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(0, 0, 0, 0)
        self.textEdit = QPlainTextEdit(Dialog)
        self.textEdit.setObjectName(u"textEdit")
        self.textEdit.setMinimumSize(QSize(0, 0))

        self.verticalLayout.addWidget(self.textEdit)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setSpacing(0)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalSpacer = QSpacerItem(160, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.label1 = QLabel(Dialog)
        self.label1.setObjectName(u"label1")
        self.label1.setMinimumSize(QSize(0, 0))
        self.label1.setMaximumSize(QSize(16777215, 16777215))

        self.horizontalLayout.addWidget(self.label1)

        self.ipLineEdit = QLineEdit(Dialog)
        self.ipLineEdit.setObjectName(u"ipLineEdit")
        self.ipLineEdit.setMinimumSize(QSize(0, 23))

        self.horizontalLayout.addWidget(self.ipLineEdit)

        self.horizontalSpacer_2 = QSpacerItem(5, 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer_2)

        self.label2 = QLabel(Dialog)
        self.label2.setObjectName(u"label2")
        self.label2.setMinimumSize(QSize(0, 0))
        self.label2.setMaximumSize(QSize(16777215, 16777215))

        self.horizontalLayout.addWidget(self.label2)

        self.portLineEdit = QLineEdit(Dialog)
        self.portLineEdit.setObjectName(u"portLineEdit")
        self.portLineEdit.setMinimumSize(QSize(0, 23))
        self.portLineEdit.setMaximumSize(QSize(75, 16777215))

        self.horizontalLayout.addWidget(self.portLineEdit)

        self.sendButton = QPushButton(Dialog)
        self.sendButton.setObjectName(u"sendButton")
        self.sendButton.setMinimumSize(QSize(0, 25))
        self.sendButton.setMaximumSize(QSize(60, 16777215))
        self.sendButton.setAutoFillBackground(False)

        self.horizontalLayout.addWidget(self.sendButton)

        self.clearButton = QPushButton(Dialog)
        self.clearButton.setObjectName(u"clearButton")
        self.clearButton.setMinimumSize(QSize(0, 25))
        self.clearButton.setMaximumSize(QSize(60, 16777215))

        self.horizontalLayout.addWidget(self.clearButton)


        self.verticalLayout.addLayout(self.horizontalLayout)


        self.retranslateUi(Dialog)

        QMetaObject.connectSlotsByName(Dialog)
    # setupUi

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"\u62d3\u5c55\u53d1\u9001", None))
        self.label1.setText(QCoreApplication.translate("Dialog", u"IP\uff1a", None))
        self.label2.setText(QCoreApplication.translate("Dialog", u"Port\uff1a", None))
        self.sendButton.setText(QCoreApplication.translate("Dialog", u"\u53d1\u9001", None))
        self.clearButton.setText(QCoreApplication.translate("Dialog", u"\u6e05\u7a7a", None))
    # retranslateUi

