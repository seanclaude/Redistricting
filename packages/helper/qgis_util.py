import glob
import logging
import os
from osgeo import osr
from qgis.gui import QgisInterface, QgsMessageBar
from extensions import attach_method


def get_spatialreference(epsg):
    sf = {}
    if epsg in sf:
        return sf[epsg]

    sr = osr.SpatialReference()
    sr.ImportFromEPSG(epsg)
    sf[epsg] = sr
    return sr


def delete_shapefile(output_filename):
    """deletes other files that defines the shapefile as well"""
    outfilename, outfileextension = os.path.splitext(output_filename)
    for existing_file in glob.glob("{0}.*".format(outfilename)):
        os.remove(existing_file)


def get_epsg_from_shapefile(shapefile_path):
    """try get EPSG value from file"""
    from helper.string import parse_int
    epsg = None

    for ext in (".qpj", ".prj"):
        try:
            with open(shapefile_path.replace(".shp", ext), 'r') as prj_file:
                prj_txt = prj_file.read()
                srs = osr.SpatialReference()
                srs.ImportFromESRI([prj_txt])
                srs.AutoIdentifyEPSG()
                epsg = parse_int(srs.GetAuthorityCode(None))
                if epsg is not None:
                    break
        except RuntimeError as re:
            logging.debug(re)

    return epsg


def save_qpj(filepath, epsg):
    with open(filepath.replace(".shp", ".qpj"), 'w') as pfile:
        crs = osr.SpatialReference()
        crs.ImportFromEPSG(epsg)
        pfile.write(crs.ExportToWkt())


def extend_qgis_interface(instance):
    def info(self, message, duration=2):
        self.messageBar().pushMessage("Info", message, QgsMessageBar.INFO, duration)

    def warning(self, message, duration=8):
        self.messageBar().pushMessage("Warning", message, QgsMessageBar.WARNING, duration)

    def error(self, message, duration=10):
        self.messageBar().pushMessage("Error", message, QgsMessageBar.CRITICAL, duration)

    attach_method(info, instance, QgisInterface)
    attach_method(warning, instance, QgisInterface)
    attach_method(error, instance, QgisInterface)

    return instance





