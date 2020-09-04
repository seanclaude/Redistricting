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
from builtins import str
from builtins import object


class Graph(object):
    def __init__(self, is_sorted=True):
        self.sorted = is_sorted
        self.nodeEdge = {}
        pass

    def add_edge(self, i, j):
        ij = [i, j]
        if self.sorted:
            ij.sort()
        (i, j) = ij
        if i in self.nodeEdge:
            self.nodeEdge[i].add(j)
        else:
            self.nodeEdge[i] = {j}

    def dump(self):
        out = []
        for k in list(self.nodeEdge.keys()):
            out.append(str(k)+":")
            for v in self.nodeEdge[k]:
                out.append(" --> "+str(v))
        return "\n".join(out)

    def write_dot(self, name, filepath):
        dot = self.make_dot(name)
        fp = open(filepath, "w")
        fp.write(dot)
        fp.close()

    def make_dot(self, name):
        s = ['graph "%s" {' % name]
        for k in list(self.nodeEdge.keys()):
            for v in self.nodeEdge[k]:
                s.append('"%s" -- "%s" ;' % (str(k), str(v)))
        s.append("}")
        return "\n".join(s)

    def makefull(self):
        g = Graph(is_sorted=False)
        for k in list(self.nodeEdge.keys()):
            for v in self.nodeEdge[k]:
                g.add_edge(v, k)
                g.add_edge(k, v)
        return g
