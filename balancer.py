"""
/***************************************************************************
 DelimitationToolbox
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

import math
import colouring
from configuration import KEY_CIRCULARITY, KEY_COMPACTNESS, KEY_AREA, KEY_GEOMETRY, KEY_VOTERS, KEY_STATES
from enum import Enum
from helper.ui import QgisMessageBarProgress, isnull
from qgis.core import QgsVectorLayer, QgsFeature, QgsPoint, QgsGeometry
from layer_type import LayerType


class EqualStatus(Enum):
    TOOSMALL = -1
    OK = 0
    TOOBIG = 1


class Balancer(object):
    def __init__(self, name, layer, voters_field, polling_field, state_field, par_field, delta,
                 par_count_limit=None,
                 state_count_limit=None,
                 state_prefix_format="%02d",
                 par_prefix_format="%03d",
                 polling_prefix_format="%d",
                 readonly=True):

        self.name = name
        self.total_voters = 0
        self.readonly = readonly

        # storage - they keep growing!
        self.topology_polling = {}
        self.topology_state = {}
        self.topology_par = {}
        self.map_par_state = {}
        self.par_statistics = {}
        self.state_statistics = {}
        self.layer = layer
        self.polling_field = polling_field
        self.state_field = state_field
        self.par_field = par_field
        self.voters_field = voters_field
        self.delta = delta

        self.state_count_limit = state_count_limit
        self.par_count_limit = par_count_limit
        self.state_count = 0
        self.par_count = 0
        self.topology_dirty = True
        self.state_average = 0
        self.statemax_target = None
        self.statemax_actual = None
        self.statemax_actual_precentage = 0.00
        self.statemin_target = None
        self.statemin_actual = None
        self.statemin_actual_precentage = 0.00

        self.par_average = 0
        self.parmax_target = None
        self.parmax_actual = None
        self.parmax_actual_precentage = 0.00
        self.parmin_target = None
        self.parmin_actual = None
        self.parmin_actual_precentage = 0.00

        self.polling_prefix_format = polling_prefix_format
        self.state_prefix_format = state_prefix_format
        self.par_prefix_format = par_prefix_format

        # store list of DMs that fits into the normalized range
        self.__successes = {}

        # stores list of previous failed attempts
        self.__failures = {}

        # current attempt
        self.__current_walk = []

        # adjacency graph
        self.__graphs_state = None
        self.__graphs_par = None

        self.__inprogress = False

        self.topology_load()

        self.colouring_par = colouring.Colouring()
        self.colouring_state = colouring.Colouring()

        self.init_colouring()

    def adjlayer_make(self, name, layertype):
        if layertype == LayerType.Parliament:
            ig = self.colouring_par.id_graph
        elif layertype == LayerType.State:
            ig = self.colouring_state.id_graph
        else:
            raise Exception("Not implemented")

        vl = QgsVectorLayer("LineString?crs={}&index=yes&field=label:string&field=from:string&field=to:string"
                            .format(self.layer.dataProvider().crs().authid()),
                            "{}-{}-adj".format(name, layertype.name),
                            "memory")
        pr = vl.dataProvider()
        info = self.__box_info(layertype)
        fet = QgsFeature()
        for (f, tlist) in ig.nodeEdge.iteritems():
            for t in tlist:
                # make a feature from id=f to id=t
                centref, labelf = info[f]
                ptf = QgsPoint(centref[0], centref[1])
                centret, labelt = info[t]
                ptt = QgsPoint(centret[0], centret[1])
                lines = [ptf, ptt]
                fet.setGeometry(QgsGeometry().fromPolyline(lines))
                attributes = ["{}-{}".format(labelf, labelt), labelf, labelt]
                fet.setAttributes(attributes)
                pr.addFeatures([fet])
        vl.updateExtents()
        return vl

    def __box_info(self, layertype):
        info = {}
        for k, v in self.__get_layertype_features(layertype).items():
            bbox = v[KEY_GEOMETRY].boundingBox()
            info[k] = ((bbox.xMinimum() + bbox.width() / 2.0, bbox.yMinimum() + bbox.height() / 2.0), k)
        return info

    def init_colouring(self):
        self.colouring_par.init_colours(self.topology_par)
        self.colouring_state.init_colours(self.topology_state)

    def get_adjacency(self, layertype):
        if layertype == LayerType.Parliament:
            return self.adjlayer_make(self.colouring_par.id_graph, layertype)
        elif layertype == LayerType.State:
            return self.adjlayer_make(self.colouring_state.id_graph, layertype)

        raise Exception("Not implemented")

    def statistics_calculate(self, transform):
        # todo: does not handle multipart polygons properly
        # calculate state statistics
        # circularity => https://sites.google.com/site/mathagainstgerrymandering/advanced-attributes#TOC-Compactness

        if self.state_statistics.keys().__len__() == 0:
            for k, v in self.topology_state.iteritems():
                v[KEY_GEOMETRY].transform(transform)
                area = v[KEY_GEOMETRY].area()
                length = v[KEY_GEOMETRY].length()

                self.state_statistics.update({k: {
                    KEY_AREA: area / (1000 * 1000),
                    KEY_CIRCULARITY: 4.0 * math.pi * area / math.pow(length, 2),
                    KEY_COMPACTNESS: math.pow(length, 2) / area
                }})

        # calculate par statistics
        if self.par_statistics.keys().__len__() == 0:
            for k, v in self.topology_par.iteritems():
                v[KEY_GEOMETRY].transform(transform)
                area = v[KEY_GEOMETRY].area()
                length = v[KEY_GEOMETRY].length()

                self.par_statistics.update({k: {
                    KEY_AREA: area / (1000 * 1000),
                    KEY_CIRCULARITY: 4.0 * math.pi * area / math.pow(length, 2),
                    KEY_COMPACTNESS: math.pow(length, 2) / area
                }})

    # todo: getFeatures no longer required since geometry info is saved
    def topology_init(self):
        import re

        self.topology_polling.clear()

        nfeatures = self.layer.featureCount()
        nop = nfeatures
        iop = 0
        progress = QgisMessageBarProgress("Reading {} attribute fields ...".format(self.name))
        try:
            for f in self.layer.getFeatures():
                self.topology_polling.update({f.id(): {
                    self.polling_field: None if isnull(f[self.polling_field]) else f[self.polling_field],
                    self.par_field: None if isnull(f[self.par_field]) else int(
                        re.search(r'\d+', str(f[self.par_field])).group()).__str__(),
                    self.state_field: None if isnull(f[self.state_field]) else int(
                        re.search(r'\d+', str(f[self.state_field])).group()).__str__(),
                    self.voters_field: int(f[self.voters_field]),
                    KEY_GEOMETRY: QgsGeometry(f.geometry())
                }})
                iop += 1
                progress.setPercentage(int(100 * iop / nop))
        except:
            raise
        finally:
            progress.close()

    def topology_update(self, dict_values):
        if self.readonly:
            raise Exception("Cannot write to read-only balancer")

        import re

        for k, v in dict_values.items():
            for k2, v2 in v.items():
                self.layer.changeAttributeValue(k, self.layer.fieldNameIndex(k2), v2)
                self.topology_polling[k][k2] = int(re.search(r'\d+', str(v2)).group())

        self.state_statistics.clear()
        self.par_statistics.clear()

        self.topology_dirty = True

    def topology_load(self):
        if not self.topology_dirty:
            return

        self.topology_state.clear()
        self.topology_par.clear()
        self.topology_init()

        for k, v in self.topology_polling.iteritems():
            voters_value = v[self.voters_field]
            geom_value = v[KEY_GEOMETRY]
            key_state = v[self.state_field]
            key_par = v[self.par_field]
            if key_state:
                self.topology_state.setdefault(key_state, {KEY_VOTERS: 0, KEY_GEOMETRY: geom_value})
                if key_state in self.topology_state:
                    self.topology_state[key_state][KEY_GEOMETRY] = QgsGeometry(
                        self.topology_state[key_state][KEY_GEOMETRY].combine(geom_value))
                self.topology_state[key_state][KEY_VOTERS] += voters_value

            if key_par:
                self.topology_par.setdefault(key_par, {KEY_VOTERS: 0, KEY_GEOMETRY: geom_value})
                if key_par in self.topology_par:
                    self.topology_par[key_par][KEY_GEOMETRY] = QgsGeometry(
                        self.topology_par[key_par][KEY_GEOMETRY].combine(geom_value))
                self.topology_par[key_par][KEY_VOTERS] += voters_value

        self.calculate_limits(self.delta)
        self.init_par_state_map()
        self.topology_dirty = False

    def get_colour_by_state(self, attr_value, colour_index):
        value = self.topology_state.get(attr_value)
        if not value:
            return None

        if value[KEY_VOTERS] > self.statemax_target:
            return self.colouring_state.colours_red[colour_index - 1]

        if value[KEY_VOTERS] < self.statemin_target:
            return self.colouring_state.colours_blue[colour_index - 1]

        return self.colouring_state.colours_grey[colour_index - 1]

    def get_colour_by_parliament(self, attr_value, colour_index):
        value = self.topology_par.get(attr_value)
        if not value:
            return None

        if value[KEY_VOTERS] > self.parmax_target:
            return self.colouring_par.colours_red[colour_index - 1]

        if value[KEY_VOTERS] < self.parmin_target:
            return self.colouring_par.colours_blue[colour_index - 1]

        return self.colouring_par.colours_grey[colour_index - 1]

    def init_par_state_map(self):
        # {par_key : {voters:voters, d: "-+",
        # states: { state_key: (voters, d)}  }}
        self.map_par_state.clear()
        for v in self.topology_polling.values():
            par_key = v[self.par_field]
            state_key = v[self.state_field]
            if not par_key:
                continue

            self.map_par_state \
                .setdefault(par_key, {"d": "{:.2f}".format(self.get_par_deviation(par_key)),
                                      KEY_STATES: {},
                                      KEY_VOTERS: self.get_par_voters(par_key)})

            if not state_key:
                continue

            if state_key not in self.map_par_state[par_key][KEY_STATES]:
                voters_dev_tuple = self.get_state_voters_and_deviation(state_key)
                self.map_par_state[par_key][KEY_STATES] \
                    .update({state_key: (voters_dev_tuple[0], "{:.2f}".format(voters_dev_tuple[1]))})

    def get_par_voters(self, par_name):
        if not par_name or not par_name in self.topology_par:
            return 0

        return self.topology_par[par_name][KEY_VOTERS]

    def get_par_deviation(self, par_name):
        if not par_name or not par_name in self.topology_par:
            return 0.0

        return (self.topology_par[par_name][KEY_VOTERS] - self.par_average) * 100 / self.par_average

    def get_state_voters_and_deviation(self, state_name):
        if not state_name or not state_name in self.topology_state:
            return 0, 0.0

        voters = self.topology_state[state_name][KEY_VOTERS]
        return voters, (voters - self.state_average) * 100 / self.state_average

    def get_feature_label(self):
        if self.readonly:
            return """CASE
                        WHEN
                            {0} IS NULL or {1} IS NULL THEN ''
                            ELSE concat(toint(regexp_substr({0}, '(\\\d+)')),
                                '/', toint(regexp_substr({1}, '(\\\d+)')),
                                CASE WHEN {2} IS NULL THEN ''
                                ELSE concat('/', toint(regexp_substr(coalesce({2},''), '(\\\d+)'))) END)
                        END""".format(self.par_field, self.state_field, self.polling_field)

        return """CASE
                        WHEN
                            {0} IS NULL or {1} IS NULL THEN ''
                            ELSE concat(toint(regexp_substr({0}, '(\\\d+)')),
                                '/', toint(regexp_substr({1}, '(\\\d+)')))
                        END""".format(self.par_field, self.state_field)

    def get_par_code_sequence(self):
        if self.topology_par.keys().__len__():
            startval = int(min(self.topology_par.keys()))
        else:
            startval = 1

        return [p for p in range(startval, startval + self.par_count_limit)]

    def get_state_code_sequence(self):
        return [s for s in range(1, self.state_count_limit + 1)]

    def recommendation_by_par(self, par_name):

        voters_par = self.get_par_voters(par_name)

        if not self.state_average or not voters_par:
            return ""

        # get min/max for number of state seats in a par
        seats_state_min = math.floor(1.0 * self.state_count_limit / self.par_count_limit)
        seats_state_max = math.ceil(1.0 * self.state_count_limit / self.par_count_limit)
        seats_extras = self.state_count_limit % self.par_count_limit

        dun_size_with_max_seats = float(voters_par) / seats_state_max
        delta_max = math.fabs(self.state_average - dun_size_with_max_seats)
        dun_size_with_min_seats = float(voters_par) / seats_state_min
        delta_min = math.fabs(self.state_average - dun_size_with_min_seats)

        if delta_max < delta_min:
            return "{} STATE seats".format(int(seats_state_max))
        elif delta_max > delta_min:
            return "{} STATE seats".format(int(seats_state_min))
        else:
            return "{} STATE seats".format(int(seats_state_max))

            # recommended size (voters)
            # recommended_par

    def calculate_limits(self, delta):
        self.delta = delta
        self.total_voters = sum([v[self.voters_field] for k, v in self.topology_polling.iteritems()])
        self.state_count = self.topology_state.keys().__len__()
        self.par_count = self.topology_par.keys().__len__()

        # for old topo
        if not self.state_count_limit:
            self.state_count_limit = self.state_count

        self.state_average = float(self.total_voters) / self.state_count_limit
        self.statemax_target = self.state_average + self.delta * self.state_average
        self.statemin_target = self.state_average - self.delta * self.state_average

        if self.state_count:
            self.statemax_actual = max(v[KEY_VOTERS] for v in self.topology_state.values())
            self.statemax_actual_precentage = (self.statemax_actual - self.state_average) * 100 / self.state_average
            self.statemin_actual = min(v[KEY_VOTERS] for v in self.topology_state.values())
            self.statemin_actual_precentage = (self.statemin_actual - self.state_average) * 100 / self.state_average

        # for old topo
        if not self.par_count_limit:
            self.par_count_limit = self.par_count

        self.par_average = float(self.total_voters) / self.par_count_limit
        self.parmax_target = self.par_average + self.delta * self.par_average
        self.parmin_target = self.par_average - self.delta * self.par_average

        if self.par_count:
            self.parmax_actual = max(v[KEY_VOTERS] for v in self.topology_par.values())
            self.parmax_actual_precentage = (self.parmax_actual - self.par_average) * 100 / self.par_average
            self.parmin_actual = min(v[KEY_VOTERS] for v in self.topology_par.values())
            self.parmin_actual_precentage = (self.parmin_actual - self.par_average) * 100 / self.par_average

    def get_best_deviation(self):
        """assumming fixed number of seats"""
        state = [self.state_count, self.state_count_limit][bool(self.state_count_limit)]
        par = [self.par_count, self.par_count_limit][bool(self.par_count_limit)]

        mean = 100.0 * state / par
        min = math.floor(mean) - mean
        max = math.ceil(mean) - mean

        return min, max

    def calculate_live_totals(self, current_par, current_state, selected_ids):
        import re

        voters_state = 0
        voters_par = 0
        voters_selected = 0
        if current_par:
            current_par = re.search(r'\d+', str(current_par)).group()

        if current_state:
            current_state = re.search(r'\d+', str(current_state)).group()

        for k, v in self.topology_polling.items():
            voters = v[self.voters_field]
            if k in selected_ids:
                voters_state += voters
                voters_par += voters
                voters_selected += voters
            else:
                if v[self.state_field] == current_state:
                    voters_state += voters

                if v[self.par_field] == current_par:
                    voters_par += voters

        return tuple((voters_par, voters_state, voters_selected))

    def __get_layertype_features(self, layertype):
        if layertype == LayerType.State:
            return self.topology_state
        elif layertype == LayerType.Parliament:
            return self.topology_par
        else:
            return self.topology_polling

    def is_balanced(self):
        return (self.parmin_actual >= self.parmin_target and
                self.parmax_actual <= self.parmax_target and
                self.statemin_actual >= self.statemin_target and
                self.statemax_actual <= self.statemax_target)

    def get_unused(self):
        pars = [str(p) for p in self.get_par_code_sequence()]
        states = [str(s) for s in self.get_state_code_sequence()]
        pars_left = set(pars) \
            .difference([str(v[self.par_field]) for v in self.topology_polling.values()])
        states_left = set(states) \
            .difference([str(v[self.state_field]) for v in self.topology_polling.values()])
        return tuple((pars_left, states_left))

    # todo par_new_prefix unused
    def resequence(self):
        action_dict = {}

        # build state to polling district mapping
        state_dms_map = {}
        for k1, v1 in self.topology_polling.items():
            state_key = v1[self.state_field]

            if state_key in state_dms_map:
                state_dms_map[state_key].append((k1, v1[KEY_GEOMETRY]))
            else:
                state_dms_map[state_key] = [(k1, v1[KEY_GEOMETRY])]

        # start with par
        par_ordered = sorted(self.topology_par.items(), key=lambda x: x[1][KEY_GEOMETRY].centroid().asPoint().x())

        # then state
        par_counter = 0
        state_counter = 0
        for par in par_ordered:
            par_counter += 1
            states_keys = self.map_par_state[par[0]][KEY_STATES].keys()
            states = [(sk, self.topology_state[sk]) for sk in states_keys]
            states_ordered = sorted(states, key=lambda x: x[1][KEY_GEOMETRY].centroid().asPoint().x())

            # then polling district
            for state_entry in states_ordered:
                state_counter += 1
                dms = state_dms_map[state_entry[0]]
                dms_ordered = sorted(dms, key=lambda x: x[1].centroid().asPoint().x())

                dm_counter = 0
                for dm in dms_ordered:
                    dm_counter += 1

                    assert dm[0] not in action_dict

                    action_dict.update({dm[0]: {self.state_field: self.state_prefix_format % state_counter,
                                                self.polling_field: self.polling_prefix_format % dm_counter,
                                                self.par_field: self.par_prefix_format % par_counter}})

        self.topology_update(action_dict)
