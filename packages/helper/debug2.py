import pydevd_pycharm


def init_remote():
    pydevd_pycharm.settrace('127.0.0.1', port=12345, stdoutToServer=True,
                            stderrToServer=True)
