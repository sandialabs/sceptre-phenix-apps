import inspect
import logging
import os
import sys
from typing import Literal

import phenix_apps.common.settings as settings

logger = None

class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to log levels."""

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format_str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format_str + reset,
        logging.INFO: grey + format_str + reset,
        logging.WARNING: yellow + format_str + reset,
        logging.ERROR: red + format_str + reset,
        logging.CRITICAL: bold_red + format_str + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def log(level: Literal['DEBUG', 'INFO', 'WARNING', 'WARN', 'ERROR'] , msg: str) -> None:
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
        log_file = settings.PHENIX_LOG_FILE
        if log_file:
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            handler = logging.FileHandler(log_file)
            caller = os.path.basename(inspect.stack()[1].filename)
            fmt = f'{{"time": "%(asctime)s", "level": "%(levelname)s", "msg": "%(message)s", "caller": "{caller}"}}'
            handler.setFormatter(logging.Formatter(fmt))
        else:
            handler = logging.StreamHandler(sys.stderr)
            # Use colored formatter
            handler.setFormatter(ColoredFormatter())

        # add handler to phenix logger
        logger.handlers[:] = [handler]

    lvl = level.upper()
    if lvl == 'WARN':
        lvl = 'WARNING'
    logger.log(getattr(logging, lvl), msg)
