import inspect, logging, os

from unittest.mock import MagicMock

import phenix_apps.common.settings as s


LEVEL = {
    'DEBUG':    logging.DEBUG,
    'INFO':     logging.INFO,
    'WARN':     logging.WARN,
    'ERROR':    logging.ERROR,
    'CRITICAL': logging.CRITICAL,
}


def log(level, msg):
    """Write a log message to the phenix log.

    This function first creates (or accesses) the phenix log, and then writes
    a message to it.

    Args:
        level (str): Name of logging level.
        msg   (str): Message to write to log.
    """

    # create phenix logger
    logger = logging.getLogger('phenix')
    logger.setLevel(s.PHENIX_LOG_LEVEL.upper())

    # create handler for phenix logger
    handler = logging.FileHandler(s.PHENIX_LOG_FILE)
    caller = os.path.basename(inspect.stack()[1].filename)
    formatter = logging.Formatter(f'%(asctime)s %(levelname)8s {caller}:'
                                  ' %(message)s', datefmt='%Y/%m/%d %H:%M:%S')

    handler.setFormatter(formatter)

    # add handler to phenix logger
    logger.handlers[:] = [handler]
    logger.log(LEVEL[level], msg)
