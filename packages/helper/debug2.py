import pydevd_pycharm


def init_remote():
    pydevd_pycharm.settrace('localhost', port=12345, stdoutToServer=True,
                            stderrToServer=True)
