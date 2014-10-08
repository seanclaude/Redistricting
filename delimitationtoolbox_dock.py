# -*- coding: utf-8 -*-

"""
/***************************************************************************
 DelimitationToolbox
 delimitationtoolbox_dock.py                A QGIS plugin
 Various tools for electoral delimitation
                              -------------------
        begin                : 2014-07-06
        git sha              : $Format:%H$
        copyright            : (C) 2014 by Sean Lin
        email                : seanlinmt at gmail dot com
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
import csv
import glob
import json
import re
import traceback
from qgis.core import QgsMessageLog, QgsPalLayerSettings, QgsSymbolV2, QgsRendererCategoryV2, \
    QgsCategorizedSymbolRendererV2, QgsFeatureRequest, QgsFeature, QgsGeometry, QgsExpression, QgsMapLayerRegistry, \
    QgsVectorLayer
from qgis.gui import *
from PyQt4 import uic
from PyQt4.QtCore import Qt, SIGNAL, QObject, pyqtSignal, QThread
from PyQt4.QtGui import QComboBox, QDockWidget, QColor, QFileDialog, QMessageBox, QDialog, QTableWidgetItem, QLineEdit
from configuration import *
import configuration
from helper.qgis_util import extend_qgis_interface, delete_shapefile
from helper.string import parse_float
from helper.ui import extend_qt_list_widget, MessageType, extend_qlabel_setbold, QgisMessageBarProgress
from delimitation import Delimitation, LayerType
from balancer import Balancer


FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'ui_delimitationtoolbox_dock.ui'))
CONFIG_FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'ui_configuration.ui'))


class DelimitationToolboxDock(QDockWidget, FORM_CLASS):
    def __init__(self, iface, parent=None):

        """Constructor."""
        super(DelimitationToolboxDock, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)

        # load configuration
        Configuration().load()

        # threads
        self.thread = None
        self.worker = None
        self.progressBar = None

        # label layer
        self.palyr = QgsPalLayerSettings()

        # init the sub dialogs
        self.configuration = DelimitationToolboxConfigDialog(self)
        self.configuration.saved.connect(self.populate_state_selector)
        self.topology = None
        self.id_graph = None
        self.balancer_old = None
        self.balancer_new = None

        # extensions
        self.list_checks = extend_qt_list_widget(self.list_checks)
        self.iface = extend_qgis_interface(iface)

        # manual rebalancer
        self.balancer_started = False

        self.canvas = self.iface.mapCanvas()
        self.clickTool = DelimitationMapTool(self.canvas)
        self.canvas.setMapTool(self.clickTool)
        self.clickTool.canvasDoubleClicked.connect(self.canvas_doubleclicked)
        self.clicked_feature_id = None

        self.layer_id = None
        self.layer = None
        self.voters_fieldname = None
        self.polling_old_fieldname = None
        self.state_old_fieldname = None
        self.par_old_fieldname = None
        self.state_new_fieldname = None
        self.par_new_fieldname = None
        self.polling_new_fieldname = None
        self.par_new_prefix = None

        # set selection colour
        colour = QColor(255, 255, 51, 150)  # transparent yellow
        self.canvas.setSelectionColor(colour)

        self.btGenerateKML.setEnabled(False)

        # extend labels
        extend_qlabel_setbold(self.label_live_state)
        extend_qlabel_setbold(self.label_live_par)

        QObject.connect(self.btShowTopology, SIGNAL("clicked()"), self.topology_display)
        QObject.connect(self.btRenumber, SIGNAL("clicked()"), self.layer_renumber)
        QObject.connect(self.btLoadLayer, SIGNAL("clicked()"), self.select_layer)
        QObject.connect(self.btRebalance, SIGNAL("clicked()"), self.balancer_start)
        QObject.connect(self.btGenerate, SIGNAL("clicked()"), self.generator_start)
        QObject.connect(self.btGenerateKML, SIGNAL("clicked()"), self.balancer_generate_start)
        QObject.connect(self.BtInputDir, SIGNAL("clicked()"), self.select_input_dir)
        QObject.connect(self.btEditConfig, SIGNAL("clicked()"), self.configuration.show)
        QObject.connect(self.btDuplicate, SIGNAL("clicked()"), self.fields_duplicate_old)
        QObject.connect(self.btRedrawLayer, SIGNAL("clicked()"), self.layer_redraw)
        QObject.connect(self.selector_layers, SIGNAL('currentIndexChanged(const QString&)'),
                        self.layer_changed)
        QObject.connect(self.selector_state, SIGNAL('currentIndexChanged(const QString&)'),
                        self.live_show)
        QObject.connect(self.selector_par, SIGNAL('currentIndexChanged(const QString&)'),
                        self.live_show)

        # http://qgis.org/api/classQgsMapCanvas.html
        QObject.connect(self.cb_label, SIGNAL("stateChanged(int)"), self.label_handler)
        QObject.connect(self.cb_feature_id, SIGNAL("stateChanged(int)"), self.label_handler)

        # monitor layer selection change
        QObject.connect(self.btClearSelected, SIGNAL("clicked()"), self.selection_clear)
        QObject.connect(self.btReset, SIGNAL("clicked()"), self.fields_reset)
        QObject.connect(self.btUpdateAttributes, SIGNAL("clicked()"), self.selection_update)
        QObject.connect(self.canvas, SIGNAL("layersChanged()"), self.layers_load)

        self.setAttribute(Qt.WidgetAttribute(Qt.WA_DeleteOnClose))

        # read from qgis settings
        self.inputDir.setText(Configuration().read_qt(Configuration.SRC_DIR))

        # populate state
        self.populate_state_selector()

    def messsage_handler(self, message_type, message):
        if message_type == MessageType.Fail:
            self.list_checks.msg_fail(message)
        elif message_type == MessageType.Normal:
            self.list_checks.msg_normal(message)
        elif message_type == MessageType.OK:
            self.list_checks.msg_ok(message)
        else:
            raise Exception("Unknown message type {}".format(message_type))

    def statistics_update(self):
        self.label_total_voters.setText(str(self.balancer_old.total_voters))
        self.label_par_range_old.setText("{:.2f}%/{:.2f}/{:.2f}%"
                                         .format(self.balancer_old.parmin_actual_precentage,
                                                 self.balancer_old.par_average,
                                                 self.balancer_old.parmax_actual_precentage))
        self.label_state_range_old.setText("{:.2f}%/{:.2f}/{:.2f}%"
                                           .format(self.balancer_old.statemin_actual_precentage,
                                                   self.balancer_old.state_average,
                                                   self.balancer_old.statemax_actual_precentage))
        self.label_par_range_new.setText("{:.2f}%/{:.2f}/{:.2f}%"
                                         .format(self.balancer_new.parmin_actual_precentage,
                                                 self.balancer_new.par_average_target,
                                                 self.balancer_new.parmax_actual_precentage))
        self.label_state_range_new.setText("{:.2f}%/{:.2f}/{:.2f}%"
                                           .format(self.balancer_new.statemin_actual_precentage,
                                                   self.balancer_new.state_average_target,
                                                   self.balancer_new.statemax_actual_precentage))

    def live_show(self):

        selectedfeatureids = self.layer.selectedFeaturesIds()
        current_state = self.selector_state.itemData(self.selector_state.currentIndex())
        current_par = self.selector_par.itemData(self.selector_par.currentIndex())
        balancer = self.get_balancer()

        totals = balancer.calculate_live_totals(current_par, current_state, selectedfeatureids)
        voters_par = totals[0]
        voters_state = totals[1]
        voters_selected = totals[2]

        # number of state seats in current parliament seat
        if str(current_par) in balancer.map_par_state:
            states_per_par = balancer.map_par_state[str(current_par)]['states'].__len__()
        else:
            states_per_par = "-"

        self.label_state_voters.setText(str(voters_state))
        self.label_par_voters.setText("{}({})".format(voters_par, states_per_par))

        if balancer.state_average:
            delta_state = voters_state - balancer.state_average
            delta_state_percentage = 100 * delta_state / balancer.state_average
            self.label_delta_state.setText("{:.0f},{:.2f}%".format(delta_state, delta_state_percentage))
            self.label_selected_state \
                .setText("{:.0f},{:.2f}%"
                         .format(voters_selected,
                                 100 * voters_selected / balancer.state_average))

        if balancer.par_average:
            delta_par = voters_par - balancer.par_average
            delta_par_percentage = 100 * delta_par / balancer.par_average
            self.label_delta_par.setText("{:.0f},{:.2f}%".format(delta_par, delta_par_percentage))
            self.label_selected_par \
                .setText("{:.0f},{:.2f}%"
                         .format(voters_selected,
                                 100 * voters_selected / balancer.par_average))

        self.statistics_update()

    def fields_duplicate_old(self):
        confirmation = QMessageBox.question(self,
                                            "Overwrite values",
                                            "Are you sure? Allocation for the new "
                                            "constituencies will be overwritten with the old map.",
                                            QMessageBox.Yes | QMessageBox.No)
        if confirmation == QMessageBox.No:
            return

        delta = self.get_delta()
        if not delta:
            return

        # get all values then sort by PAR and then by STATE which returns a tuple
        attributes_old = sorted(self.balancer_old.topology_polling.items(),
                                key=lambda x: (x[1][self.par_old_fieldname],
                                               x[1][self.state_old_fieldname],
                                               x[1][self.polling_old_fieldname]))
        par_format = self.balancer_new.par_prefix_format
        state_format = self.balancer_new.state_prefix_format
        poll_format = self.balancer_new.polling_prefix_format
        regexp = "(\d+)"
        base_par = int(re.match(regexp, attributes_old[0][1][self.par_old_fieldname], re.I).group(1))

        # http://gis.stackexchange.com/questions/58296/speed-of-editing-attributes-in-qgis-from-a-python-plugin
        self.layer.startEditing()
        for row in attributes_old:
            old_par = int(re.match(regexp, row[1][self.par_old_fieldname], re.I).group(1))
            old_state = int(re.match(regexp, row[1][self.state_old_fieldname], re.I).group(1))
            old_polling = int(re.match(regexp, row[1][self.polling_old_fieldname], re.I).group(1))
            new_par = par_format % (old_par - base_par + 1)
            new_state = state_format % old_state
            new_polling = poll_format % old_polling

            self.balancer_new.update_topology(
                {row[0]: {
                    self.state_new_fieldname: new_state,
                    self.par_new_fieldname: new_par,
                    self.polling_new_fieldname: new_polling}})

        self.layer.commitChanges()
        self.layer_redraw(True)
        self.iface.info("Done")

    def fields_reset(self):
        confirmation = QMessageBox.question(self,
                                            "Reset values",
                                            """Are you sure? This operation will permanently remove all new allocations.
                                            You will need to rebalance all areas from the beginning.""",
                                            QMessageBox.Yes | QMessageBox.No)
        if confirmation == QMessageBox.No:
            return

        self.layer.startEditing()
        for k, v in self.balancer_new.topology_polling.items():
            self.layer.changeAttributeValue(k, self.layer.fieldNameIndex(self.polling_new_fieldname), None)
            self.layer.changeAttributeValue(k, self.layer.fieldNameIndex(self.state_new_fieldname), None)
            self.layer.changeAttributeValue(k, self.layer.fieldNameIndex(self.par_new_fieldname), None)

        self.layer.commitChanges()
        self.layer_redraw(True)
        self.iface.info("Done")

    def label_handler(self):
        self.label_update()
        self.canvas.refresh()

    def label_update(self):
        self.palyr.readFromLayer(self.layer)

        if self.cb_label.isChecked() or self.cb_feature_id.isChecked():
            self.palyr.enabled = True
        else:
            self.palyr.enabled = False

        expr = []
        balancer = self.get_balancer()

        if self.cb_feature_id.isChecked():
            expr.append("""CASE
                    WHEN
                        {0} IS NULL or {1} IS NULL THEN ''
                        ELSE concat(toint(regexp_substr({0}, '(\\\d+)')),'/',toint(regexp_substr({1}, '(\\\d+)')))
                    END""".format(balancer.par_field, balancer.state_field))

        if self.cb_label.isChecked():
            if self.selector_seat_type.currentIndex() == 1:
                divisor = balancer.par_average
            elif self.selector_seat_type.currentIndex() == 0:
                divisor = balancer.state_average
            else:
                raise Exception("Unknown seat type")

            if expr.__len__():
                expr.append("'\\n'")

            expr.append("round({}*100.0/{}, 2)".format(self.voters_fieldname, divisor))

        self.palyr.fieldName = "concat({})".format(",".join(expr))
        self.palyr.isExpression = True
        self.palyr.placement = QgsPalLayerSettings.OverPoint
        self.palyr.setDataDefinedProperty(QgsPalLayerSettings.Size, True, True, '8', '')

        self.palyr.writeToLayer(self.layer)

    def combobox_state_save(self):
        saved_state = {}
        for widget in self.findChildren(QComboBox):
            saved_state.update({widget.objectName(): widget.currentIndex()})

        for widget in self.findChildren(QLineEdit):
            saved_state.update({widget.objectName(): widget.text()})

        Configuration().store_qt(Configuration.UI_STATE, json.dumps(saved_state))

    def combobox_state_load(self, excludes=None):
        if not excludes:
            excludes = []
        try:
            saved_state = json.loads(Configuration().read_qt(Configuration.UI_STATE))
        except:
            return

        for widget in self.findChildren(QComboBox):
            if widget.objectName() in saved_state and widget.objectName() not in excludes:
                widget.setCurrentIndex(saved_state[widget.objectName()])

        for widget in self.findChildren(QLineEdit):
            if widget.objectName() in saved_state and widget.objectName() not in excludes:
                widget.setText(saved_state[widget.objectName()])

    def layer_changed(self):
        self.layer = None
        layer_id = self.selector_layers.itemData(self.selector_layers.currentIndex())

        for layer in self.canvas.layers():
            if layer.id() == layer_id:
                self.layer = layer

        if not self.layer:
            self.balancer_stop()
            return

        # don't do anything if old layer is still there
        if self.layer_id == layer_id:
            return

        self.layer_id = layer_id
        self.selector_voters.clear()
        self.selector_polling_old.clear()
        self.selector_state_old.clear()
        self.selector_par_old.clear()
        self.selector_state_new.clear()
        self.selector_par_new.clear()
        self.selector_polling_new.clear()

        self.selector_voters.addItem("Select field ...", "")
        self.selector_polling_old.addItem("Select area ...", "")
        self.selector_state_old.addItem("Select state ...", "")
        self.selector_par_old.addItem("Select par ...", "")
        self.selector_state_new.addItem("Select state ...", "")
        self.selector_par_new.addItem("Select par ...", "")
        self.selector_polling_new.addItem("Select area ...", "")

        # http://qgis.org/api/classQgsVectorDataProvider.html
        fields = self.layer.dataProvider().fields()
        for field in fields:
            self.selector_voters.addItem(field.name(), field.name())
            self.selector_polling_old.addItem(field.name(), field.name())
            self.selector_state_old.addItem(field.name(), field.name())
            self.selector_par_old.addItem(field.name(), field.name())
            self.selector_state_new.addItem(field.name(), field.name())
            self.selector_par_new.addItem(field.name(), field.name())
            self.selector_polling_new.addItem(field.name(), field.name())

            # load save state
        self.combobox_state_load(["selector_layers"])

    def layers_load(self):
        self.selector_layers.clear()
        for layer in self.canvas.layers():
            if layer.type() == layer.VectorLayer and layer.geometryType() == 2:
                self.selector_layers.addItem(layer.name(), layer.id())

    def layer_redraw(self, zoom_to_layer=True):
        delta = self.get_delta()
        if not delta:
            return

        # init selectors
        self.feature_selector_init()

        # update label parameters
        self.label_update()

        # update map redraw parameters
        map_type = self.selector_map_type.currentIndex()
        if map_type == 0:
            balancer = self.balancer_old
        else:
            # new map, need to reload
            balancer = self.balancer_new
            balancer.load_topology()
            balancer.init_colouring()

        seat_type = self.selector_seat_type.currentIndex()
        if seat_type == 0:
            # state
            get_colour_method = balancer.get_colour_by_state
            attr_prefix = balancer.state_prefix_format
            attr_name = balancer.state_field
            colouring = balancer.colouring_state
            self.label_live_state.setBold(True)
            self.label_live_par.setBold(False)
        else:
            # par
            get_colour_method = balancer.get_colour_by_parliament
            attr_prefix = balancer.par_prefix_format
            attr_name = balancer.par_field
            colouring = balancer.colouring_par
            self.label_live_state.setBold(False)
            self.label_live_par.setBold(True)

        geomtype = self.layer.geometryType()

        if self.selector_overlay_type.currentIndex() == 2:
            # load adjacency layers
            name = self.selector_target_state.currentText()
            state_alayer = balancer.adjlayer_make(name, LayerType.State)
            par_alayer = balancer.adjlayer_make(name, LayerType.Parliament)

            existing_layerids = []
            for lyr in [state_alayer, par_alayer]:
                existing_layerids.extend(
                    [x.id() for x in QgsMapLayerRegistry().instance().mapLayersByName(lyr.name()) if x is not None])

            QgsMapLayerRegistry().instance().removeMapLayers(existing_layerids)
            QgsMapLayerRegistry().instance().addMapLayer(state_alayer)
            QgsMapLayerRegistry().instance().addMapLayer(par_alayer)
            return

        # balancer
        categories = []

        # add blank category for unallocated features
        empty_symbol = QgsSymbolV2.defaultSymbol(geomtype)
        empty_symbol.setColor(QColor('white'))
        empty_category = QgsRendererCategoryV2("", empty_symbol, "")
        categories.append(empty_category)

        for k, v in colouring.gColouring.iteritems():
            if self.selector_overlay_type.currentIndex() == 1:
                colour = get_colour_method(k, v)
            elif self.selector_overlay_type.currentIndex() == 0:
                colour = colouring.get_colour(v)
            else:
                self.iface.warning("That analysis option is not available yet")
                return

            if not colour:
                continue

            symbol = QgsSymbolV2.defaultSymbol(geomtype)
            symbol.setColor(QColor(colour.hex))
            val = attr_prefix % int(k)
            category = QgsRendererCategoryV2(val, symbol, val)
            categories.append(category)

        # create the renderer and assign it to a layer
        renderer = QgsCategorizedSymbolRendererV2(attr_name, categories)
        self.layer.setRendererV2(renderer)
        # self.canvas.setDirty(True)
        self.canvas.clearCache()
        if zoom_to_layer:
            self.canvas.setExtent(self.layer.extent())
            self.canvas.zoomToNextExtent()
        self.canvas.refresh()

    def layer_renumber(self):
        confirmation = QMessageBox.question(self,
                                            "Reorder allocation",
                                            "Are you sure? This will renumber and " +
                                            "reorganise any constituencies that are out of sequence.",
                                            QMessageBox.Yes | QMessageBox.No)
        if confirmation == QMessageBox.No:
            return

        self.layer.startEditing()
        self.balancer_new.resequence(self.par_new_prefix)

        par_used = [v[self.par_new_fieldname] for v in self.balancer_new.topology_polling.values()]
        state_used = [v[self.state_new_fieldname] for v in self.balancer_new.topology_polling.values()]

        if set(par_used).__len__() > self.balancer_old.par_count or \
                        set(state_used).__len__() > self.balancer_old.state_count:
            self.iface.error("Allocation limit exceeded")
            self.layer.rollBack()
            return

        self.layer.commitChanges()
        self.iface.info("Renumbering completed.")

    def map_type_change(self):
        self.feature_selector_init()
        self.label_handler()

    def canvas_doubleclicked(self, point, button):
        current_state = self.selector_state.itemData(self.selector_state.currentIndex())
        current_par = self.selector_par.itemData(self.selector_par.currentIndex())
        balancer = self.get_balancer()
        par_field = balancer.par_field
        state_field = balancer.state_field

        if current_state and current_par:
            ids = [int(k) for k, v in balancer.topology_polling.items()
                   if v[par_field] == str(current_par) and v[state_field] == str(current_state)]

            if set(ids) \
                    .difference(self.layer.selectedFeaturesIds()) \
                    .difference([self.clicked_feature_id]) \
                    .__len__() == 0:
                self.layer.modifySelection([], ids)
            else:
                self.layer.modifySelection(ids, [])

    def canvas_clicked(self, point, button):
        if self.layer is None:
            self.iface.warning("Active layer not found")
            return

        # self.iface.info("clicked = %s,%s" % (str(point.x()), str(point.y())))

        # setup the provider select to filter results based on a rectangle
        point = QgsGeometry().fromPoint(point)
        # scale-dependent buffer of 2 pixels-worth of map units
        buff = point.buffer((self.canvas.mapUnitsPerPixel() * 2), 0)
        rect = buff.boundingBox()
        rect.normalize()

        # set up featureReq
        req = QgsFeatureRequest()
        req.setFilterRect(rect)
        req.setFlags(QgsFeatureRequest.NoGeometry)
        fit = self.layer.getFeatures(req)

        feats = []
        f = QgsFeature()
        while fit.nextFeature(f):
            feats.append(f)

        if feats.__len__() == 0:
            return
        elif feats.__len__() != 1:
            self.iface.warning("{} features clicked".format(feats.__len__()))

        changed_feature = feats[0]
        self.clicked_feature_id = changed_feature.id()

        if button == Qt.RightButton:
            # update selectors & recalculate
            balancer = self.get_balancer()

            self.tab_rebalance.setCurrentIndex(1)
            raw_par = changed_feature[balancer.par_field]
            if raw_par:
                par_val = int(re.search(r'\d+', raw_par).group())
                selector_par_index = self.selector_par.findData(par_val)
                if selector_par_index != -1:
                    self.selector_par.setCurrentIndex(selector_par_index)

            raw_state = changed_feature[balancer.state_field]
            if raw_state:
                state_val = int(re.search(r'\d+', raw_state).group())
                selector_state_index = self.selector_state.findData(state_val)
                if selector_state_index != -1:
                    self.selector_state.setCurrentIndex(selector_state_index)

            self.live_show()
        else:
            # toggle selection & recalculate
            self.layer.invertSelectionInRectangle(rect)

    def populate_state_selector(self):
        self.selector_target_state.clear()
        self.selector_target_state.addItem("Select state ...", "")
        map(lambda x: self.selector_target_state.addItem(x[0], x[1] if x.__len__() == 2 else ""),
            [entry.split(':') for entry in Configuration().read("Settings", "state_prefixes")])

    def selection_update(self):
        # don't allow write to old layer
        if self.selector_map_type == 0:
            self.iface.warning("Not allowed to modify old location codes. Select new map to assign new location codes.")
            return

        current_state = self.balancer_new.state_prefix_format % self.selector_state.itemData(
            self.selector_state.currentIndex())
        current_par = self.balancer_new.par_prefix_format % self.selector_par.itemData(self.selector_par.currentIndex())

        confirmation = QMessageBox.question(self,
                                            "Confirm action",
                                            "Add selection to the following constituencies?\n" +
                                            "Parliament:{}\nState:{}".format(current_par, current_state),
                                            QMessageBox.Yes | QMessageBox.No)
        if confirmation == QMessageBox.Yes:
            self.layer.startEditing()
            updates = [(current_par, current_state)]
            for f in self.layer.selectedFeatures():
                updates.append((f[self.par_new_fieldname], f[self.state_new_fieldname]))
                self.balancer_new.update_topology(
                    {f.id(): {self.state_new_fieldname: current_state,
                              self.par_new_fieldname: current_par}})

            # renumber POLLs in the changed
            for entry in updates:
                filter_expression = "'{}' = '{}' AND '{}' = '{}'" \
                    .format(self.par_new_fieldname,
                            entry[0],
                            self.state_new_fieldname,
                            entry[1])
                req = QgsFeatureRequest(QgsExpression(filter_expression))
                for i, f in enumerate(self.layer.getFeatures(req)):
                    self.balancer_new.update_topology(
                        {f.id(): {self.polling_new_fieldname: self.balancer_new.polling_prefix_format % (i + 1)}})

            self.layer.commitChanges()
            self.selection_clear()
            self.statistics_update()
            # self.balancer_new.load_topology()
            # self.balancer_new.init_colouring()
            self.layer_redraw(False)

            self.iface.info("Selected features updated")

    def selection_clear(self):
        if self.layer is None:
            return

        self.layer.setSelectedFeatures([])

    def select_layer(self):
        startdir = os.path.join(self.inputDir.text(), Configuration().read("KML", "outputdir"))
        filepath = QFileDialog.getOpenFileName(parent=self,
                                               caption='Select shapefile',
                                               filter="*.shp",
                                               directory=startdir)
        if filepath:
            path, filename = os.path.split(filepath)
            name, ext = os.path.splitext(filename)
            layer = self.iface.addVectorLayer(filepath, name, "ogr")
            if not layer.isValid():
                self.iface.error("Layer failed to load!")
                return

                # QgsMapLayerRegistry.instance().addMapLayer(layer)

    def select_input_dir(self):
        startdir = os.path.dirname(self.inputDir.text())
        directory = QFileDialog.getExistingDirectory(parent=self,
                                                     caption="Open Directory",
                                                     directory=startdir,
                                                     options=(
                                                         QFileDialog.ShowDirsOnly |
                                                         QFileDialog.DontResolveSymlinks))
        if directory:
            self.inputDir.setText(directory)

    def generator_start(self):
        # generate KML
        if self.selector_target_state.currentIndex() == 0:
            self.iface.warning("Please select state first")
            return

        src_dir = self.inputDir.text()

        self.list_checks.clear()
        self.messsage_handler(MessageType.Normal, "Validating requirements ...")

        if not src_dir:
            self.iface.error("Location of files not specified")
            return

        shapefiles = glob.glob1(src_dir, '*.shp')
        if shapefiles.__len__() == 1:
            self.messsage_handler(MessageType.OK,
                                  "{} Shapefile found. Using {}".format(shapefiles.__len__(), shapefiles[0]))
        else:
            self.messsage_handler(MessageType.Fail, "Unexpected number of Shapefiles found. Only one " +
                                  "shapefile is required. Aborting.")
            return

        csvfiles = glob.glob1(src_dir, '*.csv')
        if csvfiles.__len__():
            self.messsage_handler(MessageType.OK,
                                  "{} CSV files(s) found. Using {}".format(csvfiles.__len__(), csvfiles[0]))
        else:
            self.messsage_handler(MessageType.Fail, "No CSV files found. Aborting.")
            return

        # save settings
        Configuration().store_qt(Configuration.SRC_DIR, src_dir)

        # check that CSV file contains all fields
        if not self.validate_csv_file(src_dir, csvfiles[0]):
            return

        self.worker = Delimitation(self.selector_target_state.currentText(), src_dir)

        wfiles = self.worker.get_working_files([LayerType.Polling, LayerType.State, LayerType.Parliament])

        if not self.files_check_opened(wfiles):
            self.messsage_handler(MessageType.Fail, "Operation cancelled")
            return

        # get duplicate values if any
        match_feat_name = Configuration().read("CSV", "field")
        layer = QgsVectorLayer(os.path.join(src_dir, shapefiles[0]), self.selector_target_state.currentText(), "ogr")
        field_values = {}
        for f in layer.getFeatures():
            if f.fieldNameIndex(match_feat_name) == -1:
                self.messsage_handler(MessageType.Fail,
                                      "The field '{}' does not exist in Feature {}".format(match_feat_name, f.id()))
                return
            field_values.setdefault(f[match_feat_name], []).append(f.id())

        duplicates = []
        duplicate_ids = []
        for k, v in field_values.iteritems():
            if v.__len__() > 1:
                duplicates.append(k)
                duplicate_ids.extend(v)

        if duplicates.__len__():
            QgsMapLayerRegistry.instance().addMapLayer(layer)
            layer.setSelectedFeatures(duplicate_ids)
            self.messsage_handler(MessageType.Fail,
                                  "Duplicate values found for {}. Aborting ...".format(", ".join(duplicates)))
            return

        self.messsage_handler(MessageType.OK, "All requirements validated. Starting ...")

        self.btGenerate.setEnabled(False)

        self.thread = QThread(self)

        self.worker.moveToThread(self.thread)
        self.worker.finished.connect(self.generator_end)
        # self.worker.error.connect(self.generator_error)
        self.worker.message.connect(self.messsage_handler)
        try:
            self.progressBar = QgisMessageBarProgress()
            self.worker.progress.connect(self.progressBar.setPercentage)
            self.thread.started.connect(self.worker.run_generate_shapefile_kml)
            self.thread.start()
        except Exception, e:
            self.generator_error(e, traceback.format_exc())

    def generator_error(self, e, exception_string):
        self.messsage_handler(MessageType.Fail, exception_string)
        QgsMessageLog.logMessage('DelimitationToolbox Exception:\n'.format(exception_string),
                                 level=QgsMessageLog.CRITICAL)

    def generator_end(self, ret):
        # clean up the worker and thread
        self.worker.deleteLater()
        self.thread.quit()
        self.thread.wait()
        self.thread.deleteLater()

        if not ret:
            self.iface.info('Done!')
        else:
            self.messsage_handler(MessageType.Fail, ret)

        if self.progressBar:
            self.progressBar.close()
            self.progressBar = None
        self.btGenerate.setEnabled(True)

    def files_check_opened(self, files):
        opened = {}
        for f in files:
            for lyr in self.canvas.layers():
                if lyr.type() != lyr.VectorLayer:
                    continue

                lyr_path = lyr.dataProvider().dataSourceUri()
                if lyr_path.find('|') != -1:
                    lyr_path, _ = lyr_path.split("|")

                if f == os.path.normpath(lyr_path):
                    opened.update({lyr.id(): lyr_path})

        if opened.__len__():
            confirmation = QMessageBox.question(self,
                                                "Files in use",
                                                "Some files are currently opened in QGIS. Click YES to automatically close these files or NO to do it yourself",
                                                QMessageBox.Yes | QMessageBox.No)
            if confirmation == QMessageBox.No:
                return False

            # close these files
            for k, v in opened.items():
                QgsMapLayerRegistry().instance().removeMapLayer(k)
                delete_shapefile(v)

        return True

    def topology_display(self):
        selected_index = self.selector_topo_type.currentIndex()

        if selected_index == 0:
            balancer = self.balancer_old
        else:
            balancer = self.balancer_new

        pars = sorted(balancer.map_par_state.items())
        rows = []
        for par in pars:
            rows.append((par[0], par[1]['states'].keys().__len__(), par[1]['d'], par[1]['voters']))
            for state in sorted(par[1]['states'].items()):
                rows.append(("", state[0], state[1]))

        # extra 2 for unused info rows and +1 for header row
        self.table_topo.setRowCount(1)
        self.table_topo.setRowCount(rows.__len__() - balancer.map_par_state.keys().__len__() + 2)

        par_cell = None
        row_count = 0
        for row in rows:
            if row[0]:
                par_cell = QTableWidgetItem("{}\n{}\n{}".format(row[0], row[3], row[2])), row[1]
            else:
                if par_cell:
                    self.table_topo.setItem(row_count, 0, QTableWidgetItem(par_cell[0]))
                    self.table_topo.setSpan(row_count, 0, par_cell[1], 1)
                    par_cell = None

                self.table_topo.setItem(row_count, 1, QTableWidgetItem(row[1]))
                self.table_topo.setItem(row_count, 2, QTableWidgetItem(row[2]))
                row_count += 1

        unused_header = QTableWidgetItem("Unused codes")
        unused_header.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.table_topo.setItem(row_count, 0, unused_header)
        self.table_topo.setSpan(row_count, 0, 1, 3)

        row_count += 1
        unused_totals = balancer.get_unused()
        if unused_totals[0].__len__() == 0:
            par_cell = QTableWidgetItem('')
        else:
            par_cell = QTableWidgetItem(", ".join(unused_totals[0]))
        self.table_topo.setItem(row_count, 0, par_cell)

        state_cell = QTableWidgetItem(", ".join(unused_totals[1]))
        self.table_topo.setItem(row_count, 1, state_cell)
        self.table_topo.setItem(row_count, 2, QTableWidgetItem(''))

        self.iface.info("Allocation table refreshed")

    def validate_csv_file(self, cdir, cfile):
        with open(os.path.join(cdir, cfile), 'rb') as csvfile:
            rows = csv.reader(csvfile, delimiter=',', quoting=csv.QUOTE_NONE)
            csv_columns = rows.next()

        # configuration requirements
        conf_columns = set()
        conf_columns.update(Configuration().read("CSV", "columns"))
        conf_columns.update(Configuration().read("Polling", "name_columns"))
        conf_columns.update(Configuration().read("Polling", "attributes"))
        conf_columns.update(Configuration().read("State", "name_columns"))
        conf_columns.update(Configuration().read("State", "attributes"))
        conf_columns.update(Configuration().read("Parliament", "name_columns"))
        conf_columns.update(Configuration().read("Parliament", "attributes"))

        # check name not more than 10 characters
        toolongs = []
        for col in conf_columns:
            if col.__len__() > 10:
                toolongs.append(col)

        if toolongs.__len__():
            self.messsage_handler(MessageType.Fail,
                                  "The name of column(s) {} is too long (max 10 characters). Aborting.".format(
                                      ", ".join(toolongs),
                                      cfile))
            return False

        diff = conf_columns.difference(csv_columns)

        if diff.__len__():
            self.messsage_handler(MessageType.Fail, "Column(s) {} missing from {}. Aborting."
                                  .format(", ".join(diff), cfile))
            return False

        return True

    def balancer_start(self):
        if self.balancer_started:
            self.balancer_stop()
        else:
            if self.rb_manual.isChecked():
                self.balancer_manual_start()
            elif self.rb_automated.isChecked():
                self.analyse()
            else:
                self.iface.info("Feature not yet implemented")

    def balancer_generate_start(self):
        if not self.balancer_new.is_balanced():
            self.iface.error("Map not balanced. Unable to generate KML.")
            return

        if self.selector_target_state.currentIndex() == 0:
            self.iface.warning("Please select a target state first")
            return

        filepath, layerid = self.layer.dataProvider().dataSourceUri().split("|")
        path, filename = os.path.split(filepath)
        self.worker = Delimitation(self.selector_target_state.currentText(), path, path)

        # set the temp layer as currently loaded layer
        self.worker.master_layer = self.layer
        self.worker.map_layers.setdefault(LayerType.Polling, []).append(self.layer)

        # check for open files
        wfiles = self.worker.get_working_files([LayerType.State, LayerType.Parliament])

        if not self.files_check_opened(wfiles):
            self.iface.warning("Operation aborted")
            return

        self.thread = QThread(self)

        self.worker.moveToThread(self.thread)
        self.worker.finished.connect(self.generator_end)
        # self.worker.error.connect(self.generator_error)
        self.worker.message.connect(self.messsage_handler)

        try:
            self.progressBar = QgisMessageBarProgress()
            self.worker.progress.connect(self.progressBar.setPercentage)
            self.thread.started.connect(self.worker.run_generate_kml)
            self.thread.start()
        except Exception, e:
            self.generator_error(e, traceback.format_exc())

    def get_balancer(self):
        if self.selector_map_type.currentIndex() == 0:
            return self.balancer_old

        return self.balancer_new

    def get_delta(self):
        delta = parse_float(self.tbDelta.text())
        if not delta or delta > 1 or delta < 0:
            self.iface.info("Please specify a value between 0 and 1")
        return delta

    def balancer_manual_start(self):
        if not self.layer:
            return

        self.voters_fieldname = self.selector_voters.itemData(self.selector_voters.currentIndex())
        self.polling_old_fieldname = self.selector_polling_old.itemData(self.selector_polling_old.currentIndex())
        self.state_old_fieldname = self.selector_state_old.itemData(self.selector_state_old.currentIndex())
        self.par_old_fieldname = self.selector_par_old.itemData(self.selector_par_old.currentIndex())
        self.state_new_fieldname = self.selector_state_new.itemData(self.selector_state_new.currentIndex())
        self.par_new_fieldname = self.selector_par_new.itemData(self.selector_par_new.currentIndex())
        self.polling_new_fieldname = self.selector_polling_new.itemData(self.selector_polling_new.currentIndex())
        self.par_new_prefix = self.selector_target_state.itemData(self.selector_target_state.currentIndex())

        delta = self.get_delta()
        if (not self.voters_fieldname or
                not self.polling_old_fieldname or
                not self.state_old_fieldname or
                not self.par_old_fieldname or
                not self.state_new_fieldname or
                not self.par_new_fieldname or
                not self.polling_new_fieldname or
                not self.par_new_prefix or
                not delta):
            self.iface.error("Some fields are unspecified")
            return

        try:
            self.balancer_old = Balancer(self.layer,
                                         self.voters_fieldname,
                                         self.polling_old_fieldname,
                                         self.state_old_fieldname,
                                         self.par_old_fieldname,
                                         delta)

            self.balancer_new = Balancer(self.layer,
                                         self.voters_fieldname,
                                         self.polling_new_fieldname,
                                         self.state_new_fieldname,
                                         self.par_new_fieldname,
                                         delta,
                                         self.balancer_old.par_average,
                                         self.balancer_old.state_average,
                                         self.balancer_old.par_count,
                                         self.balancer_old.state_count,
                                         state_prefix_format="N%03d",
                                         par_prefix_format="{}%02d".format(self.par_new_prefix))
        except ValueError:
            self.iface.error("The specified voters field is not a number")
            return

        QObject.connect(self.clickTool,
                        SIGNAL("canvasClicked(const QgsPoint &, Qt::MouseButton)"),
                        self.canvas_clicked)
        QObject.connect(self.layer, SIGNAL("selectionChanged()"), self.live_show)
        # QObject.connect(self.selector_map_type, SIGNAL('currentIndexChanged(const QString &)'),
        # self.map_type_change)

        self.btRebalance.setStyleSheet("background-color: red")
        self.btRebalance.setText("Stop Balancer")
        self.selector_target_state.setEnabled(False)
        self.selector_voters.setEnabled(False)
        self.selector_polling_old.setEnabled(False)
        self.selector_state_old.setEnabled(False)
        self.selector_par_old.setEnabled(False)
        self.selector_state_new.setEnabled(False)
        self.selector_par_new.setEnabled(False)
        self.selector_layers.setEnabled(False)
        self.selector_layers.setEnabled(False)
        self.selector_polling_new.setEnabled(False)
        self.btLoadLayer.setEnabled(False)
        self.tbDelta.setEnabled(False)

        self.statistics_update()

        self.btDuplicate.setEnabled(True)
        self.btUpdateAttributes.setEnabled(True)
        self.btClearSelected.setEnabled(True)
        self.btReset.setEnabled(True)
        self.selector_map_type.setEnabled(True)
        self.selector_seat_type.setEnabled(True)
        self.selector_overlay_type.setEnabled(True)
        self.btRedrawLayer.setEnabled(True)
        self.btGenerateKML.setEnabled(True)
        self.btRenumber.setEnabled(True)
        self.btShowTopology.setEnabled(True)

        # checkboxes
        self.cb_label.setEnabled(True)
        self.cb_feature_id.setEnabled(True)

        # set following only after balancers initialised
        self.selector_target_state.setEnabled(False)

        # save state
        self.combobox_state_save()
        self.layer_redraw()
        self.balancer_started = True
        self.iface.info("{} features found. Balancer started.".format(self.balancer_old.get_features_total()[2]), 4)

        # populate best deviation after redraw
        # bestmin, bestmax = self.balancer_old.get_best_deviation()
        # self.label_best_deviation.setText("{:.2f}%/{:.2f}%".format(bestmin, bestmax))

        QMessageBox().information(self,
                                  "{} features found. Balancer started.".format(
                                      self.balancer_old.get_features_total()[2]),
                                  """Right mouse button: Get details of clicked feature
                                      \nLeft mouse button: Toggle feature selection
                                      \nDouble click: Toggle entire state""")

    def feature_selector_init(self):
        self.selector_state.clear()
        self.selector_par.clear()
        balancer = self.get_balancer()

        for s in balancer.get_state_code_sequence():
            self.selector_state.addItem(balancer.state_prefix_format % s, s)

        for p in balancer.get_par_code_sequence():
            self.selector_par.addItem(balancer.par_prefix_format % p, p)

        # update unused codes
        total = self.balancer_old.get_features_total()
        current = self.balancer_new.get_features_total()

        self.label_live_par.setText("Parliament/{}".format(total[0] - current[0]))
        self.label_live_state.setText("State/{}".format(total[1] - current[1]))

    def balancer_stop(self):
        if not self.balancer_started:
            return

        if QObject:
            if self.clickTool:
                QObject.disconnect(self.clickTool,
                                   SIGNAL("canvasDoubleClicked(const QgsPoint &, Qt::MouseButton)"),
                                   self.canvas_doubleclicked)
                QObject.disconnect(self.clickTool,
                                   SIGNAL("canvasClicked(const QgsPoint &, Qt::MouseButton)"),
                                   self.canvas_clicked)
            if self.layer:
                QObject.disconnect(self.layer, SIGNAL("selectionChanged()"),
                                   self.live_show)

            QObject.disconnect(self.selector_map_type, SIGNAL('currentIndexChanged(const QString&)'),
                               self.map_type_change)

        self.btRebalance.setStyleSheet("background-color: green")
        self.btRebalance.setText("Start Balancer")
        self.selector_target_state.setEnabled(True)
        self.selector_voters.setEnabled(True)
        self.selector_polling_old.setEnabled(True)
        self.selector_state_old.setEnabled(True)
        self.selector_par_old.setEnabled(True)
        self.selector_state_new.setEnabled(True)
        self.selector_par_new.setEnabled(True)
        self.selector_layers.setEnabled(True)
        self.selector_polling_new.setEnabled(True)
        self.btLoadLayer.setEnabled(True)
        self.tbDelta.setEnabled(True)

        # disable
        self.btDuplicate.setEnabled(False)
        self.btUpdateAttributes.setEnabled(False)
        self.btRedrawLayer.setEnabled(False)
        self.btClearSelected.setEnabled(False)
        self.btReset.setEnabled(False)
        self.selector_map_type.setEnabled(False)
        self.selector_seat_type.setEnabled(False)
        self.selector_overlay_type.setEnabled(False)
        self.btGenerateKML.setEnabled(False)
        self.btRenumber.setEnabled(False)
        self.btShowTopology.setEnabled(False)

        # checkboxes
        self.cb_label.setEnabled(False)
        self.cb_feature_id.setEnabled(False)

        self.balancer_started = False
        self.iface.info("Balancer stopped")


class DelimitationToolboxConfigDialog(QDialog, CONFIG_FORM_CLASS):
    saved = pyqtSignal()

    def __init__(self, parent=None):
        """Constructor."""
        super(DelimitationToolboxConfigDialog, self).__init__(parent)
        self.setModal(True)
        self.setupUi(self)
        self.dock = parent
        self.__path = os.path.split(__file__)[0]
        QObject.connect(self.btSave, SIGNAL("clicked()"), self.save_config)
        QObject.connect(self.btReset, SIGNAL("clicked()"), self.confirm_reset)

    def show(self):
        # load settings
        content = Configuration().read_qt(Configuration.SETTINGS)
        if not content:
            with open(os.path.join(self.__path, configuration.defaultConfigFile), 'r') as f:
                content = f.readall()
        self.txt_settings.setText(content)

        # load styles
        polling = Delimitation.get_config_polling()
        self.txt_Polling.setText(polling)
        state = Delimitation.get_config_state()
        self.txt_State.setText(state)
        parliamentary = Delimitation.get_config_parliament()
        self.txt_Parliamentary.setText(parliamentary)

        others = Configuration().read_qt_file(Configuration.KML_OTHERS, "others.style")
        self.txt_Others.setText(others)

        super(DelimitationToolboxConfigDialog, self).show()
        self.exec_()

    def save_config(self):

        # todo: check settings for syntax errors
        Configuration().store_qt(Configuration.SETTINGS, self.txt_settings.toPlainText())
        Configuration().store_qt(Configuration.KML_POLLING, self.txt_Polling.toPlainText())
        Configuration().store_qt(Configuration.KML_STATE, self.txt_State.toPlainText())
        Configuration().store_qt(Configuration.KML_PARLIAMENTARY, self.txt_Parliamentary.toPlainText())
        Configuration().store_qt(Configuration.KML_OTHERS, self.txt_Others.toPlainText())

        # reload configuration
        Configuration().load()

        self.saved.emit()
        self.close()

    def confirm_reset(self):
        confirmation = QMessageBox.question(self,
                                            "Configuration Reset",
                                            "Are you sure? This will reset all configuration changes. If necessary, " +
                                            "ensure that you have made a backup.",
                                            QMessageBox.Yes | QMessageBox.No)
        if confirmation == QMessageBox.Yes:
            self.reset_config()

    def reset_config(self):
        content = ""
        with codecs.open(filename=os.path.join(self.__path, defaultConfigFile), mode='r', encoding='utf-8') as f:
            content = f.read()

        Configuration().store_qt(Configuration.SETTINGS, content)

        with codecs.open(filename=os.path.join(self.__path, "polling.style"), mode='r', encoding='utf-8') as f:
            content = f.read()
        Configuration().store_qt(Configuration.KML_POLLING, content)

        with codecs.open(filename=os.path.join(self.__path, "state.style"), mode='r', encoding='utf-8') as f:
            content = f.read()
        Configuration().store_qt(Configuration.KML_STATE, content)

        with codecs.open(filename=os.path.join(self.__path, "parliament.style"), mode='r', encoding='utf-8') as f:
            content = f.read()
        Configuration().store_qt(Configuration.KML_PARLIAMENTARY, content)

        with codecs.open(filename=os.path.join(self.__path, "others.style"), mode='r', encoding='utf-8') as f:
            content = f.read()
        Configuration().store_qt(Configuration.KML_OTHERS, content)

        # reload configuration
        Configuration().load()
        self.dock.populate_state_selector()
        self.close()


class DelimitationMapTool(QgsMapToolEmitPoint, object):
    canvasDoubleClicked = pyqtSignal(object, object)

    def __init__(self, canvas):
        super(DelimitationMapTool, self).__init__(canvas)

    def canvasDoubleClickEvent(self, e):
        point = self.toMapCoordinates(e.pos())
        self.canvasDoubleClicked.emit(point, e.button())
        super(DelimitationMapTool, self).canvasDoubleClickEvent(e)


