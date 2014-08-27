import os
from lxml import etree
from osgeo import osr, ogr
from packages.enum import Enum
from configuration import Configuration
from packages.helper.qgis_util import get_epsg_from_shapefile, get_spatialreference
from packages.pykml.factory import KML_ElementMaker as KML
from packages.pykml.factory import GX_ElementMaker as GX


osr.UseExceptions()
ogr.UseExceptions()


class LayerType(Enum):
    __order__ = 'Polling State Parliament'  # only needed in 2.x
    Polling = 1
    State = 2
    Parliament = 3


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



