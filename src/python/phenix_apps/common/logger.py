import sys

from loguru import logger

import phenix_apps.common.settings as settings


def configure_logging(force_console: bool = False) -> None:
    """Configures the logger based on settings."""
    logger.remove()

    log_level = settings.PHENIX_LOG_LEVEL.upper()
    log_file = settings.PHENIX_LOG_FILE

    if log_file and not force_console:
        # File logging with JSON serialization
        logger.add(
            log_file,
            level=log_level,
            rotation="10 MB",
            serialize=True,
        )
    else:
        # Console logging
        logger.add(
            sys.stderr,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        )
