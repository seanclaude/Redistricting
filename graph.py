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

class Graph:
    def __init__(self, is_sorted=True):
        self.sorted = is_sorted
        self.nodeEdge = {}
        pass

    def add_edge(self, i, j):
        ij = [i, j]
        if self.sorted:
            ij.sort()
        (i, j) = ij
        if self.nodeEdge.has_key(i):
            self.nodeEdge[i].add(j)
        else:
            self.nodeEdge[i] = set([j])

    def dump(self):
        out = []
        for k in self.nodeEdge.keys():
            out.append(str(k)+":")
            for v in self.nodeEdge[k]:
                out.append(" --> "+str(v))
        return "\n".join(out)

    def write_dot(self, name, filepath):
        dot = self.make_dot(name)
        fp = file(filepath, "w")
        fp.write(dot)
        fp.close()

    def make_dot(self, name):
        s = ['graph "%s" {' % name]
        for k in self.nodeEdge.keys():
            for v in self.nodeEdge[k]:
                s.append('"%s" -- "%s" ;' % (str(k), str(v)))
        s.append("}")
        return "\n".join(s)

    def makefull(self):
        g = Graph(is_sorted=False)
        for k in self.nodeEdge.keys():
            for v in self.nodeEdge[k]:
                g.add_edge(v, k)
                g.add_edge(k, v)
        return g
            

