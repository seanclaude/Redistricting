from builtins import range
from builtins import object
import colorsys
import os
import random
import subprocess
import sys
import enum
import types
from qgis.core import Qgis
from qgis.utils import iface
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QBrush
from qgis.PyQt.QtWidgets import QListWidget, QListWidgetItem, QLabel, QProgressBar
from helper.string import remove_tags


def isnull(instance):
    if type(instance) is QVariant:
        return instance.isNull()

    if instance is None:
        return True

    return False


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

    def setBold(is_bold):
        txt = remove_tags(instance.text())
        if is_bold:
            txt = "<strong>{}</strong>".format(txt)
        else:
            txt = "<span>{}</span>".format(txt)

        instance.setText(txt)

    instance.setBold = types.MethodType(setBold, instance)


def extend_qt_list_widget(instance):
    brush_ok = QBrush(Qt.darkGreen)
    brush_fail = QBrush(Qt.darkRed)
    brush_normal = QBrush(Qt.darkGray)

    def msg_ok(message):
        item = QListWidgetItem(message)
        item.setForeground(brush_ok)
        instance.addItem(item)

    def msg_fail(message):
        item = QListWidgetItem(message)
        item.setForeground(brush_fail)
        instance.addItem(item)

    def msg_normal(message):
        item = QListWidgetItem(message)
        item.setForeground(brush_normal)
        instance.addItem(item)

    instance.msg_normal = types.MethodType(msg_normal, instance)
    instance.msg_ok = types.MethodType(msg_ok, instance)
    instance.msg_fail = types.MethodType(msg_fail, instance)

    return instance


class MessageType(enum.Enum):
    Fail = -1
    Normal = 0
    OK = 1


class QgisMessageBarProgress(object):

    def __init__(self, text=""):
        self.progressMessageBar = \
            iface.messageBar().createMessage(text)
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.progressMessageBar.layout().addWidget(self.progress)
        iface.messageBar().pushWidget(self.progressMessageBar,
                                      Qgis.Info)

    def error(self, msg):
        iface.messageBar().clearWidgets()
        iface.messageBar().pushMessage("Error", msg,
                                       level=Qgis.Critical,
                                       duration=8)

    def setPercentage(self, i):
        self.progress.setValue(i)

    def close(self):
        iface.messageBar().clearWidgets()
