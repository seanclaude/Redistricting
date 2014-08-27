__author__ = 'sean'


def init_remote():
    import sys

    sys.path.insert(0, r'C:/Program Files (x86)/JetBrains/PyCharm 3.4.1/pycharm-debug.egg')

    import pydevd
    pydevd.settrace('localhost', port=5678,
                    suspend=False,
                    trace_only_current_thread=False,
                    stdoutToServer=False,
                    stderrToServer=False)
