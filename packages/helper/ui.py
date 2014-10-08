import colorsys
import os
import random
import subprocess
import sys
from qgis.gui import QgsMessageBar
from qgis.utils import iface
from PyQt4.QtCore import Qt
from PyQt4.QtGui import QBrush, QListWidget, QListWidgetItem, QLabel, QProgressBar
from enum import Enum
from helper.string import remove_tags
from helper.extensions import attach_method
from PyQt4 import QtCore

try:
    _fromUtf8 = QtCore.QString.fromUtf8
except AttributeError:
    _fromUtf8 = lambda s: s


def isnull(instance):
    return instance is None or type(instance) is QtCore.QPyNullVariant


def generate_random_color(count):
    golden_ratio_conjugate = 0.618033988749895
    vals = []
    # use random start value
    h = random.random()
    for i in range(count):
        h += golden_ratio_conjugate
        h %= 1
        c = colorsys.hsv_to_rgb(h, 0.5, 0.95)
        vals.append('%02x%02x%02x' % (int(c[0]*255), int(c[1]*255), int(c[2]*255)))

    return vals


def open_folder(path):
    path = os.path.normpath(path)
    if sys.platform == 'darwin':
        subprocess.call(['open', '--', path])
    elif sys.platform == 'linux2':
        subprocess.call(['gnome-open', '--', path])
    elif sys.platform == 'win32':
        subprocess.call(['explorer', path])


def extend_qlabel_setbold(instance):

    if instance.textFormat() == Qt.RichText:
        raise Exception("Leave text format as Qt.PlainText")

    instance.setTextFormat(Qt.RichText)

    def setBold(self, is_bold):
        txt = remove_tags(self.text())
        if is_bold:
            txt = "<strong>{}</strong>".format(txt)
        else:
            txt = "<span>{}</span>".format(txt)

        self.setText(txt)

    attach_method(setBold, instance, QLabel)


def extend_qt_list_widget(instance):
    brush_ok = QBrush(Qt.darkGreen)
    brush_fail = QBrush(Qt.darkRed)
    brush_normal = QBrush(Qt.darkGray)

    def msg_ok(self, message):
        item = QListWidgetItem(message)
        item.setForeground(brush_ok)
        self.addItem(item)

    def msg_fail(self, message):
        item = QListWidgetItem(message)
        item.setForeground(brush_fail)
        self.addItem(item)

    def msg_normal(self, message):
        item = QListWidgetItem(message)
        item.setForeground(brush_normal)
        self.addItem(item)

    attach_method(msg_normal, instance, QListWidget)
    attach_method(msg_ok, instance, QListWidget)
    attach_method(msg_fail, instance, QListWidget)

    return instance


class MessageType(Enum):
    Fail = -1
    Normal = 0
    OK = 1


class QgisMessageBarProgress:

    def __init__(self, text=""):
        self.progressMessageBar = \
            iface.messageBar().createMessage(text)
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.progressMessageBar.layout().addWidget(self.progress)
        iface.messageBar().pushWidget(self.progressMessageBar,
                                      iface.messageBar().INFO)

    def error(self, msg):
        iface.messageBar().clearWidgets()
        iface.messageBar().pushMessage("Error", msg,
                                       level=QgsMessageBar.CRITICAL,
                                       duration=3)

    def setPercentage(self, i):
        self.progress.setValue(i)

    def close(self):
        iface.messageBar().clearWidgets()
