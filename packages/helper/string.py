import re

__author__ = 'sean'


def parse_int(string):
    if string is None:
        return None

    if not string.isdigit():
        return None

    return int(string)


def parse_float(string):
    if string is None:
        return None

    import re
    if not re.match("^\d+?\.\d+?$", string):
        return None

    return float(string)


def remove_tags(text):
    return re.sub("<[^>]*>", '', text)