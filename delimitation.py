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
import traceback
from PyQt4 import QtCore
import ogr
import osr
from colouring import Colouring
import os
from zipfile import ZipFile
import csv
import glob
import re
from enum import Enum
from qgis.core import QgsVectorLayer, QgsFeature, QgsVectorFileWriter, QgsGeometry, QgsMapLayerRegistry
from helper.qgis_util import get_spatialreference
from lxml import etree
from configuration import Configuration
from packages.pykml.factory import KML_ElementMaker as KML
from packages.pykml.factory import GX_ElementMaker as GX
from helper.ui import open_folder, MessageType

# ogr.UseExceptions()
#osr.UseExceptions()


class OutputFlag(Enum):
    __order__ = 'Shapefile_KML Shapefile KML_ONLY'  # only needed in 2.x
    Shapefile_KML = 1
    Shapefile = 2
    KML_ONLY = 4


class LayerType(Enum):
    __order__ = 'Polling State Parliament'  # only needed in 2.x
    Polling = 1
    State = 2
    Parliament = 4


class Layers(object):
    def __init__(self):
        self.features = {}
        self.schema = {}

    def add(self, features, layer_type):
        if layer_type in self.features:
            self.features[layer_type].extend(features)
        else:
            self.features[layer_type] = features

    def add_schema(self, schema, layer_type):
        self.schema[layer_type] = schema

    @staticmethod
    def get_schema_name(layertype):
        return "{0}schema".format(Configuration().read(layertype.name, "prefix"))

    @staticmethod
    def get_style_name(layertype, prefix=""):
        return "{0}style{1}".format(Configuration().read(layertype.name, "prefix"), prefix).lower()

    @staticmethod
    def get_stylemap_name(layertype):
        return "{0}stylemap".format(Configuration().read(layertype.name, "prefix")).lower()

    @staticmethod
    def sortkey_expression(layer_type):
        sortkey = Configuration().read(layer_type.name, "sort")
        return lambda x: x.attributes[sortkey]

    def export_kml_schema(self, layer_type, idstring, namestring):
        kml = KML.Schema(id=idstring, name=namestring)
        for name in self.schema[layer_type]:
            sf = KML.SimpleField(name=name, type="string")
            kml.append(sf)

        return kml

    def groupsort(self, layertype, groupkey=None):
        if groupkey is None:
            groupkey = Configuration().read(layertype.name, "sort")
        self.features[layertype].sort(key=lambda x: x.attributes[groupkey])


class ShapeFileBase(object):
    def __init__(self, layertype, srcepsg):
        self.layer_type = layertype
        self.epsg = srcepsg
        self.__spatial_reference = None

    @property
    def spatial_refence(self):
        if self.__spatial_reference is None:
            self.__spatial_reference = osr.SpatialReference()
            self.__spatial_reference.ImportFromEPSG(self.epsg)
        return self.__spatial_reference


class Feature(ShapeFileBase):
    @property
    def attributes(self):
        return self.__attributes

    @property
    def geometry(self):
        return self.__qgs_geometry

    def __init__(self, id, attributes, geometry, srcepsg, layertype):
        super(Feature, self).__init__(layertype, int(srcepsg))
        self.id = id
        self.__attributes = attributes
        self.__qgs_geometry = geometry

    def get_name(self):
        mformat = Configuration().read(self.layer_type.name, "name_format")
        mvalues = [self.__attributes[x.strip()] for x in Configuration().read(self.layer_type.name, "name_columns")]

        return mformat.format(*mvalues)

    def __get_kml_polygon(self):
        in_crs = osr.SpatialReference()
        in_crs.ImportFromEPSG(self.epsg)
        transform = osr.CoordinateTransformation(get_spatialreference(self.epsg), get_spatialreference(4326))
        geom = ogr.CreateGeometryFromWkt(self.__qgs_geometry.exportToWkt())
        geom.Transform(transform)

        return etree.fromstring(geom.ExportToKML("clampToGround"))

    def __get_draworder(self):
        return Configuration().read(self.layer_type.name, "kml_draworder")

    # returns a placemark object
    def export_as_placemark(self, fillcolour=None):
        schemaurl = Layers.get_schema_name(self.layer_type)
        styleurl = Layers.get_stylemap_name(self.layer_type)

        placemark = KML.Placemark(
            KML.name(self.get_name()),
            KML.styleUrl('#' + styleurl)
        )

        if fillcolour is not None:
            placemark.append(
                KML.Style(
                    KML.PolyStyle(
                        KML.color('88' + fillcolour),
                    )
                )
            )

        extdata = KML.ExtendedData(
            KML.SchemaData(schemaUrl='#' + schemaurl))
        for attr in self.__attributes.items():
            data = KML.SimpleData(attr[1], name=attr[0])
            extdata.SchemaData.append(data)

        placemark.append(extdata)
        geom = self.__get_kml_polygon()
        self.__append_draworder(geom)

        placemark.append(geom)

        return placemark

    def __append_draworder(self, root):
        if root.tag == 'Polygon':
            do = GX.drawOrder(self.__get_draworder())
            root.append(do)
        elif root.tag == 'MultiGeometry':
            for polygon in root.getchildren():
                self.__append_draworder(polygon)
        else:
            raise Exception('Unknown Polygon type => {}'.format(root.tag))


class Delimitation(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)
    #error = QtCore.pyqtSignal(Exception, basestring)
    progress = QtCore.pyqtSignal(float)
    message = QtCore.pyqtSignal(Enum, basestring)

    def __init__(self, region_name, source_path, dest_path=None):
        QtCore.QObject.__init__(self)

        self.__all_attribute_fieldnames = set()
        self.__input_directory = source_path
        self.killed = False

        if not dest_path:
            dest_path = os.path.join(os.path.normpath(source_path), Configuration().read("KML", "outputdir"))
        self.__output_directory = dest_path

        self.__working_name = region_name

        # qgis
        self.map_layers = {}
        self.master_layer = None

        if not os.path.isdir(self.__output_directory):
            os.mkdir(self.__output_directory)

    def __get_output_file(self, prefix=""):
        return os.path.join(self.__output_directory, "{}{}.shp".format(prefix, self.__working_name))

    def __create_master_layer(self, filepath):
        src_filepath = filepath
        if not os.path.isabs(src_filepath):
            src_filepath = os.path.join(self.__input_directory, src_filepath)

        # Read the original Shapefile
        input_layer = QgsVectorLayer(src_filepath, self.__working_name, "ogr")

        # get csv file
        csvfilename = glob.glob1(self.__input_directory, '*.csv')[0]
        csvfile_abs = os.path.join(self.__input_directory, csvfilename)

        # we need to also add all attributes in both State and Parliamentary map_layers
        # because we obtain value from POLL layer when merging
        for layertype in LayerType:
            self.__all_attribute_fieldnames.update(Configuration().read(layertype.name, "attributes"))

        authid = input_layer.dataProvider().crs().authid()
        if not authid:
            raise Exception("Unable to determine EPSG for {}".format(src_filepath))
        fieldstrings = ["field={}:string(120)".format(x) for x in self.__all_attribute_fieldnames]
        fieldstrings.append("crs={}".format(authid))
        fieldstrings.append("index=yes")

        # create temp layer
        self.master_layer = QgsVectorLayer("Polygon?{}".format("&".join(fieldstrings)), "temporary_layer", "memory")

        # read csv into a dict first
        iop = 0
        csv_map = {}
        key_columns = Configuration().read("CSV", "columns")

        with open(csvfile_abs, "rb") as csvfile:
            reader = csv.DictReader(csvfile, delimiter=',', quoting=csv.QUOTE_NONE)
            rows = list(reader)
            totalrows = len(rows)
            for row in rows:
                iop += 1
                self.progress.emit(int(100 * iop / totalrows))
                csv_map.update({tuple([row[k] for k in key_columns]): row})

        # go thru each polygon
        match_feat_name = Configuration().read("CSV", "field")

        self.message.emit(MessageType.Normal, "Using {} in {} to match attribute {} in {}."
                          .format(", ".join(key_columns), csvfilename, match_feat_name, filepath))

        nop = csv_map.__len__()
        master_provider = self.master_layer.dataProvider()
        try:
            for f in input_layer.getFeatures():
                iop += 1
                self.progress.emit(int(100 * iop / nop))

                # insert attributes
                attributes = []
                row_match_value = f[match_feat_name]
                if row_match_value:
                    match_feat_value = row_match_value.strip()
                else:
                    raise Exception("{} in Feature {} has no value".format(match_feat_name, f.id()))

                regexp = Configuration().read("CSV", "regexp")
                match = re.match(regexp, match_feat_value, re.I)
                if not match:
                    raise Exception("{} attribute value of {} is in the incorrect format".format(match_feat_name,
                                                                                                 match_feat_value))

                match_values = []
                for i, col in enumerate(key_columns):
                    match_values.append(match.group(i + 1))

                row = csv_map.get(tuple(match_values), None)
                if row is None:
                    raise Exception("Unable to find {} in CSV file".format("/".join(match_values)))

                for entry in self.__all_attribute_fieldnames:
                    attributes.append(row[entry])

                feature = QgsFeature()
                feature.setGeometry(f.geometry())
                feature.setAttributes(attributes)
                master_provider.addFeatures([feature])
        except Exception, e:
            raise e
        finally:
            del master_provider

        self.message.emit(MessageType.OK, "Insertion complete. {} attributes added to {} features"
                          .format(self.master_layer.dataProvider().fields().__len__(),
                                  self.master_layer.dataProvider().featureCount()))

    def __merge_polygons(self, output_layertype):
        dissolve_fieldname = Configuration().read(output_layertype.name, "merge")
        msg = "Dissolving/merging using {}".format(dissolve_fieldname)
        self.message.emit(MessageType.Normal, msg)

        input_layer = self.master_layer

        # merge/dissolve features
        vprovider = input_layer.dataProvider()
        nfeat = vprovider.featureCount()
        dissolve_field_index = input_layer.fieldNameIndex(dissolve_fieldname)
        fields = ["field={}:string(120)".format(x.name()) for x in vprovider.fields()]
        fields.append("index=yes")
        authid = vprovider.crs().authid()
        if not authid:
            del vprovider
            raise Exception("Unable to determine EPSG for {}".format(vprovider.name()))
        merged_layer = QgsVectorLayer("Polygon?crs={}&{}".format(authid, "&".join(fields)),
                                      "temporary_merge", "memory")
        merged_provider = merged_layer.dataProvider()
        try:
            out_feat = QgsFeature()
            nelement = 0
            unique = get_unique_values(input_layer, int(dissolve_field_index))
            nfeat *= len(unique)
            attrs = None
            for item in unique:
                first = True
                add = True
                for inFeat in input_layer.getFeatures():
                    nelement += 1
                    self.progress.emit(int(100 * nelement / nfeat))
                    attr_map = inFeat.attributes()
                    temp_item = attr_map[dissolve_field_index]
                    if unicode(temp_item).strip() == unicode(item).strip():
                        if first:
                            QgsGeometry(inFeat.geometry())
                            tmp_ingeom = QgsGeometry(inFeat.geometry())
                            out_feat.setGeometry(tmp_ingeom)
                            first = False
                            attrs = inFeat.attributes()
                        else:
                            tmp_ingeom = QgsGeometry(inFeat.geometry())
                            tmp_outgeom = QgsGeometry(out_feat.geometry())
                            try:
                                tmp_outgeom = QgsGeometry(
                                    tmp_outgeom.combine(tmp_ingeom))
                                out_feat.setGeometry(tmp_outgeom)
                            except:
                                raise Exception('Geometry exception while dissolving')
                if add:
                    out_feat.setAttributes(attrs)
                    merged_provider.addFeatures([out_feat])
            merged_layer.commitChanges()
        except:
            raise Exception("Merge failed.")
        finally:
            del vprovider
            del merged_provider

        self.message.emit(MessageType.OK, "Merge completed.")
        return merged_layer

    def run_generate_shapefile_kml(self):
        self.generate(OutputFlag.Shapefile_KML)

    def run_generate_shapefile(self):
        self.generate(OutputFlag.Shapefile)

    def run_generate_kml(self):
        self.generate(OutputFlag.KML_ONLY)

    def generate(self, outputflag):
        try:
            from helper import debug2

            debug2.init_remote(5677)
        except:
            pass

        fail = ""
        try:
            if outputflag == OutputFlag.Shapefile_KML:
                self.generate_vector_file(LayerType.Polling, True)
                self.generate_vector_file(LayerType.State)
                self.generate_vector_file(LayerType.Parliament)
                self.generate_kml()
            elif outputflag == OutputFlag.Shapefile:
                self.generate_vector_file(LayerType.Polling, True)
            elif outputflag == OutputFlag.KML_ONLY:
                self.generate_vector_file(LayerType.State)
                self.generate_vector_file(LayerType.Parliament)
                self.generate_kml()
            else:
                raise Exception('Unknown output type')
        except Exception, e:
            self.message.emit(MessageType.Fail, "{}\n".format(e.message.__str__()))
            fail = traceback.format_exc()

        self.finished.emit(fail.__str__())

    def generate_vector_file(self, layertype, writetodisk=False, src_layer=None):
        if not src_layer:
            if self.master_layer is None:
                src_dir = Configuration().read_qt(Configuration.SRC_DIR)
                shapefiles = glob.glob1(src_dir, '*.shp')
                self.__create_master_layer(shapefiles[0])
                src_layer = self.master_layer

        if layertype == LayerType.State or layertype == LayerType.Parliament:
            src_layer = self.__merge_polygons(layertype)

        fields_uri = ["field={}:string(120)".format(x) for x in Configuration().read(layertype.name, "attributes")]
        fields_uri.append("index=yes")
        self.message.emit(MessageType.Normal, "Generating {} layer ...".format(layertype.name))
        authid = src_layer.dataProvider().crs().authid()
        if not authid:
            raise Exception("Unable to determine EPSG for {}".format(src_layer.dataProvider().name()))
        out_layer = QgsVectorLayer(
            "Polygon?crs={}&{}".format(authid, "&".join(fields_uri)),
            "temporary_generate", "memory")
        out_provider = out_layer.dataProvider()
        for temp_f in src_layer.getFeatures():
            feature = QgsFeature()
            feature.setGeometry(temp_f.geometry())
            attributes = []
            attr_map = temp_f.attributes()
            for fname in Configuration().read(layertype.name, "attributes"):
                attributes.append(attr_map[src_layer.fieldNameIndex(fname)])
            feature.setAttributes(attributes)
            out_provider.addFeatures([feature])

        del out_provider
        self.map_layers.setdefault(layertype, []).append(out_layer)

        if writetodisk:
            filepath = self.__get_output_file(Configuration().read(layertype.name, "prefix"))
            _, filename = os.path.split(filepath)
            error = QgsVectorFileWriter.writeAsVectorFormat(out_layer, filepath, "utf-8", None, "ESRI Shapefile")
            if error == QgsVectorFileWriter.NoError:
                self.message.emit(MessageType.OK, "{} written".format(filename))
            else:
                self.message.emit(MessageType.Fail, "Failed to write {}. {}".format(filename, error))
            return

        self.message.emit(MessageType.OK, "{} layer generated".format(layertype.name))

    def generate_kml(self):
        self.message.emit(MessageType.Normal, "Generating Google Earth file ...")

        layers = Layers()
        # extract POLL, STATE and PAR layers
        for ltype, lyrs in self.map_layers.items():
            features = []
            for l in lyrs:
                prod = l.dataProvider()
                attr_keys = [a.name() for a in prod.fields()]
                for f in prod.getFeatures():
                    _, epsg = prod.crs().authid().split(":")
                    new_f = Feature(f.id(), dict(zip(attr_keys, f.attributes())),
                                    f.geometryAndOwnership(),
                                    epsg,
                                    ltype)
                    features.append(new_f)
                layers.add(features, ltype)
                layers.add_schema(attr_keys, ltype)
                del prod

        # group/sort features
        for state_index in layers.features.keys():
            if state_index == LayerType.Polling:
                # different for POLLs as they are only unique within the same STATE
                layers.groupsort(state_index, Configuration().read(LayerType.State.name, "sort"))
            else:
                layers.groupsort(state_index)

        # init colour
        colouring = Colouring()
        features_state = dict([(f.id, {"geom": f.geometry}) for f in layers.features[LayerType.State]])
        colouring.init_colours(features=features_state)

        kmldoc = KML.kml()

        root = KML.Document(
            KML.name(self.__working_name),
            KML.open(1))
        kmldoc.append(root)

        # add schema
        for state_index in layers.features.keys():
            idname = layers.get_schema_name(state_index)
            root.append(layers.export_kml_schema(state_index, idname, idname))

        # add style
        styles = [self.get_config_polling(), self.get_config_state(), self.get_config_parliament(),
                  self.get_config_others()]
        for style in styles:
            branch = etree.fromstring(style)

            for element in list(branch):
                root.append(element)

        # add category folders
        par_folder = None
        state_folder = None
        poll_folder = None
        for item in Configuration().read("KML", "kml_folders"):
            folder = KML.Folder(KML.name(item))
            root.append(folder)
            if folder.name == Configuration().read(LayerType.Parliament.name, "kml_folder"):
                par_folder = folder
            elif folder.name == Configuration().read(LayerType.State.name, "kml_folder"):
                state_folder = folder
            elif folder.name == Configuration().read(LayerType.Polling.name, "kml_folder"):
                poll_folder = folder

        # now we populate the folders
        state_index = 0
        poll_index = 0
        for par in layers.features[LayerType.Parliament]:
            # add par polygon
            par_folder.append(par.export_as_placemark())

            # get states
            states = []
            field_match_par = Configuration().read(LayerType.Parliament.name, "merge")
            field_match_state = Configuration().read(LayerType.State.name, "merge")
            statelist = layers.features[LayerType.State][state_index:]
            for i in range(len(statelist)):
                state = statelist[i]
                if state.attributes[field_match_par] == par.attributes[field_match_par]:
                    states.append(state)
                else:
                    break
                state_index += 1

            # add par folder to state folder
            state_par_folder = KML.Folder(KML.name(par.get_name()))
            state_folder.append(state_par_folder)

            # generate poll colours grouped by state
            states.sort(key=Layers.sortkey_expression(LayerType.State))
            for state in states:
                state_colour = colouring.get_colour(colouring.gColouring[state.id]).hex[1:]
                polls = []
                # add state polygon
                state_par_folder.append(state.export_as_placemark())
                polllist = layers.features[LayerType.Polling][poll_index:]
                for j in range(len(polllist)):
                    poll = polllist[j]
                    if poll.attributes[field_match_par] == \
                            par.attributes[field_match_par] and \
                                    poll.attributes[field_match_state] == \
                                    state.attributes[field_match_state]:
                        polls.append(poll)
                    else:
                        break
                    poll_index += 1

                # add state folder to poll folder
                poll_state_folder = KML.Folder(KML.name(state.get_name()))
                poll_folder.append(poll_state_folder)

                # sort and add poll polygon
                polls.sort(key=Layers.sortkey_expression(LayerType.Polling))
                for poll in polls:
                    poll_state_folder.append(poll.export_as_placemark(fillcolour=state_colour))

        # validate kml
        # if sys.flags.debug:
        # self.__validate_kml()

        # save to disk
        with open("doc.kml", "w") as txt_file:
            txt_file.write(etree.tostring(etree.ElementTree(kmldoc), pretty_print=True))

        # zip everything up
        outputkmz = os.path.join(self.__output_directory, '{}.kmz'.format(self.__working_name))
        with ZipFile(outputkmz, 'w') as myzip:
            myzip.write("doc.kml")
            resource_files = Configuration().read("KML", "resource_files")
            for resource in resource_files:
                myzip.write(os.path.join(self.__input_directory, resource), resource)

        os.remove("doc.kml")

        self.message.emit(MessageType.OK, "{}.kmz created".format(self.__working_name))

        # open folder
        open_folder(self.__output_directory)

    @staticmethod
    def get_config_parliament():
        return Configuration().read_qt_file(Configuration.KML_PARLIAMENTARY, "parliament.style")

    @staticmethod
    def get_config_state():
        return Configuration().read_qt_file(Configuration.KML_STATE, "state.style")

    @staticmethod
    def get_config_polling():
        return Configuration().read_qt_file(Configuration.KML_POLLING, "polling.style")

    @staticmethod
    def get_config_others():
        return Configuration().read_qt_file(Configuration.KML_OTHERS, "others.style")

    def get_working_files(self, layertypes):
        files = []
        for l in layertypes:
            f = self.__get_output_file(Configuration().read(l.name, "prefix"))
            files.append(os.path.abspath(f))

        return files

    def kill(self):
        self.killed = True


def get_unique_values(layer, field_index):
    values = []
    for feat in layer.getFeatures():
        if feat.attributes()[field_index] not in values:
            values.append(feat.attributes()[field_index])
    return values

