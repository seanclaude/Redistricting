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
# This will get replaced with a git SHA1 when you do a git archive
from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, Qt
from PyQt4.QtGui import QAction, QIcon, QMainWindow, QDockWidget

__revision__ = '$Format:%H$'
__version__ = '0.1'
__pname__ = 'Redistricting'
__modname__ = 'Redistricting'

# Import the code for the dialog
import resources_rc


def tr(message):
    """Get the translation for a string using Qt translation API."""

    # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
    return QCoreApplication.translate(__modname__, message)

from redistricting_dock import RedistrictingDock
import os.path


class Redistricting:
    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """

        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            '{}_{}.qm'.format(__modname__, locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.dock = None

    def add_action(
            self,
            icon_path,
            text,
            callback,
            enabled_flag=True,
            add_to_menu=True,
            add_to_toolbar=True,
            status_tip=None,
            whats_this=None,
            parent=None):

        """Add a toolbar icon to the InaSAFE toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            __path (e.g. ':/plugins/foo/bar.png') or a normal file system __path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(__pname__, action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/{}/icon.png'.format(__modname__)
        self.add_action(
            icon_path,
            text=str(tr(__pname__)),
            callback=self.run,
            parent=self.iface.mainWindow())

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(
                tr(__pname__),
                action)
            self.iface.removeToolBarIcon(action)

        for w in self.iface.mainWindow().findChildren(QDockWidget):
            if w.windowTitle().find(__pname__) != -1:
                self.iface.mainWindow().removeDockWidget(w)

    def run(self):
        self.iface.mainWindow().setDockOptions(QMainWindow.AllowTabbedDocks)
        widget_other = None
        widget_exist = None
        for w in self.iface.mainWindow().findChildren(QDockWidget):
            if w.windowTitle().find(__pname__) != -1:
                widget_exist = w
            elif self.iface.mainWindow().dockWidgetArea(w) == Qt.RightDockWidgetArea:
                # we want the first one only
                if not widget_other:
                    widget_other = w

        # Create the dialog (after translation) and keep reference
        if widget_exist:
            self.iface.mainWindow().removeDockWidget(widget_exist)

        self.dock = RedistrictingDock(self.iface, self.iface.mainWindow())
        self.dock.setWindowTitle('{} {}'.format(__pname__, __version__))
        self.iface.mainWindow().addDockWidget(Qt.RightDockWidgetArea, self.dock)

        if widget_other:
            self.iface.mainWindow().tabifyDockWidget(widget_other, self.dock)

        self.dock.show()
        self.dock.raise_()
        self.dock.iface.info("{} loaded".format(__pname__))
