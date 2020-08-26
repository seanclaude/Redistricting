# -*- coding: utf-8 -*-

"""
/***************************************************************************
 Redistricting
 Electorate Rebalancing and Redistricting
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
from qgis.core import QGis, QgsRectangle, QgsCoordinateTransform, QgsVectorLayer, \
    QgsPalLayerSettings, QgsSymbolV2, QgsRendererCategoryV2, QgsPoint, \
    QgsCategorizedSymbolRendererV2, QgsFeatureRequest, QgsGeometry, QgsExpression, QgsMapLayerRegistry
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from PyQt4 import uic, QtGui, QtCore
from PyQt4.QtCore import Qt, QObject, SIGNAL, QVariant
from PyQt4.QtGui import QComboBox, QDockWidget, QColor, QFileDialog, QMessageBox, QDialog, QLineEdit, \
    QWidget
import json
import os
import math
import codecs
from balancer import Balancer
import configuration as config
from helper.qgis_util import extend_qgis_interface
from helper.string import parse_float
from configuration import KEY_AREA, KEY_CIRCULARITY, KEY_COMPACTNESS, KEY_VOTERS
from layer_type import LayerType
from redistricting import tr

FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'ui_redistricting_dock.ui'))
CONFIG_FORM_CLASS, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'ui_configuration.ui'))
CONSTITUENCIES_FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), 'ui_redistricting_constituencies.ui'))
STATS_WIDGET, _ = uic.loadUiType(os.path.join(os.path.dirname(__file__), 'ui_widget_statistics.ui'))

RESX = {
    "balancer_not_started": tr("Action aborted. Press the start button first.")
}


class RedistrictingDock(QDockWidget, FORM_CLASS):
    def __init__(self, iface, parent=None):
        """Constructor."""
        super(RedistrictingDock, self).__init__(parent)
        # Set up the user interface from Designer.
        # After setupUI you can access any designer object by doing
        # self.<objectname>, and you can use autoconnect slots - see
        # http://qt-project.org/doc/qt-4.8/designer-using-a-ui-file.html
        # #widgets-and-dialogs-with-auto-connect
        self.setupUi(self)

        # load configuration
        config.Configuration().load()

        # coordinate transform
        self.coordinateTransform = None

        # threads
        self.thread = None
        self.worker = None
        self.progressBar = None

        # label layer
        self.palyr = QgsPalLayerSettings()

        # init the sub dialogs
        self.configuration = DelimitationToolboxConfigDialog(self)
        self.configuration.saved.connect(self.populate_state_selector)
        self.constituencies = RedistrictingConstituenciesDialog(self)

        # init widgets
        self.stats_old = QStatsWidget()
        self.layout_stats_old.addWidget(self.stats_old)
        self.stats_new = QStatsWidget()
        self.layout_stats_new.addWidget(self.stats_new)

        self.topology = None
        self.id_graph = None
        self.balancer_new = None
        self.balancer_old = None
        self.layer_id = None

        # extensions
        self.iface = extend_qgis_interface(iface)
        self.clickTool_prev = None
        self.clickTool = DelimitationMapTool(self.iface.mapCanvas())
        self.clickTool.canvasDoubleClicked.connect(self.canvas_doubleclicked)
        self.clickTool.canvasSingleClicked.connect(self.canvas_clicked)

        # manual rebalancer
        self.balancer_started = False
        self.clicked_feature_id = None
        self.layer = None
        self.context_fieldname = None
        self.polling_old_fieldname = None
        self.state_old_fieldname = None
        self.par_old_fieldname = None
        self.state_new_fieldname = None
        self.par_new_fieldname = None
        self.polling_new_fieldname = None
        self.par_new_prefix = None

        self.btLoadLayer.clicked.connect(self.layer_select)
        self.btShowTopology.clicked.connect(self.constituencies.show)
        self.tab_rebalance.currentChanged.connect(self.tab_change_handler)

        # todo : dropping layers and files
        QObject.connect(self.btRenumber, SIGNAL("clicked()"), self.layer_renumber)
        QObject.connect(self.btRebalance, SIGNAL("clicked()"), self.balancer_start)
        QObject.connect(self.btRebalanceStop, SIGNAL("clicked()"), self.balancer_stop)
        QObject.connect(self.btEditConfig, SIGNAL("clicked()"), self.configuration.show)
        QObject.connect(self.btDuplicate, SIGNAL("clicked()"), self.layer_copy_old)
        QObject.connect(self.btRedrawLayer, SIGNAL("clicked()"), self.layer_redraw)
        QObject.connect(self.selector_state, SIGNAL('currentIndexChanged(const QString&)'),
                        self.live_show)
        QObject.connect(self.selector_par, SIGNAL('currentIndexChanged(const QString&)'),
                        self.live_show)
        # http://qgis.org/api/classQgsMapCanvas.html
        self.cb_label.stateChanged.connect(self.label_handler)
        self.cb_feature_id.stateChanged.connect(self.label_handler)
        self.cb_old_id.stateChanged.connect(self.label_handler)

        # monitor layer selection change
        QObject.connect(self.btClearSelected, SIGNAL("clicked()"), self.selection_clear)
        QObject.connect(self.btReset, SIGNAL("clicked()"), self.layer_reset)
        QObject.connect(self.btUpdateAttributes, SIGNAL("clicked()"), self.selection_update)
        self.iface.mapCanvas().layersChanged.connect(self.layer_changed)
        QObject.connect(self.selector_layers, SIGNAL('currentIndexChanged(int)'),
                        self.layer_preload)

        # populate state
        self.populate_state_selector()

        self.selector_par_old.currentIndexChanged[int].connect(self.load_par_field)
        self.selector_state_old.currentIndexChanged[int].connect(self.load_state_field)

    def closeEvent(self, e):
        self.balancer_stop()
        self.constituencies.close()
        self.iface.mapCanvas().layersChanged.disconnect(self.layer_changed)
        self.clickTool.canvasDoubleClicked.disconnect(self.canvas_doubleclicked)
        self.clickTool.canvasSingleClicked.disconnect(self.canvas_clicked)

        self.layer = None

    @staticmethod
    def extract_stats(dic, key):
        itemlist = []
        for v in dic.itervalues():
            itemlist.append(v[key])

        itemlist.sort()
        length = len(itemlist)
        min_value = min(itemlist)
        max_value = max(itemlist)
        median = -1
        if not length % 2:
            median = (itemlist[length / 2] + itemlist[length / 2 - 1]) / 2.0
        else:
            median = itemlist[length / 2]

        return min_value, median, max_value

    def statistics_update(self):
        total_area = math.fsum([v[config.KEY_GEOMETRY].area() for v in self.balancer_old.topology_par.values()]) / 1000 / 1000

        self.label_total_area.setText("{:.0f} sqr kms".format(total_area))
        self.label_context_total.setText(str(self.balancer_old.total_voters))
        self.label_context_label.setText("{}".format(self.context_fieldname))

        self.label_stats_eq.setText(parse_float("{}%".format(self.tbDelta.text()) * 100))

        # old stats
        self.balancer_old.statistics_calculate(self.coordinateTransform)

        old_areas_state = self.extract_stats(self.balancer_old.state_statistics, KEY_AREA)
        old_circularity_state = self.extract_stats(self.balancer_old.state_statistics, KEY_CIRCULARITY)
        old_areas_par = self.extract_stats(self.balancer_old.par_statistics, KEY_AREA)
        old_circularity_par = self.extract_stats(self.balancer_old.par_statistics, KEY_CIRCULARITY)

        old_unused = self.balancer_old.get_unused()
        if old_areas_par.__len__():
            self.stats_old.setParValues(old_unused[0].__len__(),
                                        self.balancer_old.par_count_limit,
                                        self.balancer_old.parmin_actual_precentage,
                                        self.balancer_old.parmax_actual_precentage,
                                        self.balancer_old.par_average,
                                        old_areas_par,
                                        old_circularity_par)

        if old_areas_state.__len__():
            self.stats_old.setStateValues(old_unused[1].__len__(),
                                          self.balancer_old.state_count_limit,
                                          self.balancer_old.statemin_actual_precentage,
                                          self.balancer_old.statemax_actual_precentage,
                                          self.balancer_old.state_average,
                                          old_areas_state,
                                          old_circularity_state)

        # new stats
        self.balancer_new.statistics_calculate(self.coordinateTransform)
        new_areas_state = self.extract_stats(self.balancer_new.state_statistics, KEY_AREA)
        new_circularity_state = self.extract_stats(self.balancer_new.state_statistics, KEY_CIRCULARITY)
        new_areas_par = self.extract_stats(self.balancer_new.par_statistics, KEY_AREA)
        new_circularity_par = self.extract_stats(self.balancer_new.par_statistics, KEY_CIRCULARITY)
        new_unused = self.balancer_new.get_unused()

        if new_areas_par.__len__():
            self.stats_new.setParValues(new_unused[0].__len__(),
                                        self.balancer_new.par_count_limit,
                                        self.balancer_new.parmin_actual_precentage,
                                        self.balancer_new.parmax_actual_precentage,
                                        self.balancer_new.par_average,
                                        new_areas_par,
                                        new_circularity_par)

        if new_areas_state.__len__():
            self.stats_new.setStateValues(new_unused[1].__len__(),
                                          self.balancer_new.state_count_limit,
                                          self.balancer_new.statemin_actual_precentage,
                                          self.balancer_new.statemax_actual_precentage,
                                          self.balancer_new.state_average,
                                          new_areas_state,
                                          new_circularity_state)

    def load_par_field(self, index):
        if not self.layer or index < 1:
            return

        par_fieldname = self.selector_par_old.currentText()
        pars = set()
        for f in self.layer.getFeatures():
            if par_fieldname:
                pars.add(f[par_fieldname])

        self.tb_old_par_count.setText(str(pars.__len__()))
        if not self.tb_new_par_count.text():
            self.tb_new_par_count.setText(str(pars.__len__()))

    def load_state_field(self, index):
        if not self.layer or index < 1:
            return

        state_fieldname = self.selector_state_old.currentText()
        states = set()

        for f in self.layer.getFeatures():
            if state_fieldname:
                states.add(f[state_fieldname])

        self.tb_old_state_count.setText(str(states.__len__()))
        if not self.tb_new_state_count.text():
            self.tb_new_state_count.setText(str(states.__len__()))

    def live_show(self):
        """update totals and statistics"""

        if not self.layer:
            return

        if self.selector_state.currentIndex() == -1 or self.selector_par.currentIndex() == -1:
            return

        selectedfeatureids = self.layer.selectedFeaturesIds()
        self.label_selected.setText("Selected ({})".format(len(selectedfeatureids)))

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
        self.label_par_voters.setText("{} ({})".format(voters_par, states_per_par))
        self.lb_recommendation.setText(balancer.recommendation_by_par(str(current_par)))

        if balancer.state_average:
            delta_state = voters_state - balancer.state_average
            delta_state_percentage = 100 * delta_state / balancer.state_average
            self.label_delta_state.setText("{:.2f}%".format(delta_state_percentage))
            self.label_delta_state.setToolTip("{:.0f}".format(delta_state))
            self.label_selected_state.setText("{:.2f}%".format(100 * voters_selected / balancer.state_average))
            self.label_selected_state.setToolTip("{}".format(voters_selected))

        if balancer.par_average:
            delta_par = voters_par - balancer.par_average
            delta_par_percentage = 100 * delta_par / balancer.par_average
            self.label_delta_par.setText("{:.2f}%".format(delta_par_percentage))
            self.label_delta_par.setToolTip("{:.0f}".format(delta_par))
            self.label_selected_par.setText("{:.2f}%".format(100 * voters_selected / balancer.par_average))
            self.label_selected_par.setToolTip("{}".format(voters_selected))

    def layer_copy_old(self):
        import re

        confirmation = QMessageBox.question(self,
                                            "Overwrite values",
                                            "Are you sure? Any newly allocated IDs will be overwritten.",
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

            self.balancer_new.topology_update(
                {row[0]: {
                    self.state_new_fieldname: new_state,
                    self.par_new_fieldname: new_par,
                    self.polling_new_fieldname: new_polling}})

        self.layer.commitChanges()
        self.balancer_new.topology_dirty = True
        self.layer_redraw(True)
        self.iface.info("Done")

    def layer_reset(self):
        confirmation = QMessageBox.question(self,
                                            "Reset values",
                                            """Are you sure? This operation will permanently remove all new allocated IDs.
                                                You will need to start all over again from the beginning.""",
                                            QMessageBox.Yes | QMessageBox.No)
        if confirmation == QMessageBox.No:
            return

        self.layer.startEditing()
        for k, v in self.balancer_new.topology_polling.items():
            self.layer.changeAttributeValue(k, self.layer.fieldNameIndex(self.polling_new_fieldname), None)
            self.layer.changeAttributeValue(k, self.layer.fieldNameIndex(self.state_new_fieldname), None)
            self.layer.changeAttributeValue(k, self.layer.fieldNameIndex(self.par_new_fieldname), None)

        self.layer.commitChanges()
        self.balancer_new.topology_dirty = True
        self.layer_redraw(True)
        self.iface.info("Attribute fields reset")

    def label_handler(self):
        self.label_update()
        self.iface.mapCanvas().refresh()

    def label_update(self):
        self.palyr.readFromLayer(self.layer)

        if self.cb_label.isChecked() or self.cb_feature_id.isChecked():
            self.palyr.enabled = True
        else:
            self.palyr.enabled = False

        expr = []
        balancer = self.get_balancer()

        if self.cb_feature_id.isChecked():
            if self.cb_old_id.isChecked():
                # force display of old ID
                expr.append(self.balancer_old.get_feature_label())
            else:
                expr.append(balancer.get_feature_label())

        if self.cb_label.isChecked():
            if self.selector_seat_type.currentIndex() == 1:
                divisor = balancer.par_average
            elif self.selector_seat_type.currentIndex() == 0:
                divisor = balancer.state_average
            else:
                raise Exception("Unknown seat type")

            if expr.__len__():
                expr.append("'\\n'")

            expr.append("round({}*100.0/{}, 2)".format(self.context_fieldname, divisor))

        self.palyr.fieldName = "concat({})".format(",".join(expr))
        self.palyr.isExpression = True
        self.palyr.placement = QgsPalLayerSettings.OverPoint
        self.palyr.setDataDefinedProperty(QgsPalLayerSettings.Size, True, True, '8', '')
        # rendering distance

        self.palyr.writeToLayer(self.layer)

    def tab_change_handler(self, index):
        if index == 3:
            self.statistics_update()

    def ui_state_save(self):
        saved_state = {}
        for widget in self.findChildren(QComboBox):
            saved_state.update({widget.objectName(): widget.currentIndex()})

        for widget in self.findChildren(QLineEdit):
            saved_state.update({widget.objectName(): widget.text()})

        config.Configuration().store_qt(config.Configuration.UI_STATE, json.dumps(saved_state))

    def ui_state_load(self, excludes=None):
        if not excludes:
            excludes = []
        try:
            saved_state = json.loads(config.Configuration().read_qt(config.Configuration.UI_STATE))
        except:
            return

        for widget in self.findChildren(QComboBox):
            if widget.objectName() in saved_state and widget.objectName() not in excludes:
                widget.setCurrentIndex(saved_state[widget.objectName()])

        for widget in self.findChildren(QLineEdit):
            if widget.objectName() in saved_state and widget.objectName() not in excludes:
                widget.setText(saved_state[widget.objectName()])

    def layer_select(self):
        # startdir = Configuration().read_qt(Configuration.SRC_DIR)
        startdir = os.path.join(os.path.split(__file__)[0], "data")

        filepath = QFileDialog.getOpenFileName(parent=self,
                                               caption='Select shapefile',
                                               filter="*.shp",
                                               directory=startdir)
        if filepath:
            path, filename = os.path.split(filepath)

            # remember selected path
            config.Configuration().store_qt(config.Configuration.SRC_DIR, path)

            name, ext = os.path.splitext(filename)
            # don't assign layer to self yet. only after balancer has started
            layer = QgsVectorLayer(filepath, name, "ogr")
            # layer = self.iface.addVectorLayer(filepath, name, "ogr")
            if not layer.isValid():
                self.iface.error("Layer failed to load!")
                return

            QgsMapLayerRegistry.instance().addMapLayer(layer)
            self.layer_add_to_selector(layer)

    def layer_preload(self, index):
        layer_id = self.selector_layers.itemData(index)

        for layer in self.iface.mapCanvas().layers():
            if layer.id() == layer_id:
                self.layer = layer
                self.layer_load()

    def layer_add_to_selector(self, layer):
        self.selector_layers.addItem(layer.name(), layer.id())

    def layer_changed(self):
        layer_found = False
        selected_index = self.selector_layers.currentIndex()
        layer_id = self.selector_layers.itemData(selected_index)

        for layer in self.iface.mapCanvas().layers():
            # add layer if it's not in the list
            if layer.id() == layer_id:
                layer_found = True

            if self.selector_layers.findData(layer.id()) == -1 and \
               layer.type() == layer.VectorLayer and \
               layer.geometryType() == 2:
                self.layer_add_to_selector(layer)

        if not layer_found:
            # handle just started
            if selected_index != -1:
                self.selector_layers.removeItem(selected_index)
            else:
                if self.selector_layers.count() != 0:
                    selected_index = 0
                    self.selector_layers.setCurrentIndex(selected_index)
                    layer_found = True

        if layer_found:
            self.layer_preload(selected_index)
        else:
            if self.balancer_started:
                self.balancer_stop()
            else:
                self.layer = None

        return layer_found

    def layer_selectors_clear(self):
        self.selector_context.clear()
        self.selector_polling_old.clear()
        self.selector_state_old.clear()
        self.selector_par_old.clear()
        self.selector_state_new.clear()
        self.selector_par_new.clear()
        self.selector_polling_new.clear()

        self.selector_context.addItem("Select field ...", "")
        self.selector_polling_old.addItem("Select poll district ...", "")
        self.selector_state_old.addItem("Select state ...", "")
        self.selector_par_old.addItem("Select par ...", "")
        self.selector_state_new.addItem("Select state ...", "")
        self.selector_par_new.addItem("Select par ...", "")
        self.selector_polling_new.addItem("Select poll district ...", "")

    def layer_load(self):
        self.layer_selectors_clear()

        if self.layer is None:
            return

        self.iface.info("Reading layer definition {}".format(self.layer.id()))
        provider = self.layer.dataProvider()
        fields = provider.fields()
        try:
            for field in fields:
                field_name = field.name()
                self.selector_context.addItem(field_name, field_name)
                self.selector_polling_old.addItem(field_name, field_name)
                self.selector_state_old.addItem(field_name, field_name)
                self.selector_par_old.addItem(field_name, field_name)
                self.selector_state_new.addItem(field_name, field_name)
                self.selector_par_new.addItem(field_name, field_name)
                self.selector_polling_new.addItem(field_name, field_name)
        except Exception, e:
            self.iface.error(e.message)
        finally:
            del provider

        # load save state
        self.ui_state_load(["selector_layers", "selector_map_type"])

    def layer_redraw(self, zoom_to_layer=False):
        if not self.balancer_started:
            self.iface.warning(RESX["balancer_not_started"])
            return

        delta = self.get_delta()
        if not delta:
            return

        # update info
        self.label_map_type.setText(self.selector_map_type.currentText())

        balancer = self.get_balancer()
        balancer.topology_load()
        balancer.init_colouring()

        # init selectors
        self.feature_selector_init()

        # update label parameters
        self.label_update()

        seat_type = self.selector_seat_type.currentIndex()
        if seat_type == 0:
            # state
            get_colour_method = balancer.get_colour_by_state
            attr_prefix = balancer.state_prefix_format
            attr_name = balancer.state_field
            colouring = balancer.colouring_state
            self.label_context_type.setText("State")
        else:
            # par
            get_colour_method = balancer.get_colour_by_parliament
            attr_prefix = balancer.par_prefix_format
            attr_name = balancer.par_field
            colouring = balancer.colouring_par
            self.label_context_type.setText("Parliament")

        geomtype = self.layer.geometryType()

        if self.selector_overlay_type.currentIndex() == 2:
            # load adjacency layers
            name = self.selector_target_state.currentText()
            state_alayer = balancer.adjlayer_make(name, LayerType.State)
            par_alayer = balancer.adjlayer_make(name, LayerType.Parliament)

            existing_layerids = []
            for lyr in [state_alayer, par_alayer]:
                existing_layerids.extend(
                    [x.id() for x in QgsMapLayerRegistry.instance().mapLayersByName(lyr.name()) if x is not None])

            QgsMapLayerRegistry.instance().removeMapLayers(existing_layerids)
            QgsMapLayerRegistry.instance().addMapLayer(state_alayer)
            QgsMapLayerRegistry.instance().addMapLayer(par_alayer)
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
        # self.iface.mapCanvas().setDirty(True)
        self.iface.mapCanvas().clearCache()
        """
        if zoom_to_layer:
            extent = self.iface.mapCanvas().mapSettings().layerToMapCoordinates(self.layer, self.layer.extent())
            self.iface.mapCanvas().setExtent(extent)
            self.iface.mapCanvas().zoomToNextExtent()
        """
        self.iface.mapCanvas().refresh()

    def layer_renumber(self):
        balancer = self.get_balancer()
        if balancer.readonly:
            self.iface.warning("You cannot edit the old map. Please select the new map.")
            return

        confirmation = QMessageBox.question(self,
                                            "Reorder allocation",
                                            "Are you sure? This will renumber and " +
                                            "reorganise all the parliament, state and polling district IDs.",
                                            QMessageBox.Yes | QMessageBox.No)
        if confirmation == QMessageBox.No:
            return

        self.layer.startEditing()
        if not self.balancer_new.resequence():
            self.iface.error("Renumber failed! There are geometry errors. Please run geometry and topology checker.")
            self.layer.rollBack()
            self.layer.endEditCommand()
            return

        par_used = [v[self.par_new_fieldname] for v in self.balancer_new.topology_polling.values()]
        state_used = [v[self.state_new_fieldname] for v in self.balancer_new.topology_polling.values()]

        if set(par_used).__len__() > self.balancer_new.par_count_limit or \
                        set(state_used).__len__() > self.balancer_new.state_count_limit:
            self.iface.error("Allocation limit exceeded")
            self.layer.rollBack()
            self.layer.endEditCommand()
            return

        self.layer.commitChanges()
        self.iface.info("Renumbering completed.")

        self.layer_redraw(True)

    def canvas_doubleclicked(self, point, button):
        current_state = self.selector_state.itemData(self.selector_state.currentIndex())
        current_par = self.selector_par.itemData(self.selector_par.currentIndex())
        balancer = self.get_balancer()
        par_field = balancer.par_field
        state_field = balancer.state_field
        ids = []
        if button == Qt.LeftButton:
            if current_state and current_par:
                ids = [int(k) for k, v in balancer.topology_polling.items()
                       if v[par_field] == str(current_par) and v[state_field] == str(current_state)]
        elif button == Qt.RightButton:
            if current_par:
                ids = [int(k) for k, v in balancer.topology_polling.items()
                       if v[par_field] == str(current_par)]
        else:
            self.iface.warning("What button did you just click??")
            return

        if set(ids) \
                .difference(self.layer.selectedFeaturesIds()) \
                .difference([self.clicked_feature_id]) \
                .__len__() == 0:
            self.layer.modifySelection([], ids)
        else:
            self.layer.modifySelection(ids, [])

    def canvas_rectangle(self, p):
        # setup the provider select to filter results based on a rectangle
        point = QgsGeometry().fromPoint(p)
        # scale-dependent buffer of 2 pixels-worth of map units
        buff = point.buffer((self.iface.mapCanvas().mapUnitsPerPixel() * 2), 0)
        rect_pseudo = buff.boundingBox()
        rect = self.iface.mapCanvas().mapSettings().mapToLayerCoordinates(self.layer, rect_pseudo)

        return rect

    def canvas_clicked(self, geom, button):
        import re

        if not self.balancer_started:
            self.iface.warning(RESX["balancer_not_started"])
            return

        if self.layer is None:
            self.iface.warning("Active layer not found")
            return

        rect = None
        if type(geom) is QgsPoint:
            rect = self.canvas_rectangle(geom)
        elif type(geom) is QgsRectangle:
            rect = geom

        feats = []
        balancer = self.get_balancer()
        for f in balancer.topology_polling.iteritems():
            if f[1][config.KEY_GEOMETRY].intersects(rect):
                feats.append(f)

        if feats.__len__() == 0:
            self.layer.removeSelection()
            return

        # changed_feature = (feature id, values)
        changed_feature = feats[0]
        self.clicked_feature_id = changed_feature[0]

        if button == Qt.RightButton:
            # update selectors & recalculate
            balancer = self.get_balancer()

            self.tab_rebalance.setCurrentIndex(1)
            # changed_feature = (feature id, values)
            raw_par = changed_feature[1][balancer.par_field]
            if raw_par:
                par_val = int(re.search(r'\d+', str(raw_par)).group())
                selector_par_index = self.selector_par.findData(par_val)
                if selector_par_index != -1:
                    self.selector_par.setCurrentIndex(selector_par_index)

            raw_state = changed_feature[1][balancer.state_field]
            if raw_state:
                state_val = int(re.search(r'\d+', str(raw_state)).group())
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
            [entry.split(':') for entry in config.Configuration().read("Settings", "state_prefixes")])

    def selection_update(self):
        if not self.balancer_started:
            self.iface.warning(RESX["balancer_not_started"])
            return

        balancer = self.get_balancer()

        # don't allow write to old layer
        if balancer.readonly:
            self.iface.warning("Old map is read only. Please switch to the new map for rebalancing.")
            return

        if len(self.layer.selectedFeatures()) == 0:
            self.iface.warning("Nothing selected. Click on a feature to select it.")
            return

        current_state = balancer.state_prefix_format % self.selector_state.itemData(
            self.selector_state.currentIndex())
        current_par = balancer.par_prefix_format % self.selector_par.itemData(self.selector_par.currentIndex())

        confirmation = QMessageBox.question(self,
                                            "Confirm action",
                                            "Move selected features to the following constituencies?\n\n" +
                                            "Parliament:{}\nState:{}".format(current_par, current_state),
                                            QMessageBox.Yes | QMessageBox.No)
        if confirmation == QMessageBox.Yes:
            self.layer.startEditing()
            updates = [(current_par, current_state)]
            for f in self.layer.selectedFeatures():
                updates.append((f[self.par_new_fieldname], f[self.state_new_fieldname]))
                balancer.topology_update(
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
                    balancer.topology_update(
                        {f.id(): {self.polling_new_fieldname: balancer.polling_prefix_format % (i + 1)}})

            self.layer.commitChanges()
            self.selection_clear()
            self.layer_redraw(False)

            self.iface.info("Selected features updated")

    def selection_clear(self):
        if self.layer is None:
            return

        self.layer.setSelectedFeatures([])

    def get_balancer(self):
        """0=old map, 1=new map"""
        if self.label_map_type.text() == self.selector_map_type.itemData(1, Qt.DisplayRole):
            return self.balancer_new

        return self.balancer_old

    def get_delta(self):
        delta = parse_float(self.tbDelta.text())
        if not delta or delta < 0:
            self.iface.info("Please specify a value greater than 0")
        return delta

    def balancer_destroy(self):
        self.balancer_old = None
        self.balancer_new = None

    def balancer_start(self):
        if not self.layer:
            self.iface.error(
                "Redistricting plugin not started. Layer is missing, invalid or changed externally. Please reload layer.")
            return

        # save state
        self.ui_state_save()

        self.iface.mapCanvas().setCurrentLayer(self.layer)

        if not self.tb_new_par_count.text().isdigit() or \
                not self.tb_new_state_count.text().isdigit():
            self.iface.error("Total parliamentary and state seats must be integer values")
            return

        delta = self.get_delta()
        if (self.selector_context.currentIndex() <= 0 or
            self.selector_polling_old.currentIndex() <= 0 or
            self.selector_state_old.currentIndex() <= 0 or
            self.selector_par_old.currentIndex() <= 0 or
            self.selector_state_new.currentIndex() <= 0 or
            self.selector_par_new.currentIndex() <= 0 or
            self.selector_polling_new.currentIndex() <= 0 or
            self.selector_target_state.currentIndex() <= 0 or
                not delta or
                not self.tb_new_par_count.text() or
                not self.tb_new_state_count.text()):
            self.iface.error("Some fields are unspecified")
            return

        layer_crs = self.layer.dataProvider().crs()
        if layer_crs.projectionAcronym() != 'merc' or \
                        self.iface.mapCanvas().mapSettings().destinationCrs().projectionAcronym() != 'merc':
            self.iface.warning(
                "The current working layer is not using a mercator projection like EPSG:3857. Area calculations will not work.")

        provider = self.layer.dataProvider()
        self.coordinateTransform = QgsCoordinateTransform(layer_crs,
                                                          self.iface.mapCanvas().mapSettings().destinationCrs())

        err_fields = []

        self.context_fieldname = self.selector_context.itemData(self.selector_context.currentIndex())
        if not provider.fields().at(provider.fieldNameIndex(self.context_fieldname)).isNumeric():
            self.iface.error("The {} (voters field) must be an integer number field.".format(self.context_fieldname))
            del provider
            return

        self.polling_old_fieldname = self.selector_polling_old.itemData(self.selector_polling_old.currentIndex())
        self.par_new_prefix = self.selector_target_state.itemData(self.selector_target_state.currentIndex())

        # the following needs to be text fields
        self.state_old_fieldname = self.selector_state_old.itemData(self.selector_state_old.currentIndex())
        if provider.fields().at(provider.fieldNameIndex(self.state_old_fieldname)).type() != QVariant.String:
            err_fields.append(self.state_old_fieldname)
        self.par_old_fieldname = self.selector_par_old.itemData(self.selector_par_old.currentIndex())
        if provider.fields().at(provider.fieldNameIndex(self.par_old_fieldname)).type() != QVariant.String:
            err_fields.append(self.par_old_fieldname)
        self.state_new_fieldname = self.selector_state_new.itemData(self.selector_state_new.currentIndex())
        if provider.fields().at(provider.fieldNameIndex(self.state_new_fieldname)).type() != QVariant.String:
            err_fields.append(self.state_new_fieldname)
        self.par_new_fieldname = self.selector_par_new.itemData(self.selector_par_new.currentIndex())
        if provider.fields().at(provider.fieldNameIndex(self.par_new_fieldname)).type() != QVariant.String:
            err_fields.append(self.par_new_fieldname)
        self.polling_new_fieldname = self.selector_polling_new.itemData(self.selector_polling_new.currentIndex())

        del provider

        if err_fields.__len__() != 0:
            self.iface.error("The following fields must be text fields: {}".format(", ".join(err_fields)))
            return

        if self.layer_id != self.layer.id():
            self.balancer_destroy()

        self.layer_id = self.layer.id()

        try:
            # just need to do this once as this layer doesn't ever get changed
            if self.balancer_old is None:
                self.balancer_old = Balancer("old", self.layer,
                                             self.context_fieldname,
                                             self.polling_old_fieldname,
                                             self.state_old_fieldname,
                                             self.par_old_fieldname,
                                             delta)

            self.balancer_new = Balancer("new", self.layer,
                                         self.context_fieldname,
                                         self.polling_new_fieldname,
                                         self.state_new_fieldname,
                                         self.par_new_fieldname,
                                         delta,
                                         par_count_limit=int(self.tb_new_par_count.text()),
                                         state_count_limit=int(self.tb_new_state_count.text()),
                                         state_prefix_format="N%03d",
                                         par_prefix_format="{}%02d".format(self.par_new_prefix),
                                         polling_prefix_format="%02d",
                                         readonly=False)
        except AttributeError, attr_e:
            self.iface.error("Specified fields must be part of a sequence of numbers")
            self.balancer_destroy()
            return

        self.layer.selectionChanged.connect(self.live_show)

        # init click tool
        self.clickTool_prev = self.iface.mapCanvas().mapTool()
        self.iface.mapCanvas().setMapTool(self.clickTool)
        self.balancer_started = True
        self.panel_active.setCurrentIndex(1)
        self.iface.info("{} features found. Redistricting plugin started ({})."
                        .format(self.balancer_old.topology_polling.keys().__len__(),
                                self.layer.id()), 4)
        self.layer_redraw(True)

    def feature_selector_init(self):
        selected_state = self.selector_state.currentIndex()
        selected_par = self.selector_par.currentIndex()

        self.selector_state.clear()
        self.selector_par.clear()
        balancer = self.get_balancer()
        unused = balancer.get_unused()
        unused_colour = QColor(Qt.green)

        for i, s in enumerate(balancer.get_state_code_sequence()):
            self.selector_state.insertItem(i, balancer.state_prefix_format % s, s)
            if str(s) in unused[1]:
                self.selector_state.setItemData(i, unused_colour, Qt.BackgroundRole)

        for i, p in enumerate(balancer.get_par_code_sequence()):
            self.selector_par.insertItem(i, balancer.par_prefix_format % p, p)
            if str(p) in unused[0]:
                self.selector_par.setItemData(i, unused_colour, Qt.BackgroundRole)

        self.selector_state.setCurrentIndex(selected_state)
        self.selector_par.setCurrentIndex(selected_par)

    def balancer_stop(self):
        if not self.balancer_started:
            return

        self.iface.mapCanvas().unsetMapTool(self.clickTool)
        self.iface.mapCanvas().setMapTool(self.clickTool_prev)

        self.panel_active.setCurrentIndex(0)
        self.balancer_started = False
        self.iface.info("Redistricting plugin stopped")


class QStatsWidget(QWidget, STATS_WIDGET):
    def __init__(self, parent=None):
        super(QWidget, self).__init__(parent)
        self.setupUi(self)

    def setStateValues(self, unused, total, smin, smax, voters_mean, area, compactness):
        self.lb_state_unused.setText(str(unused))
        self.lb_state_total.setText(str(total))
        self.lb_state_voter_size.setText("{:.2f}% {:.2f}%".format(smin, smax))
        self.lb_state_mean_voters.setText("{:.0f}".format(voters_mean))
        self.lb_state_size.setText("{:.1f}/{:.1f}/{:.1f}".format(area[0], area[1], area[2]))
        self.lb_state_compact.setText("{:.2f}/{:.2f}/{:.2f}".format(compactness[0], compactness[1], compactness[2]))

    def setParValues(self, unused, total, pmin, pmax, voters_mean, area, compactness):
        self.lb_par_unused.setText(str(unused))
        self.lb_par_total.setText(str(total))
        self.lb_par_voter_size.setText("{:.2f}% {:.2f}%".format(pmin, pmax))
        self.lb_par_mean_voters.setText("{:.0f}".format(voters_mean))
        self.lb_par_size.setText("{:.1f}/{:.1f}/{:.1f}".format(area[0], area[1], area[2]))
        self.lb_par_compact.setText("{:.2f}/{:.2f}/{:.2f}".format(compactness[0], compactness[1], compactness[2]))


class RedistrictingConstituenciesDialog(QDialog, CONSTITUENCIES_FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(RedistrictingConstituenciesDialog, self).__init__(parent)
        self.setModal(False)
        self.setupUi(self)
        self.dock = parent
        self.table_topo.cellClicked.connect(self.topology_cell_clicked)

    def show(self):
        self.topology_display()

        super(RedistrictingConstituenciesDialog, self).show()
        self.exec_()

    def topology_cell_clicked(self, row, column):
        """only the state ID is utilised"""
        import re

        # if user has clicked on another layer, this will not work, set it back
        if self.dock.layer.id() != self.dock.iface.mapCanvas().currentLayer().id():
            self.dock.iface.mapCanvas().setCurrentLayer(self.dock.layer)

        # unselect first
        self.dock.selection_clear()

        id_cell = self.table_topo.item(row, 5)  # get state id
        if not id_cell:
            self.iface.error("No data to identify features for selection")
            return

        state_id = int(re.search(r'\d+', id_cell.text()).group()).__str__()

        balancer = self.dock.get_balancer()

        ids = [int(k) for k, v in balancer.topology_polling.items()
               if v[balancer.state_field] == state_id]

        self.dock.layer.modifySelection(ids, [])
        self.dock.iface.mapCanvas().panToSelected()
        self.dock.live_show()

    def topology_display(self):
        balancer = self.dock.get_balancer()

        balancer.statistics_calculate(self.dock.coordinateTransform)

        pars = sorted(balancer.map_par_state.items())
        rows = []
        for par in pars:
            par_id = balancer.par_prefix_format % int(par[0])
            par_size = par[1][KEY_VOTERS]
            par_dev = par[1]['d']
            par_geom_stats = balancer.par_statistics[par[0]]
            for state in sorted(par[1]['states'].items()):
                state_id = balancer.state_prefix_format % int(state[0])
                state_size = state[1][0]
                state_dev = state[1][1]
                state_geom_state = balancer.state_statistics[state[0]]
                rows.append((par_id,
                             ("{} ({}%)".format(par_size, par_dev), par_size),
                             ("{:.2f}".format(par_geom_stats[KEY_AREA]), par_geom_stats[KEY_AREA]),
                             ("{:.2f}".format(par_geom_stats[KEY_CIRCULARITY]), par_geom_stats[KEY_CIRCULARITY]),
                             ("{:.2f}".format(par_geom_stats[KEY_COMPACTNESS]), par_geom_stats[KEY_COMPACTNESS]),
                             state_id,
                             ("{} ({}%)".format(state_size, state_dev), state_size),
                             ("{:.2f}".format(state_geom_state[KEY_AREA]), state_geom_state[KEY_AREA]),
                             ("{:.2f}".format(state_geom_state[KEY_CIRCULARITY]), state_geom_state[KEY_CIRCULARITY]),
                             ("{:.2f}".format(state_geom_state[KEY_COMPACTNESS]), state_geom_state[KEY_COMPACTNESS])
                ))

        self.table_topo.clearContents()
        self.table_topo.setRowCount(rows.__len__())
        self.table_topo.setSortingEnabled(False)

        row_count = 0
        for row in rows:
            # par
            pname = QtGui.QTableWidgetItem(row[0])
            pname.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 0, pname)

            # par size
            psize = QTableWidgetNumberItem(row[1][0], row[1][1])
            psize.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 1, psize)

            # par area
            parea = QTableWidgetNumberItem(row[2][0], row[2][1])
            parea.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 2, parea)

            # par circularity
            pcirc = QTableWidgetNumberItem(row[3][0], row[3][1])
            pcirc.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 3, pcirc)

            # par compactness
            pcompactness = QTableWidgetNumberItem(row[4][0], row[4][1])
            pcompactness.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 4, pcompactness)

            # state
            sname = QtGui.QTableWidgetItem(row[5])
            sname.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 5, sname)

            # state size
            ssize = QTableWidgetNumberItem(row[6][0], row[6][1])
            ssize.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 6, ssize)

            # area
            sarea = QTableWidgetNumberItem(row[7][0], row[7][1])
            sarea.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 7, sarea)

            # s circularity
            scirc = QTableWidgetNumberItem(row[8][0], row[8][1])
            scirc.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 8, scirc)

            # compactness
            scompactness = QTableWidgetNumberItem(row[9][0], row[9][1])
            scompactness.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_topo.setItem(row_count, 9, scompactness)

            row_count += 1

        unused_totals = balancer.get_unused()
        if unused_totals[0].__len__() == 0:
            self.label_free_pars.setText("-")
        else:
            self.label_free_pars.setText(", ".join(unused_totals[0]))

        if unused_totals[1].__len__() == 0:
            self.label_free_states.setText("-")
        else:
            self.label_free_states.setText(", ".join(unused_totals[1]))

        self.table_topo.setSortingEnabled(True)


class DelimitationToolboxConfigDialog(QDialog, CONFIG_FORM_CLASS):
    saved = QtCore.pyqtSignal()

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
        content = config.Configuration().read_qt(config.Configuration.SETTINGS)
        if not content:
            with open(os.path.join(self.__path, config.defaultConfigFile), 'r') as f:
                content = f.readall()
        self.txt_settings.setText(content)

        super(DelimitationToolboxConfigDialog, self).show()
        self.exec_()

    def save_config(self):

        # todo: check settings for syntax errors
        config.Configuration().store_qt(config.Configuration().SETTINGS, self.txt_settings.toPlainText())

        # reload configuration
        config.Configuration().load()

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
        with codecs.open(filename=os.path.join(self.__path,
                                               config.defaultConfigFile),
                         mode='r',
                         encoding='utf-8') as f:
            content = f.read()

        config.Configuration().store_qt(config.Configuration.SETTINGS, content)

        # reload configuration
        config.Configuration().load()
        self.dock.populate_state_selector()
        self.close()


class DelimitationMapTool(QgsMapToolEmitPoint, object):
    canvasDoubleClicked = QtCore.pyqtSignal(object, object)
    canvasSingleClicked = QtCore.pyqtSignal(object, object)

    def __init__(self, canvas):
        self.map_units = canvas.mapUnitsPerPixel()
        self.start_point = None
        self.end_point = None
        self.dragging = False
        self.selecting = False
        self.double_click = False
        self.button_clicked = None
        self.rubberBand = QgsRubberBand(canvas, QGis.Polygon)
        self.rubberBand.setColor(QColor(133, 99, 6, 128))
        self.rubberBand.setWidth(1)
        self.reset()
        super(DelimitationMapTool, self).__init__(canvas)

    def canvasDoubleClickEvent(self, e):
        point = self.toMapCoordinates(e.pos())
        self.double_click = True
        self.canvasDoubleClicked.emit(point, e.button())

    def canvasPressEvent(self, e):
        point = self.toMapCoordinates(e.pos())
        self.start_point = point
        self.button_clicked = e.button()

    def canvasReleaseEvent(self, e):
        self.end_point = self.toMapCoordinates(e.pos())
        if not self.mouse_moved() and not self.double_click:
            self.canvasSingleClicked.emit(self.end_point, e.button())
        else:
            if self.dragging:
                self.canvas().panActionEnd(e.pos())
            if self.selecting:
                r = self.rectangle()
                if r is not None:
                    self.canvasSingleClicked.emit(r, e.button())
            elif self.double_click:
                pass

        self.reset()

    def mouse_moved(self):
        if self.start_point and \
                (math.fabs(self.end_point.x() - self.start_point.x()) > self.map_units and
                 math.fabs(self.end_point.y() - self.start_point.y()) > self.map_units):
            return True

        return False

    def canvasMoveEvent(self, e):
        self.end_point = self.toMapCoordinates(e.pos())
        if self.mouse_moved():
            if self.button_clicked == Qt.RightButton:
                self.canvas().panAction(e)
                self.dragging = True
            elif self.button_clicked == Qt.LeftButton:
                self.show_rect(self.start_point, self.end_point)
                self.selecting = True

    def rectangle(self):
        if self.start_point is None or self.end_point is None:
            return None
        elif not self.mouse_moved():
            return None

        return QgsRectangle(self.start_point, self.end_point)

    def reset(self):
        self.start_point = self.end_point = None
        self.selecting = False
        self.dragging = False
        self.double_click = False
        self.rubberBand.reset(QGis.Polygon)

    def show_rect(self, start, end):
        self.rubberBand.reset(QGis.Polygon)
        if start.x() == end.x() or start.y() == end.y():
            return

        point1 = QgsPoint(start.x(), start.y())
        point2 = QgsPoint(start.x(), end.y())
        point3 = QgsPoint(end.x(), end.y())
        point4 = QgsPoint(end.x(), start.y())

        self.rubberBand.addPoint(point1, False)
        self.rubberBand.addPoint(point2, False)
        self.rubberBand.addPoint(point3, False)
        self.rubberBand.addPoint(point4, True)  # true to update canvas
        self.rubberBand.show()


class QTableWidgetNumberItem(QtGui.QTableWidgetItem):
    def __init__(self, displaydata, number):
        QtGui.QTableWidgetItem.__init__(self, str(displaydata), QtGui.QTableWidgetItem.UserType)
        self.__number = number

    def __lt__(self, other):
        return self.__number < other.__number