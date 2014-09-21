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

import math
from re import search
import colouring
from delimitation import LayerType
from enum import Enum
from helper.ui import QgisMessageBarProgress, isnull
from qgis.core import QgsVectorLayer, QgsFeature, QgsPoint, QgsGeometry


class EqualStatus(Enum):
    TOOSMALL = -1
    OK = 0
    TOOBIG = 1


class Balancer(object):
    def __init__(self, layer, voters_field, polling_field, state_field, par_field, delta,
                 par_average_target=None,
                 state_average_target=None,
                 par_count_limit=None,
                 state_count_limit=None,
                 state_prefix_format="%02d",
                 par_prefix_format="%03d"):

        self.total_voters = 0
        self.topology_polling = {}
        self.topology_state = {}
        self.topology_par = {}
        self.map_par_state = {}
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

        self.state_average = 0
        self.state_average_target = state_average_target
        self.statemax_target = None
        self.statemax_actual = None
        self.statemax_actual_precentage = 0.00
        self.statemin_target = None
        self.statemin_actual = None
        self.statemin_actual_precentage = 0.00

        self.par_average = 0
        self.par_average_target = par_average_target
        self.parmax_target = None
        self.parmax_actual = None
        self.parmax_actual_precentage = 0.00
        self.parmin_target = None
        self.parmin_actual = None
        self.parmin_actual_precentage = 0.00

        self.polling_prefix_format = "%02d"
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

        self.load_topology()

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
            bbox = v['geom'].boundingBox()
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

    def init_topology(self):
        self.topology_polling.clear()

        nfeatures = self.layer.featureCount()
        nop = nfeatures
        iop = 0
        progress = QgisMessageBarProgress("Initialising topology ...")

        for f in self.layer.getFeatures():
            self.topology_polling.update({f.id(): {
                self.polling_field: None if isnull(f[self.polling_field]) else f[self.polling_field],
                self.par_field: None if isnull(f[self.par_field]) else int(
                    search(r'\d+', f[self.par_field]).group()).__str__(),
                self.state_field: None if isnull(f[self.state_field]) else int(
                    search(r'\d+', f[self.state_field]).group()).__str__(),
                self.voters_field: int(f[self.voters_field]),
                "geom": f.geometryAndOwnership()
            }})
            iop += 1
            progress.setPercentage(int(100 * iop / nop))

        progress.close()

    def update_topology(self, dict_values):
        for k, v in dict_values.items():
            for k2, v2 in v.items():
                self.layer.changeAttributeValue(k, self.layer.fieldNameIndex(k2), v2)
                self.topology_polling[k][k2] = int(search(r'\d+', v2).group())

    def load_topology(self):
        self.topology_state.clear()
        self.topology_par.clear()
        self.init_topology()

        for k, v in self.topology_polling.iteritems():
            voters_value = v[self.voters_field]
            geom_value = v["geom"]
            key_state = v[self.state_field]
            key_par = v[self.par_field]
            if key_state:
                self.topology_state.setdefault(key_state, {'voters': 0, 'geom': QgsGeometry(geom_value)})
                if key_state in self.topology_state:
                    self.topology_state[key_state]['geom'] = QgsGeometry(
                        self.topology_state[key_state]['geom'].combine(geom_value))
                self.topology_state[key_state]['voters'] += voters_value

            if key_par:
                self.topology_par.setdefault(key_par, {'voters': 0, 'geom': QgsGeometry(geom_value)})
                if key_par in self.topology_par:
                    self.topology_par[key_par]['geom'] = QgsGeometry(
                        self.topology_par[key_par]['geom'].combine(geom_value))
                self.topology_par[key_par]['voters'] += voters_value

        self.calculate_limits(self.delta)
        self.init_par_state_map()

    def get_colour_by_state(self, attr_value, colour_index):
        value = self.topology_state.get(attr_value)
        if not value:
            return None

        if value['voters'] > self.statemax_target:
            return self.colouring_state.colours_red[colour_index - 1]

        if value['voters'] < self.statemin_target:
            return self.colouring_state.colours_blue[colour_index - 1]

        return self.colouring_state.colours_grey[colour_index - 1]

    def get_colour_by_parliament(self, attr_value, colour_index):
        value = self.topology_par.get(attr_value)
        if not value:
            return None

        if value['voters'] > self.parmax_target:
            return self.colouring_par.colours_red[colour_index - 1]

        if value['voters'] < self.parmin_target:
            return self.colouring_par.colours_blue[colour_index - 1]

        return self.colouring_par.colours_grey[colour_index - 1]

    def init_par_state_map(self):
        # {par_key : {voters:voters, d: "-+",
        # states: { state_key: d}  }}
        self.map_par_state.clear()
        for v in self.topology_polling.values():
            par_key = v[self.par_field]
            state_key = v[self.state_field]
            if not par_key:
                continue

            self.map_par_state \
                .setdefault(par_key, {"d": "{:.2f}%".format(self.get_par_deviation(par_key)),
                                      "states": {},
                                      "voters": self.get_par_voters(par_key)})

            if not state_key:
                continue

            if state_key not in self.map_par_state[par_key]['states']:
                self.map_par_state[par_key]['states'] \
                    .update({state_key: "{:.2f}%".format(self.get_state_deviation(state_key))})

    def get_par_voters(self, par_name):
        if not par_name:
            return 0

        return self.topology_par[par_name]['voters']

    def get_par_deviation(self, par_name):
        if not par_name:
            return 0.0

        return (self.topology_par[par_name]['voters'] - self.par_average) * 100 / self.par_average

    def get_par_code_sequence(self):
        if self.topology_par.keys().__len__():
            startval = int(min(self.topology_par.keys()))
        else:
            startval = 1

        return [p for p in range(startval, startval + self.par_count_limit)]

    def get_state_code_sequence(self):
        return [s for s in range(1, self.state_count_limit + 1)]

    def get_recommendation(self):
        # get min/max for number of state seats in a par
        seats_state_min = math.floor(1.0 * self.state_count_limit / self.par_count_limit)
        seats_state_max = math.ceil(1.0 * self.state_count_limit / self.par_count_limit)
        seats_extras = self.state_count_limit % self.par_count_limit

        # recommended size (voters)
        # recommended_par


    def get_state_deviation(self, state_name):
        if not state_name:
            return 0.0

        return (self.topology_state[state_name]['voters'] - self.state_average) * 100 / self.state_average

    def calculate_limits(self, delta):
        self.delta = delta
        self.total_voters = sum([v['voters'] for k, v in self.topology_par.iteritems()])
        self.state_count = self.topology_state.keys().__len__()
        self.par_count = self.topology_par.keys().__len__()

        if not self.state_count:
            self.state_average = float(self.total_voters) / self.state_count_limit
        else:
            self.state_average = float(self.total_voters) / self.state_count

            # for old topo
            if not self.state_count_limit:
                self.state_count_limit = self.state_count

        if self.state_average_target:
            self.state_average = self.state_average_target

        self.statemax_target = self.state_average + self.delta * self.state_average
        self.statemin_target = self.state_average - self.delta * self.state_average

        if self.state_count:
            self.statemax_actual = max(v['voters'] for v in self.topology_state.values())
            self.statemax_actual_precentage = (self.statemax_actual - self.state_average) * 100 / self.state_average
            self.statemin_actual = min(v['voters'] for v in self.topology_state.values())
            self.statemin_actual_precentage = (self.statemin_actual - self.state_average) * 100 / self.state_average

        if not self.par_count:
            self.par_average = float(self.total_voters) / self.par_count_limit
        else:
            self.par_average = float(self.total_voters) / self.par_count

            # for old topo
            if not self.par_count_limit:
                self.par_count_limit = self.par_count

        if self.par_average_target:
            self.par_average = self.par_average_target

        self.parmax_target = self.par_average + self.delta * self.par_average
        self.parmin_target = self.par_average - self.delta * self.par_average

        if self.par_count:
            self.parmax_actual = max(v['voters'] for v in self.topology_par.values())
            self.parmax_actual_precentage = (self.parmax_actual - self.par_average) * 100 / self.par_average
            self.parmin_actual = min(v['voters'] for v in self.topology_par.values())
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
        voters_state = 0
        voters_par = 0
        voters_selected = 0
        if current_par:
            current_par = search(r'\d+', str(current_par)).group()

        if current_state:
            current_state = search(r'\d+', str(current_state)).group()

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

    def get_features_total(self):
        return tuple((self.par_count, self.state_count, self.topology_polling.keys().__len__()))

    def get_unused(self):
        pars = [str(p) for p in self.get_par_code_sequence()]
        states = [str(s) for s in self.get_state_code_sequence()]
        pars_left = set(pars) \
            .difference([str(v[self.par_field]) for v in self.topology_polling.values()])
        states_left = set(states) \
            .difference([str(v[self.state_field]) for v in self.topology_polling.values()])
        return tuple((pars_left, states_left))

    # todo par_new_prefix unused
    def resequence(self, par_new_prefix):
        ordered = sorted(self.topology_polling.items(),
                         key=lambda x: (x[1][self.par_field], x[1][self.state_field]))
        par_renumber = 0
        state_renumber = 0
        polling_renumber = 1
        par_current = None
        state_current = None

        for o in ordered:
            if state_current != o[1][self.state_field]:
                state_renumber += 1
                polling_renumber = 1  # restart polling area renumbering
            state_current = o[1][self.state_field]

            if par_current != o[1][self.par_field]:
                par_renumber += 1
            par_current = o[1][self.par_field]

            self.update_topology(
                {o[0]: {self.state_field: self.state_prefix_format % state_renumber,
                        self.polling_field: self.polling_prefix_format % polling_renumber,
                        self.par_field: self.par_prefix_format % par_renumber}})

            polling_renumber += 1


class NodePOLL(object):
    def __init__(self, pollid, neighbours, voters, state):
        self.id = pollid
        self.adjacent_states = neighbours
        self.voters = voters
        self.state_prev = None
        self.state_current = state


class NodeSTATE(object):
    def __init__(self, stateid, neighbours, states, parid):
        self.id = stateid
        self.adjacent_states = neighbours
        self.states = states
        self.par_prev = None
        self.par_current = parid

        # get all adjacent POLLs by excluding POLLs in our own STATE
        self.adjacent_states = dict(
            [(poll, [adj for adj in poll.nodeEdge if adj not in self.states]) for poll in self.states])

        # (poll, voters) : sorted[(poll_adj, voters)]
        self.adjacent_voters = {}
        for k, v in self.adjacent_states:
            self.adjacent_voters.update(
                {(k, k.voters): [(poll, poll.voters) for poll in v].sort(key=lambda x: x.voters)})

        return sum(poll.voters for poll in self.states)
