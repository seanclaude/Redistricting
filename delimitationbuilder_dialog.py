# -*- coding: utf-8 -*-
"""
/***************************************************************************
 DelimitationBuilderDialog
                                 A QGIS plugin
 Inserts attributes, merge features and generate KML files
                             -------------------
        begin                : 2014-07-06
        git sha              : $Format:%H$
        copyright            : (C) 2014 by Sean Lin
        email                : seanlinmt@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import os
import sip
from PyQt4.QtGui import QFileDialog

from configuration import Configuration, DefaultConfigFile
import qgis_settings
from shapefile import LayerType
import topology
from PyQt4 import QtGui, QtCore, uic
from delimitation import Delimitation
from balancer import Balancer


FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'ui_delimitationbuilder.ui'))

CONFIG_FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'ui_configuration.ui'))



class DelimitationBuilderDialog(QtGui.QDialog, FORM_CLASS):
    def __init__(self, iface, parent=None):
        from dialog_editor import EditorDialog
        from dialog_warning import WarningDialog

        """Constructor."""
        super(DelimitationBuilderDialog, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)

        # load configuration
        Configuration().load()

        # init the sub dialogs
        self.editor = EditorDialog()
        self.warning = WarningDialog()
        self.configuration = DelimitationBuilderConfigDialog()

        self.topology = None
        self.id_graph = None
        self.layer = None
        self.balancer = None
        self.iface = iface

        QtCore.QObject.connect(self.btRebalance, QtCore.SIGNAL("clicked()"), self.analyse)
        QtCore.QObject.connect(self.btGenerate, QtCore.SIGNAL("clicked()"), self.generate)
        QtCore.QObject.connect(self.BtInputDir, QtCore.SIGNAL("clicked()"), self.select_input_dir)
        QtCore.QObject.connect(self.BtCvsFile, QtCore.SIGNAL("clicked()"), self.select_csv_file)
        QtCore.QObject.connect(self.btEditConfig, QtCore.SIGNAL("clicked()"), self.configuration.show)

        ver = sip.getapi("QVariant")
        self.labelSIP.setText("SIP ver. {}".format(ver))

        #self.setAttribute(QtCore.Qt.WidgetAttribute(QtCore.Qt.WA_DeleteOnClose))

        # read from qgis settings
        self.inputDir.setText(qgis_settings.read(qgis_settings.SRC_DIR))
        self.csvFile.setText(qgis_settings.read(qgis_settings.CSV_FILE))
        self.kmlOut.setText(qgis_settings.read(qgis_settings.KML_OUT))

    def select_csv_file(self):
        startdir = os.path.dirname(self.csvFile.text())
        filename = QtGui.QFileDialog.getOpenFileName(parent=self,
                                                     caption='Select input CSV file"',
                                                     filter="*.csv",
                                                     directory=startdir)
        if filename:
            self.csvFile.setText(filename)

    def select_input_dir(self):

        directory = QtGui.QFileDialog.getExistingDirectory(parent=self,
                                                           caption="Open Directory",
                                                           options=(
                                                               QFileDialog.ShowDirsOnly |
                                                               QFileDialog.DontResolveSymlinks))
        if directory:
            self.inputDir.setText(directory)

    def set_selected_layer(self):
        found = False
        layer_id = self.selector_layers.itemData(self.selector_layers.currentIndex())
        for layer in self.iface.mapCanvas().layers():
            if layer.id() == layer_id:
                self.layer = layer
                found = True

        if self.layer is None:
            self.warning.display("No layer selected")

        return found

    def generate(self):
        # save settings
        qgis_settings.store(qgis_settings.SRC_DIR, self.inputDir.text())
        qgis_settings.store(qgis_settings.KML_OUT, self.kmlOut.text())
        qgis_settings.store(qgis_settings.CSV_FILE, self.csvFile.text())

        if self.inputDir.text().__len__() == 0:
            self.warning.display("Please specify location of input shapefiles")
            return

        if self.csvFile.text().__len__() == 0:
            self.warning.display("Please specify CSV file")
            return

        if self.kmlOut.text().__len__() == 0:
            self.warning.display("Please specify output KML filename")
            return

        # load configuration
        Configuration().load()

        worker = Delimitation()
        worker.process_shapefiles(self.csvFile.text(), self.inputDir.text())

        if worker.qt_progress_break_seen:
            return

        worker.generate_kml(self.kmlOut.text())

        self.warning.display("DONE")

    def analyse(self):
        if not self.set_selected_layer():
            return

        try:
            self.topology, self.id_graph = topology.compute(self.layer, "Pengundi", True)
            if not self.topology:
                return None
        except Exception as e:
            self.warning.display(e.message)
            return None

        self.balancer = Balancer(self.layer, self.id_graph)

        self.editor.display(self.balancer.dump_stats(), self.start_rebalancing)

        return None

    def start_rebalancing(self):
        self.warning.display("Rebalancing clicked")


class DelimitationBuilderConfigDialog(QtGui.QDialog, CONFIG_FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(DelimitationBuilderConfigDialog, self).__init__(parent)
        self.setModal(True)
        self.setupUi(self)

        self.path = os.path.split(__file__)[0]
        QtCore.QObject.connect(self.btSave, QtCore.SIGNAL("clicked()"), self.save_config)

    def show(self):
        # load settings
        with open(os.path.join(self.path, DefaultConfigFile), 'r') as f:
            content = f.read()
        self.txt_settings.setText(content)

        # load styles
        polling = Configuration().readfile(LayerType.Polling, "kml_style")
        self.txt_Polling.setText(polling)
        state = Configuration().readfile(LayerType.State, "kml_style")
        self.txt_State.setText(state)
        parliamentary = Configuration().readfile(LayerType.Parliament, "kml_style")
        self.txt_Parliamentary.setText(parliamentary)

        super(DelimitationBuilderConfigDialog, self).show()
        self.exec_()

    def save_config(self):
        with open(os.path.join(self.path, DefaultConfigFile), 'w') as f:
            f.write(self.txt_settings.toPlainText())

        file_polling = Configuration().read(LayerType.Polling, "kml_style").lstrip("file:")
        with open(os.path.join(self.path, file_polling), 'w') as f:
            f.write(self.txt_Polling.toPlainText())

        file_state = Configuration().read(LayerType.State, "kml_style").lstrip("file:")
        with open(os.path.join(self.path, file_state), 'w') as f:
            f.write(self.txt_State.toPlainText())

        file_parliamentary = Configuration().read(LayerType.Parliament, "kml_style").lstrip("file:")
        with open(os.path.join(self.path, file_parliamentary), 'w') as f:
            f.write(self.txt_Parliamentary.toPlainText())

        self.close()

