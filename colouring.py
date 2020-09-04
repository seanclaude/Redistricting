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
from builtins import next
from builtins import range
from builtins import object
import itertools

import chroma
from .graph import Graph
from helper.ui import generate_random_color


class Colouring(object):

    @property
    def id_graph(self):
        return self.__graphs[1]

    @property
    def graph(self):
        return self.__graphs[0]

    def __init__(self):
        self.red_shade_brightness_generator = itertools.cycle(list(range(30, 100, 15)))
        self.blue_shade_brightness_generator = itertools.cycle(list(range(30, 100, 15)))
        self.grey_shade_brightness_generator = itertools.cycle(list(range(85, 30, -15)))

        self.gColouring = None
        self.colours_all = None
        self.colours_red = None
        self.colours_blue = None
        self.colours_grey = None
        self.max_colours = 0
        self.__graphs = Graph(is_sorted=False), Graph(is_sorted=True)

    def compute_graph(self, features):
        s = self.graph
        ig = self.id_graph

        for k1, v1 in list(features.items()):
            a1 = k1
            g1 = v1['geom']

            # add to graph anyway if node is not connected to anything
            found_connection = False
            for k2, v2 in list(features.items()):
                if k2 == k1:
                    break

                g2 = v2['geom']
                if g1.intersects(g2):
                    found_connection = True
                    a2 = k2
                    s.add_edge(a1, a2)
                    s.add_edge(a2, a1)
                    ig.add_edge(k1, k2)

            if not found_connection:
                s.add_edge(a1, a1)
                ig.add_edge(a1, a1)

    def init_colours(self, features):
        self.compute_graph(features)
        self.gColouring = self.greedy()
        if self.gColouring.__len__():
            self.max_colours = max(self.gColouring.values())

        self.colours_all = [chroma.Color('#' + x) for x in generate_random_color(self.max_colours)]
        self.colours_blue = []
        self.colours_red = []
        self.colours_grey = []

        for i in range(self.max_colours):
            self.colours_blue.append(self.get_blue_shade())
            self.colours_red.append(self.get_red_shade())

            # skip colour that's similar to mouse
            grey = self.get_grey_shade()
            if grey == chroma.Color('#808080'):
                grey = self.get_grey_shade()
            self.colours_grey.append(grey)

    def get_red_shade(self):
        red = chroma.Color('#ff0000')
        brightness = next(self.red_shade_brightness_generator)
        return chroma.Color((red.hsv[0], float(brightness) / 100, red.hsv[2]), 'hsv')

    def get_blue_shade(self):
        blue = chroma.Color('#0000ff')
        brightness = next(self.blue_shade_brightness_generator)
        return chroma.Color((blue.hsv[0], float(brightness) / 100, blue.hsv[2]), 'hsv')

    def get_grey_shade(self):
        grey = chroma.Color('#000000')
        brightness = next(self.grey_shade_brightness_generator)
        return chroma.Color((grey.hsv[0], grey.hsv[1], float(brightness) / 100), 'hsv')

    def get_colour(self, colour_index):
        return self.colours_all[colour_index - 1]

    def greedy(self):
        colouring = {}
        colours = set()
        for k in list(self.graph.nodeEdge.keys()):
            adjcolours = set()
            for v in self.graph.nodeEdge[k]:
                if v in colouring:
                    adjcolours.add(colouring[v])
            avail = colours.difference(adjcolours)
            if len(avail) == 0:
                # new colour
                newcolour = len(colours) + 1
                colours.add(newcolour)
            else:
                # use any free colour
                # newcolour = random.sample(avail, 1)[0]
                newcolour = avail.pop()
            colouring[k] = newcolour
        return colouring