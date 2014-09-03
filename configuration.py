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
import codecs
import os
import cStringIO
import configparser
from helper.singleton import Singleton

defaultConfigFile = "default.ini"
__config_version__ = 1
from PyQt4.QtCore import QSettings


class Configuration(object):
    SRC_DIR = "DelimitationToolbox/src_directory"
    SETTINGS = "DelimitationToolbox/settings"
    KML_STATE = "DelimitationToolbox/balloon_state"
    KML_POLLING = "DelimitationToolbox/balloon_polling"
    KML_PARLIAMENTARY = "DelimitationToolbox/balloon_parliamentary"
    KML_OTHERS = "DelimitationToolbox/balloon_others"
    UI_STATE = "DelimitationToolbox/ui"
    VERSION = "DelimitationToolbox/config_version"

    __parser = None
    __basepath = None
    __metaclass__ = Singleton
    qsettings = QSettings()

    def __init__(self):
        self.__parser = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
        self.__basepath = os.path.split(__file__)[0]

    def _load_from_file(self):
        with codecs.open(filename=os.path.join(self.__basepath, defaultConfigFile), mode='r', encoding='utf-8') as f:
            return f.read()

    def load(self):
        txt = self.read_qt(Configuration.SETTINGS)
        if not txt:
            txt = self._load_from_file()
            self.store_qt(Configuration.SETTINGS, txt)
            self.__parser.read_string(txt)
        else:
            # compare versions to see if we need to update version stored in QGIS
            self.__parser.read_string(txt)
            self.update_version()

    def update_version(self):
        """check and fixes any differences between user's version and current release version"""
        stored_version = self.read_qt(Configuration.VERSION)
        if stored_version and stored_version == __config_version__:
            # nothing to do here
            return

        temp_parser = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())
        temp_parser.read_string(self._load_from_file())

        # remove old non-existant sections
        remove_sections = set(self.__parser.sections()).difference(set(temp_parser.sections()))
        map(lambda x: self.__parser.remove_section(x), remove_sections)

        # remove old non-existant keys
        for section in self.__parser.sections():
            for option in self.__parser.options(section):
                if not temp_parser.has_option(section, option):
                    self.__parser.remove_option(section, option)

        # add new section
        for section in temp_parser.sections():
            if not self.__parser.has_section(section):
                self.__parser.add_section(section)
            for option in temp_parser.options(section):
                if not self.__parser.has_option(section, option):
                    self.__parser.set(section, option, temp_parser.get(section, option))

        # save to qsettings
        string_output = cStringIO.StringIO()
        self.__parser.write(string_output)
        txt = string_output.getvalue()
        string_output.close()
        self.store_qt(Configuration.SETTINGS, txt)

        # update version
        self.store_qt(Configuration.VERSION, __config_version__)

    def read(self, section, option):
        result = self.__parser.get(section, option).encode('utf-8')
        if (result.__len__() and result[0] == "[") and (result[-1] == "]"):
            return [x.strip() for x in result[1:-1].split(',')]

        return result

    def read_qt(self, key):
        return self.qsettings.value(key)

    def read_qt_file(self, key, filename):
        content = self.read_qt(key)
        if not content:
            path = os.path.join(self.__basepath, filename)
            with open(path, 'r') as f:
                content = f.read()

        return content

    def store_qt(self, key, value):
        self.qsettings.setValue(key, value)
