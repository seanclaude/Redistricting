from xml import etree

# https://gist.github.com/dolph/1792904
def serialize(d):
    """Serialize a dictionary to XML"""
    assert len(d.keys()) == 1, 'Cannot encode more than one root element'

    # name the root dom element
    name = d.keys()[0]
    root = etree.Element(name)
    populate_element(root, d[name])

    return root


def populate_element(element, d):
    """Populates an etree with the given dictionary"""
    for k, v in d.iteritems():
        child = etree.Element(k)
        if type(v) is dict:
            # serialize the child dictionary
            populate_element(child, v)
        else:
            child.text = unicode(v)
        element.append(child)

