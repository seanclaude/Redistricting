from PyQt4.QtCore import QSettings

SRC_DIR = "Redistricting/src_directory"
CSV_FILE = "Redistricting/csv_file"
KML_OUT = "Redistricting/kml_out"

Settings = QSettings()


def read(key):
    return Settings.value(key, "")


def store(key, value):
    Settings.setValue(key, value)


