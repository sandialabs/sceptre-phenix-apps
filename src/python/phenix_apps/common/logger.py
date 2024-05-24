import inspect
import logging
import os

import phenix_apps.common.settings as settings


def log(level: str, msg: str) -> None:
    """
    Write a log message to the phenix log.

    This function first creates (or accesses) the phenix log, and then writes
    a message to it.

    Args:
        level (str): Name of logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        msg (str): Message to write to log
    """

    # create phenix logger
    logger = logging.getLogger('phenix-apps')
    logger.setLevel(settings.PHENIX_LOG_LEVEL.upper())

    # create handler for phenix logger
    handler = logging.FileHandler(settings.PHENIX_LOG_FILE)
    caller = os.path.basename(inspect.stack()[1].filename)
    formatter = logging.Formatter(
        f'%(asctime)s %(levelname)8s {caller}:'
        ' %(message)s', datefmt='%Y/%m/%d %H:%M:%S'
    )
    handler.setFormatter(formatter)

    # add handler to phenix logger
    logger.handlers[:] = [handler]
    logger.log(getattr(logging, level.upper()), msg)
