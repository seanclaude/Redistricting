import linecache
import sys
import logging


def exception_message():
    exc_type, exc_obj, tb = sys.exc_info()
    f = tb.tb_frame
    lineno = tb.tb_lineno
    filename = f.f_code.co_filename
    linecache.checkcache(filename)
    line = linecache.getline(filename, lineno, f.f_globals)
    return '{}:{} "{}"): {}'.format(filename, lineno, line.strip(), exc_obj)


def log_exception():
    logging.exception(exception_message())



