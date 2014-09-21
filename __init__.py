# -*- coding: utf-8 -*-
"""
/***************************************************************************
 DelimitationToolbox
 delimitation.py                       A QGIS plugin
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
import os
import sys

def classFactory(iface):  # pylint: disable=invalid-name
    """Load DelimitationToolbox class from file DelimitationToolbox.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    delimitation_path = os.path.split(__file__)[0]
    package_path = os.path.join(delimitation_path, "packages")
    sys.path.append(package_path)

    try:
        from helper import debug2
        debug2.init_remote()
    except:
        pass

    import configuration
    configuration.DEBUG = delimitation_path.find('Debug') != -1

    from delimitationtoolbox import DelimitationToolbox
    return DelimitationToolbox(iface)
