import logging


def init(handlername):
    """https://docs.python.org/2/howto/logging.html"""
    logger = logging.getLogger()
    exist = False
    for h in logger.handlers:
        if h.get_name() == handlername:
            exist = True

    if not exist:
        handler = logging.StreamHandler()
        handler.set_name(handlername)
        logger.addHandler(handler)




