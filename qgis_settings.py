from PyQt4.QtCore import QSettings

SRC_DIR = "DelimitationToolbox/src_directory"
CSV_FILE = "DelimitationToolbox/csv_file"
KML_OUT = "DelimitationToolbox/kml_out"

Settings = QSettings()


def read(key):
    return Settings.value(key, "")


def store(key, value):
    Settings.setValue(key, value)


