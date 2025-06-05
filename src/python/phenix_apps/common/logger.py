import inspect
import logging
import os
from typing import Literal

import phenix_apps.common.settings as settings

logger = None

def log(level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] , msg: str) -> None:
    """
    Write a log message to the phenix log.

    This function first creates (or accesses) the phenix log, and then writes
    a message to it.

    Args:
        level (str): Name of logging level (DEBUG, INFO, WARNING, ERROR)
        msg (str): Message to write to log
    """

    # create phenix logger
    global logger
    if logger is None:
        logger = logging.getLogger('phenix-apps')
        logger.setLevel(settings.PHENIX_LOG_LEVEL.upper())

        # create handler for phenix logger
        handler = logging.FileHandler(settings.PHENIX_LOG_FILE)
        caller = os.path.basename(inspect.stack()[1].filename)
        fmt = f'{{"time": "%(asctime)s", "level": "%(levelname)s", "msg": "%(message)s", "caller": "{caller}"}}'
        handler.setFormatter(logging.Formatter(fmt))

        # add handler to phenix logger
        logger.handlers[:] = [handler]
    logger.log(getattr(logging, level.upper()), msg)
